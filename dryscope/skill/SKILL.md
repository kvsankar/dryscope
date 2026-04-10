---
name: dryscope
description: Detect duplicate code and documentation overlap in projects using tree-sitter parsing, normalization, and embedding-based similarity. Use when the user asks to find duplicate code, detect code clones, check for copy-paste code, find repeated patterns, DRY violations, or documentation overlap. Keywords - duplicate, clone, copy-paste, DRY, repetition, similarity, refactor duplicates, documentation overlap, redundant docs, doc overlap.
allowed-tools: [Bash, Read, Glob, Grep]
---

## What this skill does

Runs **dryscope** — a unified tool for detecting code duplicates and documentation overlap. It uses tree-sitter to parse code into units (functions, classes, methods), normalizes them, generates embeddings, and clusters similar items together. For docs, it detects overlapping or redundant documentation sections.

The intended use is narrowing:
- use `dryscope` to find candidate duplicates or overlapping docs
- then let a stronger model or a human decide what to refactor or consolidate

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
| `--verify` | off | Use LLM verification plus deterministic escalation policy |
| `--llm-model` | `claude-haiku-4-5-20251001` | LLM model for verification |

### Recommended usage

**Prefer `--verify` for higher-signal results.** Without it, the tool reports all structurally similar items — including framework boilerplate and coincidental matches. The `--verify` flag uses an LLM (default: claude-haiku-4-5) to label each cluster as `refactor`, `review`, or `noise`, then applies a deterministic policy so low-value `refactor` findings do not automatically survive.

For large documentation repos, `--docs --verify` now also:
- caps intent extraction and doc-pair analysis to the strongest similarity candidates by default
- skips the intent stage entirely on large repos when stage 1 finds no overlap
- merges dense document families into grouped recommendations so the output is less pairwise and easier to review

```bash
# Code duplicates with LLM verification
{{DRYSCOPE_BIN}} scan /path/to/project --code --verify --min-tokens 15

# Documentation overlap detection
{{DRYSCOPE_BIN}} scan /path/to/project --docs --verify

# Both code and docs
{{DRYSCOPE_BIN}} scan /path/to/project --code --docs --verify
```

Backend options:
- `backend = "cli"` uses `claude -p` and can work with Claude OAuth/session auth
- `backend = "codex-cli"` uses `codex exec` and works with Codex CLI auth
- `backend = "litellm"` uses provider API keys such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- `backend = "ollama"` uses the local Ollama API at `OLLAMA_HOST` or `http://localhost:11434`

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
- **Similarity 1.0**: Identical after normalization (Type-1/Type-2 clones) — strong candidates, but still check whether the payoff is meaningful
- **Similarity 0.95-0.99**: Near-identical structure with minor differences (Type-3 clones)
- **Similarity 0.85-0.95**: Structurally similar, may be legitimate patterns or true duplicates

### Documentation overlap
- **High similarity**: Redundant sections that should be consolidated or cross-referenced
- **Moderate similarity**: Related content that may benefit from reorganization
- **Grouped recommendations**: A family of near-identical docs can now appear as one grouped recommendation instead of many pairwise duplicates

## What it detects

- Exact code copies across files (e.g., utility functions copy-pasted)
- Renamed clones (same logic, different variable/function names)
- Structural clones with shared implementation shape
- Repeated boilerplate can still appear structurally, but `--verify` is intended to filter much of it back out
- Overlapping documentation sections across markdown/text files
- Redundant explanations that could be consolidated

## What it skips

- `.venv/`, `node_modules/`, `__pycache__/`, `site-packages/`, etc.
- Code units shorter than `--min-lines`
- Supported code languages: Python, Java, JavaScript, JSX, TypeScript, TSX

## After running

Summarize the findings for the user, highlighting:
1. **Exact copies** that should definitely be refactored
2. **Structural clones** that could benefit from abstraction
3. **Redundant documentation** that should be consolidated
4. **Legitimate patterns** that look similar but serve different purposes

If the repo is docs-heavy and the tool returns no recommendations, say that explicitly. A clean negative result is a useful outcome, not a failure.
