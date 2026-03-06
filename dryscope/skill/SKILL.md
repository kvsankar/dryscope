---
name: dryscope
description: Detect duplicate code in Python projects using tree-sitter parsing and embedding-based similarity. Use when the user asks to find duplicate code, detect code clones, check for copy-paste code, find repeated patterns, or DRY violations. Keywords - duplicate, clone, copy-paste, DRY, repetition, similarity, refactor duplicates.
allowed-tools: [Bash, Read, Glob, Grep]
---

## What this skill does

Runs **dryscope** — a code duplicate detection tool that uses tree-sitter to parse code into units (functions, classes, methods), normalizes them, generates embeddings, and clusters similar code units together.

## How to use

Run dryscope using its installed binary:

```bash
{{DRYSCOPE_BIN}} scan <target-path>
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-t, --threshold` | `0.90` | Similarity threshold (0.0-1.0). Higher = stricter. |
| `-m, --min-lines` | `6` | Minimum lines for a code unit to be considered |
| `--min-tokens` | `0` | Minimum unique normalized tokens (filters trivial units) |
| `--max-cluster-size` | `15` | Drop clusters larger than this |
| `-e, --exclude` | | Glob patterns to exclude (e.g. `*/tests/*`) |
| `--exclude-type` | | Base class types to exclude (e.g. `TextChoices`) |
| `-f, --format` | `terminal` | Output format: `terminal` or `json` |
| `--model` | `all-MiniLM-L6-v2` | Sentence-transformer model name |
| `--verify` | off | Use LLM to verify clusters (requires `dryscope[verify]`) |
| `--llm-model` | `gpt-4o-mini` | LLM model for verification (any litellm-supported model) |

### Recommended usage

**Always use `--verify` for best results.** Without it, the tool reports all structurally similar code — including framework boilerplate and coincidental matches. The `--verify` flag uses an LLM (default: gpt-4o-mini) to filter noise and label each cluster as `refactor`, `review`, or `noise`. The default model (gpt-4o-mini) provides the best balance of precision and recall — only override it if you have a specific reason to.

```bash
# Recommended: scan with LLM verification (uses gpt-4o-mini by default)
{{DRYSCOPE_BIN}} scan /path/to/project --verify --min-tokens 15

# With a different LLM model
{{DRYSCOPE_BIN}} scan /path/to/project --verify --llm-model claude-haiku-4-5-20251001
```

Requires `OPENAI_API_KEY` in the environment (or the appropriate key for your chosen model). Set it in a `.env` file in the project root.

### More examples

```bash
# Quick scan without LLM verification (offline, free)
{{DRYSCOPE_BIN}} scan /path/to/project

# Strict threshold, JSON output
{{DRYSCOPE_BIN}} scan /path/to/project --verify -t 0.95 -f json

# Pipe JSON to a file for further analysis
{{DRYSCOPE_BIN}} scan /path/to/project --verify -f json > duplicates.json
```

## Interpreting results

- **Similarity 1.0**: Identical after normalization (Type-1/Type-2 clones) — strong refactoring candidates
- **Similarity 0.95-0.99**: Near-identical structure with minor differences (Type-3 clones)
- **Similarity 0.85-0.95**: Structurally similar, may be legitimate patterns or true duplicates — review needed

## What it detects

- Exact copies across files (e.g., utility functions copy-pasted)
- Renamed clones (same logic, different variable/function names)
- Structural clones (same pattern applied to different entities)
- Repeated boilerplate (factories, serializers, config classes)

## What it skips

- `.venv/`, `node_modules/`, `__pycache__/`, `site-packages/`, etc.
- Code units shorter than `--min-lines`
- Currently Python only (multi-language planned)

## After running

Summarize the findings for the user, highlighting:
1. **Exact copies** that should definitely be refactored
2. **Structural clones** that could benefit from abstraction
3. **Legitimate patterns** that look similar but serve different purposes
