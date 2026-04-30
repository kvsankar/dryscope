---
name: dryscope
description: Preflight repositories before AI-assisted refactors and documentation consolidation with Code Match, Code Review, Docs Map, Section Match, and Doc Pair Review. Use when the user asks to narrow a repo for an agent/model, find duplicate code, detect code clones, check for copy-paste code, find repeated patterns, DRY violations, redundant docs, repeated docs, or doc consolidation targets. Keywords - AI preflight, repo narrowing, Code Match, Code Review, Docs Map, Section Match, Doc Pair Review, duplicate, clone, copy-paste, DRY, repetition, similarity, refactor duplicates, redundant docs, repeated docs, doc overlap.
allowed-tools: [Bash, Read, Glob, Grep]
---

## What this skill does

Runs **dryscope** — a preflight scanner for narrowing a repository before
AI-assisted refactors and documentation consolidation. It uses tree-sitter to
parse code into units (functions, classes, methods), normalizes them, generates
embeddings, and clusters similar items together. User-facing outputs use these tracks:
- **Code Match** (`code-match`): structural duplicate-code candidates
- **Code Review** (`code-review`): optional LLM/policy filtering of Code Match findings
- **Docs Map** (`docs-map`): document descriptors, canonical labels, topic tree, facets, diagnostics, and consolidation clusters
- **Section Match** (`docs-section-match`): heading-based section comparison and concrete section-level recommendations
- **Doc Pair Review** (`docs-pair-review`): optional LLM review of selected related document pairs

The intended use is narrowing:
- use `dryscope` to find candidate duplicate code, repeated docs, and IA overlap
- hand the shortlist to an agent, stronger model, or human reviewer
- treat results as triage input, not as an automatic refactor decision

## How to use

```bash
# Code Match (default)
{{DRYSCOPE_BIN}} scan <target-path> --code

# Section Match
{{DRYSCOPE_BIN}} scan <target-path> --docs

# Full docs run: Docs Map + Section Match + Doc Pair Review
{{DRYSCOPE_BIN}} scan <target-path> --docs --stage docs-report-pack --backend cli -f html

# Both at once
{{DRYSCOPE_BIN}} scan <target-path> --code --docs
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--code` | on | Run Code Match |
| `--docs` | off | Run docs tracks |
| `--lang` | auto | Language filter: `python`, `go`, `java`, `js`, `jsx`, `ts`, `tsx` |
| `-t, --threshold` | `0.90` | Similarity threshold (0.0-1.0). Higher = stricter. |
| `-m, --min-lines` | `6` | Minimum lines for a code unit to be considered |
| `--min-tokens` | `0` | Minimum unique normalized tokens (filters trivial units) |
| `--max-cluster-size` | `15` | Drop clusters larger than this |
| `--max-findings` | | Limit Code Match/Code Review to the top N code findings |
| `-e, --exclude` | | Glob patterns to exclude (e.g. `*/tests/*`) |
| `--exclude-type` | | Base class types to exclude (e.g. `TextChoices`) |
| `-f, --format` | `terminal` | Output format: `terminal`, `json`, `markdown`, or `html` |
| `--embedding-model` | `text-embedding-3-small` | Embedding model; API models use LiteLLM, local sentence-transformers require `.[local-embeddings]` |
| `--verify` | off | Run Code Review for code; run full docs tracks for docs |
| `--llm-model` | `claude-haiku-4-5-20251001` | LLM model for verification |
| `--llm-max-doc-pairs` | config | Maximum document pairs for Doc Pair Review |

### Recommended usage

**Prefer `--verify` for higher-signal results.** Without it, the tool reports all structurally similar items — including framework boilerplate and coincidental matches. The `--verify` flag uses an LLM (default: claude-haiku-4-5) to label each cluster as `refactor`, `review`, or `noise`, then applies a deterministic policy so low-value `refactor` findings do not automatically survive.

For documentation repos, `--docs --verify` now also:
- extracts rich document descriptors across the selected docs corpus
- canonicalizes aboutness and reader-intent labels into a corpus taxonomy
- discovers a candidate Docs Map topic tree, facets, and diagnostics
- separates Docs Map clusters from Section Match recommendations
- writes markdown, HTML, and JSON reports with the same top-down section structure and no duplicate sample/full-list sections

