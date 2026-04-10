# dryscope

Code duplicate and documentation overlap detection using tree-sitter parsing, normalization, and embedding-based similarity.

## Features

- **Code duplicate detection** — Python, TypeScript, and TSX via tree-sitter + sentence-transformers
- **Documentation overlap detection** — Markdown, RST, and plaintext via embedding similarity + optional LLM analysis
- **Hybrid similarity** — 70% embedding cosine + 30% token Jaccard with size-ratio filtering
- **Optional LLM verification** — classifies findings as `refactor`, `review`, or `noise`
- **Deterministic escalation policy** — keeps `review` findings plus higher-value `refactor` findings for expensive follow-up
- **Project profiles** — auto-detects Django and pytest-factories, applies smart exclusions
- **Claude Code skill** — install/uninstall as a Claude Code skill
- **Unified JSON output** — structured `findings[]` schema for agent consumption

## Installation

```bash
uv pip install .
```

## Quick Start

```bash
# Code duplicates (default)
dryscope scan /path/to/project

# Documentation overlap
dryscope scan /path/to/docs --docs

# Both code and docs
dryscope scan /path/to/project --code --docs

# JSON output for agents
dryscope scan /path/to/project -f json

# Filter by language
dryscope scan /path/to/project --lang python

# With LLM verification
dryscope scan /path/to/project --verify

# Stricter threshold
dryscope scan /path/to/project -t 0.95 --min-tokens 15
```

## Configuration

Generate a default config file:

```bash
dryscope init
```

This creates `.dryscope.toml`:

```toml
[code]
min_lines = 6
min_tokens = 0
max_cluster_size = 15
threshold = 0.90
embedding_model = "all-MiniLM-L6-v2"
escalate_refactor_min_lines = 40
escalate_refactor_min_actionability = 2.0
escalate_refactor_min_units = 3
keep_same_file_refactors = false
# exclude = ["**/test_*.py"]
# exclude_type = ["BaseModel"]

[docs]
include = ["*.md", "*.rst", "*.txt", "*.adoc"]
exclude = ["node_modules", "venv", ".git", "*.lock"]
threshold_similarity = 0.9
threshold_intent = 0.8
min_content_words = 15
include_intra = false
token_weight = 0.3
embedding_model = "all-MiniLM-L6-v2"

[llm]
model = "claude-haiku-4-5-20251001"
backend = "cli"       # "cli" (claude -p with OAuth) or "litellm" (requires API key)
max_cost = 5.00
concurrency = 8
# cli_strip_api_key = true
# cli_permission_mode = "bypassPermissions"
# cli_dangerously_skip_permissions = false

[cache]
enabled = true
path = "~/.cache/dryscope/cache.db"
```

Configuration layers: defaults → `.dryscope.toml` → CLI flags.

## Claude Code Skill

```bash
dryscope install    # Install as Claude Code skill
dryscope uninstall  # Remove the skill
```

## CLI Reference

```
dryscope scan <path> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--code / --no-code` | `--code` | Scan for code duplicates |
| `--docs / --no-docs` | off | Scan for documentation overlap |
| `--lang` | all | Filter: `python`, `ts`, `tsx` |
| `-t, --threshold` | `0.90` | Similarity threshold (0.0-1.0) |
| `-f, --format` | `terminal` | Output: `terminal`, `json`, `markdown`, `html` |
| `-m, --min-lines` | `6` | Minimum lines per code unit |
| `--min-tokens` | `0` | Minimum unique normalized tokens |
| `--max-cluster-size` | `15` | Drop clusters larger than this |
| `-e, --exclude` | | Glob patterns to exclude (code) |
| `--exclude-type` | | Base class types to exclude (code) |
| `--embedding-model` | `all-MiniLM-L6-v2` | Sentence-transformer model |
| `--verify` | off | LLM verification + deterministic escalation policy |
| `--llm-model` | `claude-haiku-4-5-20251001` | LLM model for verification |
| `--stage` | `similarity` | Docs pipeline: `similarity` or `full` |
| `--resume` | off | Resume from latest docs run |
| `--intra` | off | Include intra-document overlap (docs) |

```
dryscope init         # Generate .dryscope.toml
dryscope install      # Install Claude Code skill
dryscope uninstall    # Remove Claude Code skill
dryscope cache stats  # Show cache statistics
dryscope cache clear  # Clear the cache
```

## How It Works

### Code Pipeline
1. **Parse** — tree-sitter extracts functions, classes, and methods
2. **Normalize** — identifiers/literals replaced with placeholders; comments stripped
3. **Embed** — sentence-transformers generates vector embeddings locally
4. **Compare** — hybrid similarity (70% cosine + 30% token Jaccard) with size-ratio filtering
5. **Cluster** — Union-Find groups similar pairs, scored by actionability
6. **Verify** _(optional)_ — LLM classifies each cluster as `refactor`, `review`, or `noise`
7. **Escalate** _(with `--verify`)_ — deterministic policy keeps all `review` findings and only higher-value `refactor` findings

### Docs Pipeline
1. **Chunk** — split documents into heading-based sections
2. **Embed** — sentence-transformers generates section embeddings
3. **Compare** — hybrid similarity finds cross-document overlap
4. **Topics** _(full stage)_ — LLM extracts topics, clusters documents by intent overlap
5. **Analyze** _(full stage)_ — LLM classifies each pair with action recommendations

## Benchmarking

`dryscope` includes a checked-in public benchmark pack under [benchmarks/README.md](/home/sankar/sankar/projects/dryscope/benchmarks/README.md).

It only references public repositories and reviewed public labels. Private repo evaluation should remain local and out of the checked-in benchmark files.

## License

MIT
