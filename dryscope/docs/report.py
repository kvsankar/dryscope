"""Report generation (terminal/Rich, markdown, JSON)."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from importlib import metadata as importlib_metadata
from pathlib import Path, PureWindowsPath
from typing import cast
from urllib.parse import unquote, urlparse

from rich.console import Console
from rich.markup import escape as escape_markup
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


@dataclass
class MarkdownContext:
    has_settings: bool
    recommendations: list[dict]
    docs_map: dict
    overview: dict
    section_titles: dict[str, str]
    child_titles: dict[str, str]
    candidate_pairs: list[OverlapPair]


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


def _doc_pair_action_count(result: AnalysisResult) -> int:
    """Count actionable topic suggestions produced by Doc Pair Review."""
    return sum(
        1
        for analysis in result.doc_pair_analyses
        if not analysis.analysis_error
        for topic in analysis.topics
        if topic.action_for_other != "keep"
    )


def _doc_pair_relationship_count(result: AnalysisResult) -> int:
    """Count successfully synthesized document relationships."""
    return sum(1 for analysis in result.doc_pair_analyses if not analysis.analysis_error)


def _status_exception_detail(status: dict, project_root: Path | None = None) -> str:
    """Return one report-safe line of actionable stage failure detail."""
    detail = " ".join(str(status.get("exception_message") or "").split())
    if not detail:
        return "-"
    if project_root is not None:
        detail = detail.replace(str(project_root.resolve()), ".")
    return _redact_machine_paths(detail)


def _join_count_phrases(phrases: list[str]) -> str:
    """Join counted report signals into one readable clause."""
    if len(phrases) < 2:
        return phrases[0] if phrases else ""
    if len(phrases) == 2:
        return " and ".join(phrases)
    return f"{', '.join(phrases[:-1])}, and {phrases[-1]}"


def _report_outcome(result: AnalysisResult, strict_pairs: list[OverlapPair]) -> dict:
    """Classify a report without equating a strict zero with no overlap."""
    docs_map = _docs_map(result)
    unavailable = [
        name
        for name, status in result.stage_status.items()
        if status.get("status") in {"degraded", "failed"}
        or (status.get("status") == "skipped" and status.get("unavailable_conclusions"))
    ]
    relationship_count = _doc_pair_relationship_count(result)
    action_count = _doc_pair_action_count(result)
    signal_counts = {
        "strict_section_pairs": len(strict_pairs),
        "semantic_candidates": len(result.candidate_overlaps),
        "docs_map_clusters": len(_topic_document_clusters(result)),
        "docs_map_diagnostics": len(docs_map.get("diagnostics", [])),
        "document_intent_relationships": relationship_count,
        "refactoring_reference_suggestions": action_count,
    }
    signal_phrases = [
        _plural(signal_counts["strict_section_pairs"], "strict section pair"),
        _plural(signal_counts["semantic_candidates"], "semantic candidate"),
        _plural(signal_counts["docs_map_clusters"], "Docs Map coverage cluster"),
        _plural(signal_counts["docs_map_diagnostics"], "Docs Map diagnostic"),
        _plural(
            signal_counts["document_intent_relationships"],
            "document-intent relationship",
        ),
        _plural(
            signal_counts["refactoring_reference_suggestions"],
            "refactoring/reference suggestion",
        ),
    ]
    surfaced = _join_count_phrases(
        [
            phrase
            for phrase, count in zip(signal_phrases, signal_counts.values(), strict=True)
            if count
        ]
    )
    if unavailable:
        status = "degraded"
        statement = (
            (
                f"The run surfaced {surfaced}, but is degraded; "
                if surfaced
                else "The run is degraded; "
            )
            + "some conclusions are unavailable. Empty outputs from affected stages are not "
            "clean-negative evidence."
        )
    elif surfaced:
        status = "findings"
        statement = f"The preflight surfaced {surfaced} for review."
    else:
        status = "clean-negative"
        statement = (
            "No candidates were surfaced by the completed stages for this exact scanned corpus and "
            "configuration. This is a preflight result, not proof that no overlap exists."
        )
    return {
        "status": status,
        "statement": statement,
        "strict_threshold_result": (
            f"{len(strict_pairs)} section pairs at or above the configured strict threshold; "
            "pairs below it may still appear in the semantic-candidate or document-intent tracks."
        ),
        "degraded_stages": unavailable,
        "signals": signal_counts,
    }


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
    doc_pair_actions = _doc_pair_action_count(result)
    outcome = _report_outcome(result, similarity_pairs)
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
                    f"{_plural(len(result.candidate_overlaps), 'semantic candidate')}, "
                    f"{_plural(_doc_pair_relationship_count(result), 'document-intent relationship')}, "
                    f"{_plural(doc_pair_actions, 'document-level suggestion')}."
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
                    "semantic_candidates": len(result.candidate_overlaps),
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
                "relationships_found": _doc_pair_relationship_count(result),
                "recommendations_found": doc_pair_actions,
            },
            "stages_run": stages_run or [],
            "stage_status": result.stage_status,
            "outcome": outcome,
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
        "embedding_cosine": pair.embedding_cosine,
        "token_similarity": pair.token_similarity,
        "combined_similarity": pair.combined_score,
        "confidence": pair.confidence,
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
        "analysis_error": analysis.analysis_error,
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
    semantic_candidates = [_pair_to_dict(pair) for pair in result.candidate_overlaps]
    sections: list[dict] = [
        {
            "id": "run_overview",
            "title": "Run Overview",
            "data": {
                "overview": overview,
                "scanned_documents": [
                    doc.path for doc in sorted(result.documents, key=lambda d: d.path)
                ],
                "stage_status": result.stage_status,
                "outcome": _report_outcome(result, similarity_pairs),
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
                "semantic_candidates": len(result.candidate_overlaps),
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
                {
                    "id": "semantic_candidates",
                    "title": "Below-Threshold Semantic Candidates",
                    "slug": DOCS_SECTION_MATCH_SLUG,
                    "data": semantic_candidates,
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


def _html_list(items: Sequence[object]) -> str:
    """Return a full escaped HTML list for collapsible markdown sections."""
    if not items:
        return "<p>None.</p>"
    rows = "\n".join(f"  <li>{_html_code(item)}</li>" for item in items)
    return f"<ul>\n{rows}\n</ul>"


def _html_text_list(items: Sequence[object]) -> str:
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


def _score_text(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "-"


def _render_terminal_section_match(
    console: Console,
    similarity_pairs: list[OverlapPair],
    candidate_pairs: list[OverlapPair],
) -> None:
    console.print(f"[bold]{DOCS_SECTION_MATCH}[/bold]", style="cyan")
    console.print(
        f"Found [bold]{len(similarity_pairs)}[/bold] strict matched section pairs and "
        f"[bold]{len(candidate_pairs)}[/bold] bounded semantic candidates"
    )
    if not similarity_pairs:
        console.print(
            "[yellow]No section pairs were above the configured strict threshold; "
            "this does not mean the corpus has no overlap.[/yellow]"
        )
    console.print()

    displayed_pairs = [*similarity_pairs[:10], *candidate_pairs[:10]]
    if not displayed_pairs:
        return
    table = Table(title="Top Section Match Results", show_lines=True)
    table.add_column("Band", style="cyan", width=18)
    table.add_column("Cosine", style="yellow", width=8)
    table.add_column("Token", style="yellow", width=8)
    table.add_column("Combined", style="yellow", width=9)
    table.add_column("Section A", style="green")
    table.add_column("Section B", style="green")

    for pair in displayed_pairs:
        heading_a = " > ".join(pair.chunk_a.heading_path) or "(no heading)"
        heading_b = " > ".join(pair.chunk_b.heading_path) or "(no heading)"
        loc_a = f"{_short_path(pair.chunk_a.document_path)}: {heading_a}"
        loc_b = f"{_short_path(pair.chunk_b.document_path)}: {heading_b}"
        table.add_row(
            pair.confidence,
            _score_text(pair.embedding_cosine),
            _score_text(pair.token_similarity),
            _score_text(pair.combined_score),
            loc_a,
            loc_b,
        )

    console.print(table)
    console.print()


def _render_terminal_doc_pair_review(console: Console, result: AnalysisResult) -> None:
    if not result.doc_pair_analyses:
        return
    console.print(f"[bold]{DOCS_PAIR_REVIEW}[/bold]", style="cyan")
    console.print(f"Analyzed [bold]{len(result.doc_pair_analyses)}[/bold] document pairs")
    console.print()

    for analysis in result.doc_pair_analyses:
        if analysis.analysis_error:
            detail = _redact_machine_paths(analysis.analysis_error)
            console.print(
                f"  [bold]{_short_path(analysis.doc_a_path)}[/bold] -> "
                f"[bold]{_short_path(analysis.doc_b_path)}[/bold] "
                "([yellow]analysis unavailable[/yellow])"
            )
            console.print(f"    Failure: {detail}", markup=False)
            console.print()
            continue
        rel = analysis.relationship
        conf = analysis.confidence
        console.print(
            f"  [bold]{_short_path(analysis.doc_a_path)}[/bold] "
            f"{'<->' if rel == 'complementary' else '->'} "
            f"[bold]{_short_path(analysis.doc_b_path)}[/bold] "
            f"([dim]{rel}[/dim], {conf} confidence)"
        )
        console.print(f"    {_short_path(analysis.doc_a_path)}: {analysis.doc_a_purpose}")
        console.print(f"    {_short_path(analysis.doc_b_path)}: {analysis.doc_b_purpose}")
        for topic in analysis.topics:
            canonical = _short_path(topic.canonical)
            console.print(
                f"    Topic: [bold]{topic.name}[/bold] -> "
                f"canonical: [green]{canonical}[/green], action: {topic.action_for_other}"
            )
        console.print()


def _render_terminal_topic_clusters(console: Console, result: AnalysisResult) -> None:
    coverage_clusters = _topic_document_clusters(result)
    if not coverage_clusters:
        return
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
            console.print(f"     - {_short_path(doc)}")
    console.print()


def _render_terminal_taxonomy(console: Console, result: AnalysisResult) -> None:
    if not result.topic_taxonomy:
        return
    canonical_topics = result.topic_taxonomy.get("canonical_topics", [])
    if not canonical_topics:
        return
    console.print("[bold]Canonical Topics:[/bold]", style="cyan")
    for topic in canonical_topics[:10]:
        console.print(
            f"  - [bold]{topic['name']}[/bold] "
            f"({topic['document_count']} docs, {topic['mention_count']} mentions)"
        )
    console.print()


def _render_terminal_docs_map(console: Console, result: AnalysisResult) -> None:
    docs_map = _docs_map(result)
    if not docs_map:
        return
    console.print(f"[bold]{DOCS_MAP}:[/bold]", style="cyan")
    console.print(
        f"  Topic groups: [bold]{len(docs_map.get('topic_tree', []))}[/bold], "
        f"facets: [bold]{len(docs_map.get('facets', {}))}[/bold], "
        f"diagnostics: [bold]{len(docs_map.get('diagnostics', []))}[/bold]"
    )
    for parent in docs_map.get("topic_tree", [])[:8]:
        children = parent.get("children", [])
        console.print(
            f"  - [bold]{parent.get('label', '(unnamed)')}[/bold] ({len(children)} children)"
        )
    console.print()


def _render_terminal_suggestions(console: Console, suggestions: list[dict] | None) -> None:
    if not suggestions:
        return
    console.print("[bold]Refactoring Suggestions:[/bold]")
    for i, s in enumerate(suggestions, 1):
        code_name = s.get("code", "?")
        docs = s.get("documents", [])
        canonical = s.get("canonical", "?")
        console.print(f'  {i}. [bold]"{code_name}"[/bold] ({len(docs)} documents)')
        console.print(f"     -> Canonical: [green]{_short_path(canonical)}[/green]")
        for sug in s.get("suggestions", []):
            doc = _short_path(sug.get("document", "?"))
            action = sug.get("action", "?")
            reason = sug.get("reason", "")
            console.print(f"     -> {doc}: {action} - {reason}")
    console.print()


def render_terminal(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    console: Console | None = None,
    settings: Settings | None = None,
    project_root: Path | None = None,
    stages_run: list[str] | None = None,
) -> None:
    """Render analysis results to terminal using Rich."""
    if console is None:
        console = Console(stderr=True)

    console.print()
    console.print(Panel.fit("[bold]dryscope Report[/bold]", style="blue"))
    console.print()
    console.print(
        f"Scanned: [bold]{len(result.documents)}[/bold] documents, "
        f"[bold]{len(result.chunks)}[/bold] sections/fragments"
    )
    console.print(
        "[dim]Scope boundary: conclusions apply only to the exact input files listed in this run.[/dim]"
    )
    console.print("[dim]Input files:[/dim]")
    for document in sorted(result.documents, key=lambda item: item.path):
        display_path = (
            _relative_path(document.path, project_root)
            if project_root is not None
            else document.path
        )
        console.print(f"  [dim]- {display_path}[/dim]")
    if settings is not None and project_root is not None:
        provenance = _build_metadata(settings, project_root, result=result)
        source_revision = provenance.get("dryscope_source_revision")
        console.print(
            f"[dim]dryscope {__import__('dryscope').__version__}; backend={settings.backend}; "
            f"model={settings.llm_model_identity}; embedding={settings.docs_embedding_model}; "
            f"threshold={settings.threshold_similarity}; token_weight={settings.token_weight}; "
            f"candidate_threshold={settings.docs_candidate_threshold}; "
            f"include_intra={settings.include_intra}; min_words={settings.min_content_words}; "
            f"timeout={settings.llm_timeout}s[/dim]"
        )
        if source_revision:
            console.print(f"[dim]dryscope source revision={source_revision}[/dim]")
    console.print()

    outcome = _report_outcome(result, similarity_pairs)
    style = "yellow" if outcome["status"] == "degraded" else "cyan"
    console.print(f"[{style}]{outcome['statement']}[/{style}]")
    for stage_name, status in result.stage_status.items():
        detail = _status_exception_detail(status, project_root)
        console.print(
            f"  {stage_name}: [bold]{status.get('status', 'unknown')}[/bold]"
            + (f"; fallback={status.get('fallback')}" if status.get("fallback") else "")
            + (f"; details={escape_markup(detail)}" if detail != "-" else "")
        )
    console.print()

    _render_terminal_section_match(console, similarity_pairs, result.candidate_overlaps)
    _render_terminal_doc_pair_review(console, result)
    _render_terminal_topic_clusters(console, result)
    _render_terminal_taxonomy(console, result)
    _render_terminal_docs_map(console, result)
    _render_terminal_suggestions(console, suggestions)


def _build_markdown_context(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    settings: Settings | None,
    project_root: Path | None,
    stages_run: list[str],
) -> MarkdownContext:
    has_settings = settings is not None and project_root is not None
    recommendations = (
        build_recommendations(similarity_pairs, suggestions, project_root)
        if has_settings and similarity_pairs
        else []
    )
    docs_map = _docs_map(result)
    overview = _build_run_overview(result, similarity_pairs, recommendations, stages_run=stages_run)
    report_sections = _report_structure(overview, recommendations, result, similarity_pairs)
    section_titles = {section["id"]: section["title_numbered"] for section in report_sections}
    child_titles = {
        child["id"]: child["title_numbered"]
        for section in report_sections
        for child in section.get("children", [])
    }
    return MarkdownContext(
        has_settings=has_settings,
        recommendations=recommendations,
        docs_map=docs_map,
        overview=overview,
        section_titles=section_titles,
        child_titles=child_titles,
        candidate_pairs=result.candidate_overlaps,
    )


def _append_markdown_dashboard(
    lines: list[str],
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    context: MarkdownContext,
    project_root: Path | None,
    stages_run: list[str],
) -> None:
    n_docs = len(result.documents)
    n_pairs = len(similarity_pairs)
    n_recs = len(context.recommendations)
    pipeline_dots = (
        "  ".join(f"* {DOCS_STAGE_LABELS.get(s, s)}" for s in stages_run) if stages_run else "-"
    )
    n_profiled_docs = len(result.document_descriptors) or n_docs
    n_docs_map_groups = len(context.docs_map.get("topic_tree", []))
    n_docs_map_facets = len(context.docs_map.get("facets", {}))
    n_consolidation_clusters = len(_topic_document_clusters(result))
    n_candidates = len(result.candidate_overlaps)
    n_doc_relationships = _doc_pair_relationship_count(result)
    n_doc_actions = _doc_pair_action_count(result)
    outcome = _report_outcome(result, similarity_pairs)
    docs_map_ran = bool(context.docs_map or result.document_descriptors or result.topic_taxonomy)
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
                _metric_card(n_candidates, "Semantic Candidates"),
                _metric_card(n_recs, "Section Match Recs"),
            ]
        )
        track_bits.append(
            f"{DOCS_SECTION_MATCH}: {n_pairs} strict matched section pairs, "
            f"{n_candidates} semantic candidates, {n_recs} strict-match recommendations."
        )
    if DOCS_PAIR_REVIEW_SLUG in set(stages_run) or result.doc_pair_analyses:
        metric_cards.extend(
            [
                _metric_card(n_doc_relationships, "Doc Relationships"),
                _metric_card(n_doc_actions, "Doc Suggestions"),
            ]
        )
        track_bits.append(
            f"{DOCS_PAIR_REVIEW}: {n_doc_relationships} relationships, "
            f"{n_doc_actions} refactoring/reference suggestions."
        )
    if not docs_map_ran and not section_match_ran:
        metric_cards.append(_metric_card(len(result.chunks), "Sections"))

    git_context = ""
    if project_root:
        commit = _git_commit(project_root)
        git_context = f" at Git revision <code>{commit[:8]}</code>" if commit else ""

    lines.append(
        '<div class="dashboard">\n'
        f"{''.join(metric_cards)}"
        f'  <div class="pipeline-bar">Pipeline: {pipeline_dots}</div>\n'
        f'  <div class="track-summary">{" ".join(track_bits) if track_bits else "No docs analysis tracks ran."}</div>\n'
        f'  <div class="track-summary"><strong>Outcome:</strong> {escape(outcome["statement"])}</div>\n'
        f'  <div class="scan-context">Scope: exactly {n_docs} listed files{git_context}. '
        "Do not generalize beyond the listed files.</div>\n"
        "</div>\n"
    )


def _append_markdown_run_overview(
    lines: list[str],
    result: AnalysisResult,
    context: MarkdownContext,
    project_root: Path | None,
) -> None:
    lines.append(f"## {context.section_titles['run_overview']}\n")
    outcome = context.overview["supporting_results"]["outcome"]
    lines.append(f"**Outcome: {outcome['status']}** — {outcome['statement']}\n")
    lines.append(f"{outcome['strict_threshold_result']}\n")

    lines.append("### Stage Status\n")
    lines.append("| Stage | Status | Exception | Details | Fallback | Unavailable Conclusions |")
    lines.append("|-------|--------|-----------|---------|----------|-------------------------|")
    for stage_name, status in result.stage_status.items():
        unavailable = "; ".join(status.get("unavailable_conclusions", [])) or "-"
        detail = _status_exception_detail(status, project_root).replace("|", "\\|")
        lines.append(
            f"| {stage_name} | {status.get('status', 'unknown')} "
            f"| {status.get('exception_category') or '-'} "
            f"| {detail} | {status.get('fallback') or '-'} | {unavailable} |"
        )
    if not result.stage_status:
        lines.append("| (not recorded) | unknown | - | - | - | stage availability is unknown |")
    lines.append("")

    lines.append("### Capabilities Exercised\n")
    lines.append("| Capability | Ran | What It Does | Result |")
    lines.append("|------------|-----|--------------|--------|")
    for capability in context.overview["capabilities"].values():
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
    for aspect in context.overview["docs_track_aspects"].values():
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
            "These are the exact corpus boundaries for this report. Unlisted files were not analyzed.\n"
        )
        lines.append(
            _details_block(
                f"{len(scanned_docs)} documents scanned",
                _html_list(scanned_docs),
                class_name="report-list",
            )
        )
        lines.append("")


def _append_markdown_docs_map(
    lines: list[str],
    context: MarkdownContext,
    project_root: Path | None,
) -> None:
    docs_map = context.docs_map
    if not docs_map:
        return
    lines.append(f"## {context.section_titles['docs_map']}\n")
    stage_status = docs_map.get("stage_status", {})
    if stage_status.get("status") in {"degraded", "failed"}:
        unavailable = "; ".join(stage_status.get("unavailable_conclusions", []))
        lines.append(
            f"> **Degraded {DOCS_MAP} stage.** {stage_status.get('exception_category', 'LLM failure')}. "
            f"Fallback: {stage_status.get('fallback', 'none')}. "
            f"Unavailable conclusions: {unavailable or 'not recorded'}. "
            "Zero groups, facets, or diagnostics from this stage must not be read as a clean result.\n"
        )
    lines.append(
        f"Method: `{docs_map.get('method', 'unknown')}`. "
        f"Top-level topic groups: {len(docs_map.get('topic_tree', []))}. "
        f"Facet dimensions: {len(docs_map.get('facets', {}))}. "
        f"Diagnostics: {len(docs_map.get('diagnostics', []))}.\n"
    )
    _append_markdown_topic_tree(lines, docs_map, project_root)
    _append_markdown_facets(lines, docs_map, project_root)
    _append_markdown_diagnostics(lines, docs_map)


def _append_markdown_topic_tree(
    lines: list[str], docs_map: dict, project_root: Path | None
) -> None:
    topic_tree = docs_map.get("topic_tree", [])
    if not topic_tree:
        return
    lines.append("### Discovered Topic Tree\n")
    for parent in topic_tree:
        child_blocks = _markdown_topic_child_blocks(parent, project_root)
        lines.append(
            _details_block(
                f"{parent.get('label') or '(unnamed group)'} ({len(parent.get('children', []))} topics)",
                "\n".join(child_blocks) if child_blocks else "<p>No child topics.</p>",
                class_name="report-item",
                open_=True,
            )
        )
    lines.append("")


def _markdown_topic_child_blocks(parent: dict, project_root: Path | None) -> list[str]:
    blocks: list[str] = []
    description = parent.get("description") or ""
    if description:
        blocks.append(f"<p>{escape(str(description))}</p>")
    for child in parent.get("children", []):
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
                    _html_list([_display_path(str(doc), project_root) for doc in documents]),
                    class_name="report-list",
                )
            )
        blocks.append(
            _details_block(
                f"{child.get('label') or '(unnamed topic)'} ({child.get('document_count', 0)} docs)",
                "\n".join(child_body) if child_body else "<p>No additional details.</p>",
                class_name="report-item",
            )
        )
    return blocks


def _append_markdown_facets(lines: list[str], docs_map: dict, project_root: Path | None) -> None:
    facets = docs_map.get("facets", {})
    if not facets:
        return
    lines.append("### Facets\n")
    for facet_name, facet in sorted(facets.items()):
        facet_body = _markdown_facet_body(facet, project_root)
        values = facet.get("values", []) if isinstance(facet, dict) else []
        lines.append(
            _details_block(
                f"{facet_name} ({len(values)} values)",
                "\n".join(facet_body) if facet_body else "<p>No facet values.</p>",
                class_name="report-item",
                open_=True,
            )
        )
    lines.append("")


def _markdown_facet_body(facet: object, project_root: Path | None) -> list[str]:
    if not isinstance(facet, dict):
        return []
    facet_data = cast(dict[str, object], facet)
    facet_body: list[str] = []
    description = facet_data.get("description")
    if description:
        facet_body.append(f"<p>{escape(str(description))}</p>")
    raw_values = facet_data.get("values", [])
    values = raw_values if isinstance(raw_values, list) else []
    for value in values:
        if not isinstance(value, dict):
            continue
        value_data = cast(dict[str, object], value)
        raw_docs = value_data.get("documents")
        raw_evidence = value_data.get("evidence")
        docs = raw_docs if isinstance(raw_docs, list) else []
        evidence = raw_evidence if isinstance(raw_evidence, list) else []
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
                f"{value_data.get('value', '(unspecified)')} ({len(docs)} docs)",
                "\n".join(value_body) if value_body else "<p>No additional details.</p>",
                class_name="report-item",
            )
        )
    return facet_body


def _append_markdown_diagnostics(lines: list[str], docs_map: dict) -> None:
    diagnostics = docs_map.get("diagnostics", [])
    if not diagnostics:
        return
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


def _append_markdown_docs_map_clusters(
    lines: list[str],
    result: AnalysisResult,
    context: MarkdownContext,
    project_root: Path | None,
) -> None:
    coverage_clusters = _topic_document_clusters(result)
    if not coverage_clusters:
        return
    lines.append(f"## {context.section_titles['docs_map_clusters']}\n")
    lines.append(
        f"Found {len(coverage_clusters)} canonical labels covered by 2+ documents. "
        "These are candidates to inspect for consolidation, splitting, or stronger cross-links.\n"
    )
    for i, cluster in enumerate(coverage_clusters, 1):
        docs = cluster.get("documents", [])
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
                f"{i}. {cluster.get('topic') or '(unnamed topic)'} "
                f"({len(docs)} docs, {cluster.get('mention_count', 0)} mentions)",
                "\n".join(cluster_body),
                class_name="report-item",
            )
        )
    lines.append("")


def _append_markdown_section_match(
    lines: list[str],
    similarity_pairs: list[OverlapPair],
    context: MarkdownContext,
) -> None:
    lines.append(f"## {context.section_titles['docs_section_match']}\n")
    lines.append(
        "Section Match is the docs section-level pass: split documents into sections, "
        "embed them, and report matched cross-document section pairs.\n"
    )
    lines.append(
        f"Found {len(similarity_pairs)} strict matched section pairs and "
        f"{len(context.candidate_pairs)} "
        "bounded semantic candidates.\n"
    )
    if not similarity_pairs:
        lines.append(
            "**No section candidates were above the configured strict threshold.** "
            "This is not a claim that the scanned documents have no overlap; inspect the "
            "semantic-candidate, Docs Map, and Doc Pair Review sections.\n"
        )
    _append_markdown_recommendations(lines, context)
    _append_markdown_matched_pairs(lines, similarity_pairs, context)
    _append_markdown_semantic_candidates(lines, context)


def _append_markdown_recommendations(lines: list[str], context: MarkdownContext) -> None:
    if not context.recommendations:
        return
    lines.append(f"### {context.child_titles['docs_section_match_recommendations']}\n")
    lines.append(
        "These recommendations are derived from the matched section pairs in this track. "
        "Docs Map consolidation candidates are listed separately under Docs Map Clusters.\n"
    )
    for rec in context.recommendations:
        rec_body: list[str] = [
            f"<p><strong>Action:</strong> {escape(str(rec['suggested_action']))}</p>",
            f"<p><strong>Score:</strong> {escape(str(rec['priority_score']))}</p>",
            f"<p>{escape(str(rec['action_detail']))}</p>",
            _html_list([str(f["file"]) for f in rec["affected_files"]]),
        ]
        lines.append(
            _details_block(
                f"{rec['priority_rank']}. {rec['suggested_action'].title()} "
                f"({rec['priority_score']} pts, {len(rec['affected_files'])} files)",
                "\n".join(rec_body),
                class_name="report-item",
            )
        )
    lines.append("")


def _append_markdown_matched_pairs(
    lines: list[str],
    similarity_pairs: list[OverlapPair],
    context: MarkdownContext,
) -> None:
    if not similarity_pairs:
        return
    lines.append(f"### {context.child_titles['matched_section_pairs']}\n")
    lines.append("| Embedding Cosine | Token Similarity | Combined Score | Section A | Section B |")
    lines.append("|------------------|------------------|----------------|-----------|-----------|")
    for pair in similarity_pairs:
        heading_a = " > ".join(pair.chunk_a.heading_path) or "(no heading)"
        heading_b = " > ".join(pair.chunk_b.heading_path) or "(no heading)"
        loc_a = f"`{_short_path(pair.chunk_a.document_path)}`: {heading_a}"
        loc_b = f"`{_short_path(pair.chunk_b.document_path)}`: {heading_b}"
        lines.append(
            f"| {_score_text(pair.embedding_cosine)} | {_score_text(pair.token_similarity)} "
            f"| {_score_text(pair.combined_score)} | {loc_a} | {loc_b} |"
        )
    lines.append("")


def _append_markdown_semantic_candidates(lines: list[str], context: MarkdownContext) -> None:
    candidates = context.candidate_pairs
    if not candidates:
        return
    lines.append(f"### {context.child_titles['semantic_candidates']}\n")
    lines.append(
        "These are bounded, below-strict-threshold preflight candidates selected by embedding cosine. "
        "They require LLM or human review and are not duplication findings.\n"
    )
    lines.append("| Embedding Cosine | Token Similarity | Combined Score | Section A | Section B |")
    lines.append("|------------------|------------------|----------------|-----------|-----------|")
    for pair in candidates:
        heading_a = " > ".join(pair.chunk_a.heading_path) or "(no heading)"
        heading_b = " > ".join(pair.chunk_b.heading_path) or "(no heading)"
        loc_a = f"`{_short_path(pair.chunk_a.document_path)}`: {heading_a}"
        loc_b = f"`{_short_path(pair.chunk_b.document_path)}`: {heading_b}"
        lines.append(
            f"| {_score_text(pair.embedding_cosine)} | {_score_text(pair.token_similarity)} "
            f"| {_score_text(pair.combined_score)} | {loc_a} | {loc_b} |"
        )
    lines.append("")


def _append_markdown_doc_pair_review(
    lines: list[str],
    result: AnalysisResult,
    context: MarkdownContext,
) -> None:
    if not result.doc_pair_analyses:
        return
    lines.append(f"## {context.section_titles['docs_pair_review']}\n")
    lines.append(f"Analyzed {len(result.doc_pair_analyses)} document pairs\n")

    for analysis in result.doc_pair_analyses:
        name_a = _short_path(analysis.doc_a_path)
        name_b = _short_path(analysis.doc_b_path)
        lines.append(f"### `{name_a}` / `{name_b}`\n")
        if analysis.analysis_error:
            detail = _redact_machine_paths(analysis.analysis_error).replace("|", "\\|")
            lines.append("- **Analysis status**: unavailable")
            lines.append(f"- **Failure**: {detail}\n")
            continue
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


def _append_markdown_taxonomy(
    lines: list[str],
    result: AnalysisResult,
    context: MarkdownContext,
) -> None:
    if not result.topic_taxonomy:
        return
    canonical_topics = result.topic_taxonomy.get("canonical_topics", [])
    if not canonical_topics:
        return
    lines.append(f"## {context.section_titles['docs_map_taxonomy']}\n")
    lines.append(
        "Canonical labels are the normalized vocabulary produced from document descriptors. "
        "Document coverage for multi-document labels is listed above under Docs Map Clusters; "
        "this section gives the full vocabulary and alias map once.\n"
    )
    for topic in canonical_topics:
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
                f"{topic.get('name', '(unnamed label)')} ({topic.get('document_count', 0)} docs, "
                f"{topic.get('mention_count', 0)} mentions)",
                "\n".join(topic_body),
                class_name="report-item",
            )
        )
    _append_markdown_co_occurrence(lines, result.topic_taxonomy)
    lines.append("")


def _append_markdown_co_occurrence(lines: list[str], taxonomy: dict) -> None:
    co_occurrence = taxonomy.get("co_occurrence", [])
    if not co_occurrence:
        return
    co_items = []
    for item in co_occurrence:
        topics = item.get("topics", [])
        if len(topics) == 2:
            co_items.append(f"{topics[0]} + {topics[1]} ({item.get('count')} docs)")
    lines.append("")
    lines.append(
        _details_block(
            f"{len(co_items)} co-occurring label pairs",
            _html_text_list(co_items),
            class_name="report-list",
        )
    )


def _append_markdown_suggestions(lines: list[str], suggestions: list[dict] | None) -> None:
    if not suggestions:
        return
    lines.append("## Refactoring Suggestions\n")
    for i, s in enumerate(suggestions, 1):
        lines.append(f'{i}. **"{s.get("code", "?")}"** ({len(s.get("documents", []))} documents)')
        lines.append(f"   - Canonical: `{_short_path(s.get('canonical', '?'))}`")
        for sug in s.get("suggestions", []):
            doc = _short_path(sug.get("document", "?"))
            action = sug.get("action", "?")
            reason = sug.get("reason", "")
            lines.append(f"   - `{doc}`: {action} - {reason}")
        lines.append("")


def _append_markdown_methodology(
    lines: list[str],
    context: MarkdownContext,
    settings: Settings | None,
    project_root: Path | None,
) -> None:
    lines.append(f"## {context.section_titles['methodology']}\n")
    lines.append("### Tracks\n")
    lines.append(
        "dryscope reports use stable track names and slugs. This report is for docs tracks:\n\n"
        f"1. **{DOCS_MAP}** (`{DOCS_MAP_SLUG}`) - Extracts document descriptors, canonicalizes aboutness and "
        "reader-intent labels, discovers an IA topic tree and facets, and lists multi-document "
        "consolidation clusters.\n"
        f"2. **{DOCS_SECTION_MATCH}** (`{DOCS_SECTION_MATCH_SLUG}`) - Splits documents into sections and safe structured fragments, "
        "reports strict hybrid matches plus a bounded below-threshold semantic-candidate band, and produces "
        "preflight recommendations. Depending on configuration it compares cross-document pairs only or also "
        "intra-document pairs.\n"
        f"3. **{DOCS_PAIR_REVIEW}** (`{DOCS_PAIR_REVIEW_SLUG}`) - Sends selected document pairs to an LLM for "
        "relationship classification, topic-level canonical/action assignments, and consolidation suggestions.\n"
    )
    lines.append("### Scoring\n")
    lines.append(
        "Each recommendation is scored 0-100 based on:\n\n"
        "- **Combined similarity** (0-60 base): `combined_score * 60`\n"
        "- **LLM confirmation** (+15): overlap confirmed by coding stage\n"
        "- **Multiple sections** (+5 each): additional overlapping section pairs\n"
        "- **Boilerplate penalty** (-15): structural/boilerplate overlap\n\n"
        "Raw score is normalized: `score * 100 / 80`.\n"
    )
    lines.append("### Actions\n")
    lines.append(
        "- **consolidate** - Near-identical content; merge into one location\n"
        "- **link** - Boilerplate/structural duplication; use shared include or cross-reference\n"
        "- **brief_reference** - Partial overlap; replace shorter version with a link to canonical\n"
        "- **keep** - Overlap is intentional or serves different audiences\n"
    )
    if context.has_settings and settings is not None and project_root is not None:
        _append_markdown_config(lines, settings, project_root)


def _append_markdown_config(lines: list[str], settings: Settings, project_root: Path) -> None:
    from dryscope import __version__

    meta = _build_metadata(settings, project_root)
    lines.append("### Configuration\n")
    lines.append(f"- **Date**: {meta['timestamp']}")
    lines.append(f"- **dryscope version**: {__version__}")
    if meta.get("git_commit"):
        lines.append(f"- **Scanned project Git commit**: `{meta['git_commit'][:12]}`")
    if meta.get("dryscope_source_revision"):
        lines.append(f"- **dryscope source revision**: `{meta['dryscope_source_revision'][:12]}`")
    lines.append(f"- **dryscope source type**: `{meta['dryscope_source_type']}`")
    threshold_name = (
        "Hybrid-similarity threshold" if settings.token_weight > 0 else "Embedding-cosine threshold"
    )
    lines.append(f"- **{threshold_name}**: {settings.threshold_similarity}")
    lines.append(f"- **Semantic-candidate cosine floor**: {settings.docs_candidate_threshold}")
    lines.append(f"- **Maximum semantic candidates**: {settings.docs_max_semantic_candidates}")
    lines.append(f"- **Token weight**: {settings.token_weight}")
    lines.append(f"- **Include intra-document pairs**: {settings.include_intra}")
    lines.append(f"- **Minimum section words**: {settings.min_content_words}")
    if settings.threshold_intent > 0:
        lines.append(f"- **Intent threshold**: {settings.threshold_intent}")
    lines.append(f"- **Embedding model**: {settings.docs_embedding_model}")
    lines.append(f"- **LLM backend**: {settings.backend}")
    lines.append(f"- **LLM model behavior**: {settings.llm_model_identity}")
    lines.append(f"- **LLM timeout**: {settings.llm_timeout} seconds")
    lines.append("")


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
    stages_run = stages_run or []
    lines = ["# dryscope Report\n"]
    context = _build_markdown_context(
        result,
        similarity_pairs,
        suggestions,
        settings,
        project_root,
        stages_run,
    )

    _append_markdown_dashboard(lines, result, similarity_pairs, context, project_root, stages_run)
    _append_markdown_run_overview(lines, result, context, project_root)
    _append_markdown_docs_map(lines, context, project_root)
    _append_markdown_docs_map_clusters(lines, result, context, project_root)
    _append_markdown_section_match(lines, similarity_pairs, context)
    _append_markdown_doc_pair_review(lines, result, context)
    _append_markdown_taxonomy(lines, result, context)
    _append_markdown_suggestions(lines, suggestions)
    _append_markdown_methodology(lines, context, settings, project_root)
    return _redact_machine_paths("\n".join(lines))


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
            "semantic_candidates_found": len(result.candidate_overlaps),
            "section_match_recommendations_found": len(recommendations),
            "document_intent_relationships_found": _doc_pair_relationship_count(result),
            "document_level_suggestions_found": _doc_pair_action_count(result),
            "recommendations_count": len(recommendations) + _doc_pair_action_count(result),
            "outcome": _report_outcome(result, similarity_pairs),
        },
        "report_structure": _report_structure(
            overview,
            recommendations,
            result,
            similarity_pairs,
        ),
    }

    if settings is not None and project_root is not None:
        data["metadata"] = _build_metadata(settings, project_root, result=result)
    if result.categories:
        data["categories"] = {
            cat.name: {
                code.name: sorted({c.document_path for c in code.chunks}) for code in cat.codes
            }
            for cat in result.categories
        }

    if suggestions:
        data["refactoring_suggestions"] = suggestions

    if project_root is not None:
        data = _sanitize_report_paths(data, project_root)
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
    if not isinstance(html_body, str):
        html_body = str(html_body)

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
    """Return a report-safe path relative to the scan root."""
    if not path:
        return None
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return f"<outside-scan-root>/{Path(path).name}"


def _sanitize_report_paths(value, root: Path):
    """Recursively remove absolute machine paths from report payloads."""
    if isinstance(value, dict):
        return {
            _sanitize_report_paths(key, root)
            if isinstance(key, str)
            else key: _sanitize_report_paths(item, root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_report_paths(item, root) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_report_paths(item, root) for item in value)
    if isinstance(value, str):
        if Path(value).is_absolute():
            return _relative_path(value, root)
        if PureWindowsPath(value).is_absolute():
            return f"<absolute-path>/{PureWindowsPath(value).name}"
        return _redact_machine_paths(value)
    return value


def _redact_machine_paths(text: str) -> str:
    """Redact user-home paths embedded inside otherwise free-form text."""
    import re

    text = re.sub(
        r"(?i)(?:file://)?/(?:home|users)/[^\s`\"'<>|]+",
        "<redacted-user-path>",
        text,
    )
    return re.sub(
        r"(?i)\b[A-Z]:\\Users\\[^\s`\"'<>|]+",
        "<redacted-user-path>",
        text,
    )


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


def _git_dirty(root: Path) -> bool | None:
    """Return whether a Git worktree is dirty, or None outside Git."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return bool(proc.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _installation_origin() -> str | None:
    """Read the installed distribution origin when direct_url metadata exists."""
    try:
        raw = importlib_metadata.distribution("dryscope").read_text("direct_url.json")
        data = json.loads(raw) if raw else {}
        return str(data.get("url")) if data.get("url") else None
    except (importlib_metadata.PackageNotFoundError, json.JSONDecodeError, TypeError):
        return None


