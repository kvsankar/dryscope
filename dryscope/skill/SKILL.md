---
name: dryscope
description: Detect duplicate code and documentation overlap in projects using tree-sitter parsing, normalization, and embedding-based similarity. Use when the user asks to find duplicate code, detect code clones, check for copy-paste code, find repeated patterns, DRY violations, or documentation overlap. Keywords - duplicate, clone, copy-paste, DRY, repetition, similarity, refactor duplicates, documentation overlap, redundant docs, doc overlap.
allowed-tools: [Bash, Read, Glob, Grep]
---

## What this skill does

Runs **dryscope** — a unified tool for detecting code duplicates and documentation overlap. It uses tree-sitter to parse code into units (functions, classes, methods), normalizes them, generates embeddings, and clusters similar items together. For docs, it has two tracks:
- **Information Architecture**: document descriptors, canonical labels, IA topic tree, facets, diagnostics, and suggested consolidation clusters
- **Section Similarity**: heading-based section comparison and concrete section-level recommendations

The intended use is narrowing:
- use `dryscope` to find candidate duplicates or overlapping docs
- then let a stronger model or a human decide what to refactor or consolidate

## How to use

```bash
# Code duplicates (default)
{{DRYSCOPE_BIN}} scan <target-path> --code

# Documentation overlap
{{DRYSCOPE_BIN}} scan <target-path> --docs

# Full documentation IA + section similarity report
{{DRYSCOPE_BIN}} scan <target-path> --docs --stage full --backend cli -f html

# Both at once
{{DRYSCOPE_BIN}} scan <target-path> --code --docs
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--code` | on | Scan for code duplicates |
| `--docs` | off | Scan for documentation overlap |
| `--lang` | auto | Language filter: `python`, `go`, `java`, `js`, `jsx`, `ts`, `tsx` |
| `-t, --threshold` | `0.90` | Similarity threshold (0.0-1.0). Higher = stricter. |
| `-m, --min-lines` | `6` | Minimum lines for a code unit to be considered |
| `--min-tokens` | `0` | Minimum unique normalized tokens (filters trivial units) |
| `--max-cluster-size` | `15` | Drop clusters larger than this |
| `-e, --exclude` | | Glob patterns to exclude (e.g. `*/tests/*`) |
| `--exclude-type` | | Base class types to exclude (e.g. `TextChoices`) |
| `-f, --format` | `terminal` | Output format: `terminal`, `json`, `markdown`, or `html` |
| `--embedding-model` | `text-embedding-3-small` | Embedding model; API models use LiteLLM, local sentence-transformers require `.[local-embeddings]` |
| `--verify` | off | Use LLM verification plus deterministic escalation policy |
| `--llm-model` | `claude-haiku-4-5-20251001` | LLM model for verification |

### Recommended usage

**Prefer `--verify` for higher-signal results.** Without it, the tool reports all structurally similar items — including framework boilerplate and coincidental matches. The `--verify` flag uses an LLM (default: claude-haiku-4-5) to label each cluster as `refactor`, `review`, or `noise`, then applies a deterministic policy so low-value `refactor` findings do not automatically survive.

For documentation repos, `--docs --verify` now also:
- extracts rich document descriptors across the selected docs corpus
- canonicalizes aboutness and reader-intent labels into a corpus taxonomy
- discovers a candidate Information Architecture topic tree, facets, and diagnostics
- separates IA consolidation clusters from Section Similarity recommendations
- writes markdown, HTML, and JSON reports with the same top-down section structure and no duplicate sample/full-list sections

```bash
# Code duplicates with LLM verification
{{DRYSCOPE_BIN}} scan /path/to/project --code --verify --min-tokens 15

# Documentation overlap detection
{{DRYSCOPE_BIN}} scan /path/to/project --docs --verify

# Full docs IA report
{{DRYSCOPE_BIN}} scan /path/to/project --docs --stage full --backend cli -f html

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

### Code duplicates
- **Similarity 1.0**: Identical after normalization (Type-1/Type-2 clones) — strong candidates, but still check whether the payoff is meaningful
- **Similarity 0.95-0.99**: Near-identical structure with minor differences (Type-3 clones)
- **Similarity 0.85-0.95**: Structurally similar, may be legitimate patterns or true duplicates

### Documentation overlap
- **Information Architecture**: Corpus-level topic groups, facets, diagnostics, and consolidation clusters. Use this to understand how docs should be organized.
- **Section Similarity**: Similar section pairs and section similarity recommendations. Use this to find repeated text that should be consolidated or cross-referenced.
- **Doc-pair analysis**: Optional deeper LLM analysis of related document pairs when enabled and within the configured cost cap.

## What it detects

- Exact code copies across files (e.g., utility functions copy-pasted)
- Renamed clones (same logic, different variable/function names)
- Structural clones with shared implementation shape
- Repeated boilerplate can still appear structurally, but `--verify` is intended to filter much of it back out
- Documentation IA overlap across documents that cover the same subjects or reader intents
- Overlapping documentation sections across markdown/text files
- Redundant explanations that could be consolidated or cross-referenced

## What it skips

- `.venv/`, `node_modules/`, `__pycache__/`, `site-packages/`, etc.
- Code units shorter than `--min-lines`
- Supported code languages: Python, Go, Java, JavaScript, JSX, TypeScript, TSX

## After running

Summarize the findings for the user, highlighting:
1. **Exact copies** that should definitely be refactored
2. **Structural clones** that could benefit from abstraction
3. **Information Architecture findings**: topic groups, facets, diagnostics, and suggested consolidation clusters
4. **Section Similarity findings**: concrete repeated sections and recommendations
5. **Legitimate patterns** that look similar but serve different purposes

If the repo is docs-heavy and the tool returns no section recommendations, still check whether the IA track found consolidation clusters or diagnostics. A clean negative result is a useful outcome, not a failure.
