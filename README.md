# dryscope

Find duplicate code and overlapping documentation before handing work to an expensive model.

`dryscope` is a narrowing tool:
- for code, it surfaces structural duplicate candidates and filters them down to a shortlist
- for docs, it finds overlapping sections and groups repeated document families into consolidation recommendations

It is designed to reduce how much of a repository a stronger model needs to read, not to replace the stronger model entirely.

## Features

- **Code duplicate detection** — Python, TypeScript, and TSX via tree-sitter + sentence-transformers
- **Documentation overlap detection** — Markdown, RST, and plaintext via embedding similarity + optional LLM analysis
- **Hybrid similarity** — 70% embedding cosine + 30% token Jaccard with size-ratio filtering
- **Optional LLM verification** — classifies findings as `refactor`, `review`, or `noise`
- **Deterministic escalation policy** — keeps `review` findings plus higher-value `refactor` findings for expensive follow-up
- **Project profiles** — auto-detects Django and pytest-factories, applies smart exclusions
- **Agent skills** — install as both a Claude Code and Codex skill
- **Unified JSON output** — structured `findings[]` schema for agent consumption

## Positioning

`dryscope` is best used as:
- a code duplicate candidate generator
- a documentation overlap detector
- a prefilter before a stronger model does deeper refactoring or docs consolidation work

It is not positioned as:
- a perfect semantic clone detector
- a final refactor oracle
- a complete replacement for human or stronger-model judgment

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

## Real-World Examples

Public examples from recent validation passes:

- `kvsankar/sattosat`
  - code scan produced a 2-item shortlist
  - one clear refactor candidate survived: duplicated TLE epoch parsing logic across two scripts and one library module
  - docs scan produced 0 recommendations

- `stellar/stellar-docs`
  - docs scan found real overlap in repeated sequence-diagram flows
  - grouped recommendation output reduced noisy pairwise suggestions into a compact 4-item shortlist

- `gethomepage/homepage`
  - docs scan found 0 overlap pairs
  - the pipeline exited early instead of spending LLM work on a large negative repo

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
exclude = ["node_modules", "venv", ".git", ".dryscope", "*.lock"]
threshold_similarity = 0.9
threshold_intent = 0.8
min_content_words = 15
include_intra = false
token_weight = 0.3
embedding_model = "all-MiniLM-L6-v2"
intent_max_docs = 250
llm_max_doc_pairs = 250
intent_skip_without_similarity_min_docs = 100

[llm]
model = "claude-haiku-4-5-20251001"
backend = "cli"       # "cli" (claude -p), "codex-cli", "litellm" (provider API keys), or "ollama" (local Ollama)
max_cost = 5.00
concurrency = 8
# ollama_host = "http://localhost:11434"
# cli_strip_api_key = true
# cli_permission_mode = "bypassPermissions"
# cli_dangerously_skip_permissions = false

[cache]
enabled = true
path = "~/.cache/dryscope/cache.db"
```

Configuration layers: defaults → `.dryscope.toml` → CLI flags.

## LLM Backend Configuration

`dryscope` supports four verification backends:

- `cli`
  - shells out to `claude -p`
  - good when you use Claude CLI with OAuth/session auth
- `codex-cli`
  - shells out to `codex exec`
  - good when you use Codex CLI directly
- `litellm`
  - uses provider APIs through LiteLLM
  - good for OpenAI, Anthropic, Gemini, Azure OpenAI, Bedrock, OpenRouter, and other LiteLLM-supported providers
- `ollama`
  - uses the local Ollama HTTP API
  - good for local/private verification without a cloud provider

### Claude CLI

```toml
[llm]
backend = "cli"
model = "claude-haiku-4-5-20251001"
# cli_strip_api_key = true
# cli_permission_mode = "bypassPermissions"
# cli_dangerously_skip_permissions = false
```

```bash
dryscope scan /path/to/project --verify --backend cli --llm-model claude-haiku-4-5-20251001
```

### Codex CLI

```toml
[llm]
backend = "codex-cli"
# Use the Codex default model, or set one your Codex auth supports.
model = "gpt-5.4"
```

```bash
dryscope scan /path/to/project --verify --backend codex-cli --llm-model gpt-5.4
```

`codex-cli` shells out to `codex exec`. On this machine, explicit mini models like
`gpt-4o-mini` were rejected under ChatGPT-account Codex auth, while the default
Codex model worked. If you want mini models through Codex CLI, use API-key login
with `codex login --with-api-key` if your account supports them.

### LiteLLM Providers

Use `litellm` when you want hosted provider APIs.

OpenAI example:

```toml
[llm]
backend = "litellm"
model = "gpt-4o"
```

```bash
OPENAI_API_KEY=... dryscope scan /path/to/project --verify --backend litellm --llm-model gpt-4o
```

Anthropic example:

```toml
[llm]
backend = "litellm"
model = "claude-3-5-sonnet-latest"
```

```bash
ANTHROPIC_API_KEY=... dryscope scan /path/to/project --verify --backend litellm --llm-model claude-3-5-sonnet-latest
```

### Ollama

```toml
[llm]
backend = "ollama"
model = "qwen2.5:3b"
# ollama_host = "http://localhost:11434"
```

```bash
dryscope scan /path/to/project --verify --backend ollama --llm-model qwen2.5:3b
```

## Agent Skills

```bash
dryscope install    # Install as both Claude Code and Codex skills
dryscope uninstall  # Remove the skill
```

`dryscope install` creates a shared skill venv under
`$XDG_DATA_HOME/dryscope/skill-venv` or `~/.local/share/dryscope/skill-venv`,
then renders `SKILL.md` into both `~/.claude/skills/dryscope` and
`~/.codex/skills/dryscope`.

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
dryscope install      # Install Claude Code and Codex skills
dryscope uninstall    # Remove Claude Code and Codex skills
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
4. **Restrict** _(large repos)_ — cap later stages to docs and doc-pairs with the strongest similarity evidence
5. **Skip Early** _(large negative repos)_ — if stage 1 finds no overlap in a large corpus, the intent stage is skipped instead of spending LLM work on the whole repo
6. **Topics** _(full stage)_ — LLM extracts topics, clusters documents by intent overlap
7. **Analyze** _(full stage)_ — LLM classifies each pair with action recommendations
8. **Group** — related pairwise recommendations are merged into document-family recommendations to reduce output spam

## What Good Output Looks Like

For code:
- a small shortlist of `refactor` and `review` findings
- exact or near-exact helpers extracted across files
- borderline same-file or low-payoff duplicates left as `review`

For docs:
- 0 recommendations on clean negative repos
- a few grouped recommendations on docs-heavy repos
- one family recommendation for many near-identical sibling docs, rather than many pairwise duplicates

## Benchmarking

`dryscope` includes a checked-in public benchmark pack under [benchmarks/README.md](/home/sankar/sankar/projects/dryscope/benchmarks/README.md).

It only references public repositories and reviewed public labels. Private repo evaluation should remain local and out of the checked-in benchmark files.

## License

MIT