def _installation_source_path(origin: str | None) -> Path | None:
    """Resolve a local direct-url origin for source revision provenance."""
    if not origin:
        return None
    parsed = urlparse(origin)
    if parsed.scheme != "file":
        return None
    path = Path(unquote(parsed.path)).resolve()
    return path if path.exists() else None


def _installation_origin_label(origin: str | None) -> str:
    """Describe installation provenance without serializing a private URL or path."""
    if not origin:
        return "package-index-or-environment"
    scheme = urlparse(origin).scheme.lower()
    if scheme == "file":
        return "local-source"
    if "git" in scheme:
        return "vcs-source"
    return "remote-source"


def _build_metadata(
    settings: Settings,
    project_root: Path,
    *,
    result: AnalysisResult | None = None,
) -> dict:
    """Build metadata dict for JSON outputs."""
    from dryscope import __version__

    source_root = Path(__file__).resolve().parents[2]
    installation_origin = _installation_origin()
    installation_source = _installation_source_path(installation_origin)
    source_revision = _git_commit(source_root)
    source_dirty = _git_dirty(source_root)
    source_type = "source-checkout" if source_revision is not None else "installed-package"
    if source_revision is None and installation_source is not None:
        source_revision = _git_commit(installation_source)
        source_dirty = _git_dirty(installation_source)
    input_files = (
        sorted(
            filter(
                None,
                (_relative_path(document.path, project_root) for document in result.documents),
            )
        )
        if result is not None
        else []
    )
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_root": ".",
        "git_commit": _git_commit(project_root),
        "dryscope_version": __version__,
        "dryscope_source_path": None,
        "dryscope_source_type": source_type,
        "dryscope_source_revision": source_revision,
        "dryscope_source_dirty": source_dirty,
        "installation_origin": _installation_origin_label(installation_origin),
        "input_files": input_files,
        "stage_status": result.stage_status if result is not None else {},
        "config": {
            "threshold_similarity": settings.threshold_similarity,
            "threshold_label": (
                "hybrid-similarity" if settings.token_weight > 0 else "embedding-cosine"
            ),
            "candidate_threshold": settings.docs_candidate_threshold,
            "max_semantic_candidates": settings.docs_max_semantic_candidates,
            "threshold_intent": settings.threshold_intent,
            "include": settings.include,
            "exclude": settings.exclude,
            "backend": settings.backend,
            "model_override": settings.model,
            "effective_model_identity": settings.llm_model_identity,
            "uses_configured_default_model": settings.model is None,
            "embedding_model": settings.docs_embedding_model,
            "token_weight": settings.token_weight,
            "include_intra": settings.include_intra,
            "min_words": settings.min_content_words,
            "llm_timeout_seconds": settings.llm_timeout,
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
            "kind": chunk.kind,
            "content_snippet": chunk.content[:300],
        }

    return {
        # Keys for deserialization (matching back to in-memory Chunk objects)
        "chunk_a_key": f"{_relative_path(pair.chunk_a.document_path, root)}:{pair.chunk_a.line_start}",
        "chunk_b_key": f"{_relative_path(pair.chunk_b.document_path, root)}:{pair.chunk_b.line_start}",
        "chunk_a": _chunk_dict(pair.chunk_a),
        "chunk_b": _chunk_dict(pair.chunk_b),
        "embedding_similarity": pair.embedding_similarity,
        "embedding_cosine": pair.embedding_cosine,
        "token_similarity": pair.token_similarity,
        "combined_similarity": pair.combined_score,
        "confidence": pair.confidence,
        "shared_codes": pair.shared_codes,
    }


