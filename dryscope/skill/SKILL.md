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
| `-t, --threshold` | `0.85` | Similarity threshold (0.0-1.0). Higher = stricter. Use 0.95 for high-confidence only. |
| `-m, --min-lines` | `3` | Minimum lines for a code unit to be considered |
| `-f, --format` | `terminal` | Output format: `terminal` or `json` |
| `--model` | `all-MiniLM-L6-v2` | Sentence-transformer model name |

### Examples

```bash
# Scan a project with default settings
{{DRYSCOPE_BIN}} scan /path/to/project

# Strict threshold, min 5 lines, JSON output
{{DRYSCOPE_BIN}} scan /path/to/project -t 0.95 -m 5 -f json

# Pipe JSON to a file for further analysis
{{DRYSCOPE_BIN}} scan /path/to/project -f json > duplicates.json
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
