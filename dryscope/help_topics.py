"""Progressive CLI help topics for dryscope."""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

from dryscope.terminology import (
    CODE_MATCH,
    CODE_MATCH_SLUG,
    CODE_REVIEW,
    CODE_REVIEW_SLUG,
    DOCS_MAP,
    DOCS_PAIR_REVIEW,
    DOCS_REPORT_PACK,
    DOCS_REPORT_PACK_SLUG,
    DOCS_SECTION_MATCH,
    DOCS_SECTION_MATCH_SLUG,
)


@dataclass(frozen=True)
class HelpTopic:
    """A named help topic with aliases."""

    name: str
    aliases: tuple[str, ...]
    summary: str
    body: str


OUTPUT_FORMATS = (
    (
        "terminal",
        "code, docs, code+docs",
        "Human-readable CLI output. This is the default.",
    ),
    (
        "json",
        "code, docs, code+docs",
        "Machine-readable output for agents, scripts, and benchmark runners.",
    ),
    (
        "markdown",
        "docs-only",
        "Docs Report Pack as a readable Markdown report.",
    ),
    (
        "html",
        "docs-only",
        "Docs Report Pack as a collapsible HTML report.",
    ),
)


def _format_table(rows: tuple[tuple[str, str, str], ...]) -> str:
    lines = ["Format      Supported modes        Meaning"]
    lines.append("----------  ---------------------  ----------------------------------------")
    for name, modes, meaning in rows:
        lines.append(f"{name:<10}  {modes:<21}  {meaning}")
    return "\n".join(lines)


OUTPUT_FORMAT_TABLE = _format_table(OUTPUT_FORMATS)


