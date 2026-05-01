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
[Union-Find Clustering] ──> Code Match candidate clusters
    |
    v
[LLM Verifier] ──> Code Review: optional refactor/review/noise classification
    |
    v
[Escalation Policy] ──> Keeps review + higher-value refactor clusters
    |
    v
[Reporter] ──> JSON / terminal output with tiered classification
```

## Docs Pipeline

```
Documentation Files (.md, .mdx, .rst, .txt, .adoc)
    |
    v
[Chunker] ──> Heading-based sections with line tracking
    |
    v
[Embedder] ──> Vector embeddings per section (API embeddings or local sentence-transformers)
    |
    v
[Section Match] ──> Cross-document section pairs above threshold
    |                              (docs-section-match)
    v
[Section Match Recommendations] ──> Ranked section-level consolidation/link suggestions
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
[Docs Map] ──> Topic tree, facets, diagnostics, docs map clusters
    |                              (docs-map, docs-report-pack)
    v
[Intent Pair Evidence] ──> Canonical labels are embedded to find related doc pairs
    |
    v
[Doc Pair Review] ──> Optional LLM classification with recommendations
    |                              (docs-pair-review, cost-capped)
    v
[Reporter] ──> Docs Report Pack: markdown/html/json + stage artifacts
```

The docs report has named tracks:

1. **Docs Map** (`docs-map`) — document descriptors, canonical labels, topic tree, facets, diagnostics, and consolidation clusters.
2. **Section Match** (`docs-section-match`) — heading chunks, embedding comparison, matched section pairs, and section-level recommendations.
3. **Doc Pair Review** (`docs-pair-review`) — optional LLM review of selected related document pairs.

Docs Map is corpus-level and helps decide how to organize documentation. Section
Match is section-level and points at concrete repeated text.

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
- Heading-based Markdown/MDX chunking via mistune AST
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
- Docs Map discovery: topic tree, facets, diagnostics, and consolidation clusters
- Facet seeds are configurable under `[docs.map]`; they guide generic dimensions but do not impose a product-specific taxonomy

**Coding** (`docs/coding.py`)
- Doc Pair Review with relationship classification
- Topic-level canonical/action assignments
- Content-aware chunk-to-topic attribution

**Pipeline** (`docs/pipeline.py`)
- Multi-stage orchestrator: Section Match → Docs Map descriptors/taxonomy → optional intent pair evidence → optional Doc Pair Review
- Descriptor extraction and canonicalization run across the selected docs corpus; `intent_max_docs = 0` means no doc cap
- Caps Doc Pair Review to strongest pairs when many related pairs are found
- Cost estimation with model-specific pricing
- Run persistence via RunStore, with cleanup support for keeping the newest N runs or runs newer than a date cutoff
- Progress tracking with rich console

**Report Generation** (`docs/report.py`)
- Produces matching markdown, HTML, and JSON report structures
- Numbered sections: Run Overview, Docs Map, Docs Map Clusters, Section Match, optional Doc Pair Review, Docs Map Taxonomy, Methodology
- HTML sections and subsections are collapsible
- JSON uses the same ordered `report_structure` section list and avoids duplicate top-level IA/taxonomy payloads
- Builds prioritized Section Match recommendations from overlap pairs
- Separates Docs Map clusters from Section Match recommendations so the report does not mix corpus organization signals with repeated-section findings

### Shared (`dryscope/`)

**Match Engine** (`similarity.py`)
- Hybrid similarity: 70% embedding cosine + 30% token Jaccard (configurable)
- Size-ratio filter (max 3x) prevents mismatched unit pairing
- Union-Find clustering with max cluster size
- `cosine_similarity_matrix()` — shared L2-normalize + matmul, used by both pipelines

**Config** (`config.py`)
- Settings dataclass with `[code]`, `[docs]`, `[llm]`, `[cache]` sections
- `[docs.map]` facet seed settings for generic Docs Map dimensions and suggested values
- 3-layer merge: defaults → `.dryscope.toml` → CLI flags
- TOML loading for the current `.dryscope.toml` schema
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
- **litellm** + **tenacity** (Code Review and Doc Pair Review calls)
- **mistune** (markdown parsing)
- **uv** (package management)