# ─── Stage Serializers ─────────────────────────────────────────────────


def serialize_section_match_stage(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    settings: Settings,
    project_root: Path,
    *,
    candidate_pairs: list[OverlapPair] | None = None,
) -> dict:
    """Serialize Section Match output for persistent storage."""
    data = {
        "track": DOCS_SECTION_MATCH,
        "track_slug": DOCS_SECTION_MATCH_SLUG,
        "metadata": _build_metadata(settings, project_root, result=result),
        "stage_status": result.stage_status.get(DOCS_SECTION_MATCH_SLUG, {}),
        "summary": {
            "documents_scanned": len(result.documents),
            "chunks_analyzed": len(result.chunks),
            "matched_section_pairs_found": len(similarity_pairs),
            "semantic_candidates_found": len(candidate_pairs or []),
            "threshold": settings.threshold_similarity,
            "threshold_label": (
                "hybrid-similarity" if settings.token_weight > 0 else "embedding-cosine"
            ),
            "candidate_threshold": settings.docs_candidate_threshold,
            "token_weight": settings.token_weight,
            "include_intra": settings.include_intra,
            "min_words": settings.min_content_words,
            "model": settings.docs_embedding_model,
        },
        "matched_section_pairs": [_pair_to_rich_dict(p, project_root) for p in similarity_pairs],
        "semantic_candidates": [
            _pair_to_rich_dict(p, project_root) for p in (candidate_pairs or [])
        ],
    }
    return _sanitize_report_paths(data, project_root)


