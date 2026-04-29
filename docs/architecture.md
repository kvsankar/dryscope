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
[Embedder] ──> Vector embeddings per code unit (API embeddings or local sentence-transformers)
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
[Embedder] ──> Vector embeddings per section (API embeddings or local sentence-transformers)
    |
    v
[Similarity] ──> Cross-document section pairs above threshold
    |                              (similarity stage)
    v
[Section Recommendations] ──> Ranked section-level consolidation/link suggestions
    |
    +──────────────────────────────────────────────────────────────┐
                                                                   |
                                                                   v
[Document Descriptors] ──> LLM profiles title, summary, aboutness, reader intent,
    |                       role, audience, lifecycle, content type, surface
    |
    v
[Canonical Label Taxonomy] ──> Deterministic + LLM canonicalization of
    |                            aboutness and reader-intent labels
    |
    v
[Information Architecture] ──> Topic tree, facets, diagnostics,
    |                           suggested consolidation clusters
    |                              (intent/full stage)
    v
[Intent Pair Evidence] ──> Canonical labels are embedded to find related doc pairs
    |
    v
[Doc-Pair Analysis] ──> Optional LLM classification with recommendations
    |                              (full stage, cost-capped)
    v
[Reporter] ──> numbered collapsible markdown/html + structured json
```

The docs report has two top-level Doc DRY tracks:

1. **Information Architecture** — document descriptors, canonical labels, IA topic tree, facets, diagnostics, and suggested consolidation clusters.
2. **Section Similarity** — heading chunks, embedding comparison, similar section pairs, and section similarity recommendations.

The IA track is corpus-level and helps decide how to organize documentation. The
Section Similarity track is section-level and points at concrete repeated text.

## Core Components

### Code Pipeline (`dryscope/code/`)

**Parser** (`code/parser.py`)
- tree-sitter extraction of CodeUnit dataclasses from Python, Go, Java, and JavaScript/TypeScript families
- Handles: functions, methods, classes, arrow functions, exported declarations
- Python classes include methods in source; TypeScript extracts methods separately

**Normalizer** (`code/normalizer.py`)
- Replaces identifiers with positional placeholders (`VAR_0`, `VAR_1`, ...)
- Replaces literals with type-based placeholders (`STR`, `INT`, `FLOAT`)
- Strips comments, docstrings, type annotations (TypeScript)
- Preserves language-specific builtins (Python builtins/dunders, TypeScript globals)
- Makes Type 2 clones detectable as Type 1

**Embedder** (`code/embedder.py`)
- API embedding models through LiteLLM, e.g. `text-embedding-3-small`
- optional local sentence-transformers models such as `all-MiniLM-L6-v2`
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
- LiteLLM for API embedding models and optional sentence-transformers for local models
- Hybrid similarity: `(1 - token_weight) * cosine + token_weight * Jaccard`
- Cross-document and intra-document pair finding

**Topics** (`docs/topics.py`)
- Rich LLM document descriptor extraction
- Descriptor fields include title, summary, aboutness labels, reader intents, doc role, audience, lifecycle, content type, surface, canonicality, and evidence
- Descriptor labels are the input to canonical label normalization
- Canonical labels can still be embedded to find related doc pairs for optional deeper analysis

**Taxonomy** (`docs/taxonomy.py`)
- Deterministic exact/fuzzy label normalization
- Optional LLM canonicalization of descriptor labels into a durable corpus vocabulary
- Canonical label taxonomy with document coverage, aliases, and co-occurrence
- Information Architecture discovery: topic tree, facets, diagnostics, and suggested consolidation clusters
- Facet seeds are configurable under `[docs.ia]`; they guide generic dimensions but do not impose a product-specific taxonomy

**Coding** (`docs/coding.py`)
- LLM doc-pair analysis with relationship classification
- Topic-level canonical/action assignments
- Content-aware chunk-to-topic attribution

**Pipeline** (`docs/pipeline.py`)
- Multi-stage orchestrator: section similarity → descriptors/canonical taxonomy/IA → optional intent pair evidence → optional LLM doc-pair analysis
- Descriptor extraction and canonicalization run across the selected docs corpus; `intent_max_docs = 0` means no doc cap
- Caps LLM doc-pair analysis to strongest pairs when many related pairs are found
- Cost estimation with model-specific pricing
- Run persistence via RunStore, with cleanup support for keeping the newest N runs or runs newer than a date cutoff
- Progress tracking with rich console

**Report Generation** (`docs/report.py`)
- Produces matching markdown, HTML, and JSON report structures
- Numbered sections: Run Overview, Information Architecture, Suggested Consolidation Clusters, Section Similarity, optional Document Pair Analysis, Canonical Label Taxonomy, Methodology
- HTML sections and subsections are collapsible
- JSON uses the same ordered `report_structure` section list and avoids duplicate top-level IA/taxonomy payloads
- Builds prioritized section similarity recommendations from overlap pairs
- Separates IA consolidation clusters from section similarity recommendations so the report does not mix corpus organization signals with repeated-section findings

### Shared (`dryscope/`)

**Similarity Engine** (`similarity.py`)
- Hybrid similarity: 70% embedding cosine + 30% token Jaccard (configurable)
- Size-ratio filter (max 3x) prevents mismatched unit pairing
- Union-Find clustering with max cluster size
- `cosine_similarity_matrix()` — shared L2-normalize + matmul, used by both pipelines

**Config** (`config.py`)
- Settings dataclass with `[code]`, `[docs]`, `[llm]`, `[cache]` sections
- `[docs.ia]` facet seed settings for generic IA dimensions and suggested values
- 3-layer merge: defaults → `.dryscope.toml` → CLI flags
- TOML loading with backward compatibility
- Includes code escalation policy knobs for post-verify filtering

**Cache** (`cache.py`)
- Thread-safe SQLite cache for embeddings and LLM coding results
- WAL + busy-timeout tuning for concurrent docs/code runs
- Context manager support with batch commit on exit

**Run Store** (`run_store.py`)
- Persists docs pipeline runs under `.dryscope/runs/<run-id>/`
- Tracks resumable stage artifacts plus generated `report.md`, `report.html`, and `report.json`
- Maintains `.dryscope/latest` as a relative symlink to the newest or selected run
- Provides cleanup primitives for `dryscope reports clean`, including keep-newest, keep-since, keep-days, dry-run, and latest-symlink repair after deletion

**LLM Backend** (`llm_backend.py`)
- Abstraction over litellm API and `claude -p` CLI backend
- Configurable via `.dryscope.toml` `[llm]` section

**Unified Reporter** (`unified_report.py`)
- Unified `findings[]` JSON schema with `mode: "code"` / `mode: "docs"`
- Unified terminal output with mode-grouped sections

## Tech Stack

- **Python 3.10+**
- **tree-sitter** + language grammars (Python, TypeScript)
- **LiteLLM embeddings** by default, with optional **sentence-transformers** local embeddings
- **numpy** (vector math, cosine similarity)
- **click** (CLI), **rich** (docs terminal output)
- **litellm** + **tenacity** (LLM verification/analysis)
- **mistune** (markdown parsing)
- **uv** (package management)

## Milestones

### M1-M3: Code Pipeline ✓
- Parse, normalize, embed, cluster, report via CLI

### M4: Multi-language ✓
- Go/Java/JavaScript/JSX/TypeScript/TSX support (parsing, normalization, arrow functions)

### M5: LLM Verification ✓
- Provider-agnostic LLM verification, project profiles, min-tokens filter
- Shared code/docs backend support for `litellm` and `claude -p`
- Deterministic escalation policy after verification

### M6: Docs Pipeline ✓
- Documentation overlap detection merged from doclens project
- Unified CLI with `--code`/`--docs` flags
- Shared embedding abstraction for API and optional local models
- Unified JSON `findings[]` schema

### Future
- Additional languages: C/C++, Rust, Go, Java
- Code-specific embedding models (UniXcoder, CodeBERT)
