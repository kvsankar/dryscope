# Existing Code Clone Detection Tools — Analysis

## Product Positioning

dryscope is not trying to win the broad "duplicate code detector" category. Its
practical role is narrower: it is a preflight scanner for AI-assisted repository
work.

The target workflow is:

1. A user is about to ask an agent, stronger model, or human reviewer to clean up
   a non-trivial repository.
2. dryscope narrows the repo to likely duplicate implementation shapes,
   repeated documentation sections, and scattered documentation intents.
3. The follow-up reviewer spends context on the shortlist instead of reading the
   whole repository from scratch.

This positioning matters because functional readiness should be judged by
whether dryscope improves that workflow, not by whether it replaces mature clone
detectors, linters, IDEs, or human review.

## Current Readiness

As of April 29, 2026, dryscope is functionally ready for a public alpha under
this positioning.

The strongest evidence is not broad precision/recall. It is that dryscope can
turn duplicate-rich, agent-created or agent-oriented repositories into a smaller
review queue:

| Repo | Structural candidates | Verified shortlist from top 15 |
|------|----------------------:|-------------------------------:|
| `CLI-Anything-WEB` | 94 | 5 |
| `nanowave` | 82 | 10 |
| `ClaudeCode_generated_app` | 51 | 6 |
| `VibesOS` | 23 | 4 |

The checked-in benchmark labels are deliberately sparse but include real
refactor candidates and known non-actionable cases. That is enough for alpha
regression coverage of the narrowing workflow. The separate quality report
scores the reviewed slice with TP/FP/FN, labeled precision, curated recall, F1,
and top-K metrics, but it is still not a broad mature precision/recall claim.

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

No widely used tool combines all of:

1. **tree-sitter** for multi-language parsing (fast, production-grade, incremental)
2. **Embedding-based similarity** for detecting Type 2/3 clones and some higher-level structural similarity
3. **Practical CLI tool** (not a research prototype)
4. **Cluster output** ready for LLM review

The text-based tools (jscpd, CPD) are production-quality but only catch Type 1-2 clones.
The research tools target Type 3-4 more directly but are not packaged for practical use.

## Docs Track Detection

The landscape for docs track detection is even sparser:

- **Manual review** — most teams rely on manual auditing of docs for redundancy
- **Diff-based tools** — git diff and similar tools only catch textual duplication, not semantic overlap
- **Search-based approaches** — full-text search can find exact phrases but misses paraphrased content
- **Static site inventories** — navigation maps and generated link reports describe structure, but rarely infer whether documents cover the same reader intent or belong under the same IA branch

dryscope's docs pipeline addresses this gap with named docs tracks:

1. **Docs Map** (`docs-map`) — LLM document descriptors capture aboutness,
   reader intent, document role, audience, lifecycle, content type, surface, and
   canonicality. These descriptors are canonicalized into a corpus-level label
   taxonomy, then used to infer a topic tree, facets, diagnostics, and
   consolidation clusters.
2. **Section Match** (`docs-section-match`) — heading-based sections are embedded and compared to
   find concrete repeated or near-repeated text. Section-level findings become
   Section Match recommendations.
3. **Doc Pair Review** (`docs-pair-review`) — selected related document pairs
   are reviewed by an LLM for relationship and consolidation actions.

Docs Map is meant to answer "how should these docs be organized?" Section Match
is meant to answer "where is repeated content?" They are related but
intentionally reported separately.

## Conclusion

dryscope fills a real gap, but in a narrower and more practical sense than
"semantic clone detector" might suggest.

What it does well:
- surfaces structural duplicate candidates across multiple languages before a larger refactor pass
- filters code findings into a smaller shortlist for agent, model, or human follow-up
- discovers Docs Map signals and consolidation clusters across a docs corpus
- detects repeated documentation sections and ranks concrete section-level recommendations

What it does not claim to do:
- replace general linting, IDE inspection, or mature text-clone tooling
- perfectly detect Type 4 semantic clones
- decide every refactor automatically
- replace deeper review by a stronger model or a human

The product value is that it reduces search space before expensive attention is
spent. In recent public validation:
- `kvsankar/sattosat` produced one clear code refactor candidate and no docs noise
- `stellar/stellar-docs` produced a compact grouped docs shortlist
- `gethomepage/homepage` exited early as a large negative docs case
- agent-created or agent-oriented repos produced large structural candidate sets
  that bounded verification narrowed to single-digit or low-double-digit review
  queues

That is the right bar for dryscope: high-signal narrowing before expensive follow-up.
Use `uv run python benchmarks/run_quality_report.py` to generate the current
label-based quality report.