def serialize_doc_pair_review_stage(
    codes: list[Code],
    categories: list[Category],
    suggestions: list[dict] | None,
    settings: Settings,
    project_root: Path,
    analyses: list[DocPairAnalysis] | None = None,
    result: AnalysisResult | None = None,
) -> dict:
    """Serialize Doc Pair Review output for persistent storage."""
    data: dict = {
        "track": DOCS_PAIR_REVIEW,
        "track_slug": DOCS_PAIR_REVIEW_SLUG,
        "metadata": _build_metadata(settings, project_root, result=result),
        "stage_status": (
            result.stage_status.get(DOCS_PAIR_REVIEW_SLUG, {}) if result is not None else {}
        ),
        "summary": {
            "codes_found": len(codes),
            "categories_found": len(categories),
            "model": settings.llm_model_identity,
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
                "analysis_error": a.analysis_error,
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
    return _sanitize_report_paths(data, project_root)


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
        for cluster in _connected_recommendation_clusters(recs):
            merged = _merge_recommendation_cluster(cluster)
            if merged is None:
                merged_output.extend(cluster)
            else:
                merged_output.append(merged)

    merged_output.sort(key=lambda r: r["priority_score"], reverse=True)
    for i, rec in enumerate(merged_output, 1):
        rec["priority_rank"] = i
    return merged_output


def _connected_recommendation_clusters(recs: list[dict]) -> list[list[dict]]:
    """Group recommendations that share affected files."""
    clusters: list[list[dict]] = []
    remaining = list(recs)
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        changed = True
        while changed:
            changed = _pull_connected_recommendations(cluster, remaining)
        clusters.append(cluster)
    return clusters


def _pull_connected_recommendations(cluster: list[dict], remaining: list[dict]) -> bool:
    """Move recs sharing any current file into cluster."""
    current_files = {f["file"] for rec in cluster for f in rec["affected_files"]}
    changed = False
    next_remaining: list[dict] = []
    for rec in remaining:
        rec_files = {f["file"] for f in rec["affected_files"]}
        if current_files & rec_files:
            cluster.append(rec)
            changed = True
        else:
            next_remaining.append(rec)
    remaining[:] = next_remaining
    return changed


def _merge_recommendation_cluster(cluster: list[dict]) -> dict | None:
    cluster_files = {f["file"] for rec in cluster for f in rec["affected_files"]}
    if len(cluster) < 2 or len(cluster_files) < 3:
        return None
    sections_by_file, best_similarity, best_score = _cluster_recommendation_stats(cluster)
    seed = cluster[0]
    action = seed["suggested_action"]
    group_score = min(100, max(best_score, best_score + min(15, 3 * (len(cluster_files) - 2))))
    return {
        "priority_score": group_score,
        "affected_files": [
            {"file": file, "sections": _merge_sections(sections)}
            for file, sections in sorted(sections_by_file.items())
        ],
        "overlap_type": seed["overlap_type"],
        "embedding_similarity": round(best_similarity, 4),
        "suggested_action": action,
        "action_detail": _recommendation_family_detail(action, cluster_files, len(cluster)),
    }


def _cluster_recommendation_stats(
    cluster: list[dict],
) -> tuple[dict[str, list[dict]], float, int]:
    sections_by_file: dict[str, list[dict]] = defaultdict(list)
    best_similarity = 0.0
    best_score = 0
    for rec in cluster:
        best_similarity = max(best_similarity, rec.get("embedding_similarity") or 0.0)
        best_score = max(best_score, rec.get("priority_score") or 0)
        for file_entry in rec["affected_files"]:
            sections_by_file[file_entry["file"]].extend(file_entry.get("sections", []))
    return sections_by_file, best_similarity, best_score


def _recommendation_family_detail(action: str, cluster_files: set[str], cluster_size: int) -> str:
    file_list = ", ".join(f"`{Path(f).name}`" for f in sorted(cluster_files)[:4])
    if len(cluster_files) > 4:
        file_list += f", and {len(cluster_files) - 4} more"
    if action == "consolidate":
        return (
            f"A family of {len(cluster_files)} documents shares highly similar content "
            f"across {cluster_size} pairwise overlaps ({file_list}). "
            "Consider extracting a shared canonical reference and replacing repeated copies with links."
        )
    if action == "link":
        return (
            f"A family of {len(cluster_files)} documents repeats the same structural or reference material "
            f"across {cluster_size} pairwise overlaps ({file_list}). "
            "Consider one shared include/reference instead of repeating the content pairwise."
        )
    return (
        f"A family of {len(cluster_files)} documents overlaps across {cluster_size} pairwise matches "
        f"({file_list}). Consider keeping one canonical explanation and replacing the rest with brief references."
    )


def build_recommendations(
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    project_root: Path,
) -> list[dict]:
    """Build prioritized recommendations from overlap data.

    Groups overlapping pairs by file-pair, scores and ranks them.
    """
    suggestion_codes = {s.get("code", "") for s in suggestions or []}
    file_pair_groups = _group_similarity_pairs_by_file(similarity_pairs, project_root)

    recommendations: list[dict] = []
    for (file_a, file_b), pairs in file_pair_groups.items():
        recommendations.append(
            _build_file_pair_recommendation(file_a, file_b, pairs, suggestion_codes)
        )

    return _merge_related_recommendations(recommendations)


def _group_similarity_pairs_by_file(
    similarity_pairs: list[OverlapPair],
    project_root: Path,
) -> dict[tuple[str, str], list[OverlapPair]]:
    file_pair_groups: dict[tuple[str, str], list[OverlapPair]] = defaultdict(list)
    for pair in similarity_pairs:
        fa = _relative_path(pair.chunk_a.document_path, project_root) or ""
        fb = _relative_path(pair.chunk_b.document_path, project_root) or ""
        file_pair_groups[(min(fa, fb), max(fa, fb))].append(pair)
    return file_pair_groups


def _build_file_pair_recommendation(
    file_a: str,
    file_b: str,
    pairs: list[OverlapPair],
    suggestion_codes: set[str],
) -> dict:
    best_pair = max(pairs, key=lambda p: p.combined_score or 0)
    best_similarity = best_pair.combined_score or 0
    overlap_type = _classify_overlap(best_pair)
    action = _suggest_action(overlap_type, best_pair)
    score = _recommendation_score(best_pair, pairs, suggestion_codes, overlap_type)
    sections_a, sections_b = _recommendation_sections(pairs)
    return {
        "priority_score": score,
        "affected_files": [
            {"file": file_a, "sections": sections_a},
            {"file": file_b, "sections": sections_b},
        ],
        "overlap_type": overlap_type,
        "embedding_similarity": round(best_similarity, 4),
        "embedding_cosine": round(best_pair.embedding_cosine or 0, 4),
        "token_similarity": round(best_pair.token_similarity or 0, 4),
        "combined_similarity": round(best_similarity, 4),
        "confidence": best_pair.confidence,
        "suggested_action": action,
        "action_detail": _recommendation_detail(action, file_a, file_b, best_similarity),
    }


def _recommendation_score(
    best_pair: OverlapPair,
    pairs: list[OverlapPair],
    suggestion_codes: set[str],
    overlap_type: str,
) -> int:
    best_similarity = best_pair.combined_score or 0
    score = best_similarity * 60
    if best_pair.shared_codes and any(c in suggestion_codes for c in best_pair.shared_codes):
        score += 15
    if len(pairs) > 1:
        score += 5 * (len(pairs) - 1)
    if overlap_type == "structural_boilerplate":
        score -= 15
    return min(100, max(0, round(score * 100 / _MAX_RAW_SCORE)))


def _recommendation_sections(pairs: list[OverlapPair]) -> tuple[list[dict], list[dict]]:
    sections_a: list[dict] = []
    sections_b: list[dict] = []
    for pair in pairs:
        sections_a.append(
            {
                "sections": pair.chunk_a.heading_path or ["(no heading)"],
                "line_range": [pair.chunk_a.line_start, pair.chunk_a.line_end],
            }
        )
        sections_b.append(
            {
                "sections": pair.chunk_b.heading_path or ["(no heading)"],
                "line_range": [pair.chunk_b.line_start, pair.chunk_b.line_end],
            }
        )
    return sections_a, sections_b


def _recommendation_detail(action: str, file_a: str, file_b: str, similarity: float) -> str:
    if action == "consolidate":
        adjective = "near-identical" if similarity > 0.95 else "highly similar"
        return (
            f"These sections in `{file_a}` and `{file_b}` contain {adjective} content. "
            "Consider consolidating into one location and linking from the other."
        )
    if action == "link":
        return (
            f"Boilerplate/structural content duplicated between `{file_a}` and `{file_b}`. "
            "Consider using a shared include or cross-reference link."
        )
    if action == "remove":
        return f"Redundant content in `{file_a}` and `{file_b}` that could be removed from one document."
    return (
        f"Partial overlap between `{file_a}` and `{file_b}`. "
        "Consider replacing the shorter version with a brief reference to the canonical source."
    )


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
        "metadata": _build_metadata(settings, project_root, result=result),
        "summary": {
            "documents_scanned": len(result.documents),
            "chunks_analyzed": len(result.chunks),
            "matched_section_pairs_found": len(similarity_pairs),
            "semantic_candidates_found": len(result.candidate_overlaps),
            "recommendations_count": len(recommendations) + _doc_pair_action_count(result),
            "section_match_recommendations_found": len(recommendations),
            "document_intent_relationships_found": _doc_pair_relationship_count(result),
            "document_level_suggestions_found": _doc_pair_action_count(result),
            "outcome": _report_outcome(result, similarity_pairs),
        },
        "report_structure": _report_structure(
            overview,
            recommendations,
            result,
            similarity_pairs,
        ),
    }

    return _sanitize_report_paths(report, project_root)
