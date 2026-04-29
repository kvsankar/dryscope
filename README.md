# dryscope

Preflight large repositories before AI-assisted refactors and documentation consolidation.

`dryscope` finds duplicate-code candidates and overlapping documentation so an
agent, stronger model, or human reviewer can start from a smaller, better-ranked
set of files. It is built for repo narrowing, not for replacing judgment.

`dryscope` is a narrowing tool:
- for code, it surfaces structural duplicate candidates and filters them down to a shortlist
- for docs, it has two tracks:
  - **Information Architecture**: profiles documents, discovers canonical labels, builds a topic/facet view, and suggests multi-document consolidation clusters
  - **Section Similarity**: compares heading-based sections and ranks concrete section-level consolidation/link recommendations

The core bet is simple: before spending expensive model context on a large repo,
first identify the repeated implementation shapes, duplicated docs, and scattered
documentation intents that are most likely to deserve follow-up.

## Features

- **Code duplicate detection** — Python, Go, Java, JavaScript, JSX, TypeScript, and TSX via tree-sitter + embeddings
- **Documentation Information Architecture** — LLM document descriptors, canonical label taxonomy, IA topic tree, facets, diagnostics, and consolidation clusters
- **Documentation section similarity** — Markdown, RST, and plaintext via heading chunks, embedding similarity, and optional LLM pair analysis
- **HTML/Markdown/JSON docs reports** — top-down Doc DRY report with numbered collapsible sections and the same structure across formats
- **Saved report cleanup** — prune old `.dryscope/runs` outputs by count or date, dry-run first by default
- **Hybrid similarity** — 70% embedding cosine + 30% token Jaccard with size-ratio filtering
- **Optional LLM verification** — classifies findings as `refactor`, `review`, or `noise`
- **Deterministic escalation policy** — keeps `review` findings plus higher-value `refactor` findings for expensive follow-up
- **Project profiles** — auto-detects Django and pytest-factories, applies smart exclusions
- **Agent skills** — install as both a Claude Code and Codex skill
- **Unified JSON output** — structured `findings[]` schema for agent consumption

## Positioning

`dryscope` is best used as:
- an AI preflight scanner before repository-wide refactors
- a repo narrowing tool before handing work to an agent or stronger model
- a code duplicate candidate generator for structural refactor opportunities
- a documentation overlap and IA review aid for answering "how should these docs be organized?"
- a prefilter that helps decide what a deeper reviewer should read first

It is not positioned as:
- a general-purpose lint replacement
- a universal duplicate-code product for every developer workflow
- a perfect semantic clone detector
- a final refactor oracle
- a complete replacement for human or stronger-model judgment

The strongest use case is not "find every duplicate." It is "before I ask an
agent to clean this up, show me the small set of likely duplicate code and docs
consolidation targets worth spending attention on."

## Installation

```bash
uv pip install .
```

The default install supports API embedding models through LiteLLM. Set the
provider API key for your embedding model, such as `OPENAI_API_KEY` for
`text-embedding-3-small`. Local sentence-transformer embeddings are optional
because they pull in PyTorch:

```bash
uv pip install ".[local-embeddings]"
```

## Quick Start

