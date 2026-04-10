"""LLM doc-pair analysis for overlap detection."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from dryscope.cache import Cache
from dryscope.llm_backend import completion
from dryscope.docs.models import (
    Category, Chunk, Code, DocPairAnalysis,
    OverlapPair, TopicAnalysis,
)


DOC_PAIR_VERSION = "docpair_v2"


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response text."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return text


def call_llm_cached(
    model: str,
    prompt: str,
    cache: Cache | None,
    cache_key: str,
    prompt_version: str,
    backend: str = "litellm",
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> str:
    """Call LLM with caching."""
    if cache is not None:
        cached = cache.get_coding(cache_key, model, prompt_version)
        if cached is not None:
            return cached

    text = completion(
        prompt,
        model,
        backend,
        ollama_host=ollama_host,
        cli_strip_api_key=cli_strip_api_key,
        cli_permission_mode=cli_permission_mode,
        cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
    )

    if cache is not None:
        cache.set_coding(cache_key, model, prompt_version, text)

    return text


def _build_doc_outline(chunks: list[Chunk]) -> str:
    """Build a heading outline string from a document's chunks."""
    lines: list[str] = []
    for chunk in chunks:
        if chunk.heading_path:
            depth = len(chunk.heading_path)
            heading = chunk.heading_path[-1]
            indent = "  " * (depth - 1)
            lines.append(f"{indent}- {heading}")
        else:
            lines.append("- (no heading)")
    return "\n".join(lines) if lines else "(empty document)"


def _build_overlap_evidence(pairs: list[OverlapPair]) -> str:
    """Format similarity evidence for each overlap pair."""
    lines: list[str] = []
    for i, pair in enumerate(pairs, 1):
        heading_a = " > ".join(pair.chunk_a.heading_path) or "(no heading)"
        heading_b = " > ".join(pair.chunk_b.heading_path) or "(no heading)"
        scores = ""
        if pair.embedding_similarity is not None:
            scores = f"similarity={pair.embedding_similarity:.3f}"
        lines.append(f"{i}. [{scores}] A: {heading_a} <-> B: {heading_b}")
    return "\n".join(lines) if lines else "(no evidence)"


def _prepare_doc_content(
    chunks: list[Chunk],
    overlap_chunk_ids: set[str],
    max_chars: int = 16000,
) -> str:
    """Build document content prioritizing overlap sections.

    Overlapping sections are included in full. Non-overlapping sections
    are truncated to fit within max_chars.
    """
    overlap_parts: list[str] = []
    other_parts: list[str] = []

    for chunk in chunks:
        heading = " > ".join(chunk.heading_path) if chunk.heading_path else "(no heading)"
        if chunk.id in overlap_chunk_ids:
            overlap_parts.append(f"### {heading}\n{chunk.content}")
        else:
            other_parts.append(f"### {heading}\n{chunk.content}")

    overlap_text = "\n\n".join(overlap_parts)
    remaining = max_chars - len(overlap_text)

    if remaining > 200 and other_parts:
        other_text = "\n\n".join(other_parts)
        if len(other_text) > remaining:
            other_text = other_text[:remaining - 20] + "\n[... truncated]"
        return overlap_text + "\n\n---\n(Other sections)\n\n" + other_text

    return overlap_text


def _build_intent_evidence(intent_matches: list[dict]) -> str:
    """Format intent evidence for the prompt."""
    lines: list[str] = []
    for i, m in enumerate(intent_matches, 1):
        lines.append(
            f'{i}. Doc A topic "{m["topic_a"]}" \u2194 '
            f'Doc B topic "{m["topic_b"]}" (similarity={m["similarity"]:.2f})'
        )
    return "\n".join(lines) if lines else "(no intent evidence)"