HELP_TOPICS: tuple[HelpTopic, ...] = (
    HelpTopic(
        name="tracks",
        aliases=("track", "modes", "mode"),
        summary="Choose between Code Match, Code Review, Docs Map, Section Match, and Doc Pair Review.",
        body=dedent(
            f"""
            Tracks

            {CODE_MATCH} ({CODE_MATCH_SLUG})
              Parses supported code into functions/classes/methods, normalizes
              each unit, embeds it, and returns duplicate-code candidates.

            {CODE_REVIEW} ({CODE_REVIEW_SLUG})
              Optional verification pass for Code Match. It uses the configured
              LLM backend plus deterministic policy to keep likely refactor or
              review-worthy clusters.

            {DOCS_SECTION_MATCH} ({DOCS_SECTION_MATCH_SLUG})
              Section-level docs overlap. It compares heading-based chunks and
              reports repeated or near-repeated sections across documents.

            {DOCS_MAP}
              Corpus-level docs view. It profiles documents, canonicalizes
              aboutness and intent labels, and builds topic/facet clusters.

            {DOCS_PAIR_REVIEW}
              Optional LLM review of selected related document pairs.

            {DOCS_REPORT_PACK} ({DOCS_REPORT_PACK_SLUG})
              Full docs report: Docs Map, Section Match, optional Doc Pair
              Review, Markdown/HTML/JSON reports, and saved run artifacts.

            Common commands:
              dryscope scan PATH
              dryscope scan PATH --verify
              dryscope scan PATH --docs
              dryscope scan PATH --docs --stage {DOCS_REPORT_PACK_SLUG}
              dryscope scan PATH --code --docs -f json
            """
        ).strip(),
    ),
    HelpTopic(
        name="output",
        aliases=("outputs", "format", "formats"),
        summary="Understand terminal, JSON, Markdown, and HTML output choices.",
        body=dedent(
            """
            Output Formats

            Use -f/--format on `dryscope scan`.

            {output_format_table}

            Mode rules:
              - Code-only scans support terminal and json.
              - Docs-only scans support terminal, json, markdown, and html.
              - Combined --code --docs scans support terminal and json.
              - Docs report files are also saved under .dryscope/runs/<run-id>/
                when docs mode runs.

            Examples:
              dryscope scan PATH -f terminal
              dryscope scan PATH --code -f json
              dryscope scan PATH --docs -f markdown
              dryscope scan PATH --docs --stage {docs_report_pack_slug} -f html

            More detail:
              dryscope help json
              docs/json-output.md
            """
        ).strip().format(
            output_format_table=OUTPUT_FORMAT_TABLE,
            docs_report_pack_slug=DOCS_REPORT_PACK_SLUG,
        ),
    ),
    HelpTopic(
        name="json",
        aliases=("schema", "schemas", "json-output", "output-json"),
        summary="Explain the machine-readable JSON output contracts.",
        body=dedent(
            f"""
            JSON Output

            `dryscope scan ... -f json` has two main shapes.

            Code JSON, including Code Match and Code Review:
              {{
                "dryscope_version": "...",
                "report_pack": {{"label": "Code Report Pack", "slug": "code-report-pack"}},
                "track": "{CODE_MATCH} | {CODE_REVIEW}",
                "track_slug": "{CODE_MATCH_SLUG} | {CODE_REVIEW_SLUG}",
                "findings": [...],
                "summary": {{"code": {{"total": 0, "exact": 0, "near": 0, "structural": 0}}}}
              }}

            Code finding fields include:
              id, mode, track, track_slug, similarity, tier, files,
              is_cross_file, total_lines, actionability, units, and optional
              verdict/verdict_reason after Code Review.

            Docs report JSON:
              {{
                "report_pack": {{"label": "{DOCS_REPORT_PACK}", "slug": "{DOCS_REPORT_PACK_SLUG}"}},
                "metadata": {{...}},
                "summary": {{...}},
                "report_structure": [...]
              }}

            `report_structure` is the stable traversal point for docs JSON.
            Each section owns its detailed data, such as Docs Map, Docs Map
            Clusters, Section Match recommendations, matched section pairs, Doc
            Pair Review, and Docs Map Taxonomy.

            Stage artifacts under .dryscope/runs/<run-id>/ expose narrower
            intermediate JSON files such as docs_section_match.json,
            docs_map.json, and docs_pair_review.json.

            Full schema notes and examples:
              docs/json-output.md
            """
        ).strip(),
    ),
    HelpTopic(
        name="config",
        aliases=("configuration", "settings"),
        summary="See config layering, .dryscope.toml, and common scan knobs.",
        body=dedent(
            """
            Configuration

            Generate a starting config:
              dryscope init

            Settings are resolved in this order:
              defaults -> .dryscope.toml -> CLI flags

            Main sections:
              [code]      code thresholds, min size filters, embedding model
              [docs]      docs include/exclude rules, thresholds, stage limits
              [docs.map]  generic facet seed dimensions for Docs Map
              [llm]       model, backend, max cost, concurrency
              [cache]     cache enablement and path

            More detail:
              README.md#configuration
            """
        ).strip(),
    ),
    HelpTopic(
        name="benchmarks",
        aliases=("benchmark", "quality"),
        summary="Find public benchmark runners, artifacts, and quality reports.",
        body=dedent(
            """
            Benchmarks

            Public benchmark inputs, labels, runners, and quality report
            generation live under benchmarks/.

            Durable benchmark repos and outputs default to:
              ~/.dryscope/benchmarks/

            Benchmark input folders include repo names plus commit hashes so
            generated outputs can be traced to exact repository revisions.

            Common commands:
              uv run python benchmarks/run_public_benchmark.py
              uv run python benchmarks/run_public_docs_benchmark.py
              uv run python benchmarks/run_quality_report.py

            More detail:
              benchmarks/README.md
              benchmarks/quality_report.md
            """
        ).strip(),
    ),
)

_TOPICS_BY_NAME: dict[str, HelpTopic] = {}
for _topic in HELP_TOPICS:
    _TOPICS_BY_NAME[_topic.name] = _topic
    for _alias in _topic.aliases:
        _TOPICS_BY_NAME[_alias] = _topic


def topic_names() -> list[str]:
    """Return canonical topic names in display order."""
    return [topic.name for topic in HELP_TOPICS]


def topic_summaries() -> str:
    """Render the topic index."""
    lines = [
        "Help Topics",
        "",
        "Use `dryscope help TOPIC` for details. `dryscope --help TOPIC` is also supported.",
        "",
    ]
    width = max(len(topic.name) for topic in HELP_TOPICS)
    for topic in HELP_TOPICS:
        aliases = f" (aliases: {', '.join(topic.aliases)})" if topic.aliases else ""
        lines.append(f"  {topic.name:<{width}}  {topic.summary}{aliases}")
    return "\n".join(lines)


def get_topic(name: str) -> HelpTopic | None:
    """Find a help topic by name or alias."""
    key = name.strip().lower().replace("_", "-")
    return _TOPICS_BY_NAME.get(key)


def render_topic(name: str) -> str:
    """Render a help topic, raising KeyError when it does not exist."""
    topic = get_topic(name)
    if topic is None:
        raise KeyError(name)
    return topic.body
