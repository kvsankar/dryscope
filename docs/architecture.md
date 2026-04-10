# dryscope — Architecture

## Code Pipeline

```
Source Files (.py, .ts, .tsx)
    |
    v
[tree-sitter Parser] ──> Code Units (functions, classes, methods, arrow functions)
    |
    v
[Normalizer] ──> Strips identifiers, literals, comments; retains structure
    |
    v
[Embedder] ──> Vector embeddings per code unit (sentence-transformers, local)
    |
    v
[Similarity Engine] ──> Hybrid cosine+Jaccard with size-ratio filtering
    |
    v
[Union-Find Clustering] ──> Candidate duplicate clusters
    |
    v
[LLM Verifier] ──> (optional) Classifies clusters as refactor/review/noise
    |
    v
[Escalation Policy] ──> Keeps review + higher-value refactor clusters
    |
    v
[Reporter] ──> JSON / terminal output with tiered classification
```

## Docs Pipeline

```
Documentation Files (.md, .rst, .txt, .adoc)
    |
    v
[Chunker] ──> Heading-based sections with line tracking
    |
    v
[Embedder] ──> Vector embeddings per section (sentence-transformers, local)
    |
    v
[Similarity] ──> Cross-document section pairs above threshold
    |                              (similarity stage)
    v
[Scaling Gates] ──> Limit later stages to strongest docs / doc pairs
    |
    v
[Topic Extraction] ──> LLM extracts topics per document
    |
    v
[Topic Embedding] ──> Cosine matching finds intent overlap
    |                              (intent stage)
    v
[Doc-Pair Analysis] ──> LLM classifies overlap with recommendations
    |                              (full stage)
    v
[Reporter] ──> terminal / markdown / html / json output
```

## Core Components

### Code Pipeline (`dryscope/code/`)

**Parser** (`code/parser.py`)
- tree-sitter extraction of CodeUnit dataclasses from Python and TypeScript/TSX
- Handles: functions, methods, classes, arrow functions, exported declarations
- Python classes include methods in source; TypeScript extracts methods separately

**Normalizer** (`code/normalizer.py`)
- Replaces identifiers with positional placeholders (`VAR_0`, `VAR_1`, ...)
- Replaces literals with type-based placeholders (`STR`, `INT`, `FLOAT`)
- Strips comments, docstrings, type annotations (TypeScript)
- Preserves language-specific builtins (Python builtins/dunders, TypeScript globals)
- Makes Type 2 clones detectable as Type 1

**Embedder** (`code/embedder.py`)
- sentence-transformers (`all-MiniLM-L6-v2`) — local, no API key needed
- Batch embedding with L2 normalization for dot-product cosine similarity
- Suppresses noisy model loading output via OS-level fd redirection

**Profiles** (`code/profiles.py`)
- Auto-detects Django and pytest-factories projects
- Each profile provides exclusion rules (dirs, patterns, base class types)
- Merges detected profiles with user-provided CLI exclusions

**Verifier** (`code/verifier.py`)
- Optional LLM-based cluster verification via shared LLM backend
- Classifies clusters as `refactor`, `review`, or `noise`
- Supports `litellm` providers plus `claude -p` CLI backend
- Prompt includes path-aware context for examples/tests/benchmarks and stricter low-payoff heuristics
- Parallel processing via configured concurrency

**Policy** (`code/policy.py`)
- Deterministic post-verification gate for expensive follow-up
- Keeps all `review` findings
- Keeps `refactor` findings only when they meet stronger line/actionability/cross-file thresholds
- Prevents small same-file helper duplicates from automatically reaching expensive models

**Reporter** (`code/reporter.py`)
- Tiered classification: exact, near-identical, structural
- Actionability scoring (similarity, total lines, cross-file, production code)
- JSON and terminal output formats

### Docs Pipeline (`dryscope/docs/`)

**Chunker** (`docs/chunker.py`)
- Heading-based markdown chunking via mistune AST
- Plaintext paragraph chunking with line tracking
- File discovery via git ls-files or recursive glob
- Boilerplate heading detection across document corpus

**Embeddings** (`docs/embeddings.py`)
- sentence-transformers for local embedding, litellm for API models
- Hybrid similarity: `(1 - token_weight) * cosine + token_weight * Jaccard`
- Cross-document and intra-document pair finding

**Topics** (`docs/topics.py`)
- LLM topic extraction per document (max 15 granular phrases)
- Topic embedding and cosine matching for intent overlap
- Document clustering by shared topics via Union-Find

**Coding** (`docs/coding.py`)
- LLM doc-pair analysis with relationship classification
- Topic-level canonical/action assignments
- Content-aware chunk-to-topic attribution

**Pipeline** (`docs/pipeline.py`)
- Multi-stage orchestrator: similarity → intent → LLM analysis
- Large-repo guards: caps intent extraction to docs with strongest similarity evidence and caps LLM doc-pair analysis to strongest pairs
- Cost estimation with model-specific pricing
- Run persistence via RunStore
- Progress tracking with rich console

### Shared (`dryscope/`)

**Similarity Engine** (`similarity.py`)
- Hybrid similarity: 70% embedding cosine + 30% token Jaccard (configurable)
- Size-ratio filter (max 3x) prevents mismatched unit pairing
- Union-Find clustering with max cluster size
- `cosine_similarity_matrix()` — shared L2-normalize + matmul, used by both pipelines

**Config** (`config.py`)
- Settings dataclass with `[code]`, `[docs]`, `[llm]`, `[cache]` sections
- 3-layer merge: defaults → `.dryscope.toml` → CLI flags
- TOML loading with backward compatibility
- Includes code escalation policy knobs for post-verify filtering

**Cache** (`cache.py`)
- Thread-safe SQLite cache for embeddings and LLM coding results
- WAL + busy-timeout tuning for concurrent docs/code runs
- Context manager support with batch commit on exit

**LLM Backend** (`llm_backend.py`)
- Abstraction over litellm API and `claude -p` CLI backend
- Configurable via `.dryscope.toml` `[llm]` section

**Unified Reporter** (`unified_report.py`)
- Unified `findings[]` JSON schema with `mode: "code"` / `mode: "docs"`
- Unified terminal output with mode-grouped sections

## Tech Stack

- **Python 3.10+**
- **tree-sitter** + language grammars (Python, TypeScript)
- **sentence-transformers** (embeddings — local, no API)
- **numpy** (vector math, cosine similarity)
- **click** (CLI), **rich** (docs terminal output)
- **litellm** + **tenacity** (LLM verification/analysis)
- **mistune** (markdown parsing)
- **uv** (package management)

## Milestones

### M1-M3: Code Pipeline ✓
- Parse, normalize, embed, cluster, report via CLI

### M4: Multi-language ✓
- TypeScript/TSX support (parsing, normalization, arrow functions)

### M5: LLM Verification ✓
- Provider-agnostic LLM verification, project profiles, min-tokens filter
- Shared code/docs backend support for `litellm` and `claude -p`
- Deterministic escalation policy after verification

### M6: Docs Pipeline ✓
- Documentation overlap detection merged from doclens project
- Unified CLI with `--code`/`--docs` flags
- Shared embeddings (sentence-transformers for both pipelines)
- Unified JSON `findings[]` schema

### Future
- Additional languages: C/C++, Rust, Go, Java
- Code-specific embedding models (UniXcoder, CodeBERT)
