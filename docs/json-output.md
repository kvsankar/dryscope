# JSON Output Contracts

This document explains the machine-readable output surfaces that dryscope
produces. It is a contract guide for agents and scripts, not a formal JSON
Schema file.

For CLI help:

```bash
dryscope help output
dryscope help json
```

## Output Surfaces

| Surface | Command | Shape |
| --- | --- | --- |
| Code JSON | `dryscope scan PATH --code -f json` | Unified `findings[]` JSON for Code Match or Code Review |
| Combined JSON | `dryscope scan PATH --code --docs -f json` | Unified `findings[]` JSON with code and docs findings |
| Docs report JSON | `dryscope scan PATH --docs -f json` | Docs Report Pack JSON with `report_structure[]` |
| Saved docs report | `.dryscope/runs/<run-id>/report.json` | Same docs report contract as docs report JSON |
| Docs stage artifacts | `.dryscope/runs/<run-id>/*.json` | Narrow stage-specific payloads |
| Benchmark quality JSON | `quality_report.json` | Label-scored benchmark quality metrics |

Consumers should ignore unknown fields. New fields may be added, but existing
field meanings should remain stable.

## Unified Findings JSON

Code scans and combined code/docs scans use the unified findings shape:

```json
{
  "dryscope_version": "0.1.0",
  "findings": [],
  "summary": {}
}
```

Code-only scans also include the active report pack and track:

```json
{
  "dryscope_version": "0.1.0",
  "report_pack": {
    "label": "Code Report Pack",
    "slug": "code-report-pack"
  },
  "track": "Code Match",
  "track_slug": "code-match",
  "findings": [],
  "summary": {
    "code": {
      "total": 0,
      "exact": 0,
      "near": 0,
      "structural": 0
    }
  }
}
```

When `--verify` keeps verified code findings, `track` becomes `Code Review` and
`track_slug` becomes `code-review`.

### Code Finding

Code findings have this shape:

```json
{
  "id": 0,
  "mode": "code",
  "track": "Code Match",
  "track_slug": "code-match",
  "tier": "exact",
  "similarity": 1.0,
  "is_cross_file": true,
  "total_lines": 42,
  "files": ["src/a.py", "src/b.py"],
  "actionability": 2.31,
  "units": [
    {
      "name": "load_config",
      "type": "function",
      "file": "src/a.py",
      "start_line": 10,
      "end_line": 32,
      "lines": 23,
      "source": "..."
    }
  ]
}
```

Important fields:

- `tier`: `exact`, `near`, or `structural`.
- `similarity`: highest pair similarity inside the cluster.
- `actionability`: ranking score; higher appears earlier.
- `files`: scan-root-relative file paths.
- `units`: concrete code units in the cluster.
- `verdict` and `verdict_reason`: present only after Code Review keeps a
  verified finding.

### Docs Finding In Combined JSON

Combined `--code --docs -f json` output includes docs findings in the same
`findings[]` list:

```json
{
  "id": 1,
  "mode": "docs",
  "track": "Section Match",
  "track_slug": "docs-section-match",
  "similarity": 0.94,
  "files": ["docs/a.md", "docs/b.md"],
  "sections": [
    {
      "file": "docs/a.md",
      "heading": "Configuration",
      "line_start": 10,
      "line_end": 24,
      "content": "..."
    }
  ],
  "verdict": null,
  "verdict_reason": null
}
```

If Doc Pair Review ran and matched that document pair, `track` becomes
`Doc Pair Review`, and `verdict` / `verdict_reason` summarize the relationship
and recommended action.

## Docs Report JSON

Docs-only JSON output and saved `.dryscope/runs/<run-id>/report.json` use the
Docs Report Pack contract:

```json
{
  "report_pack": {
    "label": "Docs Report Pack",
    "slug": "docs-report-pack"
  },
  "metadata": {},
  "summary": {
    "documents_scanned": 0,
    "chunks_analyzed": 0,
    "matched_section_pairs_found": 0,
    "section_match_recommendations_found": 0
  },
  "report_structure": []
}
```

`report_structure[]` is the stable traversal point. Each item is an ordered
section with:

- `id`: stable section identifier.
- `number` and `title_numbered`: display order.
- `title`: human-readable section name.
- `slug`: track slug when a section belongs to a track.
- `data`: section-owned payload.
- `children`: optional nested sections.

Common section IDs:

- `run_overview`
- `docs_map`
- `docs_map_clusters`
- `docs_section_match`
- `docs_section_match_recommendations`
- `matched_section_pairs`
- `docs_pair_review`
- `docs_map_taxonomy`
- `methodology`

The docs report avoids duplicate "sample first, full list later" payloads.
Detailed data belongs under the owning section.

## Docs Stage Artifacts

Docs runs save resumable stage artifacts under `.dryscope/runs/<run-id>/`.
These are useful for debugging and benchmarking, but they are narrower than the
final report contract.

Common artifacts:

- `docs_section_match.json`: matched section pairs and Section Match metadata.
- `docs_map.json`: document descriptors, taxonomy, topic tree, facets, and
  Docs Map clusters.
- `docs_pair_review.json`: Doc Pair Review analyses and suggestions.
- `docs_pair_review.jsonl`: incremental raw review results for resume.
- `report.md`, `report.html`, `report.json`: final report outputs.

## Benchmark Quality JSON

`benchmarks/run_quality_report.py` writes `quality_report.json` next to the
readable `quality_report.md`. It scores generated benchmark outputs against
curated public labels.

Top-level keys:

- `metric_notes`
- `code_review`
- `docs_section_match`

Each scored track contains:

- `benchmark_metadata`
- `aggregate`
- `by_repo`

Aggregate and per-repo rows use TP, FP, FN, labeled precision, curated recall,
F1, precision@K, recall@K, surfaced counts, and gold-label counts. The readable
companion report explains which numbers are better when higher or lower.