```bash
# Code duplicates (default)
dryscope scan /path/to/project

# Documentation overlap
dryscope scan /path/to/docs --docs

# Local embeddings, after installing .[local-embeddings]
dryscope scan /path/to/project --embedding-model all-MiniLM-L6-v2

# Full documentation IA + section similarity report
dryscope scan /path/to/docs --docs --stage full --backend cli -f html

# Both code and docs
dryscope scan /path/to/project --code --docs

# JSON output for agents
dryscope scan /path/to/project -f json

# Filter by language
dryscope scan /path/to/project --lang python

# With LLM verification
dryscope scan /path/to/project --verify

# Bounded verification for large duplicate-rich repos
dryscope scan /path/to/project --verify --max-findings 15

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
  - grouped Section Similarity output reduced noisy pairwise suggestions into a compact 4-item shortlist

- `gethomepage/homepage`
  - docs scan found 0 overlap pairs
  - with the old large-repo guard enabled, the pipeline exited early instead of spending LLM work on a large negative repo

Recent AI-generated / agent-oriented public repo checks show the code path doing
the intended narrowing job:

| Repo | Structural candidates | Verified shortlist from top 15 |
| --- | ---: | ---: |
| `CLI-Anything-WEB` | 94 | 5 |
| `nanowave` | 82 | 10 |
| `ClaudeCode_generated_app` | 51 | 6 |
| `VibesOS` | 23 | 4 |

These are candidate shortlists, not precision/recall claims. The benchmark pack
keeps reviewed labels for selected findings, including real refactor candidates
and at least one false-positive regression case.

For docs-heavy repositories, the current docs report is organized around the two Doc DRY tracks:

1. **Information Architecture**: document descriptors -> canonical label normalization -> IA topic tree/facets -> suggested consolidation clusters.
2. **Section Similarity**: document sections -> embeddings -> similar section pairs -> section similarity recommendations.

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
embedding_model = "text-embedding-3-small"
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
# Same embedding backend choices as [code].
embedding_model = "text-embedding-3-small"
intent_max_docs = 0
llm_max_doc_pairs = 250
intent_skip_without_similarity_min_docs = 0

[docs.ia]
# Generic seed dimensions shown to the LLM. These are suggestions, not a
# product-specific taxonomy; dryscope still infers the corpus topic tree.
facet_dimensions = ["doc_role", "audience", "lifecycle", "content_type", "surface", "canonicality"]

[docs.ia.facet_values]
doc_role = ["guide", "reference", "tutorial", "spec", "plan", "status", "research", "changelog", "architecture", "decision", "overview", "troubleshooting"]
audience = ["user", "contributor", "maintainer", "operator", "internal", "agent"]
lifecycle = ["current", "proposed", "historical", "deprecated", "draft", "unknown"]
content_type = ["concept", "workflow", "api", "troubleshooting", "decision", "benchmark", "example", "architecture", "requirements"]
surface = ["public", "internal", "generated", "extension", "package", "integration"]
canonicality = ["primary", "supporting", "archive", "duplicate", "index", "unknown"]

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
| `--lang` | all | Filter: `python`, `go`, `java`, `js`, `jsx`, `ts`, `tsx` |
| `-t, --threshold` | `0.90` | Similarity threshold (0.0-1.0) |
| `-f, --format` | `terminal` | Output: `terminal`, `json`, `markdown`, `html` |
| `-m, --min-lines` | `6` | Minimum lines per code unit |
| `--min-tokens` | `0` | Minimum unique normalized tokens |
| `--max-cluster-size` | `15` | Drop clusters larger than this |
| `--max-findings` | | Limit output and verification to the top N code findings |
| `-e, --exclude` | | Glob patterns to exclude (code) |
| `--exclude-type` | | Base class types to exclude (code) |
| `--embedding-model` | `text-embedding-3-small` | Embedding model; API models use LiteLLM, local sentence-transformers such as `all-MiniLM-L6-v2` require `.[local-embeddings]` |
| `--verify` | off | LLM verification + deterministic escalation policy |
| `--llm-model` | `claude-haiku-4-5-20251001` | LLM model for verification |
| `--stage` | `similarity` | Docs pipeline: `similarity` or `full` |
| `--resume` | off | Resume from latest docs run |
| `--intra` | off | Include intra-document overlap (docs) |
| `--threshold-intent` | `0.8` | Topic/intent matching threshold for docs full stage |
| `--concurrency` | config | Max parallel LLM calls for docs full stage |
| `--backend` | config | LLM backend: `cli`, `codex-cli`, `litellm`, or `ollama` |

Report cleanup:

| Command | Description |
|---------|-------------|
| `dryscope reports clean <path> --keep-last N` | Keep the newest N saved report runs |
| `dryscope reports clean <path> --keep-since YYYY-MM-DD` | Keep runs on or after a calendar date |
| `dryscope reports clean <path> --keep-since YYYY-MM` | Keep runs on or after the first day of a month |
| `dryscope reports clean <path> --keep-days N` | Keep runs from the last N days |
| `--force` | Actually delete runs; without this, cleanup is preview-only |

```
dryscope init         # Generate .dryscope.toml
dryscope install      # Install Claude Code and Codex skills
dryscope uninstall    # Remove Claude Code and Codex skills
dryscope cache stats  # Show cache statistics
dryscope cache clear  # Clear the cache
dryscope reports clean /path/to/project --keep-last 5          # Preview deleting older saved runs
dryscope reports clean /path/to/project --keep-days 30 --force # Delete runs older than 30 days
```

### Saved Report Cleanup

Docs scans are saved under `.dryscope/runs/<run-id>/` with `report.md`,
`report.html`, `report.json`, and resumable stage artifacts. Cleanup is dry-run
by default:

```bash
# Keep the newest 10 runs; preview only
dryscope reports clean /path/to/project --keep-last 10