def analyze_doc_pair(
    doc_a_path: str,
    doc_b_path: str,
    doc_a_chunks: list[Chunk],
    doc_b_chunks: list[Chunk],
    overlap_pairs: list[OverlapPair],
    model: str,
    cache: "Cache | None",
    backend: str = "litellm",
    intent_evidence: list[dict] | None = None,
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> dict:
    """Analyze overlap between two documents via a single LLM call.

    Returns a dict with: doc_a_purpose, doc_b_purpose, relationship,
    topics (list of dicts), confidence.
    """
    # Collect overlap chunk IDs for content prioritization
    overlap_ids_a: set[str] = set()
    overlap_ids_b: set[str] = set()
    for pair in overlap_pairs:
        overlap_ids_a.add(pair.chunk_a.id)
        overlap_ids_b.add(pair.chunk_b.id)

    outline_a = _build_doc_outline(doc_a_chunks)
    outline_b = _build_doc_outline(doc_b_chunks)
    evidence = _build_overlap_evidence(overlap_pairs)
    content_a = _prepare_doc_content(doc_a_chunks, overlap_ids_a)
    content_b = _prepare_doc_content(doc_b_chunks, overlap_ids_b)

    intro = "You are a documentation analyst. Two documents have been identified as potentially overlapping by automated analysis (content similarity and/or shared topic detection). Analyze the relationship and overlapping topics."

    intent_section = ""
    if intent_evidence:
        formatted = _build_intent_evidence(intent_evidence)
        intent_section = f"""
---

Intent evidence (from topic extraction stage):
{formatted}
"""

    prompt = f"""{intro}

DOCUMENT A: {doc_a_path}
Outline:
{outline_a}

Content:
{content_a}

---

DOCUMENT B: {doc_b_path}
Outline:
{outline_b}

Content:
{content_b}

---

Overlap evidence (from similarity stage):
{evidence}
{intent_section}
---

Analyze these two documents and respond with ONLY a JSON object (no other text):
{{
  "doc_a_purpose": "one-sentence purpose of document A",
  "doc_b_purpose": "one-sentence purpose of document B",
  "relationship": "subset|complementary|stale-copy|divergent-versions|different-audiences|fragmented",
  "topics": [
    {{
      "name": "kebab-case-topic-name",
      "canonical": "path of the document that should own this topic",
      "action_for_other": "consolidate|link|brief-reference|keep",
      "reason": "why this action"
    }}
  ],
  "confidence": "high|medium|low"
}}

Guidelines:
- "relationship" describes the overall document relationship
- Each "topic" is a specific overlap area identified from the evidence
- "canonical" should be the document that covers the topic most thoroughly
- "action_for_other" says what the NON-canonical document should do:
  - "consolidate": merge into canonical, remove from other
  - "link": replace with a cross-reference link
  - "brief-reference": keep a brief mention + link to canonical
  - "keep": both documents need this content (different audiences/contexts)
- "fragmented": documents split coverage of the same specific topic with different specifics (e.g., different items in the same list). Consolidation recommended.
"""

    sorted_paths = "|".join(sorted([doc_a_path, doc_b_path]))
    pair_hash = hashlib.sha256(
        "|".join(sorted(p.chunk_a.id + p.chunk_b.id for p in overlap_pairs)).encode()
    ).hexdigest()[:16]
    cache_key = f"docpair|{sorted_paths}|{pair_hash}"

    text = call_llm_cached(
        model,
        prompt,
        cache,
        cache_key,
        DOC_PAIR_VERSION,
        backend,
        ollama_host=ollama_host,
        cli_strip_api_key=cli_strip_api_key,
        cli_permission_mode=cli_permission_mode,
        cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
    )

    try:
        text = _strip_code_fences(text)
        return json.loads(text)
    except (json.JSONDecodeError, IndexError, ValueError):
        # Fallback: return a minimal valid result
        return {
            "doc_a_purpose": "unknown",
            "doc_b_purpose": "unknown",
            "relationship": "complementary",
            "topics": [],
            "confidence": "low",
        }


def doc_pairs_to_codes_and_categories(
    analyses: list[DocPairAnalysis],
) -> tuple[list[Code], list[Category], list[dict]]:
    """Bridge function: convert DocPairAnalysis objects to legacy Code/Category/suggestions.

    Each topic across all analyses becomes a Code object with chunks from both docs.
    Categories are grouped by relationship type.
    Suggestions are derived from topics where action_for_other != "keep".
    """
    # Deduplicate topics by name, merging chunks
    code_map: dict[str, Code] = {}
    for analysis in analyses:
        for topic in analysis.topics:
            if topic.name in code_map:
                existing = code_map[topic.name]
                for c in topic.chunks_a:
                    if c not in existing.chunks:
                        existing.chunks.append(c)
                for c in topic.chunks_b:
                    if c not in existing.chunks:
                        existing.chunks.append(c)
            else:
                code_map[topic.name] = Code(
                    name=topic.name,
                    category=analysis.relationship,
                    chunks=list(topic.chunks_a) + list(topic.chunks_b),
                    canonical_doc=topic.canonical,
                )

    codes = list(code_map.values())

    # Group codes into categories by relationship type
    cat_map: dict[str, list[Code]] = {}
    for code in codes:
        cat_map.setdefault(code.category, []).append(code)

    categories = [
        Category(name=cat_name, codes=cat_codes)
        for cat_name, cat_codes in sorted(cat_map.items())
    ]

    # Build suggestions from non-"keep" topics
    suggestions: list[dict] = []
    for analysis in analyses:
        for topic in analysis.topics:
            if topic.action_for_other == "keep":
                continue
            canonical = topic.canonical
            other = analysis.doc_b_path if canonical == analysis.doc_a_path else analysis.doc_a_path
            suggestions.append({
                "code": topic.name,
                "documents": sorted([analysis.doc_a_path, analysis.doc_b_path]),
                "canonical": canonical,
                "suggestions": [{
                    "document": other,
                    "action": topic.action_for_other,
                    "reason": topic.reason,
                }],
            })

    return codes, categories, suggestions


def _build_analysis_from_raw(
    doc_a: str, doc_b: str, raw: dict, pairs: list[OverlapPair],
) -> DocPairAnalysis:
    """Build a DocPairAnalysis from a raw LLM response dict."""
    overlap_ids_a = {p.chunk_a.id: p.chunk_a for p in pairs}
    overlap_ids_b = {p.chunk_b.id: p.chunk_b for p in pairs}

    topics: list[TopicAnalysis] = []
    for t in raw.get("topics", []):
        topic_name = t.get("name", "unknown")
        # Extract significant words (3+ chars) from the topic name for matching
        topic_words = {
            w for w in topic_name.replace("-", " ").replace("_", " ").lower().split()
            if len(w) >= 3
        }

        def _chunk_matches_topic(chunk: Chunk, words: set[str]) -> bool:
            """Check if a chunk's content or heading contains any topic word."""
            text = chunk.content.lower()
            if chunk.heading_path:
                text += " " + " ".join(chunk.heading_path).lower()
            text_words = set(text.split())
            return bool(text_words & words)

        if topic_words:
            matched_a = [
                c for c in overlap_ids_a.values()
                if _chunk_matches_topic(c, topic_words)
            ]
            matched_b = [
                c for c in overlap_ids_b.values()
                if _chunk_matches_topic(c, topic_words)
            ]
            # Fall back to all chunks if heuristic is too strict
            if not matched_a and not matched_b:
                matched_a = list(overlap_ids_a.values())
                matched_b = list(overlap_ids_b.values())
        else:
            matched_a = list(overlap_ids_a.values())
            matched_b = list(overlap_ids_b.values())

        topics.append(TopicAnalysis(
            name=topic_name,
            canonical=t.get("canonical", doc_a),
            action_for_other=t.get("action_for_other", "keep"),
            reason=t.get("reason", ""),
            chunks_a=matched_a,
            chunks_b=matched_b,
        ))

    return DocPairAnalysis(
        doc_a_path=doc_a,
        doc_b_path=doc_b,
        doc_a_purpose=raw.get("doc_a_purpose", "unknown"),
        doc_b_purpose=raw.get("doc_b_purpose", "unknown"),
        relationship=raw.get("relationship", "complementary"),
        topics=topics,
        confidence=raw.get("confidence", "medium"),
        overlap_pairs=pairs,
    )


def run_doc_pair_pipeline(
    doc_pair_groups: dict[tuple[str, str], list[OverlapPair]],
    doc_chunks_map: dict[str, list[Chunk]],
    model: str,
    cache: "Cache | None",
    on_progress: "callable | None" = None,
    backend: str = "litellm",
    prior_analyses: dict[str, dict] | None = None,
    on_pair_analyzed: "callable | None" = None,
    concurrency: int = 1,
    intent_evidence: dict[tuple[str, str], list[dict]] | None = None,
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> tuple[list[DocPairAnalysis], list[Code], list[Category], list[dict]]:
    """Run doc-pair level LLM analysis pipeline.

    Args:
        doc_pair_groups: Mapping of (doc_a, doc_b) -> list of OverlapPairs.
        doc_chunks_map: Mapping of doc path -> all chunks in that document.
        model: LLM model name.
        cache: Optional cache instance.
        on_progress: Callback(done, total) for progress reporting.
        backend: LLM backend name.
        prior_analyses: Dict of pair_key -> raw analysis dict for resume.
        on_pair_analyzed: Callback(pair_key, raw_dict) for incremental save.
        concurrency: Max parallel LLM calls (1 = sequential).

    Returns:
        (analyses, codes, categories, suggestions)
    """
    if prior_analyses is None:
        prior_analyses = {}

    # Build ordered list of items and collect results keyed by pair_key
    items = list(doc_pair_groups.items())
    total = len(items)
    results: dict[str, tuple[dict, str, str, list[OverlapPair]]] = {}
    callback_lock = threading.Lock()
    done_count = 0

    # Handle resumed pairs first (no LLM call needed)
    pending_items: list[tuple[int, tuple[str, str], list[OverlapPair]]] = []
    for idx, ((doc_a, doc_b), pairs) in enumerate(items):
        pair_key = f"{doc_a}|{doc_b}"
        if pair_key in prior_analyses:
            results[pair_key] = (prior_analyses[pair_key], doc_a, doc_b, pairs)
            done_count += 1
        else:
            pending_items.append((idx, (doc_a, doc_b), pairs))

    if on_progress and done_count > 0:
        on_progress(done_count, total)

    _intent_evidence = intent_evidence or {}

    def _analyze_one(doc_a: str, doc_b: str, pairs: list[OverlapPair]) -> tuple[str, dict]:
        doc_a_chunks = doc_chunks_map.get(doc_a, [])
        doc_b_chunks = doc_chunks_map.get(doc_b, [])
        pair_intent = _intent_evidence.get((doc_a, doc_b)) or _intent_evidence.get((doc_b, doc_a))
        raw = analyze_doc_pair(
            doc_a, doc_b, doc_a_chunks, doc_b_chunks,
            pairs, model, cache, backend,
            intent_evidence=pair_intent,
            ollama_host=ollama_host,
            cli_strip_api_key=cli_strip_api_key,
            cli_permission_mode=cli_permission_mode,
            cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
        )
        return f"{doc_a}|{doc_b}", raw

    if concurrency > 1 and pending_items:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_analyze_one, doc_a, doc_b, pairs): (doc_a, doc_b, pairs)
                for _idx, (doc_a, doc_b), pairs in pending_items
            }
            for future in as_completed(futures):
                doc_a, doc_b, pairs = futures[future]
                pair_key, raw = future.result()
                with callback_lock:
                    results[pair_key] = (raw, doc_a, doc_b, pairs)
                    if on_pair_analyzed:
                        on_pair_analyzed(pair_key, raw)
                    done_count += 1
                    if on_progress:
                        on_progress(done_count, total)
    else:
        for _idx, (doc_a, doc_b), pairs in pending_items:
            pair_key, raw = _analyze_one(doc_a, doc_b, pairs)
            results[pair_key] = (raw, doc_a, doc_b, pairs)
            if on_pair_analyzed:
                on_pair_analyzed(pair_key, raw)
            done_count += 1
            if on_progress:
                on_progress(done_count, total)

    # Build analyses list preserving original pair order
    analyses: list[DocPairAnalysis] = []
    for (doc_a, doc_b), pairs in items:
        pair_key = f"{doc_a}|{doc_b}"
        raw, _, _, _ = results[pair_key]
        analyses.append(_build_analysis_from_raw(doc_a, doc_b, raw, pairs))

    codes, categories, suggestions = doc_pairs_to_codes_and_categories(analyses)
    return analyses, codes, categories, suggestions
