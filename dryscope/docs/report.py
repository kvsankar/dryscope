"""Report generation (terminal/Rich, markdown, JSON)."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dryscope.config import Settings
from dryscope.docs.models import AnalysisResult, Category, Code, DocPairAnalysis, OverlapPair


def _short_path(path: str) -> str:
    """Return just the filename from a path."""
    return Path(path).name


def render_terminal(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    console: Console | None = None,
    topic_clusters: list[dict] | None = None,
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

    # Stage 1: Similarity
    console.print("[bold]Stage 1: Semantic Similarity[/bold]", style="cyan")
    console.print(f"Found [bold]{len(similarity_pairs)}[/bold] similar section pairs")
    console.print()

    if similarity_pairs:
        table = Table(title="Top Similarity Matches", show_lines=True)
        table.add_column("Similarity", style="yellow", width=10)
        table.add_column("Section A", style="green")
        table.add_column("Section B", style="green")

        for pair in similarity_pairs[:10]:
            heading_a = " > ".join(pair.chunk_a.heading_path) or "(no heading)"
            heading_b = " > ".join(pair.chunk_b.heading_path) or "(no heading)"
            loc_a = f"{_short_path(pair.chunk_a.document_path)}: {heading_a}"
            loc_b = f"{_short_path(pair.chunk_b.document_path)}: {heading_b}"
            sim_str = f"{pair.embedding_similarity:.3f}" if pair.embedding_similarity is not None else "—"
            table.add_row(sim_str, loc_a, loc_b)

        console.print(table)
        console.print()

    # Stage 2: Document-Pair Analysis
    if result.doc_pair_analyses:
        console.print("[bold]Stage 2: Document-Pair Analysis[/bold]", style="cyan")
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

    # Topic Clusters
    if topic_clusters:
        console.print("[bold]Document Clusters by Topic:[/bold]", style="cyan")
        for i, cluster in enumerate(topic_clusters, 1):
            label = cluster["label"]
            docs = cluster["documents"]
            console.print(f"  {i}. [bold]\"{label}\"[/bold] ({len(docs)} documents)")
            for doc in docs:
                console.print(f"     • {_short_path(doc)}")
        console.print()

    # Refactoring Suggestions
    if suggestions:
        console.print("[bold]Refactoring Suggestions:[/bold]")
        for i, s in enumerate(suggestions, 1):
            code_name = s.get("code", "?")
            docs = s.get("documents", [])
            canonical = s.get("canonical", "?")
            console.print(f"  {i}. [bold]\"{code_name}\"[/bold] ({len(docs)} documents)")
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
    topic_clusters: list[dict] | None = None,
) -> str:
    """Render analysis results as markdown.

    When settings and project_root are provided, includes dashboard,
    recommendations, and methodology sections.

    Args:
        stages_run: List of stage names that actually executed,
            e.g. ["Similarity", "Intent", "LLM Analysis"].
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
    n_sections = len(result.chunks)
    n_pairs = len(similarity_pairs)
    n_recs = len(recommendations)
    pipeline_dots = "  ".join(f"● {s}" for s in stages_run) if stages_run else "—"

    # Scan context
    scan_path_str = str(project_root) if project_root else "unknown"
    git_name = ""
    if project_root:
        commit = _git_commit(project_root)
        if commit:
            git_name = f" ({project_root.name}, {commit[:8]})"
        else:
            git_name = f" ({project_root.name})"

    # File list (collapsible)
    file_list_html = ""
    if result.documents:
        file_items = "\n".join(
            f"    <li>{_short_path(doc.path)}</li>"
            for doc in sorted(result.documents, key=lambda d: d.path)
        )
        file_list_html = (
            '\n  <details class="file-list">\n'
            f"    <summary>{n_docs} files scanned</summary>\n"
            f"    <ol>\n{file_items}\n    </ol>\n"
            "  </details>\n"
        )

    lines.append(
        '<div class="dashboard">\n'
        f'  <div class="metric-card"><div class="metric-value">{n_docs}</div>'
        f'<div class="metric-label">Documents</div></div>\n'
        f'  <div class="metric-card"><div class="metric-value">{n_sections}</div>'
        f'<div class="metric-label">Sections</div></div>\n'
        f'  <div class="metric-card"><div class="metric-value">{n_pairs}</div>'
        f'<div class="metric-label">Sim Pairs</div></div>\n'
        f'  <div class="metric-card"><div class="metric-value">{n_recs}</div>'
        f'<div class="metric-label">Recommendations</div></div>\n'
        f'  <div class="pipeline-bar">Pipeline: {pipeline_dots}</div>\n'
        f'  <div class="scan-context">Scanned: <code>{scan_path_str}</code>{git_name}</div>\n'
        f'{file_list_html}'
        '</div>\n'
    )

    # ── Recommendations (moved to top) ─────────────────────────────────
    if recommendations:
        lines.append("## Recommendations\n")
        lines.append("| # | Score | Files | Action |")
        lines.append("|---|-------|-------|--------|")
        for rec in recommendations:
            files = ", ".join(
                f"`{Path(f['file']).name}`" for f in rec["affected_files"]
            )
            lines.append(
                f"| {rec['priority_rank']} "
                f"| {rec['priority_score']} "
                f"| {files} "
                f"| {rec['suggested_action']} |"
            )
        lines.append("")

        for rec in recommendations:
            lines.append(f"### {rec['priority_rank']}. {rec['suggested_action'].title()} ({rec['priority_score']} pts)\n")
            lines.append(f"{rec['action_detail']}\n")
            for f in rec["affected_files"]:
                file_path = f["file"]
                for section in f.get("sections", []):
                    sec = " > ".join(section.get("sections", []))
                    lr = section.get("line_range")
                    loc = file_path
                    if sec:
                        loc += f": {sec}"
                    if lr:
                        loc += f" (L{lr[0]}–{lr[1]})"
                    lines.append(f"- `{loc}`")
            lines.append("")

    # ── Stage 1: Similarity ────────────────────────────────────────────
    lines.append("## Stage 1: Semantic Similarity\n")
    lines.append(f"Found {len(similarity_pairs)} similar section pairs\n")

    if similarity_pairs:
        lines.append("| Similarity | Section A | Section B |")
        lines.append("|------------|-----------|-----------|")
        for pair in similarity_pairs[:20]:
            heading_a = " > ".join(pair.chunk_a.heading_path) or "(no heading)"
            heading_b = " > ".join(pair.chunk_b.heading_path) or "(no heading)"
            loc_a = f"`{_short_path(pair.chunk_a.document_path)}`: {heading_a}"
            loc_b = f"`{_short_path(pair.chunk_b.document_path)}`: {heading_b}"
            sim_str = f"{pair.embedding_similarity:.3f}" if pair.embedding_similarity is not None else "—"
            lines.append(f"| {sim_str} | {loc_a} | {loc_b} |")
        lines.append("")

    # ── Stage 2: Doc-pair analysis ─────────────────────────────────────
    if result.doc_pair_analyses:
        lines.append("## Stage 2: Document-Pair Analysis\n")
        lines.append(f"Analyzed {len(result.doc_pair_analyses)} document pairs\n")

        for analysis in result.doc_pair_analyses:
            name_a = _short_path(analysis.doc_a_path)
            name_b = _short_path(analysis.doc_b_path)
            lines.append(f"### `{name_a}` / `{name_b}`\n")
            lines.append(f"- **Relationship**: {analysis.relationship} ({analysis.confidence} confidence)")
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

    # ── Topic Clusters ─────────────────────────────────────────────────
    if topic_clusters:
        lines.append("## Document Clusters by Topic\n")
        lines.append(f"Found {len(topic_clusters)} document clusters sharing common topics.\n")
        for i, cluster in enumerate(topic_clusters, 1):
            label = cluster["label"]
            docs = cluster["documents"]
            lines.append(f"### Cluster {i}: \"{label}\" ({len(docs)} documents)\n")
            for doc in docs:
                lines.append(f"- `{_short_path(doc)}`")
            shared = cluster.get("shared_topics", [])
            if shared:
                lines.append("")
                lines.append("**Shared topics:**\n")
                seen = set()
                for m in shared[:10]:
                    pair_key = (m["topic_a"], m["topic_b"])
                    if pair_key in seen:
                        continue
                    seen.add(pair_key)
                    if m["topic_a"] == m["topic_b"]:
                        lines.append(f"- {m['topic_a']} ({m['similarity']:.2f})")
                    else:
                        lines.append(f"- {m['topic_a']} ↔ {m['topic_b']} ({m['similarity']:.2f})")
            lines.append("")

    # ── Refactoring Suggestions ────────────────────────────────────────
    if suggestions:
        lines.append("## Refactoring Suggestions\n")
        for i, s in enumerate(suggestions, 1):
            code_name = s.get("code", "?")
            docs = s.get("documents", [])
            canonical = s.get("canonical", "?")
            lines.append(f"{i}. **\"{code_name}\"** ({len(docs)} documents)")
            lines.append(f"   - Canonical: `{_short_path(canonical)}`")
            for sug in s.get("suggestions", []):
                doc = _short_path(sug.get("document", "?"))
                action = sug.get("action", "?")
                reason = sug.get("reason", "")
                lines.append(f"   - `{doc}`: {action} — {reason}")
            lines.append("")

    # ── Methodology ────────────────────────────────────────────────────
    lines.append("## Methodology\n")
    lines.append("### Pipeline\n")
    lines.append(
        "dryscope uses a multi-stage pipeline to detect documentation overlap:\n\n"
        "1. **Similarity** — Splits documents into sections, generates sentence-transformers embeddings, "
        "and finds cross-document section pairs above the similarity threshold.\n"
        "2. **Intent** — Extracts granular topics per document via LLM, embeds them, "
        "and matches cross-document topics by cosine similarity to detect fragmented overlap.\n"
        "3. **LLM Analysis** — Sends each overlapping document pair to an LLM for "
        "relationship classification, topic-level canonical/action assignments, and "
        "refactoring suggestions.\n"
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
    topic_clusters: list[dict] | None = None,
) -> str:
    """Render analysis results as JSON."""

    def _pair_to_dict(pair: OverlapPair) -> dict:
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

    data: dict = {
        "summary": {
            "documents_scanned": len(result.documents),
            "chunks_analyzed": len(result.chunks),
            "similarity_pairs_found": len(similarity_pairs),
        },
        "documents": [
            _short_path(doc.path) for doc in sorted(result.documents, key=lambda d: d.path)
        ],
        "stages_run": stages_run or [],
    }

    if settings is not None and project_root is not None:
        data["metadata"] = _build_metadata(settings, project_root)
        recommendations = build_recommendations(similarity_pairs, suggestions, project_root)
        if recommendations:
            data["summary"]["recommendations_count"] = len(recommendations)
            data["recommendations"] = recommendations

    data["similarity_pairs"] = [_pair_to_dict(p) for p in similarity_pairs]

    if result.doc_pair_analyses:
        data["doc_pair_analyses"] = [
            {
                "doc_a": a.doc_a_path,
                "doc_a_name": _short_path(a.doc_a_path),
                "doc_b": a.doc_b_path,
                "doc_b_name": _short_path(a.doc_b_path),
                "doc_a_purpose": a.doc_a_purpose,
                "doc_b_purpose": a.doc_b_purpose,
                "relationship": a.relationship,
                "confidence": a.confidence,
                "topics": [
                    {
                        "name": t.name,
                        "canonical": t.canonical,
                        "canonical_name": _short_path(t.canonical),
                        "action_for_other": t.action_for_other,
                        "reason": t.reason,
                    }
                    for t in a.topics
                ],
            }
            for a in result.doc_pair_analyses
        ]

    if result.categories:
        data["categories"] = {
            cat.name: {
                code.name: sorted(set(c.document_path for c in code.chunks))
                for code in cat.codes
            }
            for cat in result.categories
        }

    if topic_clusters:
        data["topic_clusters"] = topic_clusters

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
.dashboard { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem;
             margin: 1.5rem 0; }
