"""Report generation (terminal/Rich, markdown, JSON)."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dryscope.config import Settings
from dryscope.docs.models import AnalysisResult, Category, Code, DocPairAnalysis, OverlapPair
from dryscope.terminology import (
    CODE_MATCH,
    CODE_MATCH_SLUG,
    DOCS_MAP,
    DOCS_MAP_SLUG,
    DOCS_PAIR_REVIEW,
    DOCS_PAIR_REVIEW_SLUG,
    DOCS_REPORT_PACK,
    DOCS_REPORT_PACK_SLUG,
    DOCS_SECTION_MATCH,
    DOCS_SECTION_MATCH_SLUG,
    DOCS_STAGE_LABELS,
)


def _short_path(path: str | None) -> str:
    """Return just the filename from a path, or a placeholder if missing."""
    if not path:
        return "(unspecified)"
    return Path(path).name


def _display_path(path: str | None, project_root: Path | None = None) -> str:
    """Return a readable path for report tables and topic clusters."""
    if not path:
        return "(unspecified)"
    if project_root is not None:
        try:
            return str(Path(path).relative_to(project_root))
        except ValueError:
            pass
    return _short_path(path)


def _topic_document_clusters(result: AnalysisResult) -> list[dict]:
    """Return all multi-document canonical topic clusters from the taxonomy."""
    taxonomy = result.topic_taxonomy or {}
    clusters = taxonomy.get("topic_document_clusters")
    if clusters is None:
        clusters = [
            {
                "topic": topic.get("name"),
                "documents": topic.get("documents", []),
                "document_count": topic.get("document_count", 0),
                "mention_count": topic.get("mention_count", 0),
                "aliases": topic.get("aliases", []),
            }
            for topic in taxonomy.get("canonical_topics", [])
            if int(topic.get("document_count") or 0) >= 2
        ]
    return sorted(
        clusters,
        key=lambda c: (
            -int(c.get("document_count") or 0),
            -int(c.get("mention_count") or 0),
            str(c.get("topic") or ""),
        ),
    )


def _docs_map(result: AnalysisResult) -> dict:
    """Return discovered Docs Map data from the topic taxonomy."""
    taxonomy = result.topic_taxonomy or {}
    docs_map = taxonomy.get("docs_map")
    return docs_map if isinstance(docs_map, dict) else {}


def _build_run_overview(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    recommendations: list[dict],
    stages_run: list[str] | None = None,
) -> dict:
    """Build the top-down capability/aspect summary shared by all report formats."""
    stages = set(stages_run or [])
    docs_map = _docs_map(result)
    taxonomy = result.topic_taxonomy or {}
    canonical_topics = taxonomy.get("canonical_topics", []) if isinstance(taxonomy, dict) else []
    coverage_clusters = _topic_document_clusters(result)
    docs_tracks_ran = bool(
        result.documents or DOCS_SECTION_MATCH_SLUG in stages or DOCS_MAP_SLUG in stages
    )
    docs_map_ran = bool(DOCS_MAP_SLUG in stages or result.document_descriptors or taxonomy)
    section_match_ran = bool(DOCS_SECTION_MATCH_SLUG in stages or similarity_pairs)

    return {
        "capabilities": {
            "code_match": {
                "ran": False,
                "label": CODE_MATCH,
                "slug": CODE_MATCH_SLUG,
                "what_it_does": "Finds duplicate or near-duplicate code units.",
                "result": "Not exercised in this documentation run.",
            },
            "docs_tracks": {
                "ran": docs_tracks_ran,
                "label": "Docs tracks",
                "slug": "docs-tracks",
                "what_it_does": "Runs Docs Map, Section Match, and optional Doc Pair Review.",
                "result": (
                    f"{_plural(len(result.documents), 'document')}, "
                    f"{_plural(len(result.chunks), 'section')}, "
                    f"{_plural(len(similarity_pairs), 'matched section pair')}, "
                    f"{_plural(len(coverage_clusters), 'consolidation cluster')}."
                ),
            },
        },
        "docs_track_aspects": {
            "docs_map": {
                "ran": docs_map_ran,
                "label": DOCS_MAP,
                "slug": DOCS_MAP_SLUG,
                "pipeline": [
                    "document descriptor extraction",
                    "canonical label normalization",
                    "topic tree and facet discovery",
                    "docs map clusters",
                ],
                "results": {
                    "documents_profiled": len(result.document_descriptors),
                    "descriptor_labels": sum(
                        len(descriptor.get("about", [])) + len(descriptor.get("reader_intents", []))
                        for descriptor in result.document_descriptors.values()
                    ),
                    "canonical_labels": len(canonical_topics),
                    "docs_map_clusters": len(coverage_clusters),
                    "docs_map_groups": len(docs_map.get("topic_tree", [])),
                    "facet_dimensions": len(docs_map.get("facets", {})),
                    "docs_map_diagnostics": len(docs_map.get("diagnostics", [])),
                },
            },
            "docs_section_match": {
                "ran": section_match_ran,
                "label": DOCS_SECTION_MATCH,
                "slug": DOCS_SECTION_MATCH_SLUG,
                "pipeline": [
                    "split documents into sections",
                    "embed sections",
                    "compare cross-document section pairs",
                    "section match recommendations",
                ],
                "results": {
                    "sections_analyzed": len(result.chunks),
                    "matched_section_pairs": len(similarity_pairs),
                    "section_match_recommendations": len(recommendations),
                },
            },
        },
        "supporting_results": {
            "doc_pair_reviews": len(result.doc_pair_analyses),
            "doc_pair_review": {
                "label": DOCS_PAIR_REVIEW,
                "slug": DOCS_PAIR_REVIEW_SLUG,
                "pairs_analyzed": len(result.doc_pair_analyses),
            },
            "stages_run": stages_run or [],
        },
    }


def _pair_to_dict(pair: OverlapPair) -> dict:
    """Convert a matched section pair to structured JSON."""
    return {
        "chunk_a": {
            "document": pair.chunk_a.document_path,
            "heading_path": pair.chunk_a.heading_path,
            "line_start": pair.chunk_a.line_start,
            "line_end": pair.chunk_a.line_end,
        },
        "chunk_b": {
            "document": pair.chunk_b.document_path,
            "heading_path": pair.chunk_b.heading_path,
            "line_start": pair.chunk_b.line_start,
            "line_end": pair.chunk_b.line_end,
        },
        "embedding_similarity": pair.embedding_similarity,
        "shared_codes": pair.shared_codes,
    }


def _doc_pair_analysis_to_dict(analysis: DocPairAnalysis) -> dict:
    """Convert a Doc Pair Review analysis to structured JSON."""
    return {
        "doc_a": analysis.doc_a_path,
        "doc_a_name": _short_path(analysis.doc_a_path),
        "doc_b": analysis.doc_b_path,
        "doc_b_name": _short_path(analysis.doc_b_path),
        "doc_a_purpose": analysis.doc_a_purpose,
        "doc_b_purpose": analysis.doc_b_purpose,
        "relationship": analysis.relationship,
        "confidence": analysis.confidence,
        "topics": [
            {
                "name": topic.name,
                "canonical": topic.canonical,
                "canonical_name": _short_path(topic.canonical),
                "action_for_other": topic.action_for_other,
                "reason": topic.reason,
            }
            for topic in analysis.topics
        ],
    }


def _docs_map_taxonomy_data(result: AnalysisResult) -> dict:
    """Return canonical label taxonomy data without duplicating Docs Map clusters."""
    taxonomy = result.topic_taxonomy or {}
    canonical_topics = []
    for topic in taxonomy.get("canonical_topics", []):
        canonical_topics.append(
            {
                "name": topic.get("name"),
                "aliases": topic.get("aliases", []),
                "document_count": topic.get("document_count", 0),
                "mention_count": topic.get("mention_count", 0),
            }
        )
    return {
        "canonical_topics": canonical_topics,
        "raw_to_canonical": taxonomy.get("raw_to_canonical", {}),
        "co_occurrence": taxonomy.get("co_occurrence", []),
        "document_descriptors": result.document_descriptors,
    }


def _report_structure(
    overview: dict,
    recommendations: list[dict],
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
) -> list[dict]:
    """Return the ordered report sections and backing data for JSON consumers."""
    taxonomy = result.topic_taxonomy or {}
    matched_section_pairs = [_pair_to_dict(pair) for pair in similarity_pairs]
    sections: list[dict] = [
        {
            "id": "run_overview",
            "title": "Run Overview",
            "data": {
                "overview": overview,
                "scanned_documents": [
                    doc.path for doc in sorted(result.documents, key=lambda d: d.path)
                ],
            },
        },
    ]
    if _docs_map(result):
        sections.append(
            {
                "id": "docs_map",
                "title": DOCS_MAP,
                "slug": DOCS_MAP_SLUG,
                "data": _docs_map(result),
            }
        )
    if _topic_document_clusters(result):
        sections.append(
            {
                "id": "docs_map_clusters",
                "title": "Docs Map Clusters",
                "slug": DOCS_MAP_SLUG,
                "data": _topic_document_clusters(result),
            }
        )
    sections.append(
        {
            "id": "docs_section_match",
            "title": DOCS_SECTION_MATCH,
            "slug": DOCS_SECTION_MATCH_SLUG,
            "data": {
                "matched_section_pairs": len(similarity_pairs),
                "section_match_recommendations": len(recommendations),
            },
            "children": [
                {
                    "id": "docs_section_match_recommendations",
                    "title": "Section Match Recommendations",
                    "slug": DOCS_SECTION_MATCH_SLUG,
                    "data": recommendations,
                },
                {
                    "id": "matched_section_pairs",
                    "title": "Matched Section Pairs",
                    "slug": DOCS_SECTION_MATCH_SLUG,
                    "data": matched_section_pairs,
                },
            ],
        }
    )
    if result.doc_pair_analyses:
        sections.append(
            {
                "id": "docs_pair_review",
                "title": DOCS_PAIR_REVIEW,
                "slug": DOCS_PAIR_REVIEW_SLUG,
                "data": [
                    _doc_pair_analysis_to_dict(analysis) for analysis in result.doc_pair_analyses
                ],
            }
        )
    if taxonomy:
        sections.append(
            {
                "id": "docs_map_taxonomy",
                "title": "Docs Map Taxonomy",
                "slug": DOCS_MAP_SLUG,
                "data": _docs_map_taxonomy_data(result),
            }
        )
    sections.append({"id": "methodology", "title": "Methodology", "data": {}})

    for index, section in enumerate(sections, 1):
        section["number"] = index
        section["title_numbered"] = f"{index}. {section['title']}"
        for child_index, child in enumerate(section.get("children", []), 1):
            child["number"] = f"{index}.{child_index}"
            child["title_numbered"] = f"{index}.{child_index}. {child['title']}"
    return sections


def _ran_text(value: bool) -> str:
    """Human-readable report status."""
    return "Yes" if value else "No"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """Return a small count phrase with correct singular/plural wording."""
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _metric_card(value: int, label: str) -> str:
    """Return one dashboard metric card."""
    return (
        f'  <div class="metric-card"><div class="metric-value">{value}</div>'
        f'<div class="metric-label">{label}</div></div>\n'
    )


def _html_code(value: object) -> str:
    """Return an escaped inline code element for raw HTML blocks in markdown."""
    return f"<code>{escape(str(value or ''))}</code>"


def _html_list(items: list[object]) -> str:
    """Return a full escaped HTML list for collapsible markdown sections."""
    if not items:
        return "<p>None.</p>"
    rows = "\n".join(f"  <li>{_html_code(item)}</li>" for item in items)
    return f"<ul>\n{rows}\n</ul>"


def _html_text_list(items: list[object]) -> str:
    """Return a full escaped HTML list for non-code text values."""
    if not items:
        return "<p>None.</p>"
    rows = "\n".join(f"  <li>{escape(str(item or ''))}</li>" for item in items)
    return f"<ul>\n{rows}\n</ul>"


def _details_block(
    summary: str, body: str, class_name: str = "report-item", open_: bool = False
) -> str:
    """Return a raw HTML details block that works in markdown and HTML reports."""
    open_attr = " open" if open_ else ""
    return (
        f'<details class="{class_name}"{open_attr}>\n'
        f"<summary>{escape(summary)}</summary>\n"
        f"{body}\n"
        "</details>\n"
    )


def _markdown_table_cell(value: object) -> str:
    """Escape a value for use inside a markdown table cell."""
    text = str(value or "").replace("\n", " ").replace("\r", " ")
    text = text.replace("|", r"\|")
    return " ".join(text.split())


def render_terminal(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    console: Console | None = None,
) -> None:
    """Render analysis results to terminal using Rich."""
    if console is None:
        console = Console(stderr=True)

    console.print()
    console.print(Panel.fit("[bold]dryscope Report[/bold]", style="blue"))
    console.print()
    console.print(
        f"Scanned: [bold]{len(result.documents)}[/bold] documents, "
        f"[bold]{len(result.chunks)}[/bold] sections"
    )
    console.print()

    # Section Match
    console.print(f"[bold]{DOCS_SECTION_MATCH}[/bold]", style="cyan")
    console.print(f"Found [bold]{len(similarity_pairs)}[/bold] matched section pairs")
    console.print()

    if similarity_pairs:
        table = Table(title="Top Section Match Results", show_lines=True)
        table.add_column("Similarity", style="yellow", width=10)
        table.add_column("Section A", style="green")
        table.add_column("Section B", style="green")

        for pair in similarity_pairs[:10]:
            heading_a = " > ".join(pair.chunk_a.heading_path) or "(no heading)"
            heading_b = " > ".join(pair.chunk_b.heading_path) or "(no heading)"
            loc_a = f"{_short_path(pair.chunk_a.document_path)}: {heading_a}"
            loc_b = f"{_short_path(pair.chunk_b.document_path)}: {heading_b}"
            sim_str = (
                f"{pair.embedding_similarity:.3f}" if pair.embedding_similarity is not None else "—"
            )
            table.add_row(sim_str, loc_a, loc_b)

        console.print(table)
        console.print()

    # Doc Pair Review
    if result.doc_pair_analyses:
        console.print(f"[bold]{DOCS_PAIR_REVIEW}[/bold]", style="cyan")
        console.print(f"Analyzed [bold]{len(result.doc_pair_analyses)}[/bold] document pairs")
        console.print()

        for analysis in result.doc_pair_analyses:
            rel = analysis.relationship
            conf = analysis.confidence
            console.print(
                f"  [bold]{_short_path(analysis.doc_a_path)}[/bold] "
                f"{'↔' if rel == 'complementary' else '→'} "
                f"[bold]{_short_path(analysis.doc_b_path)}[/bold] "
                f"([dim]{rel}[/dim], {conf} confidence)"
            )
            console.print(f"    {_short_path(analysis.doc_a_path)}: {analysis.doc_a_purpose}")
            console.print(f"    {_short_path(analysis.doc_b_path)}: {analysis.doc_b_purpose}")
            for topic in analysis.topics:
                action = topic.action_for_other
                canonical = _short_path(topic.canonical)
                console.print(
                    f"    Topic: [bold]{topic.name}[/bold] → "
                    f"canonical: [green]{canonical}[/green], action: {action}"
                )
            console.print()

    coverage_clusters = _topic_document_clusters(result)
    if coverage_clusters:
        console.print("[bold]Topic Coverage Clusters:[/bold]", style="cyan")
        console.print(
            f"Found [bold]{len(coverage_clusters)}[/bold] canonical topics covered by 2+ documents"
        )
        for i, cluster in enumerate(coverage_clusters, 1):
            docs = cluster.get("documents", [])
            console.print(
                f'  {i}. [bold]"{cluster.get("topic", "(unnamed topic)")}"[/bold] '
                f"({len(docs)} documents, {cluster.get('mention_count', 0)} mentions)"
            )
            for doc in docs:
                console.print(f"     • {_short_path(doc)}")
        console.print()

    if result.topic_taxonomy:
        canonical_topics = result.topic_taxonomy.get("canonical_topics", [])
        if canonical_topics:
            console.print("[bold]Canonical Topics:[/bold]", style="cyan")
            for topic in canonical_topics[:10]:
                console.print(
                    f"  • [bold]{topic['name']}[/bold] "
                    f"({topic['document_count']} docs, {topic['mention_count']} mentions)"
                )
            console.print()

    docs_map = _docs_map(result)
    if docs_map:
        console.print(f"[bold]{DOCS_MAP}:[/bold]", style="cyan")
        console.print(
            f"  Topic groups: [bold]{len(docs_map.get('topic_tree', []))}[/bold], "
            f"facets: [bold]{len(docs_map.get('facets', {}))}[/bold], "
            f"diagnostics: [bold]{len(docs_map.get('diagnostics', []))}[/bold]"
        )
        for parent in docs_map.get("topic_tree", [])[:8]:
            children = parent.get("children", [])
            console.print(
                f"  • [bold]{parent.get('label', '(unnamed)')}[/bold] ({len(children)} children)"
            )
        console.print()

    # Refactoring Suggestions
    if suggestions:
        console.print("[bold]Refactoring Suggestions:[/bold]")
        for i, s in enumerate(suggestions, 1):
            code_name = s.get("code", "?")
            docs = s.get("documents", [])
            canonical = s.get("canonical", "?")
            console.print(f'  {i}. [bold]"{code_name}"[/bold] ({len(docs)} documents)')
            console.print(f"     → Canonical: [green]{_short_path(canonical)}[/green]")
            for sug in s.get("suggestions", []):
                doc = _short_path(sug.get("document", "?"))
                action = sug.get("action", "?")
                reason = sug.get("reason", "")
                console.print(f"     → {doc}: {action} — {reason}")
        console.print()


def render_markdown(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    settings: Settings | None = None,
    project_root: Path | None = None,
    stages_run: list[str] | None = None,
) -> str:
    """Render analysis results as markdown.

    When settings and project_root are provided, includes dashboard,
    recommendations, and methodology sections.

    Args:
        stages_run: List of track slugs that actually executed,
            e.g. ["docs-section-match", "docs-map", "docs-pair-review"].
    """
    lines: list[str] = []
    lines.append("# dryscope Report\n")

    has_settings = settings is not None and project_root is not None

    # Use provided stages or fall back to empty
    if stages_run is None:
        stages_run = []

    # Build recommendations early (needed for dashboard count)
    recommendations: list[dict] = []
    if has_settings and similarity_pairs:
        recommendations = build_recommendations(similarity_pairs, suggestions, project_root)

    # ── Dashboard ──────────────────────────────────────────────────────
    n_docs = len(result.documents)
    n_pairs = len(similarity_pairs)
    n_recs = len(recommendations)
    pipeline_dots = (
        "  ".join(f"● {DOCS_STAGE_LABELS.get(s, s)}" for s in stages_run) if stages_run else "—"
    )
    docs_map = _docs_map(result)
    n_profiled_docs = len(result.document_descriptors) or n_docs
    n_docs_map_groups = len(docs_map.get("topic_tree", []))
    n_docs_map_facets = len(docs_map.get("facets", {}))
    n_consolidation_clusters = len(_topic_document_clusters(result))
    docs_map_ran = bool(docs_map or result.document_descriptors or result.topic_taxonomy)
    section_match_ran = bool(DOCS_SECTION_MATCH_SLUG in set(stages_run) or similarity_pairs)

    metric_cards = [_metric_card(n_docs, "Documents")]
    track_bits: list[str] = []
    if docs_map_ran:
        metric_cards.extend(
            [
                _metric_card(n_docs_map_groups, "Docs Map Groups"),
                _metric_card(n_consolidation_clusters, "Docs Map Clusters"),
            ]
        )
        track_bits.append(
            f"{DOCS_MAP}: {n_profiled_docs} docs profiled, "
            f"{n_docs_map_groups} groups, {n_docs_map_facets} facets, "
            f"{n_consolidation_clusters} consolidation clusters."
        )
    if section_match_ran:
        metric_cards.extend(
            [
                _metric_card(n_pairs, "Matched Section Pairs"),
                _metric_card(n_recs, "Section Match Recs"),
            ]
        )
        track_bits.append(
            f"{DOCS_SECTION_MATCH}: {n_pairs} matched section pairs, {n_recs} recommendations."
        )
    if not docs_map_ran and not section_match_ran:
        metric_cards.append(_metric_card(len(result.chunks), "Sections"))
    track_summary = " ".join(track_bits) if track_bits else "No docs analysis tracks ran."

    # Scan context
    scan_path_str = str(project_root) if project_root else "unknown"
    git_name = ""
    if project_root:
        commit = _git_commit(project_root)
        if commit:
            git_name = f" ({project_root.name}, {commit[:8]})"
        else:
            git_name = f" ({project_root.name})"

    lines.append(
        '<div class="dashboard">\n'
        f"{''.join(metric_cards)}"
        f'  <div class="pipeline-bar">Pipeline: {pipeline_dots}</div>\n'
        f'  <div class="track-summary">{track_summary}</div>\n'
        f'  <div class="scan-context">Scanned: <code>{scan_path_str}</code>{git_name}</div>\n'
        "</div>\n"
    )

    overview = _build_run_overview(
        result,
        similarity_pairs,
        recommendations,
        stages_run=stages_run,
    )
    report_sections = _report_structure(
        overview,
        recommendations,
        result,
        similarity_pairs,
    )
    section_titles = {section["id"]: section["title_numbered"] for section in report_sections}
    child_titles = {
        child["id"]: child["title_numbered"]
        for section in report_sections
        for child in section.get("children", [])
    }

    # ── Run Overview ───────────────────────────────────────────────────
    lines.append(f"## {section_titles['run_overview']}\n")
    lines.append("### Capabilities Exercised\n")
    lines.append("| Capability | Ran | What It Does | Result |")
    lines.append("|------------|-----|--------------|--------|")
    for capability in overview["capabilities"].values():
        lines.append(
            f"| {capability['label']} "
            f"| {_ran_text(capability['ran'])} "
            f"| {capability['what_it_does']} "
            f"| {capability['result']} |"
        )
    lines.append("")

    lines.append("### Docs Track Summary\n")
    lines.append("| Aspect | Ran | Pipeline | Results |")
    lines.append("|--------|-----|----------|---------|")
    for aspect in overview["docs_track_aspects"].values():
        results = ", ".join(
            f"{key.replace('_', ' ')}: {value}" for key, value in aspect["results"].items()
        )
        lines.append(
            f"| {aspect['label']} "
            f"| {_ran_text(aspect['ran'])} "
            f"| {' -> '.join(aspect['pipeline'])} "
            f"| {results} |"
        )
    lines.append("")

    if result.documents:
        scanned_docs = [
            _display_path(doc.path, project_root)
            for doc in sorted(result.documents, key=lambda d: d.path)
        ]
        lines.append("### Scanned Documents\n")
        lines.append(
            _details_block(
                f"{len(scanned_docs)} documents scanned",
                _html_list(scanned_docs),
                class_name="report-list",
            )
        )
        lines.append("")

    # ── Docs Map ───────────────────────────────────────────────────────
    if docs_map:
        lines.append(f"## {section_titles['docs_map']}\n")
        lines.append(
            f"Method: `{docs_map.get('method', 'unknown')}`. "
            f"Top-level topic groups: {len(docs_map.get('topic_tree', []))}. "
            f"Facet dimensions: {len(docs_map.get('facets', {}))}. "
            f"Diagnostics: {len(docs_map.get('diagnostics', []))}.\n"
        )

        topic_tree = docs_map.get("topic_tree", [])
        if topic_tree:
            lines.append("### Discovered Topic Tree\n")
            for parent in topic_tree:
                label = parent.get("label") or "(unnamed group)"
                description = parent.get("description") or ""
                child_blocks: list[str] = []
                if description:
                    child_blocks.append(f"<p>{escape(str(description))}</p>")
                for child in parent.get("children", []):
                    child_label = child.get("label") or "(unnamed topic)"
                    doc_count = child.get("document_count", 0)
                    child_body: list[str] = []
                    child_desc = child.get("description")
                    if child_desc:
                        child_body.append(f"<p>{escape(str(child_desc))}</p>")
                    topics = child.get("topics", [])
                    if topics:
                        child_body.append(
                            _details_block(
                                f"{len(topics)} canonical labels",
                                _html_list([str(topic) for topic in topics]),
                                class_name="report-list",
                            )
                        )
                    documents = child.get("documents", [])
                    if documents:
                        child_body.append(
                            _details_block(
                                f"{len(documents)} documents",
                                _html_list(
                                    [_display_path(str(doc), project_root) for doc in documents]
                                ),
                                class_name="report-list",
                            )
                        )
                    child_blocks.append(
                        _details_block(
                            f"{child_label} ({doc_count} docs)",
                            "\n".join(child_body)
                            if child_body
                            else "<p>No additional details.</p>",
                            class_name="report-item",
                        )
                    )
                lines.append(
                    _details_block(
                        f"{label} ({len(parent.get('children', []))} topics)",
                        "\n".join(child_blocks) if child_blocks else "<p>No child topics.</p>",
                        class_name="report-item",
                        open_=True,
                    )
                )
            lines.append("")

        facets = docs_map.get("facets", {})
        if facets:
            lines.append("### Facets\n")
            for facet_name, facet in sorted(facets.items()):
                facet_body: list[str] = []
                description = facet.get("description") if isinstance(facet, dict) else ""
                if description:
                    facet_body.append(f"<p>{escape(str(description))}</p>")
                values = facet.get("values", []) if isinstance(facet, dict) else []
                for value in values:
                    label = value.get("value", "(unspecified)")
                    docs = value.get("documents", [])
                    evidence = value.get("evidence", [])
                    value_body: list[str] = []
                    if docs:
                        value_body.append(
                            _details_block(
                                f"{len(docs)} documents",
                                _html_list([_display_path(str(doc), project_root) for doc in docs]),
                                class_name="report-list",
                            )
                        )
                    if evidence:
                        value_body.append(
                            _details_block(
                                f"{len(evidence)} evidence items",
                                _html_text_list(evidence),
                                class_name="report-list",
                            )
                        )
                    facet_body.append(
                        _details_block(
                            f"{label} ({len(docs)} docs)",
                            "\n".join(value_body)
                            if value_body
                            else "<p>No additional details.</p>",
                            class_name="report-item",
                        )
                    )
                lines.append(
                    _details_block(
                        f"{facet_name} ({len(values)} values)",
                        "\n".join(facet_body) if facet_body else "<p>No facet values.</p>",
                        class_name="report-item",
                        open_=True,
                    )
                )
            lines.append("")

        diagnostics = docs_map.get("diagnostics", [])
        if diagnostics:
            lines.append("### Docs Map Diagnostics\n")
            lines.append("| Severity | Kind | Issue | Recommendation |")
            lines.append("|----------|------|-------|----------------|")
            for item in diagnostics:
                lines.append(
                    f"| {_markdown_table_cell(item.get('severity', ''))} "
                    f"| `{_markdown_table_cell(item.get('kind', ''))}` "
                    f"| {_markdown_table_cell(item.get('message', ''))} "
                    f"| {_markdown_table_cell(item.get('recommendation', ''))} |"
                )
            lines.append("")

    # ── Docs Map Clusters ──────────────────────────────────────────────
    coverage_clusters = _topic_document_clusters(result)
    if coverage_clusters:
        lines.append(f"## {section_titles['docs_map_clusters']}\n")
        lines.append(
            f"Found {len(coverage_clusters)} canonical labels covered by 2+ documents. "
            "These are candidates to inspect for consolidation, splitting, or stronger cross-links.\n"
        )
        for i, cluster in enumerate(coverage_clusters, 1):
            topic = cluster.get("topic") or "(unnamed topic)"
            docs = cluster.get("documents", [])
            mention_count = cluster.get("mention_count", 0)
            cluster_body = [
                _details_block(
                    f"{len(docs)} documents",
                    _html_list([_display_path(str(doc), project_root) for doc in docs]),
                    class_name="report-list",
                )
            ]
            aliases = cluster.get("aliases", [])
            if aliases:
                cluster_body.append(
                    _details_block(
                        f"{len(aliases)} aliases",
                        _html_list([str(alias) for alias in aliases]),
                        class_name="report-list",
                    )
                )
            lines.append(
                _details_block(
                    f"{i}. {topic} ({len(docs)} docs, {mention_count} mentions)",
                    "\n".join(cluster_body),
                    class_name="report-item",
                )
            )
        lines.append("")

    # ── Section Match ─────────────────────────────────────────────────
    lines.append(f"## {section_titles['docs_section_match']}\n")
    lines.append(
        "Section Match is the docs section-level pass: split documents into sections, "
        "embed them, and report matched cross-document section pairs.\n"
    )
    lines.append(f"Found {len(similarity_pairs)} matched section pairs.\n")

    if recommendations:
        lines.append(f"### {child_titles['docs_section_match_recommendations']}\n")
        lines.append(
            "These recommendations are derived from the matched section pairs in this track. "
            "Docs Map consolidation candidates are listed separately under "
            "Docs Map Clusters.\n"
        )
        for rec in recommendations:
            rec_body: list[str] = [
                f"<p><strong>Action:</strong> {escape(str(rec['suggested_action']))}</p>",
                f"<p><strong>Score:</strong> {escape(str(rec['priority_score']))}</p>",
                f"<p>{escape(str(rec['action_detail']))}</p>",
            ]
            file_items = [str(f["file"]) for f in rec["affected_files"]]
            rec_body.append(_html_list(file_items))
            lines.append(
                _details_block(
                    f"{rec['priority_rank']}. {rec['suggested_action'].title()} "
                    f"({rec['priority_score']} pts, {len(rec['affected_files'])} files)",
                    "\n".join(rec_body),
                    class_name="report-item",
                )
            )
        lines.append("")

    if similarity_pairs:
        lines.append(f"### {child_titles['matched_section_pairs']}\n")
        lines.append("| Similarity | Section A | Section B |")
        lines.append("|------------|-----------|-----------|")
        for pair in similarity_pairs:
            heading_a = " > ".join(pair.chunk_a.heading_path) or "(no heading)"
            heading_b = " > ".join(pair.chunk_b.heading_path) or "(no heading)"
            loc_a = f"`{_short_path(pair.chunk_a.document_path)}`: {heading_a}"
            loc_b = f"`{_short_path(pair.chunk_b.document_path)}`: {heading_b}"
            sim_str = (
                f"{pair.embedding_similarity:.3f}" if pair.embedding_similarity is not None else "—"
            )
            lines.append(f"| {sim_str} | {loc_a} | {loc_b} |")
        lines.append("")

    # ── Doc Pair Review ────────────────────────────────────────────────
    if result.doc_pair_analyses:
        lines.append(f"## {section_titles['docs_pair_review']}\n")
        lines.append(f"Analyzed {len(result.doc_pair_analyses)} document pairs\n")

        for analysis in result.doc_pair_analyses:
            name_a = _short_path(analysis.doc_a_path)
            name_b = _short_path(analysis.doc_b_path)
            lines.append(f"### `{name_a}` / `{name_b}`\n")
            lines.append(
                f"- **Relationship**: {analysis.relationship} ({analysis.confidence} confidence)"
            )
            lines.append(f"- **`{name_a}`**: {analysis.doc_a_purpose}")
            lines.append(f"- **`{name_b}`**: {analysis.doc_b_purpose}\n")

            if analysis.topics:
                lines.append("| Topic | Canonical | Action | Reason |")
                lines.append("|-------|-----------|--------|--------|")
                for topic in analysis.topics:
                    lines.append(
                        f"| `{topic.name}` | `{_short_path(topic.canonical)}` "
                        f"| {topic.action_for_other} | {topic.reason} |"
                    )
                lines.append("")

    if result.topic_taxonomy:
        canonical_topics = result.topic_taxonomy.get("canonical_topics", [])
        if canonical_topics:
            lines.append(f"## {section_titles['docs_map_taxonomy']}\n")
            lines.append(
                "Canonical labels are the normalized vocabulary produced from document "
                "descriptors. Document coverage for multi-document labels is listed above "
                "under Docs Map Clusters; this section gives the full "
                "vocabulary and alias map once.\n"
            )
            for topic in canonical_topics:
                name = topic.get("name", "(unnamed label)")
                aliases = topic.get("aliases", [])
                topic_body = [
                    f"<p><strong>Documents:</strong> {escape(str(topic.get('document_count', 0)))}</p>",
                    f"<p><strong>Mentions:</strong> {escape(str(topic.get('mention_count', 0)))}</p>",
                    _details_block(
                        f"{len(aliases)} aliases",
                        _html_list([str(alias) for alias in aliases]),
                        class_name="report-list",
                    ),
                ]
                lines.append(
                    _details_block(
                        f"{name} ({topic.get('document_count', 0)} docs, "
                        f"{topic.get('mention_count', 0)} mentions)",
                        "\n".join(topic_body),
                        class_name="report-item",
                    )
                )
            co_occurrence = result.topic_taxonomy.get("co_occurrence", [])
            if co_occurrence:
                lines.append("")
                co_items = []
                for item in co_occurrence:
                    topics = item.get("topics", [])
                    if len(topics) == 2:
                        co_items.append(f"{topics[0]} + {topics[1]} ({item.get('count')} docs)")
                lines.append(
                    _details_block(
                        f"{len(co_items)} co-occurring label pairs",
                        _html_text_list(co_items),
                        class_name="report-list",
                    )
                )
            lines.append("")

    # ── Refactoring Suggestions ────────────────────────────────────────
    if suggestions:
        lines.append("## Refactoring Suggestions\n")
        for i, s in enumerate(suggestions, 1):
            code_name = s.get("code", "?")
            docs = s.get("documents", [])
            canonical = s.get("canonical", "?")
            lines.append(f'{i}. **"{code_name}"** ({len(docs)} documents)')
            lines.append(f"   - Canonical: `{_short_path(canonical)}`")
            for sug in s.get("suggestions", []):
                doc = _short_path(sug.get("document", "?"))
                action = sug.get("action", "?")
                reason = sug.get("reason", "")
                lines.append(f"   - `{doc}`: {action} — {reason}")
            lines.append("")

    # ── Methodology ────────────────────────────────────────────────────
    lines.append(f"## {section_titles['methodology']}\n")
    lines.append("### Tracks\n")
    lines.append(
        "dryscope reports use stable track names and slugs. This report is for docs tracks:\n\n"
        f"1. **{DOCS_MAP}** (`{DOCS_MAP_SLUG}`) — Extracts document descriptors, canonicalizes aboutness and "
        "reader-intent labels, discovers an IA topic tree and facets, and lists multi-document "
        "consolidation clusters.\n"
        f"2. **{DOCS_SECTION_MATCH}** (`{DOCS_SECTION_MATCH_SLUG}`) — Splits documents into sections, generates API or local embeddings, "
        "finds cross-document section pairs above the similarity threshold, and produces section match "
        "recommendations.\n"
        f"3. **{DOCS_PAIR_REVIEW}** (`{DOCS_PAIR_REVIEW_SLUG}`) — Sends selected document pairs to an LLM for "
        "relationship classification, topic-level canonical/action assignments, and "
        "consolidation suggestions.\n"
    )
    lines.append("### Scoring\n")
    lines.append(
        "Each recommendation is scored 0–100 based on:\n\n"
        "- **Embedding similarity** (0–60 base): `similarity × 60`\n"
        "- **LLM confirmation** (+15): overlap confirmed by coding stage\n"
        "- **Multiple sections** (+5 each): additional overlapping section pairs\n"
        "- **Boilerplate penalty** (−15): structural/boilerplate overlap\n\n"
        "Raw score is normalized: `score × 100 / 80`.\n"
    )
    lines.append("### Actions\n")
    lines.append(
        "- **consolidate** — Near-identical content; merge into one location\n"
        "- **link** — Boilerplate/structural duplication; use shared include or cross-reference\n"
        "- **brief_reference** — Partial overlap; replace shorter version with a link to canonical\n"
        "- **keep** — Overlap is intentional or serves different audiences\n"
    )
    if has_settings:
        from dryscope import __version__

        meta = _build_metadata(settings, project_root)
        lines.append("### Configuration\n")
        lines.append(f"- **Date**: {meta['timestamp']}")
        lines.append(f"- **dryscope version**: {__version__}")
        if meta.get("git_commit"):
            lines.append(f"- **Git commit**: `{meta['git_commit'][:12]}`")
        lines.append(f"- **Similarity threshold**: {settings.threshold_similarity}")
        if settings.threshold_intent > 0:
            lines.append(f"- **Intent threshold**: {settings.threshold_intent}")
        lines.append(f"- **Embedding model**: {settings.docs_embedding_model}")
        lines.append(f"- **LLM model**: {settings.model}")
        lines.append("")

    return "\n".join(lines)


def render_json(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    settings: Settings | None = None,
    project_root: Path | None = None,
    stages_run: list[str] | None = None,
) -> str:
    """Render analysis results as JSON."""
    recommendations: list[dict] = []
    if settings is not None and project_root is not None:
        recommendations = build_recommendations(similarity_pairs, suggestions, project_root)
    overview = _build_run_overview(
        result,
        similarity_pairs,
        recommendations,
        stages_run=stages_run,
    )

    data: dict = {
        "report_pack": {
            "label": DOCS_REPORT_PACK,
            "slug": DOCS_REPORT_PACK_SLUG,
        },
        "summary": {
            "documents_scanned": len(result.documents),
            "chunks_analyzed": len(result.chunks),
            "matched_section_pairs_found": len(similarity_pairs),
            "section_match_recommendations_found": len(recommendations),
        },
        "report_structure": _report_structure(
            overview,
            recommendations,
            result,
            similarity_pairs,
        ),
    }

    if settings is not None and project_root is not None:
        data["metadata"] = _build_metadata(settings, project_root)
    if recommendations:
        data["summary"]["recommendations_count"] = len(recommendations)

    if result.categories:
        data["categories"] = {
            cat.name: {
                code.name: sorted({c.document_path for c in code.chunks}) for code in cat.codes
            }
            for cat in result.categories
        }

    if suggestions:
        data["refactoring_suggestions"] = suggestions

    return json.dumps(data, indent=2)


# ─── HTML Report ───────────────────────────────────────────────────────

_HTML_CSS = """\
:root { --bg: #fff; --fg: #1a1a2e; --muted: #6c757d; --border: #dee2e6;
        --accent: #0d6efd; --green: #198754; --amber: #fd7e14; --red: #dc3545; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: var(--fg);
       background: var(--bg); line-height: 1.6; }
