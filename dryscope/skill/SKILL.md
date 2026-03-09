---
name: dryscope
description: Detect duplicate code and documentation overlap in projects using tree-sitter parsing and embedding-based similarity. Use when the user asks to find duplicate code, detect code clones, check for copy-paste code, find repeated patterns, DRY violations, or documentation overlap. Keywords - duplicate, clone, copy-paste, DRY, repetition, similarity, refactor duplicates, documentation overlap, redundant docs, doc overlap.
allowed-tools: [Bash, Read, Glob, Grep]
---

## What this skill does

Runs **dryscope** — a unified tool for detecting code duplicates and documentation overlap. It uses tree-sitter to parse code into units (functions, classes, methods), normalizes them, generates embeddings, and clusters similar items together. For docs, it detects overlapping or redundant documentation sections.

## How to use

```bash
# Code duplicates (default)
{{DRYSCOPE_BIN}} scan <target-path> --code

# Documentation overlap
{{DRYSCOPE_BIN}} scan <target-path> --docs

# Both at once
{{DRYSCOPE_BIN}} scan <target-path> --code --docs
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--code` | on | Scan for code duplicates |
| `--docs` | off | Scan for documentation overlap |
| `--lang` | auto | Language filter: `python`, `ts`, `tsx` |
| `-t, --threshold` | `0.90` | Similarity threshold (0.0-1.0). Higher = stricter. |
| `-m, --min-lines` | `6` | Minimum lines for a code unit to be considered |
| `--min-tokens` | `0` | Minimum unique normalized tokens (filters trivial units) |
| `--max-cluster-size` | `15` | Drop clusters larger than this |
| `-e, --exclude` | | Glob patterns to exclude (e.g. `*/tests/*`) |
| `--exclude-type` | | Base class types to exclude (e.g. `TextChoices`) |
| `-f, --format` | `terminal` | Output format: `terminal` or `json` |
| `--embedding-model` | `all-MiniLM-L6-v2` | Sentence-transformer model name |
| `--verify` | off | Use LLM to verify clusters (requires `dryscope[verify]`) |
| `--llm-model` | `claude-haiku-4-5` | LLM model for verification (any litellm-supported model) |

### Recommended usage

**Always use `--verify` for best results.** Without it, the tool reports all structurally similar items — including framework boilerplate and coincidental matches. The `--verify` flag uses an LLM (default: claude-haiku-4-5) to filter noise and label each cluster as `refactor`, `review`, or `noise`.

```bash
# Code duplicates with LLM verification
{{DRYSCOPE_BIN}} scan /path/to/project --code --verify --min-tokens 15

# Documentation overlap detection
{{DRYSCOPE_BIN}} scan /path/to/project --docs --verify

# Both code and docs
{{DRYSCOPE_BIN}} scan /path/to/project --code --docs --verify
```

Requires `OPENAI_API_KEY` in the environment (or the appropriate key for your chosen model).

### More examples

```bash
# Quick offline scan (no LLM)
{{DRYSCOPE_BIN}} scan /path/to/project --code

# Strict threshold, JSON output
{{DRYSCOPE_BIN}} scan /path/to/project --code --verify -t 0.95 -f json

# Docs only, custom embedding model
{{DRYSCOPE_BIN}} scan /path/to/project --docs --embedding-model all-mpnet-base-v2

# Pipe JSON for further analysis
{{DRYSCOPE_BIN}} scan /path/to/project --code --docs --verify -f json > results.json
```

## Interpreting results

### Code duplicates
- **Similarity 1.0**: Identical after normalization (Type-1/Type-2 clones) — strong refactoring candidates
- **Similarity 0.95-0.99**: Near-identical structure with minor differences (Type-3 clones)
- **Similarity 0.85-0.95**: Structurally similar, may be legitimate patterns or true duplicates

### Documentation overlap
- **High similarity**: Redundant sections that should be consolidated or cross-referenced
- **Moderate similarity**: Related content that may benefit from reorganization

## What it detects

- Exact code copies across files (e.g., utility functions copy-pasted)
- Renamed clones (same logic, different variable/function names)
- Structural clones (same pattern applied to different entities)
- Repeated boilerplate (factories, serializers, config classes)
- Overlapping documentation sections across markdown/text files
- Redundant explanations that could be consolidated

## What it skips

- `.venv/`, `node_modules/`, `__pycache__/`, `site-packages/`, etc.
- Code units shorter than `--min-lines`
- Supported code languages: Python, TypeScript, TSX

## After running

Summarize the findings for the user, highlighting:
1. **Exact copies** that should definitely be refactored
2. **Structural clones** that could benefit from abstraction
3. **Redundant documentation** that should be consolidated
4. **Legitimate patterns** that look similar but serve different purposes
