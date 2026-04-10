# Existing Code Clone Detection Tools — Analysis

## Established Tools (text/token-based)

| Tool | Approach | Languages | Limitations |
|------|----------|-----------|-------------|
| [jscpd](https://github.com/kucherenko/jscpd) | Rabin-Karp token matching | 150+ | Only textual/near-textual clones |
| [PMD CPD](https://pmd.github.io/pmd/pmd_userdocs_cpd.html) | Token-based | 31 | No semantic awareness |
| [pycode_similar](https://github.com/fyrestone/pycode_similar) | AST normalization + difflib | Python only | Single language, no embeddings |
| [pydups](https://github.com/glumia/pydups) | AST inspection | Python only | Single language |
| [duplicate-code-detection-tool](https://github.com/platisd/duplicate-code-detection-tool) | Text similarity | Multi | Shallow — not AST-aware |

## Research / Academic Tools (AST + ML)

| Tool | Approach | Status |
|------|----------|--------|
| [TreeCen](https://github.com/CGCL-codes/TreeCen) | AST to tree graphs, 79x faster than ASTNN | Research prototype |
| [TransformCode](https://arxiv.org/html/2311.08157v2) | AST transformations + contrastive learning | Paper only |
| [CloneCognition](https://github.com/pseudoPixels/CloneCognition) | ML-based clone validation | Research prototype |
| [Amain](https://github.com/CGCL-codes/Amain) | AST-based Markov chains | Research prototype |

## Clone Types (standard taxonomy)

- **Type 1**: Exact clones (ignoring whitespace/comments)
- **Type 2**: Renamed clones (identifiers/literals changed)
- **Type 3**: Near-miss clones (statements added/removed/modified)
- **Type 4**: Semantic clones (same logic, different syntax)

## Gap Analysis

No existing tool combines all of:

1. **tree-sitter** for multi-language parsing (fast, production-grade, incremental)
2. **Embedding-based similarity** for detecting Type 2/3 clones and some higher-level structural similarity
3. **Practical CLI tool** (not a research prototype)
4. **Cluster output** ready for LLM review

The text-based tools (jscpd, CPD) are production-quality but only catch Type 1-2 clones.
The research tools target Type 3-4 more directly but are not packaged for practical use.

## Documentation Overlap Detection

The landscape for documentation overlap detection is even sparser:

- **Manual review** — most teams rely on manual auditing of docs for redundancy
- **Diff-based tools** — git diff and similar tools only catch textual duplication, not semantic overlap
- **Search-based approaches** — full-text search can find exact phrases but misses paraphrased content

dryscope's docs pipeline fills this gap with embedding-based semantic similarity
across document sections, combined with LLM topic extraction for intent-level overlap detection.

## Conclusion

dryscope fills a real gap: a practical CLI that uses tree-sitter + normalization +
embeddings to surface structural duplicate candidates across multiple languages, and
embedding-based similarity to detect documentation overlap. Both pipelines output
structured findings suitable for LLM-assisted review and automated refactoring agents.
