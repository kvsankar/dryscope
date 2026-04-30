"""Pipeline orchestrator: runs stages, manages progressive output."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from dryscope.cache import Cache
from dryscope.docs.chunker import chunk_documents, chunk_file_list, detect_boilerplate_headings
from dryscope.docs.coding import run_doc_pair_pipeline
from dryscope.config import Settings
from dryscope.docs.embeddings import embed_chunks, find_similar_pairs
from dryscope.docs.models import AnalysisResult, Chunk, Document, OverlapPair
from dryscope.run_store import RunStore
from dryscope.terminology import (
    DOCS_MAP,
    DOCS_MAP_SLUG,
    DOCS_PAIR_REVIEW,
    DOCS_PAIR_REVIEW_SLUG,
    DOCS_REPORT_PACK_SLUG,
    DOCS_SECTION_MATCH,
    DOCS_SECTION_MATCH_SLUG,
)


def _chunk_key(chunk: Chunk) -> str:
    """Create a unique key for a chunk for serialization matching."""
    return f"{chunk.document_path}:{chunk.line_start}"


def _serialize_pairs(pairs: list[OverlapPair]) -> list[dict]:
    """Serialize overlap pairs for JSON storage."""
    result = []
    for p in pairs:
        result.append({
            "chunk_a_key": _chunk_key(p.chunk_a),
            "chunk_b_key": _chunk_key(p.chunk_b),
            "embedding_similarity": p.embedding_similarity,
            "shared_codes": p.shared_codes,
        })
    return result


def _deserialize_pairs(
    data: list[dict], chunks: list[Chunk],
) -> list[OverlapPair]:
    """Deserialize overlap pairs, matching back to in-memory Chunk objects."""
    chunk_map = {_chunk_key(c): c for c in chunks}
    pairs = []
    for d in data:
        a = chunk_map.get(d["chunk_a_key"])
        b = chunk_map.get(d["chunk_b_key"])
        if a is None or b is None:
            continue
        pairs.append(OverlapPair(
            chunk_a=a,
            chunk_b=b,
            embedding_similarity=d.get("embedding_similarity"),
            shared_codes=d.get("shared_codes", []),
        ))
    return pairs


def _group_pairs_by_doc_pair(
    pairs: list[OverlapPair],
) -> dict[tuple[str, str], list[OverlapPair]]:
    """Group overlap pairs by document pair (sorted paths)."""
    groups: dict[tuple[str, str], list[OverlapPair]] = {}
    for p in pairs:
        a, b = p.chunk_a.document_path, p.chunk_b.document_path
        key = (min(a, b), max(a, b))
        groups.setdefault(key, []).append(p)
    return groups


def _rank_doc_paths_by_similarity_evidence(
    doc_pair_groups: dict[tuple[str, str], list[OverlapPair]],
) -> list[str]:
    """Rank docs by how much strong similarity evidence they participate in."""
    scores: dict[str, tuple[float, int]] = {}
    for (doc_a, doc_b), pairs in doc_pair_groups.items():
        pair_count = len(pairs)
        max_similarity = max((p.embedding_similarity or 0.0) for p in pairs) if pairs else 0.0
        pair_score = (max_similarity * 100.0) + pair_count
        for doc in (doc_a, doc_b):
            total_score, total_pairs = scores.get(doc, (0.0, 0))
            scores[doc] = (total_score + pair_score, total_pairs + pair_count)

    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1][0], -item[1][1], item[0]),
    )
    return [doc for doc, _ in ranked]


def _filter_doc_chunks_map(
    doc_chunks_map: dict[str, list[Chunk]],
    allowed_docs: set[str],
) -> dict[str, list[Chunk]]:
    """Keep only documents allowed to proceed to later stages."""
    return {
        doc_path: chunks
        for doc_path, chunks in doc_chunks_map.items()
        if doc_path in allowed_docs
    }


def _restrict_doc_pair_groups(
    doc_pair_groups: dict[tuple[str, str], list[OverlapPair]],
    *,
    allowed_docs: set[str] | None = None,
    max_pairs: int = 0,
) -> dict[tuple[str, str], list[OverlapPair]]:
    """Restrict doc-pair groups by allowed docs and/or strongest pair budget."""
    items = list(doc_pair_groups.items())
    if allowed_docs is not None:
        items = [
            (key, pairs)
            for key, pairs in items
            if key[0] in allowed_docs and key[1] in allowed_docs
        ]

    if max_pairs > 0 and len(items) > max_pairs:
        items.sort(
            key=lambda item: (
                -max((p.embedding_similarity or 0.0) for p in item[1]) if item[1] else 0.0,
                -len(item[1]),
                item[0],
            )
        )
        items = items[:max_pairs]

    return dict(items)


def _should_skip_intent_extraction(
    doc_chunks_map: dict[str, list[Chunk]],
    doc_pair_groups: dict[tuple[str, str], list[OverlapPair]],
    settings: Settings,
) -> bool:
    """Skip full-corpus intent extraction when there is no similarity evidence."""
    return (
        not doc_pair_groups
        and settings.docs_intent_skip_without_similarity_min_docs > 0
        and len(doc_chunks_map) >= settings.docs_intent_skip_without_similarity_min_docs
    )


# Pricing per million tokens: (input, output)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "sonnet": (3.0, 15.0),
    "haiku": (0.25, 1.25),
    "opus": (15.0, 75.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4": (10.0, 30.0),
}
_DEFAULT_PRICING = (3.0, 15.0)


def _get_pricing(model: str) -> tuple[float, float]:
    """Look up (input, output) pricing per million tokens for a model."""
    model_lower = model.lower()
    # Check most-specific keys first (e.g. "gpt-4o-mini" before "gpt-4")
    for key in sorted(MODEL_PRICING, key=len, reverse=True):
        if key in model_lower:
            return MODEL_PRICING[key]
    return _DEFAULT_PRICING


def _build_doc_chunks_map(documents: list[Document]) -> dict[str, list[Chunk]]:
    """Build mapping from document path to its chunks."""
    return {doc.path: doc.chunks for doc in documents}


def estimate_doc_pair_cost(
    doc_pair_groups: dict[tuple[str, str], list[OverlapPair]],
    doc_chunks_map: dict[str, list[Chunk]],
    model: str,
) -> float:
    """Estimate LLM cost for doc-pair analysis.

    Each doc pair gets one LLM call. Cost depends on the combined
    document size (capped at ~32k chars = ~8k tokens per call).
    """
    total_input_tokens = 0
    for (doc_a, doc_b), pairs in doc_pair_groups.items():
        chars_a = sum(len(c.content) for c in doc_chunks_map.get(doc_a, []))
        chars_b = sum(len(c.content) for c in doc_chunks_map.get(doc_b, []))
        # Cap each doc at 16k chars in the prompt
        capped = min(chars_a, 16000) + min(chars_b, 16000)
        # Add ~500 chars for prompt template + evidence
        total_input_tokens += (capped + 500) // 4

    cost_per_m_input, cost_per_m_output = _get_pricing(model)

    total_output_tokens = total_input_tokens * 0.3  # doc-pair responses are concise
    cost = (total_input_tokens / 1_000_000) * cost_per_m_input
    cost += (total_output_tokens / 1_000_000) * cost_per_m_output
    return cost


def estimate_cost(num_chunks: int, model: str) -> float:
    """Rough cost estimate for LLM coding stage.

    Assumes ~300 tokens per chunk average, plus overhead for axial coding
    and refactoring prompts. Uses approximate pricing.
    """
    tokens_per_chunk = 300
    total_input_tokens = num_chunks * tokens_per_chunk
    total_input_tokens += 1000 + num_chunks * 100

    cost_per_m_input, cost_per_m_output = _get_pricing(model)

    total_output_tokens = total_input_tokens * 0.5
    cost = (total_input_tokens / 1_000_000) * cost_per_m_input
    cost += (total_output_tokens / 1_000_000) * cost_per_m_output
    return cost


def _save_all_reports(
    run_store: RunStore,
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    settings: Settings,
    scan_path: Path,
    stages_run: list[str] | None = None,
) -> None:
    """Save report.json, report.md, and report.html to the run directory."""
    from dryscope.docs.report import render_final_report, render_html, render_markdown

    run_store.save_stage(
        "report.json",
        render_final_report(result, similarity_pairs, suggestions, settings, scan_path, stages_run),
    )
    md_content = render_markdown(
        result, similarity_pairs, suggestions,
        settings=settings, project_root=scan_path,
        stages_run=stages_run,
    )
    (run_store.run_dir / "report.md").write_text(md_content)
    (run_store.run_dir / "report.html").write_text(render_html(md_content))


def run_pipeline(
    scan_path: Path,
    settings: Settings,
    stage: str = DOCS_REPORT_PACK_SLUG,
    output_format: str = "terminal",
    output_file: str | None = None,
    skip_confirm: bool = False,
    console: Console | None = None,
    file_list: list[Path] | None = None,
    run_store: "RunStore | None" = None,
) -> AnalysisResult:
    """Run the analysis pipeline.

    Args:
        scan_path: Directory to scan for documentation.
        settings: Merged configuration settings.
        stage: "docs-section-match" or "docs-report-pack".
        output_format: "terminal", "markdown", or "json".
        output_file: Optional file path to write output.
        skip_confirm: Skip cost confirmation for LLM stage.
        console: Rich console for output (defaults to stderr).

    Returns:
        AnalysisResult with all analysis data.
    """
    valid_stages = {DOCS_SECTION_MATCH_SLUG, DOCS_REPORT_PACK_SLUG}
    if stage not in valid_stages:
        allowed = ", ".join(sorted(valid_stages))
        raise ValueError(f"Unknown docs stage {stage!r}; expected one of: {allowed}")

    if console is None:
        console = Console(stderr=True)

    result = AnalysisResult()
    similarity_pairs: list[OverlapPair] = []
    suggestions: list[dict] | None = None
    stages_run: list[str] = []

    # ─── Discover and chunk documents ───
    with console.status("[bold green]Discovering and chunking documents..."):
        if file_list is not None:
            result.documents = chunk_file_list(file_list, scan_path)
        else:
            result.documents = chunk_documents(
                scan_path, settings.include, settings.exclude,
            )
        for doc in result.documents:
            result.chunks.extend(doc.chunks)

    console.print(
        f"Found [bold]{len(result.documents)}[/bold] documents, "
        f"[bold]{len(result.chunks)}[/bold] sections"
    )

    if not result.chunks:
        console.print("[yellow]No documentation sections found.[/yellow]")
        return result

    # ─── Section Match ───
    console.print()
    console.print(f"[bold cyan]{DOCS_SECTION_MATCH}[/bold cyan]")

    cache = None
    if settings.cache_enabled:
        cache = Cache(settings.resolved_cache_path)

    similarity_resumed = False
    if run_store and run_store.stage_exists("docs_section_match.json"):
        saved = run_store.load_stage("docs_section_match.json")
        if saved:
            similarity_pairs = _deserialize_pairs(saved.get("matched_section_pairs", []), result.chunks)
            if similarity_pairs:
                similarity_resumed = True
                console.print(f"[green]Resumed {len(similarity_pairs)} matched section pairs from previous run.[/green]")

    if not similarity_resumed:
        # Detect boilerplate headings
        num_docs = len(result.documents)
        boilerplate_headings = detect_boilerplate_headings(result.chunks, num_docs)
        if boilerplate_headings:
            console.print(
                f"Detected [bold]{len(boilerplate_headings)}[/bold] boilerplate headings "
                f"(appear in >30% of docs): {', '.join(sorted(boilerplate_headings))}"
            )

        if settings.min_content_words > 0:
            short_count = sum(
                1 for c in result.chunks if len(c.content.split()) < settings.min_content_words
            )
            if short_count:
                console.print(
                    f"Filtering [bold]{short_count}[/bold] short sections "
                    f"(<{settings.min_content_words} words)"
                )

        # Embed all chunks
        def emb_progress(done: int, total: int) -> None:
            console.print(f"  Embedding {done}/{total} chunks...", end="\r")

        with console.status("[bold green]Embedding all chunks..."):
            embeddings = embed_chunks(
                result.chunks, settings.docs_embedding_model, cache,
                on_progress=emb_progress, concurrency=settings.concurrency,
            )

        if cache:
            cache.commit()

        console.print(f"Embedded [bold]{len(embeddings)}[/bold] chunks")

        # Find similar pairs
        similarity_pairs = find_similar_pairs(
            result.chunks, embeddings,
            threshold=settings.threshold_similarity,
            min_content_words=settings.min_content_words,
            boilerplate_headings=boilerplate_headings,
            include_intra=settings.include_intra,
            token_weight=settings.token_weight,
        )

        if run_store:
            from dryscope.docs.report import serialize_section_match_stage
            run_store.save_stage(
                "docs_section_match.json",
                serialize_section_match_stage(result, similarity_pairs, settings, scan_path),
            )

    result.overlaps = similarity_pairs
    stages_run.append(DOCS_SECTION_MATCH_SLUG)

    console.print(
        f"Found [bold]{len(similarity_pairs)}[/bold] matched section pairs "
        f"(cosine > {settings.threshold_similarity})"
    )

    try:
        if stage == DOCS_SECTION_MATCH_SLUG:
            if run_store:
                _save_all_reports(run_store, result, similarity_pairs, suggestions, settings, scan_path, stages_run)
            _output_results(result, similarity_pairs, suggestions,
                            output_format, output_file, console, settings, scan_path, stages_run)
            return result

        # ─── Docs Map ───
        doc_chunks_map = _build_doc_chunks_map(result.documents)
        doc_pair_groups = _group_pairs_by_doc_pair(similarity_pairs)
        intent_evidence: dict[tuple[str, str], list[dict]] = {}

        if settings.threshold_intent > 0:
            from dryscope.docs.topics import (
                descriptor_labels,
                embed_topics,
                find_intent_doc_pairs,
                run_document_descriptor_extraction,
            )

            intent_resumed = False
            doc_topics: dict[str, list[str]] = {}

            if run_store and run_store.stage_exists("docs_map.json"):
                saved = run_store.load_stage("docs_map.json")
                if saved:
                    result.document_descriptors = saved.get("document_descriptors", {})
                    result.topic_taxonomy = saved.get("topic_taxonomy")
                    if saved.get("descriptor_based") and result.document_descriptors and result.topic_taxonomy:
                        doc_topics = saved.get("doc_topics", {})
                        for match in saved.get("intent_matches", []):
                            key = (min(match["doc_a"], match["doc_b"]), max(match["doc_a"], match["doc_b"]))
                            intent_evidence[key] = match["matched_topics"]
                        intent_resumed = True
                        console.print(
                            f"[green]Resumed descriptor-based intent detection: {len(doc_topics)} documents, "
                            f"{len(intent_evidence)} intent pairs.[/green]"
                        )
                    existing_docs_map = (
                        result.topic_taxonomy.get("docs_map")
                        if result.topic_taxonomy else None
                    )
                    needs_docs_map = (
                        not isinstance(existing_docs_map, dict)
                        or not existing_docs_map
                        or str(existing_docs_map.get("method", "")).startswith("deterministic")
                    )
                    if intent_resumed and result.topic_taxonomy and needs_docs_map:
                        from dryscope.docs.taxonomy import build_docs_map

                        with console.status(f"[bold green]Discovering {DOCS_MAP}..."):
                            result.topic_taxonomy["docs_map"] = build_docs_map(
                                result.topic_taxonomy,
                                document_descriptors=result.document_descriptors,
                                llm_model=settings.model,
                                cache=cache,
                                backend=settings.backend,
                                ollama_host=settings.ollama_host,
                                cli_strip_api_key=settings.cli_strip_api_key,
                                cli_permission_mode=settings.cli_permission_mode,
                                cli_dangerously_skip_permissions=settings.cli_dangerously_skip_permissions,
                                facet_dimensions=settings.docs_map_facet_dimensions,
                                facet_values=settings.docs_map_facet_values,
                            )
                        docs_map = result.topic_taxonomy.get("docs_map", {})
                        console.print(
                            f"Discovered {DOCS_MAP}: "
                            f"[bold]{len(docs_map.get('topic_tree', []))}[/bold] top-level topic groups, "
                            f"[bold]{len(docs_map.get('facets', {}))}[/bold] facet dimensions, "
                            f"[bold]{len(docs_map.get('diagnostics', []))}[/bold] diagnostics"
                        )
                        saved["topic_taxonomy"] = result.topic_taxonomy
                        run_store.save_stage("docs_map.json", saved)
                        if cache:
                            cache.commit()

            if not intent_resumed:
                console.print()
                console.print(f"[bold cyan]{DOCS_MAP}[/bold cyan]")

                intent_doc_chunks_map = doc_chunks_map
                if _should_skip_intent_extraction(doc_chunks_map, doc_pair_groups, settings):
                    console.print(
                        "Skipping Docs Map extraction because there is no Section Match evidence "
                        f"and the corpus is large ([bold]{len(doc_chunks_map)}[/bold] docs)."
                    )
                    intent_doc_chunks_map = {}
                    doc_topics = {}
                elif settings.docs_intent_max_docs > 0 and len(doc_chunks_map) > settings.docs_intent_max_docs:
                    ranked_docs = _rank_doc_paths_by_similarity_evidence(doc_pair_groups)
                    if ranked_docs:
                        allowed_docs = set(ranked_docs[:settings.docs_intent_max_docs])
                        intent_doc_chunks_map = _filter_doc_chunks_map(doc_chunks_map, allowed_docs)
                        console.print(
                            "Limiting intent extraction to "
                            f"[bold]{len(intent_doc_chunks_map)}[/bold] documents "
                            "with the strongest Section Match evidence"
                        )

                if intent_doc_chunks_map:
                    def descriptor_progress(done: int, total: int) -> None:
                        console.print(f"  Extracting descriptors {done}/{total}...", end="\r")

                    result.document_descriptors = run_document_descriptor_extraction(
                        intent_doc_chunks_map, settings.model, cache,
                        backend=settings.backend,
                        concurrency=settings.concurrency,
                        on_progress=descriptor_progress,
                        ollama_host=settings.ollama_host,
                        cli_strip_api_key=settings.cli_strip_api_key,
                        cli_permission_mode=settings.cli_permission_mode,
                        cli_dangerously_skip_permissions=settings.cli_dangerously_skip_permissions,
                        facet_dimensions=settings.docs_map_facet_dimensions,
                        facet_values=settings.docs_map_facet_values,
                    )

                    if cache:
                        cache.commit()

                    raw_doc_topics = {
                        doc_path: descriptor_labels(descriptor)
                        for doc_path, descriptor in result.document_descriptors.items()
                    }
                    total_topics = sum(len(t) for t in raw_doc_topics.values())
                    console.print(
                        f"Extracted [bold]{len(result.document_descriptors)}[/bold] descriptors "
                        f"and [bold]{total_topics}[/bold] Docs Map labels"
                    )

                    from dryscope.docs.taxonomy import build_canonical_taxonomy, build_docs_map

                    with console.status("[bold green]Canonicalizing topics..."):
                        taxonomy = build_canonical_taxonomy(
                            raw_doc_topics,
                            llm_model=settings.model,
                            cache=cache,
                            backend=settings.backend,
                            llm_concurrency=settings.concurrency,
                            ollama_host=settings.ollama_host,
                            cli_strip_api_key=settings.cli_strip_api_key,
                            cli_permission_mode=settings.cli_permission_mode,
                            cli_dangerously_skip_permissions=settings.cli_dangerously_skip_permissions,
                        )
                    doc_topics = taxonomy.doc_topics
                    result.topic_taxonomy = taxonomy.to_dict()
                    topic_document_clusters = result.topic_taxonomy.get("topic_document_clusters", [])
                    console.print(
                        "Normalized to "
                        f"[bold]{len(taxonomy.canonical_topics)}[/bold] canonical topics "
                        f"({taxonomy.method})"
                    )
                    console.print(
                        "Found "
                        f"[bold]{len(topic_document_clusters)}[/bold] topic coverage clusters "
                        "(canonical topics covered by 2+ documents)"
                    )
                    with console.status(f"[bold green]Discovering {DOCS_MAP}..."):
                        result.topic_taxonomy["docs_map"] = build_docs_map(
                            result.topic_taxonomy,
                            document_descriptors=result.document_descriptors,
                            llm_model=settings.model,
                            cache=cache,
                            backend=settings.backend,
                            ollama_host=settings.ollama_host,
                            cli_strip_api_key=settings.cli_strip_api_key,
                            cli_permission_mode=settings.cli_permission_mode,
                            cli_dangerously_skip_permissions=settings.cli_dangerously_skip_permissions,
                            facet_dimensions=settings.docs_map_facet_dimensions,
                            facet_values=settings.docs_map_facet_values,
                        )
                    docs_map = result.topic_taxonomy.get("docs_map", {})
                    console.print(
                        f"Discovered {DOCS_MAP}: "
                        f"[bold]{len(docs_map.get('topic_tree', []))}[/bold] top-level topic groups, "
                        f"[bold]{len(docs_map.get('facets', {}))}[/bold] facet dimensions, "
                        f"[bold]{len(docs_map.get('diagnostics', []))}[/bold] diagnostics"
                    )

                    if cache:
                        cache.commit()

                    # Embed all unique topics
                    all_topics = list({t for topics in doc_topics.values() for t in topics})
                    if all_topics:
                        topic_embeddings = embed_topics(all_topics, settings.docs_embedding_model, cache)

                        # Find intent doc-pairs
                        intent_evidence = find_intent_doc_pairs(
                            doc_topics, topic_embeddings, settings.threshold_intent,
                        )

                    console.print(
                        f"Found [bold]{len(intent_evidence)}[/bold] intent-overlap document pairs "
                        f"(topic cosine > {settings.threshold_intent})"
                    )

                    # Save stage1b
                    if run_store:
                        intent_matches_data = [
                            {
                                "doc_a": key[0],
                                "doc_b": key[1],
                                "matched_topics": matches,
                            }
                            for key, matches in intent_evidence.items()
                        ]
                        run_store.save_stage("docs_map.json", {
                            "metadata": {},
                            "descriptor_based": True,
                            "document_descriptors": result.document_descriptors,
                            "descriptor_labels": raw_doc_topics,
                            "raw_doc_topics": raw_doc_topics,
                            "doc_topics": doc_topics,
                            "topic_taxonomy": result.topic_taxonomy,
                            "intent_matches": intent_matches_data,
                        })

            stages_run.append(DOCS_MAP_SLUG)

            # Add intent-only doc-pairs to groups (no content overlap, just topics)
            for key in intent_evidence:
                if key not in doc_pair_groups:
                    doc_pair_groups[key] = []

        if settings.docs_llm_max_doc_pairs > 0 and len(doc_pair_groups) > settings.docs_llm_max_doc_pairs:
            original_count = len(doc_pair_groups)
            doc_pair_groups = _restrict_doc_pair_groups(
                doc_pair_groups,
                max_pairs=settings.docs_llm_max_doc_pairs,
            )
            console.print(
                f"Limiting {DOCS_PAIR_REVIEW} to "
                f"[bold]{len(doc_pair_groups)}[/bold] of [bold]{original_count}[/bold] pairs "
                "with the strongest Section Match evidence"
            )

        if not doc_pair_groups:
            if run_store:
                _save_all_reports(run_store, result, similarity_pairs, suggestions, settings, scan_path, stages_run)
            _output_results(result, similarity_pairs, suggestions,
                            output_format, output_file, console, settings, scan_path, stages_run)
            return result

        # ─── Doc Pair Review ───
        est_cost = estimate_doc_pair_cost(doc_pair_groups, doc_chunks_map, settings.model)

        console.print()
        console.print(f"[bold cyan]{DOCS_PAIR_REVIEW} (LLM)[/bold cyan]")
        console.print(
            f"  Analyzing [bold]{len(doc_pair_groups)}[/bold] document pairs "
            f"→ ~${est_cost:.2f} ({settings.model})"
        )

        if est_cost > settings.max_cost:
            console.print(
                f"[red]Estimated cost ${est_cost:.2f} exceeds max_cost ${settings.max_cost:.2f}. "
                f"Skipping LLM stage.[/red]"
            )
            if run_store:
                _save_all_reports(run_store, result, similarity_pairs, suggestions, settings, scan_path, stages_run)
            _output_results(result, similarity_pairs, suggestions,
                            output_format, output_file, console, settings, scan_path, stages_run)
            return result

        if not skip_confirm:
            import click
            if not click.confirm("Proceed?"):
                console.print("[yellow]Skipping LLM stage.[/yellow]")
                if run_store:
                    _save_all_reports(run_store, result, similarity_pairs, suggestions, settings, scan_path, stages_run)
                _output_results(result, similarity_pairs, suggestions,
                                output_format, output_file, console, settings, scan_path, stages_run)
                return result

        try:
            import json as _json

            def doc_pair_progress(done: int, total: int) -> None:
                console.print(f"  Analyzing doc pair {done}/{total}...", end="\r")

            # Load prior doc-pair analyses for resume
            prior_analyses: dict[str, dict] = {}
            doc_pairs_path = None
            if run_store:
                doc_pairs_path = run_store.run_dir / "docs_pair_review.jsonl"
                if doc_pairs_path.exists():
                    for line in doc_pairs_path.read_text().splitlines():
                        if line.strip():
                            entry = _json.loads(line)
                            prior_analyses[entry["pair_key"]] = entry["analysis"]
                    if prior_analyses:
                        console.print(
                            f"[green]Resumed {len(prior_analyses)} doc-pair analyses.[/green]"
                        )

            # Incremental save callback
            def on_pair_analyzed(pair_key: str, raw: dict) -> None:
                if doc_pairs_path:
                    with open(doc_pairs_path, "a") as f:
                        f.write(_json.dumps({"pair_key": pair_key, "analysis": raw}) + "\n")

            analyses, codes, categories, suggestions = run_doc_pair_pipeline(
                doc_pair_groups, doc_chunks_map, settings.model, cache,
                on_progress=doc_pair_progress,
                backend=settings.backend,
                prior_analyses=prior_analyses,
                on_pair_analyzed=on_pair_analyzed,
                concurrency=settings.concurrency,
                intent_evidence=intent_evidence if intent_evidence else None,
                ollama_host=settings.ollama_host,
                cli_strip_api_key=settings.cli_strip_api_key,
                cli_permission_mode=settings.cli_permission_mode,
                cli_dangerously_skip_permissions=settings.cli_dangerously_skip_permissions,
            )
            result.doc_pair_analyses = analyses
            result.codes = codes
            result.categories = categories
            stages_run.append(DOCS_PAIR_REVIEW_SLUG)

            if cache:
                cache.commit()

            if run_store:
                from dryscope.docs.report import serialize_doc_pair_review_stage
                run_store.save_stage(
                    "docs_pair_review.json",
                    serialize_doc_pair_review_stage(codes, categories, suggestions, settings, scan_path, analyses=analyses),
                )
        except Exception as e:
            console.print(f"[yellow]LLM analysis stage failed: {e}[/yellow]")
            suggestions = None

        if run_store:
            _save_all_reports(run_store, result, similarity_pairs, suggestions, settings, scan_path, stages_run)

        _output_results(result, similarity_pairs, suggestions,
                        output_format, output_file, console, settings, scan_path, stages_run)
        return result
    finally:
        if cache:
            cache.close()


def _output_results(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    output_format: str,
    output_file: str | None,
    console: Console,
    settings: Settings | None = None,
    scan_path: Path | None = None,
    stages_run: list[str] | None = None,
) -> None:
    """Generate and output the report."""
    from dryscope.docs.report import render_html, render_json, render_markdown, render_terminal

    if output_format == "terminal":
        console.print()
        render_terminal(result, similarity_pairs, suggestions, console)
    elif output_format == "markdown":
        content = render_markdown(
            result, similarity_pairs, suggestions,
            settings=settings, project_root=scan_path,
            stages_run=stages_run,
        )
        if output_file:
            output_path = Path(output_file)
            output_path.write_text(content)
            html_path = output_path.with_suffix(".html")
            html_path.write_text(render_html(content))
            console.print(f"Report written to [bold]{output_file}[/bold]")
            console.print(f"HTML report written to [bold]{html_path}[/bold]")
        else:
            stdout_console = Console(soft_wrap=True)
            stdout_console.print(content)
    elif output_format == "html":
        md_content = render_markdown(
            result, similarity_pairs, suggestions,
            settings=settings, project_root=scan_path,
            stages_run=stages_run,
        )
        content = render_html(md_content)
        if output_file:
            Path(output_file).write_text(content)
            console.print(f"Report written to [bold]{output_file}[/bold]")
        else:
            stdout_console = Console(soft_wrap=True)
            stdout_console.print(content)
    elif output_format == "json":
        content = render_json(result, similarity_pairs, suggestions,
                              settings=settings, project_root=scan_path,
                              stages_run=stages_run)
        if output_file:
            Path(output_file).write_text(content)
            console.print(f"Report written to [bold]{output_file}[/bold]")
        else:
            stdout_console = Console(soft_wrap=True)
            stdout_console.print(content)
