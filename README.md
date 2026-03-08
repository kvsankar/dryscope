# dryscope

Code duplicate detection using tree-sitter and embeddings.

dryscope parses Python and TypeScript/TSX source files into code units (functions,
classes, methods), normalizes identifiers and literals, generates vector embeddings,
and clusters similar units together to find duplicates. An optional LLM verification
pass filters noise and labels clusters as `refactor`, `review`, or `noise`.

## Install

```bash
# Run directly without installing
uvx dryscope scan /path/to/project

# Or install globally
uv tool install dryscope

# Install as a Claude Code skill (includes LLM verification support)
dryscope install
```

## Usage

```bash
# Recommended: scan with LLM verification (uses gpt-4o-mini by default)
dryscope scan /path/to/project --verify --min-tokens 15

# Quick scan without LLM verification (offline, free)
dryscope scan /path/to/project

# Stricter threshold, JSON output
dryscope scan /path/to/project --verify -t 0.95 -f json

# With a different LLM model
dryscope scan /path/to/project --verify --llm-model claude-haiku-4-5-20251001

# Pipe JSON to a file for further analysis
dryscope scan /path/to/project --verify -f json > duplicates.json
```

## Commands

| Command | Description |
|---------|-------------|
| `dryscope scan <path>` | Scan for duplicate code |
| `dryscope install` | Install as a Claude Code skill |
| `dryscope uninstall` | Remove the Claude Code skill |

## Options (scan)

| Flag | Default | Description |
|------|---------|-------------|
| `-t, --threshold` | `0.90` | Similarity threshold (0.0-1.0). Higher = stricter. |
| `-m, --min-lines` | `6` | Minimum lines for a code unit to be considered |
| `--min-tokens` | `0` | Minimum unique normalized tokens (filters trivial units) |
| `--max-cluster-size` | `15` | Drop clusters larger than this |
| `-e, --exclude` | | Glob patterns to exclude (e.g. `*/tests/*`) |
| `--exclude-type` | | Base class types to exclude (e.g. `TextChoices`) |
| `-f, --format` | `terminal` | Output format: `terminal` or `json` |
| `--model` | `all-MiniLM-L6-v2` | Sentence-transformer embedding model |
| `--verify` | off | Use LLM to verify clusters and filter noise |
| `--llm-model` | `gpt-4o-mini` | LLM model for verification (any litellm-supported model) |

## How it works

1. **Parse** — tree-sitter extracts functions, classes, and methods from Python and TypeScript/TSX files
2. **Normalize** — identifiers become `VAR_0`, `VAR_1`; literals become `STR`, `INT`, `FLOAT`; comments and docstrings are stripped
3. **Embed** — sentence-transformers generates vector embeddings (runs locally, no API needed)
4. **Compare** — hybrid similarity (70% embedding cosine + 30% token Jaccard) with size-ratio filtering
5. **Cluster** — Union-Find groups similar pairs into clusters, scored by actionability
6. **Verify** _(optional)_ — LLM classifies each cluster as `refactor`, `review`, or `noise`

## Project profiles

dryscope auto-detects project types and applies appropriate exclusions:

- **Django** — excludes `migrations/` directory, `TextChoices`/`IntegerChoices` classes
- **pytest-factories** — excludes `DjangoModelFactory`/`Factory` classes
- **Flask** — detected but no special exclusions yet

## Clone types detected

- **Type 1**: Exact clones (whitespace/comment differences only)
- **Type 2**: Renamed clones (different identifiers/literals, same structure)
- **Type 3**: Near-miss clones (minor structural changes)
- **Type 4**: Semantic clones (same logic, different implementation) — partial

## Supported languages

- Python (`.py`)
- TypeScript (`.ts`)
- TSX (`.tsx`)

## LLM verification

The `--verify` flag sends each candidate cluster to an LLM for classification. This dramatically reduces false positives from framework boilerplate and coincidental structural matches.

- Default model: `gpt-4o-mini` (best precision-recall balance)
- Supports any litellm-compatible model (OpenAI, Anthropic, Google, Azure, Ollama, etc.)
- Set API keys via environment variables or a `.env` file (see `.env.example`)
- Model can be overridden via `--llm-model` or `DRYSCOPE_LLM_MODEL` env var

## License

MIT
