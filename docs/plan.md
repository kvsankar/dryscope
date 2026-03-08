# dryscope — Implementation Plan

## Architecture

```
Source Files (.py, .ts, .tsx)
    |
    v
[tree-sitter Parser] ──> Code Units (functions, classes, methods)
    |
    v
[Normalizer] ──> Strips names, literals, comments; retains structure
    |
    v
[Embedder] ──> Vector embeddings per code unit (local, no API)
    |
    v
[Similarity Engine] ──> Candidate duplicate clusters
    |
    v
[LLM Verifier] ──> (optional) Classifies clusters as refactor/review/noise
    |
    v
[Reporter] ──> JSON / terminal output
```

## Core Components

### 1. Parser (`dryscope/parser.py`)
- Uses tree-sitter to extract code units from Python and TypeScript/TSX source files
- Each code unit: function, method, class, or arrow function (TS)
- Captures: source text, file path, line range, unit type, unit name, language
- Python classes include methods in class source; TypeScript extracts methods separately

### 2. Normalizer (`dryscope/normalizer.py`)
- Replaces identifiers with positional placeholders (`VAR_0`, `VAR_1`, ...)
- Replaces literals with type-based placeholders (`STR`, `INT`, `FLOAT`)
- Removes comments, docstrings, and type annotations (TypeScript)
- Preserves language-specific builtins (Python builtins/dunders, TypeScript globals)
- Normalization makes Type 2 clones detectable as Type 1

### 3. Embedder (`dryscope/embedder.py`)
- Generates vector embeddings from normalized code text
- Uses sentence-transformers (`all-MiniLM-L6-v2`) — runs locally, no API key needed
- Batch processing for efficiency
- Suppresses noisy model loading output via OS-level fd redirection

### 4. Similarity Engine (`dryscope/similarity.py`)
- Hybrid similarity: 70% embedding cosine + 30% token Jaccard
- Size-ratio filter (max 3x) prevents mismatched units from pairing
- Quick-reject threshold for embedding similarity
- Clusters candidates using Union-Find (connected components)
- Max cluster size filter drops overly broad clusters

### 5. Profiles (`dryscope/profiles.py`)
- Auto-detects project type (Django, Flask, pytest-factories)
- Each profile provides exclusion rules (dirs, patterns, base class types)
- Merges detected profiles with user-provided CLI exclusions

### 6. Verifier (`dryscope/verifier.py`)
- Optional LLM-based cluster verification via litellm
- Classifies clusters as `refactor`, `review`, or `noise`
- Default model: `gpt-4o-mini` (best precision-recall balance)
- Supports any litellm-compatible provider (OpenAI, Anthropic, Google, Azure, Ollama)
- Sequential processing with retries to avoid rate limits
- Loads API keys from `.env` files (searches upward from current directory)

### 7. Reporter (`dryscope/reporter.py`)
- Tiered classification: exact, near-identical, structural
- Actionability scoring (similarity, total lines, cross-file, production code)
- Outputs duplicate clusters as JSON and/or pretty-printed terminal output
- Includes LLM verdict labels when verification is enabled

### 8. CLI (`dryscope/cli.py`)
- Entry point: `dryscope scan <path> [options]`
- Options: threshold, min-lines, min-tokens, exclude patterns/types, output format, verify, llm-model
- Subcommands: `scan`, `install`, `uninstall`
- Install command sets up a Claude Code skill with its own venv (includes litellm)

## Tech Stack

- **Python 3.10+**
- **tree-sitter** + **tree-sitter-python** + **tree-sitter-typescript** (grammars)
- **sentence-transformers** (embeddings — local, no API)
- **numpy** (vector math)
- **click** (CLI)
- **litellm** + **tenacity** (optional: LLM verification)
- **uv** (package management)

## Milestones

### M1: Parser + Normalizer ✓
- Extract functions/classes from Python files via tree-sitter
- Normalize code units

### M2: Embedder + Similarity ✓
- Generate embeddings, compute pairwise similarity
- Cluster candidates via Union-Find

### M3: Reporter + CLI ✓
- JSON and terminal output with tiered classification
- Click-based CLI with options

### M4: Multi-language ✓ (partial)
- TypeScript/TSX support (parsing, normalization, arrow functions)
- Language-aware normalization rules per language

### M5: LLM Verification ✓
- Provider-agnostic LLM verification via litellm
- Project profile detection and exclusion rules
- Min-tokens filter for trivial units

### Future
- Additional languages: C/C++, Rust, Go, Java
- Code-specific embedding models (UniXcoder, CodeBERT)