.metric-card { background: #f8f9fa; border: 1px solid var(--border); border-radius: 8px;
               padding: 1rem; text-align: center; }
.metric-value { font-size: 2rem; font-weight: 700; color: var(--accent); }
.metric-label { font-size: .85rem; color: var(--muted); text-transform: uppercase;
                letter-spacing: .05em; }
.pipeline-bar { grid-column: 1 / -1; background: #f8f9fa; border: 1px solid var(--border);
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

    # Post-process: wrap Stage 2 doc-pair h3 sections in <details>/<summary>
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
    """Wrap Stage 2 doc-pair h3 sections in collapsible <details> elements.

    Looks for h3 tags that follow the "file_a / file_b" pattern and wraps
    each h3 + its following content (until the next h2/h3 or end) in a
    <details><summary> block.
    """
    import re

    # Match h3 headers containing " / " (doc-pair pattern, may contain <code> tags)
    pattern = r'(<h3>(.*?/.*?)</h3>)'
    parts = re.split(pattern, html)

    if len(parts) <= 1:
        return html

    # Rebuild: parts[0] is before first match, then groups of (full_match, tag_content, inner_text, after)
    rebuilt: list[str] = [parts[0]]
    i = 1
    while i < len(parts):
        full_h3 = parts[i]       # <h3>...</h3>
        h3_text = parts[i + 1]   # inner text
        # Content after this h3, up to next section
        after = parts[i + 2] if i + 2 < len(parts) else ""

        # Split 'after' at the next h2 or h3 boundary
        next_heading = re.search(r'(?=<h[23]>)', after)
        if next_heading:
            section_content = after[:next_heading.start()]
            remaining = after[next_heading.start():]
        else:
            section_content = after
            remaining = ""

        rebuilt.append(
            f"<details>\n<summary>{h3_text.strip()}</summary>\n"
            f"{section_content}\n</details>\n"
        )
        rebuilt.append(remaining)
        i += 3

    return "".join(rebuilt)


def _inject_recommendation_slider(html: str) -> str:
    """Add data-score attributes to recommendation table rows and inject a slider.

    Finds the first table after the Recommendations heading, adds data-score to
    each body row, wraps it with an id, and inserts a range slider above it.
    """
    import re

    # Find the Recommendations h2 and the first table after it
    rec_match = re.search(r'<h2[^>]*>Recommendations</h2>', html, re.IGNORECASE)
    if not rec_match:
        return html

    # Find the first <table> after the Recommendations heading
    table_start = html.find('<table>', rec_match.end())
    if table_start == -1:
        return html
    table_end = html.find('</table>', table_start)
    if table_end == -1:
        return html
    table_end += len('</table>')

    table_html = html[table_start:table_end]

    # Add data-score to each <tr> in tbody by extracting the score from the second <td>
    def _add_data_score(match: re.Match) -> str:
        row = match.group(0)
        # Extract score from second td (first td is rank #)
        tds = re.findall(r'<td>(.*?)</td>', row)
        if len(tds) >= 2:
            try:
                score = int(tds[1].strip())
                return row.replace('<tr>', f'<tr data-score="{score}">', 1)
            except ValueError:
                pass
        return row

    # Only process rows in tbody (skip header row)
    thead_end = table_html.find('</thead>')
    if thead_end != -1:
        thead_part = table_html[:thead_end + len('</thead>')]
        tbody_part = table_html[thead_end + len('</thead>'):]
    else:
        # No explicit thead — skip the first <tr> (header row)
        first_tr_end = table_html.find('</tr>') + len('</tr>')
        thead_part = table_html[:first_tr_end]
        tbody_part = table_html[first_tr_end:]

    tbody_part = re.sub(r'<tr>.*?</tr>', _add_data_score, tbody_part, flags=re.DOTALL)

    new_table = f'<table id="rec-table">{thead_part[len("<table>"):]}{tbody_part}'

    # Count rows for slider label
    row_count = len(re.findall(r'data-score=', tbody_part))

    slider_html = (
        '<div class="slider-container">'
        '<label for="score-slider">Min score:</label>'
        '<input type="range" id="score-slider" min="0" max="100" value="0">'
        '<span class="slider-value" id="slider-label">0</span>'
        f'<span id="rec-count">{row_count} of {row_count}</span>'
        '</div>\n'
    )

    return html[:table_start] + slider_html + new_table + html[table_end:]


# ─── LLM-Friendly Output Helpers ───────────────────────────────────────


def _relative_path(path: str, root: Path) -> str:
    """Absolute path → relative to project root. Falls back to original if not under root."""
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def _git_commit(root: Path) -> str | None:
    """Get current git commit hash, or None if not a git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
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


def serialize_similarity_stage(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    settings: Settings,
    project_root: Path,
) -> dict:
    """Serialize similarity stage output for persistent storage."""
    return {
        "metadata": _build_metadata(settings, project_root),
        "summary": {
            "documents_scanned": len(result.documents),
            "chunks_analyzed": len(result.chunks),
            "pairs_found": len(similarity_pairs),
            "threshold": settings.threshold_similarity,
            "model": settings.docs_embedding_model,
        },
        "pairs": [_pair_to_rich_dict(p, project_root) for p in similarity_pairs],
    }


def serialize_coding_stage(
    codes: list[Code],
    categories: list[Category],
    suggestions: list[dict] | None,
    settings: Settings,
    project_root: Path,
    analyses: list[DocPairAnalysis] | None = None,
) -> dict:
    """Serialize LLM coding stage output for persistent storage."""
    data: dict = {
        "metadata": _build_metadata(settings, project_root),
        "summary": {
            "codes_found": len(codes),
            "categories_found": len(categories),
            "model": settings.model,
        },
        "categories": {
            cat.name: {
                code.name: sorted(set(
                    _relative_path(c.document_path, project_root) for c in code.chunks
                ))
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
    "table of contents", "toc", "license", "changelog", "change log",
    "release notes", "contributing", "code of conduct",
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
        best_similarity = best_pair.embedding_similarity if best_pair.embedding_similarity is not None else 0

        has_coding = bool(best_pair.shared_codes and
                          any(c in suggestion_codes for c in best_pair.shared_codes))

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
            sections_a.append({
                "sections": p.chunk_a.heading_path or ["(no heading)"],
                "line_range": [p.chunk_a.line_start, p.chunk_a.line_end],
            })
            sections_b.append({
                "sections": p.chunk_b.heading_path or ["(no heading)"],
                "line_range": [p.chunk_b.line_start, p.chunk_b.line_end],
            })

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

        recommendations.append({
            "priority_score": score,
            "affected_files": [
                {"file": file_a, "sections": sections_a},
                {"file": file_b, "sections": sections_b},
            ],
            "overlap_type": overlap_type,
            "embedding_similarity": (
                round(best_similarity, 4)
                if best_similarity is not None else None
            ),
            "suggested_action": action,
            "action_detail": detail,
        })

    # Sort by priority score descending, assign ranks
    recommendations.sort(key=lambda r: r["priority_score"], reverse=True)
    for i, rec in enumerate(recommendations, 1):
        rec["priority_rank"] = i

    return recommendations


# ─── Final Report ───────────────────────────────────────────────────────


def render_final_report(
    result: AnalysisResult,
    similarity_pairs: list[OverlapPair],
    suggestions: list[dict] | None,
    settings: Settings,
    project_root: Path,
    stages_run: list[str] | None = None,
    topic_clusters: list[dict] | None = None,
) -> dict:
    """Build the complete report.json for persistent storage."""
    recommendations = build_recommendations(
        similarity_pairs, suggestions, project_root,
    )

    report: dict = {
        "metadata": _build_metadata(settings, project_root),
        "summary": {
            "documents_scanned": len(result.documents),
            "chunks_analyzed": len(result.chunks),
            "similarity_pairs_found": len(similarity_pairs),
            "recommendations_count": len(recommendations),
        },
        "documents": [
            _short_path(doc.path) for doc in sorted(result.documents, key=lambda d: d.path)
        ],
        "stages_run": stages_run or [],
        "recommendations": recommendations,
    }

    if topic_clusters:
        report["topic_clusters"] = topic_clusters

    return report
