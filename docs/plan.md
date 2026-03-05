# dryscope — Implementation Plan

## Architecture

```
Source Files
    |
    v
[tree-sitter Parser] ──> Code Units (functions, classes, methods)
    |
    v
[Normalizer] ──> Strips names, literals, comments; retains structure
    |
    v
[Embedder] ──> Vector embeddings per code unit
    |
    v
[Similarity Engine] ──> Candidate duplicate clusters
    |
    v
[Reporter] ──> JSON / terminal output
```

## Core Components

### 1. Parser (`dryscope/parser.py`)
- Uses tree-sitter to extract code units from source files
- Each code unit: function, method, class, or top-level block
- Captures: source text, file path, line range, unit type, unit name
- Start with Python grammar; architecture supports adding more languages

### 2. Normalizer (`dryscope/normalizer.py`)
- Strips/replaces identifiers and literals with placeholders
- Removes comments and docstrings
- Preserves structural tokens (keywords, operators, control flow)
- Normalization makes Type 2 clones detectable as Type 1

### 3. Embedder (`dryscope/embedder.py`)
- Generates vector embeddings from normalized code text
- Default: sentence-transformers (`all-MiniLM-L6-v2`) — local, no API key needed
- Architecture allows swapping in code-specific models (UniXcoder, CodeBERT)
- Batch processing for efficiency

### 4. Similarity Engine (`dryscope/similarity.py`)
- Cosine similarity between all embedding pairs
- Configurable threshold (default: 0.85)
- Clusters candidates using Union-Find (connected components)
- Filters: minimum code unit size, same-file exclusion option

### 5. Reporter (`dryscope/reporter.py`)
- Outputs duplicate clusters as JSON and/or pretty-printed terminal output
- Each cluster contains: file paths, line ranges, similarity scores, code snippets

### 6. CLI (`dryscope/cli.py`)
- Entry point: `dryscope <path> [options]`
- Options: threshold, min-lines, output format, language filter

## Tech Stack

- **Python 3.10+**
- **tree-sitter** + **tree-sitter-python** (grammar)
- **sentence-transformers** (embeddings)
- **numpy** (vector math)
- **click** (CLI)
- **uv** (package management)

## Milestones

### M1: Parser + Normalizer
- Extract functions/classes from Python files via tree-sitter
- Normalize code units

### M2: Embedder + Similarity
- Generate embeddings, compute pairwise similarity
- Cluster candidates via Union-Find

### M3: Reporter + CLI
- JSON and terminal output
- Click-based CLI with options

### M4: Multi-language (future)
- Add JS/TS, C/C++, Rust, Go, Java grammars
- Language-aware normalization rules