```bash
# Code Review
{{DRYSCOPE_BIN}} scan /path/to/project --code --verify --min-tokens 15

# Bounded Code Review for duplicate-rich repos
{{DRYSCOPE_BIN}} scan /path/to/project --code --verify --max-findings 15

# Full docs tracks
{{DRYSCOPE_BIN}} scan /path/to/project --docs --verify

# Docs Report Pack
{{DRYSCOPE_BIN}} scan /path/to/project --docs --stage docs-report-pack --backend cli -f html

# Preview cleanup of saved report runs
{{DRYSCOPE_BIN}} reports clean /path/to/project --keep-last 10

# Delete report runs older than 30 days
{{DRYSCOPE_BIN}} reports clean /path/to/project --keep-days 30 --force

# Both code and docs
{{DRYSCOPE_BIN}} scan /path/to/project --code --docs --verify
```

Backend options:
- embedding models such as `text-embedding-3-small` use provider API keys such as `OPENAI_API_KEY`
- local embedding models such as `all-MiniLM-L6-v2` require installing dryscope with `.[local-embeddings]`
- `backend = "cli"` uses `claude -p` and can work with Claude OAuth/session auth
- `backend = "codex-cli"` uses `codex exec` and works with Codex CLI auth
- `backend = "litellm"` uses provider API keys such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- `backend = "ollama"` uses the local Ollama API at `OLLAMA_HOST` or `http://localhost:11434`

Saved report cleanup:
- `{{DRYSCOPE_BIN}} reports clean /path/to/project --keep-last 10` previews deleting all but the newest 10 saved runs
- `{{DRYSCOPE_BIN}} reports clean /path/to/project --keep-since 2026-04-01` previews deleting runs before the cutoff date
- `{{DRYSCOPE_BIN}} reports clean /path/to/project --keep-days 30 --force` deletes runs older than 30 days
- cleanup is dry-run unless `--force` is present, and `.dryscope/latest` is repointed after deletion

### More examples

```bash
# Quick offline scan (no LLM)
{{DRYSCOPE_BIN}} scan /path/to/project --code

# Strict threshold, JSON output
{{DRYSCOPE_BIN}} scan /path/to/project --code --verify -t 0.95 -f json

# Docs only, custom embedding model
{{DRYSCOPE_BIN}} scan /path/to/project --docs --embedding-model text-embedding-3-small

# Pipe JSON for further analysis
{{DRYSCOPE_BIN}} scan /path/to/project --code --docs --verify -f json > results.json
```

## Interpreting results

### Code Match and Code Review
- **Similarity 1.0**: Identical after normalization (Type-1/Type-2 clones) — strong candidates, but still check whether the payoff is meaningful
- **Similarity 0.95-0.99**: Near-identical structure with minor differences (Type-3 clones)
- **Similarity 0.85-0.95**: Structurally similar, may be legitimate patterns or true duplicates

### Docs tracks
- **Docs Map**: Corpus-level topic groups, facets, diagnostics, and consolidation clusters. Use this to understand how docs should be organized.
- **Section Match**: Matched section pairs and section-level recommendations. Use this to find repeated text that should be consolidated or cross-referenced.
- **Doc Pair Review**: Optional deeper LLM analysis of related document pairs when enabled and within the configured cost cap.

## What it detects

- Exact code copies across files (e.g., utility functions copy-pasted)
- Renamed clones (same logic, different variable/function names)
- Structural clones with shared implementation shape
- Repeated boilerplate can still appear structurally, but `--verify` is intended to filter much of it back out
- For large duplicate-rich repos, `--max-findings` keeps verification focused on the highest-ranked candidates
- Docs Map overlap across documents that cover the same subjects or reader intents
- Overlapping documentation sections across Markdown, MDX, reStructuredText, AsciiDoc, and text files
- Redundant explanations that could be consolidated or cross-referenced

## What it skips

- `.venv/`, `node_modules/`, `__pycache__/`, `site-packages/`, etc.
- Code units shorter than `--min-lines`
- Supported code languages: Python, Go, Java, JavaScript, JSX, TypeScript, TSX

## After running

Summarize the findings for the user, highlighting:
1. **Exact copies** that should definitely be refactored
2. **Structural clones** that could benefit from abstraction
3. **Docs Map findings**: topic groups, facets, diagnostics, and suggested consolidation clusters
4. **Section Match findings**: concrete repeated sections and recommendations
5. **Legitimate patterns** that look similar but serve different purposes

If the repo is docs-heavy and Section Match returns no recommendations, still check whether Docs Map found consolidation clusters or diagnostics. A clean negative result is a useful outcome, not a failure.