# Keep reports from April 2026 onward; preview only
dryscope reports clean /path/to/project --keep-since 2026-04-01

# Keep reports from the last 30 days and actually delete older runs
dryscope reports clean /path/to/project --keep-days 30 --force
```

When multiple keep rules are supplied, dryscope keeps the union. For example,
`--keep-last 5 --keep-days 30` preserves the newest five runs plus any run from
the last 30 days. After deletion, `.dryscope/latest` is repointed to the newest
remaining run.

### Report Format Structure

`report.md`, `report.html`, and `report.json` use the same top-level section
order: Run Overview, Information Architecture, Suggested Consolidation Clusters,
Section Similarity, optional Document Pair Analysis, Canonical Label Taxonomy,
and Methodology.

At the top level, JSON keeps only run metadata, a compact summary, and the
ordered `report_structure`; detailed payloads live under their owning sections.

Each detailed list is owned by one section. For example, IA topic documents live
inside Information Architecture, consolidation documents live inside Suggested
Consolidation Clusters, and canonical labels/aliases live inside Canonical Label
Taxonomy. The report avoids "sample first, full list later" output; long lists
are collapsible in Markdown/HTML and nested under the corresponding section in
JSON.

## How It Works

### Code Pipeline
1. **Parse** — tree-sitter extracts functions, classes, and methods
2. **Normalize** — identifiers/literals replaced with placeholders; comments stripped
3. **Embed** — API embeddings through LiteLLM or local sentence-transformers embeddings
4. **Compare** — hybrid similarity (70% cosine + 30% token Jaccard) with size-ratio filtering
5. **Cluster** — Union-Find groups similar pairs, scored by actionability
6. **Verify** _(optional)_ — LLM classifies each cluster as `refactor`, `review`, or `noise`
7. **Escalate** _(with `--verify`)_ — deterministic policy keeps all `review` findings and only higher-value `refactor` findings

### Docs Pipeline
1. **Chunk** — split documents into heading-based sections
2. **Embed** — API embeddings through LiteLLM or local sentence-transformers embeddings
3. **Compare sections** — hybrid similarity finds cross-document section overlap
4. **Extract descriptors** _(full stage)_ — LLM profiles each document with title, summary, aboutness labels, reader intents, role, audience, lifecycle, content type, surface, and canonicality
5. **Canonicalize labels** _(full stage)_ — deterministic matching plus optional LLM canonicalization turns raw aboutness/intent labels into a corpus-level canonical label taxonomy
6. **Discover IA** _(full stage)_ — LLM builds a candidate information architecture: topic tree, facets, diagnostics, and suggested consolidation clusters
7. **Match intent pairs** _(full stage)_ — canonical labels are embedded to find related document pairs for optional deeper pair analysis
8. **Analyze pairs** _(full stage)_ — LLM classifies overlapping document pairs with action recommendations when within cost limits
9. **Report** — markdown, HTML, and JSON share the same top-down structure: run overview, Information Architecture, Suggested Consolidation Clusters, Section Similarity, optional pair analysis, and canonical label taxonomy

## What Good Output Looks Like

For code:
- a small shortlist of `refactor` and `review` findings
- exact or near-exact helpers extracted across files
- borderline same-file or low-payoff duplicates left as `review`

For docs:
- an Information Architecture section showing topic groups, facets, and diagnostics
- suggested consolidation clusters from canonical labels shared by multiple documents
- section similarity recommendations only when section-level overlap exists
- 0 section similarity recommendations on clean negative repos, while IA may still report organizational signals
- a few grouped Section Similarity recommendations on docs-heavy repos
- one family recommendation for many near-identical sibling docs, rather than many pairwise duplicates

## Benchmarking

`dryscope` includes a checked-in public benchmark pack under [benchmarks/README.md](/home/sankar/sankar/projects/dryscope/benchmarks/README.md).

It only references public repositories and reviewed public labels. Private repo evaluation should remain local and out of the checked-in benchmark files.

The current benchmark evidence supports public alpha positioning: dryscope can
find and narrow repeated implementation shapes in AI-generated or
agent-oriented repositories. The labels are still intentionally sparse, so the
benchmark pack should be read as regression evidence for the narrowing workflow,
not as a precision/recall claim.

## License

MIT