h1 { border-bottom: 2px solid var(--accent); padding-bottom: .3em; }
h2 { border-bottom: 1px solid var(--border); padding-bottom: .2em; margin-top: 2rem; }
h3 { margin-top: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid var(--border); padding: .5em .75em; text-align: left; }
th { background: #f8f9fa; font-weight: 600; }
tr:nth-child(even) { background: #f8f9fa; }
code { background: #f1f3f5; padding: .15em .35em; border-radius: 3px; font-size: .9em; }
details { margin: .75em 0; border: 1px solid var(--border); border-radius: 4px; }
summary { padding: .5em .75em; cursor: pointer; font-weight: 600; background: #f8f9fa; }
summary:hover { background: #e9ecef; }
details[open] > summary { border-bottom: 1px solid var(--border); }
details > :not(summary) { padding: 0 .75em; }
.report-section { margin: 1.25rem 0; border-radius: 8px; }
.report-section > summary { padding: .75rem 1rem; }
.report-section-title { font-size: 1.35rem; font-weight: 700; color: var(--fg); }
.report-section > :not(summary) { padding-left: 1rem; padding-right: 1rem; }
.report-subsection { margin: .75rem 0; border-radius: 6px; }
.report-subsection > summary { padding: .55rem .75rem; }
.report-subsection-title { font-size: 1.05rem; font-weight: 650; color: var(--fg); }
.report-subsection > :not(summary) { padding-left: .75rem; padding-right: .75rem; }
.report-item { margin: .6rem 0; border-radius: 6px; background: #fff; }
.report-item > summary { background: #fff; }
.report-list { margin: .5rem 0; border-radius: 6px; background: #fff; }
.report-list > summary { background: #fff; font-size: .95rem; }
.report-list ul { margin: .5rem 0 .75rem; }
.badge { display: inline-block; padding: .15em .5em; border-radius: 3px;
         font-size: .85em; font-weight: 600; }
.badge-consolidate { background: #ffeeba; color: #856404; }
.badge-link { background: #b8daff; color: #004085; }
.badge-brief_reference, .badge-brief-reference { background: #d4edda; color: #155724; }
.badge-remove { background: #f8d7da; color: #721c24; }
.badge-high { background: var(--green); color: #fff; }
.badge-medium { background: var(--amber); color: #fff; }
.badge-low { background: var(--muted); color: #fff; }
ul { padding-left: 1.5em; }
/* Dashboard */
.dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem;
             margin: 1.5rem 0; }
.metric-card { background: #f8f9fa; border: 1px solid var(--border); border-radius: 8px;
               padding: 1rem; text-align: center; }
.metric-value { font-size: 2rem; font-weight: 700; color: var(--accent); }
.metric-label { font-size: .85rem; color: var(--muted); text-transform: uppercase;
                letter-spacing: .05em; }
.pipeline-bar { grid-column: 1 / -1; background: #f8f9fa; border: 1px solid var(--border);
                border-radius: 8px; padding: .6rem 1rem; font-size: .9rem; color: var(--fg); }
.track-summary { grid-column: 1 / -1; background: #fff; border: 1px solid var(--border);
                 border-radius: 8px; padding: .6rem 1rem; font-size: .9rem; color: var(--fg); }
.scan-context { grid-column: 1 / -1; padding: .4rem 1rem; font-size: .9rem; color: var(--muted); }
.scan-context code { font-size: .85rem; }
.file-list { grid-column: 1 / -1; border: 1px solid var(--border); border-radius: 6px;
             margin: 0; font-size: .85rem; }
.file-list summary { padding: .4rem .75rem; cursor: pointer; font-weight: 600;
                     background: #f8f9fa; font-size: .85rem; }
.file-list ol { padding: .5rem 1rem .5rem 2rem; margin: 0;
                columns: 2; column-gap: 2rem; }
.file-list li { padding: .1rem 0; }
/* Slider */
.slider-container { margin: 1rem 0; padding: .75rem 1rem; background: #f8f9fa;
                    border: 1px solid var(--border); border-radius: 6px;
                    display: flex; align-items: center; gap: 1rem; }
.slider-container label { font-weight: 600; white-space: nowrap; }
.slider-container input[type=range] { flex: 1; }
.slider-container .slider-value { font-weight: 700; color: var(--accent);
                                  min-width: 2.5em; text-align: center; }
"""


_SLIDER_JS = """\
<script>
(function() {
  var table = document.getElementById('rec-table');
  if (!table) return;
  var rows = table.querySelectorAll('tbody tr[data-score]');
  var slider = document.getElementById('score-slider');
  var label = document.getElementById('slider-label');
  var countEl = document.getElementById('rec-count');
  if (!slider) return;
  slider.oninput = function() {
    var thresh = parseInt(this.value, 10);
    label.textContent = thresh;
    var visible = 0;
    rows.forEach(function(row) {
      var show = parseInt(row.getAttribute('data-score'), 10) >= thresh;
      row.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    countEl.textContent = visible + ' of ' + rows.length;
  };
})();
</script>
"""


def render_html(markdown_content: str) -> str:
    """Convert markdown report to a self-contained HTML document.

    Uses mistune for markdown→HTML conversion, then wraps in a complete
    HTML document with embedded CSS. No external dependencies.
    """
    import re

    import mistune

    html_body = mistune.html(markdown_content)

    # Post-process: wrap Doc Pair Review h3 sections in <details>/<summary>
    # Each "### file_a / file_b" block becomes collapsible
    html_body = _wrap_doc_pairs_in_details(html_body)

    # Add badge classes to action keywords in table cells
    for keyword in ("consolidate", "link", "brief_reference", "brief-reference", "remove"):
        html_body = re.sub(
            rf"<td>\s*{re.escape(keyword)}\s*</td>",
            f'<td><span class="badge badge-{keyword}">{keyword}</span></td>',
            html_body,
            flags=re.IGNORECASE,
        )

    # Add data-score attributes to recommendation table rows and inject slider
    html_body = _inject_recommendation_slider(html_body)

    # Make report sections collapsible in HTML.
    html_body = _wrap_subsections_in_details(html_body)
    html_body = _wrap_top_level_sections_in_details(html_body)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>dryscope Report</title>\n"
        f"  <style>\n{_HTML_CSS}  </style>\n"
        "</head>\n"
        "<body>\n"
        f"{html_body}\n"
        f"{_SLIDER_JS}\n"
        "</body>\n"
        "</html>\n"
    )


def _wrap_doc_pairs_in_details(html: str) -> str:
    """Wrap Doc Pair Review h3 sections in collapsible <details> elements.

    Looks for h3 tags that follow the "file_a / file_b" pattern and wraps
    each h3 + its following content (until the next h2/h3 or end) in a
    <details><summary> block.
    """
    import re

    # Match h3 headers containing " / " (doc-pair pattern, may contain <code> tags)
    pattern = r"(<h3>(.*?/.*?)</h3>)"
    parts = re.split(pattern, html)

    if len(parts) <= 1:
        return html

    # Rebuild: parts[0] is before first match, then groups of (full_match, tag_content, inner_text, after)
    rebuilt: list[str] = [parts[0]]
    i = 1
    while i < len(parts):
        h3_text = parts[i + 1]  # inner text
        # Content after this h3, up to next section
        after = parts[i + 2] if i + 2 < len(parts) else ""

        # Split 'after' at the next h2 or h3 boundary
        next_heading = re.search(r"(?=<h[23]>)", after)
        if next_heading:
            section_content = after[: next_heading.start()]
            remaining = after[next_heading.start() :]
        else:
            section_content = after
            remaining = ""

        rebuilt.append(
            f"<details>\n<summary>{h3_text.strip()}</summary>\n{section_content}\n</details>\n"
        )
        rebuilt.append(remaining)
        i += 3

    return "".join(rebuilt)


def _wrap_top_level_sections_in_details(html: str) -> str:
    """Wrap each top-level h2 report section in an open collapsible details block."""
    import re

    pattern = r"(<h2>(.*?)</h2>)"
    parts = re.split(pattern, html)
    if len(parts) <= 1:
        return html

    rebuilt: list[str] = [parts[0]]
    i = 1
    while i < len(parts):
        section_title = parts[i + 1].strip()
        after = parts[i + 2] if i + 2 < len(parts) else ""
        next_heading = re.search(r"(?=<h2>)", after)
        if next_heading:
            section_content = after[: next_heading.start()]
            remaining = after[next_heading.start() :]
        else:
            section_content = after
            remaining = ""
        rebuilt.append(
            '<details class="report-section" open>\n'
            f'<summary><span class="report-section-title">{section_title}</span></summary>\n'
            f"{section_content}\n"
            "</details>\n"
        )
        rebuilt.append(remaining)
        i += 3

    return "".join(rebuilt)


def _wrap_subsections_in_details(html: str) -> str:
    """Wrap each h3 subsection in an open collapsible details block."""
    import re

    pattern = r"(<h3>(.*?)</h3>)"
    parts = re.split(pattern, html)
    if len(parts) <= 1:
        return html

    rebuilt: list[str] = [parts[0]]
    i = 1
    while i < len(parts):
        subsection_title = parts[i + 1].strip()
        after = parts[i + 2] if i + 2 < len(parts) else ""
        next_top_level = re.search(r"(?=<h2>)", after)
        if next_top_level:
            subsection_content = after[: next_top_level.start()]
            remaining = after[next_top_level.start() :]
        else:
            subsection_content = after
            remaining = ""
        rebuilt.append(
            '<details class="report-subsection" open>\n'
            f'<summary><span class="report-subsection-title">{subsection_title}</span></summary>\n'
            f"{subsection_content}\n"
            "</details>\n"
        )
        rebuilt.append(remaining)
        i += 3

    return "".join(rebuilt)


def _inject_recommendation_slider(html: str) -> str:
    """Add data-score attributes to recommendation table rows and inject a slider.

    Finds the first table after the Section Match Recommendations heading,
    adds data-score to each body row, wraps it with an id, and inserts a range
    slider above it.
    """
    import re

    # Find the section-similarity recommendations heading and the first table after it.
    rec_match = re.search(
        r"<h[23][^>]*>(?:\d+(?:\.\d+)*\.\s*)?Section Match Recommendations</h[23]>",
        html,
        re.IGNORECASE,
    )
    if not rec_match:
        return html

    # Find the first <table> after the recommendations heading.
    next_heading = re.search(r"<h[23][^>]*>", html[rec_match.end() :], flags=re.IGNORECASE)
    section_end = rec_match.end() + next_heading.start() if next_heading else len(html)
    table_start = html.find("<table>", rec_match.end())
    if table_start == -1 or table_start >= section_end:
        return html
    table_end = html.find("</table>", table_start)
    if table_end == -1:
        return html
    table_end += len("</table>")

    table_html = html[table_start:table_end]

    # Add data-score to each <tr> in tbody by extracting the score from the second <td>
    def _add_data_score(match: re.Match) -> str:
        row = match.group(0)
        # Extract score from second td (first td is rank #)
        tds = re.findall(r"<td>(.*?)</td>", row)
        if len(tds) >= 2:
            try:
                score = int(tds[1].strip())
                return row.replace("<tr>", f'<tr data-score="{score}">', 1)
            except ValueError:
                pass
        return row

    # Only process rows in tbody (skip header row)
    thead_end = table_html.find("</thead>")
    if thead_end != -1:
        thead_part = table_html[: thead_end + len("</thead>")]
        tbody_part = table_html[thead_end + len("</thead>") :]
    else:
        # No explicit thead — skip the first <tr> (header row)
        first_tr_end = table_html.find("</tr>") + len("</tr>")
        thead_part = table_html[:first_tr_end]
        tbody_part = table_html[first_tr_end:]

    tbody_part = re.sub(r"<tr>.*?</tr>", _add_data_score, tbody_part, flags=re.DOTALL)

    new_table = f'<table id="rec-table">{thead_part[len("<table>") :]}{tbody_part}'

    # Count rows for slider label
    row_count = len(re.findall(r"data-score=", tbody_part))

    slider_html = (
        '<div class="slider-container">'
        '<label for="score-slider">Min score:</label>'
        '<input type="range" id="score-slider" min="0" max="100" value="0">'
        '<span class="slider-value" id="slider-label">0</span>'
        f'<span id="rec-count">{row_count} of {row_count}</span>'
        "</div>\n"
    )

    return html[:table_start] + slider_html + new_table + html[table_end:]


# ─── LLM-Friendly Output Helpers ───────────────────────────────────────


def _relative_path(path: str | None, root: Path) -> str | None:
    """Absolute path → relative to project root. Falls back to original if not under root."""
    if not path:
        return None
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def _git_commit(root: Path) -> str | None:
    """Get current git commit hash, or None if not a git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _build_metadata(settings: Settings, project_root: Path) -> dict:
    """Build metadata dict for JSON outputs."""
    from dryscope import __version__

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "git_commit": _git_commit(project_root),
        "dryscope_version": __version__,
        "config": {
            "threshold_similarity": settings.threshold_similarity,
            "threshold_intent": settings.threshold_intent,
            "include": settings.include,
            "exclude": settings.exclude,
            "model": settings.model,
            "embedding_model": settings.docs_embedding_model,
            "docs_map_facet_dimensions": settings.docs_map_facet_dimensions,
            "docs_map_facet_values": settings.docs_map_facet_values,
        },
    }


def _pair_to_rich_dict(pair: OverlapPair, root: Path) -> dict:
    """Convert an OverlapPair to an LLM-friendly dict with relative paths and snippets."""

    def _chunk_dict(chunk):
        return {
            "file": _relative_path(chunk.document_path, root),
            "heading_path": chunk.heading_path,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "content_snippet": chunk.content[:300],
        }

    return {
        # Keys for deserialization (matching back to in-memory Chunk objects)
        "chunk_a_key": f"{pair.chunk_a.document_path}:{pair.chunk_a.line_start}",
        "chunk_b_key": f"{pair.chunk_b.document_path}:{pair.chunk_b.line_start}",
        "chunk_a": _chunk_dict(pair.chunk_a),
        "chunk_b": _chunk_dict(pair.chunk_b),
        "embedding_similarity": pair.embedding_similarity,
        "shared_codes": pair.shared_codes,
    }


# ─── Stage Serializers ─────────────────────────────────────────────────


def serialize_section_match_stage(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    settings: Settings,
    project_root: Path,
) -> dict:
    """Serialize Section Match output for persistent storage."""
    return {
        "track": DOCS_SECTION_MATCH,
        "track_slug": DOCS_SECTION_MATCH_SLUG,
        "metadata": _build_metadata(settings, project_root),
        "summary": {
            "documents_scanned": len(result.documents),
            "chunks_analyzed": len(result.chunks),
            "matched_section_pairs_found": len(similarity_pairs),
            "threshold": settings.threshold_similarity,
            "model": settings.docs_embedding_model,
        },
        "matched_section_pairs": [_pair_to_rich_dict(p, project_root) for p in similarity_pairs],
    }


def serialize_doc_pair_review_stage(
    codes: list[Code],
    categories: list[Category],
    suggestions: list[dict] | None,
    settings: Settings,
    project_root: Path,
    analyses: list[DocPairAnalysis] | None = None,
) -> dict:
    """Serialize Doc Pair Review output for persistent storage."""
    data: dict = {
        "track": DOCS_PAIR_REVIEW,
        "track_slug": DOCS_PAIR_REVIEW_SLUG,
        "metadata": _build_metadata(settings, project_root),
        "summary": {
            "codes_found": len(codes),
            "categories_found": len(categories),
            "model": settings.model,
        },
        "categories": {
            cat.name: {
                code.name: sorted(
                    {_relative_path(c.document_path, project_root) for c in code.chunks}
                )
                for code in cat.codes
            }
            for cat in categories
        },
        "refactoring_suggestions": suggestions or [],
    }
    if analyses:
        data["summary"]["doc_pairs_analyzed"] = len(analyses)
        data["doc_pair_analyses"] = [
            {
                "doc_a": _relative_path(a.doc_a_path, project_root),
                "doc_b": _relative_path(a.doc_b_path, project_root),
                "doc_a_purpose": a.doc_a_purpose,
                "doc_b_purpose": a.doc_b_purpose,
                "relationship": a.relationship,
                "confidence": a.confidence,
                "topics": [
                    {
                        "name": t.name,
                        "canonical": _relative_path(t.canonical, project_root),
                        "action_for_other": t.action_for_other,
                        "reason": t.reason,
                    }
                    for t in a.topics
                ],
            }
            for a in analyses
        ]
    return data


# ─── Prioritized Recommendations ───────────────────────────────────────

_BOILERPLATE_KEYWORDS = {
    "table of contents",
    "toc",
    "license",
    "changelog",
    "change log",
    "release notes",
    "contributing",
    "code of conduct",
}


def _is_boilerplate(pair: OverlapPair) -> bool:
    """Check if a pair likely represents structural boilerplate."""
    for chunk in (pair.chunk_a, pair.chunk_b):
        heading_text = " ".join(chunk.heading_path).lower()
        if any(kw in heading_text for kw in _BOILERPLATE_KEYWORDS):
            return True
        if any(kw in chunk.content[:200].lower() for kw in _BOILERPLATE_KEYWORDS):
            return True
    return False


def _classify_overlap(pair: OverlapPair) -> str:
    """Classify the type of overlap."""
    if _is_boilerplate(pair):
        return "structural_boilerplate"
    if pair.embedding_similarity is not None and pair.embedding_similarity > 0.9:
        return "content_duplication"
    return "partial_overlap"


def _suggest_action(overlap_type: str, pair: OverlapPair) -> str:
    """Suggest an action based on overlap type."""
    if overlap_type == "structural_boilerplate":
        return "link"
    if overlap_type == "content_duplication":
        return "consolidate"
    # partial_overlap
    if pair.embedding_similarity is not None and pair.embedding_similarity > 0.95:
        return "consolidate"
    return "brief_reference"


_MAX_RAW_SCORE = 80  # 1.0×60 + 15 coding + 5 section


def _merge_sections(sections: list[dict]) -> list[dict]:
    """Deduplicate section references while preserving order."""
    seen: set[tuple[tuple[str, ...], tuple[int, int]]] = set()
    merged: list[dict] = []
    for section in sections:
        heading = tuple(section.get("sections", []))
        line_range_raw = section.get("line_range", [])
        if len(line_range_raw) == 2:
            line_range = (line_range_raw[0], line_range_raw[1])
        else:
            line_range = (-1, -1)
        key = (heading, line_range)
        if key in seen:
            continue
        seen.add(key)
        merged.append(section)
    return merged


def _recommendation_family_key(rec: dict) -> tuple[str, str, str, str]:
    """Key for grouping related pairwise recommendations into doc families."""
    files = [f["file"] for f in rec["affected_files"]]
    dirs = [str(Path(f).parent) for f in files]
    common_dir = dirs[0] if len(set(dirs)) == 1 else ""
    suffixes = sorted({Path(f).suffix for f in files})
    suffix_key = ",".join(suffixes)
    return (
        rec["suggested_action"],
        rec["overlap_type"],
        common_dir,
        suffix_key,
    )


def _merge_related_recommendations(recommendations: list[dict]) -> list[dict]:
    """Merge dense families of pairwise recommendations into grouped recs."""
    buckets: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for rec in recommendations:
        buckets[_recommendation_family_key(rec)].append(rec)

    merged_output: list[dict] = []
    for recs in buckets.values():
        remaining = list(recs)
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]

            changed = True
            while changed:
                changed = False
                next_remaining: list[dict] = []
                current_files = {f["file"] for rec in cluster for f in rec["affected_files"]}
                for rec in remaining:
                    rec_files = {f["file"] for f in rec["affected_files"]}
                    if current_files & rec_files:
                        cluster.append(rec)
                        changed = True
                    else:
                        next_remaining.append(rec)
                remaining = next_remaining

            cluster_files = {f["file"] for rec in cluster for f in rec["affected_files"]}
            if len(cluster) < 2 or len(cluster_files) < 3:
                merged_output.extend(cluster)
                continue

            sections_by_file: dict[str, list[dict]] = defaultdict(list)
            best_similarity = 0.0
            best_score = 0
            for rec in cluster:
                best_similarity = max(best_similarity, rec.get("embedding_similarity") or 0.0)
                best_score = max(best_score, rec.get("priority_score") or 0)
                for file_entry in rec["affected_files"]:
                    sections_by_file[file_entry["file"]].extend(file_entry.get("sections", []))

            affected_files = [
                {"file": file, "sections": _merge_sections(sections)}
                for file, sections in sorted(sections_by_file.items())
            ]
            action = seed["suggested_action"]
            overlap_type = seed["overlap_type"]
            group_score = min(
                100, max(best_score, best_score + min(15, 3 * (len(cluster_files) - 2)))
            )
            file_list = ", ".join(f"`{Path(f).name}`" for f in sorted(cluster_files)[:4])
            if len(cluster_files) > 4:
                file_list += f", and {len(cluster_files) - 4} more"
            if action == "consolidate":
                detail = (
                    f"A family of {len(cluster_files)} documents shares highly similar content "
                    f"across {len(cluster)} pairwise overlaps ({file_list}). "
                    "Consider extracting a shared canonical reference and replacing repeated copies with links."
                )
            elif action == "link":
                detail = (
                    f"A family of {len(cluster_files)} documents repeats the same structural or reference material "
                    f"across {len(cluster)} pairwise overlaps ({file_list}). "
                    "Consider one shared include/reference instead of repeating the content pairwise."
                )
            else:
                detail = (
                    f"A family of {len(cluster_files)} documents overlaps across {len(cluster)} pairwise matches "
                    f"({file_list}). Consider keeping one canonical explanation and replacing the rest with brief references."
                )

            merged_output.append(
                {
                    "priority_score": group_score,
                    "affected_files": affected_files,
                    "overlap_type": overlap_type,
                    "embedding_similarity": round(best_similarity, 4),
                    "suggested_action": action,
                    "action_detail": detail,
                }
            )

    merged_output.sort(key=lambda r: r["priority_score"], reverse=True)
    for i, rec in enumerate(merged_output, 1):
        rec["priority_rank"] = i
    return merged_output


def build_recommendations(
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    project_root: Path,
) -> list[dict]:
    """Build prioritized recommendations from overlap data.

    Groups overlapping pairs by file-pair, scores and ranks them.
    """
    # Codes that appear in suggestions
    suggestion_codes: set[str] = set()
    if suggestions:
        for s in suggestions:
            suggestion_codes.add(s.get("code", ""))

    # Group pairs by file-pair
    file_pair_groups: dict[tuple[str, str], list[OverlapPair]] = defaultdict(list)
    for pair in similarity_pairs:
        fa = _relative_path(pair.chunk_a.document_path, project_root)
        fb = _relative_path(pair.chunk_b.document_path, project_root)
        key = (min(fa, fb), max(fa, fb))
        file_pair_groups[key].append(pair)

    recommendations: list[dict] = []

    for (file_a, file_b), pairs in file_pair_groups.items():
        # Use the best (highest) similarity score
        best_pair = max(pairs, key=lambda p: p.embedding_similarity or 0)
        best_similarity = (
            best_pair.embedding_similarity if best_pair.embedding_similarity is not None else 0
        )

        has_coding = bool(
            best_pair.shared_codes and any(c in suggestion_codes for c in best_pair.shared_codes)
        )

        # Priority scoring
        score = best_similarity * 60
        if has_coding:
            score += 15
        if len(pairs) > 1:
            score += 5 * (len(pairs) - 1)
        overlap_type = _classify_overlap(best_pair)
        if overlap_type == "structural_boilerplate":
            score -= 15

        # Collect affected sections
        sections_a: list[dict] = []
        sections_b: list[dict] = []
        for p in pairs:
            sections_a.append(
                {
                    "sections": p.chunk_a.heading_path or ["(no heading)"],
                    "line_range": [p.chunk_a.line_start, p.chunk_a.line_end],
                }
            )
            sections_b.append(
                {
                    "sections": p.chunk_b.heading_path or ["(no heading)"],
                    "line_range": [p.chunk_b.line_start, p.chunk_b.line_end],
                }
            )

        action = _suggest_action(overlap_type, best_pair)

        # Normalize score to 0-100
        score = min(100, max(0, round(score * 100 / _MAX_RAW_SCORE)))

        # Build human-readable detail
        if action == "consolidate":
            detail = (
                f"These sections in `{file_a}` and `{file_b}` contain "
                f"{'near-identical' if best_similarity > 0.95 else 'highly similar'} content. "
                f"Consider consolidating into one location and linking from the other."
            )
        elif action == "link":
            detail = (
                f"Boilerplate/structural content duplicated between `{file_a}` and `{file_b}`. "
                f"Consider using a shared include or cross-reference link."
            )
        elif action == "remove":
            detail = (
                f"Redundant content in `{file_a}` and `{file_b}` that could be removed "
                f"from one document."
            )
        else:
            detail = (
                f"Partial overlap between `{file_a}` and `{file_b}`. "
                f"Consider replacing the shorter version with a brief reference to the canonical source."
            )

        recommendations.append(
            {
                "priority_score": score,
                "affected_files": [
                    {"file": file_a, "sections": sections_a},
                    {"file": file_b, "sections": sections_b},
                ],
                "overlap_type": overlap_type,
                "embedding_similarity": (
                    round(best_similarity, 4) if best_similarity is not None else None
                ),
                "suggested_action": action,
                "action_detail": detail,
            }
        )

    return _merge_related_recommendations(recommendations)


# ─── Final Report ───────────────────────────────────────────────────────


def render_final_report(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    settings: Settings,
    project_root: Path,
    stages_run: list[str] | None = None,
) -> dict:
    """Build the complete report.json for persistent storage."""
    recommendations = build_recommendations(
        similarity_pairs,
        suggestions,
        project_root,
    )
    overview = _build_run_overview(
        result,
        similarity_pairs,
        recommendations,
        stages_run=stages_run,
    )

    report: dict = {
        "metadata": _build_metadata(settings, project_root),
        "summary": {
            "documents_scanned": len(result.documents),
            "chunks_analyzed": len(result.chunks),
            "matched_section_pairs_found": len(similarity_pairs),
            "recommendations_count": len(recommendations),
            "section_match_recommendations_found": len(recommendations),
        },
        "report_structure": _report_structure(
            overview,
            recommendations,
            result,
            similarity_pairs,
        ),
    }

    return report
