# dryscope

Code duplicate detection using tree-sitter and embeddings.

dryscope parses Python source files into code units (functions, classes, methods),
normalizes identifiers and literals, generates vector embeddings, and clusters
similar units together to find duplicates.

## Install

```bash
# Run directly without installing
uvx dryscope scan /path/to/project

# Or install globally
uv tool install dryscope
```

## Usage

```bash
# Scan for duplicates
dryscope scan /path/to/project

# Stricter threshold, minimum 5 lines, JSON output
dryscope scan /path/to/project -t 0.95 -m 5 -f json

# Install as a Claude Code skill
dryscope install
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
| `-t, --threshold` | `0.85` | Similarity threshold (0.0-1.0) |
| `-m, --min-lines` | `3` | Minimum lines per code unit |
| `-f, --format` | `terminal` | Output: `terminal` or `json` |
| `--model` | `all-MiniLM-L6-v2` | Embedding model |

## How it works

1. **Parse** — tree-sitter extracts functions, classes, and methods
2. **Normalize** — identifiers become `VAR_0`, `VAR_1`; literals become `STR`, `INT`, `FLOAT`
3. **Embed** — sentence-transformers generates vector embeddings
4. **Compare** — hybrid similarity (70% embedding cosine + 30% token Jaccard)
5. **Cluster** — Union-Find groups similar pairs into clusters

## Clone types detected

- **Type 1**: Exact clones (whitespace/comment differences only)
- **Type 2**: Renamed clones (different identifiers/literals, same structure)
- **Type 3**: Near-miss clones (minor structural changes)
- **Type 4**: Semantic clones (same logic, different implementation) — partial

## License

MIT
