# CLAUDE.md

## Project Orientation

`dryscope` is a Python CLI/library for narrowing large repositories before
AI-assisted cleanup. It scans code and documentation for repeated
implementation shapes, duplicated helpers, overlapping document sections, and
document-level intent overlap. Its output is a ranked shortlist for humans,
agents, or stronger review models, not a claim that every match should be
refactored.

## Progressive Disclosure

Start with the smallest useful document, then drill down:

- [README.md](./README.md) - product framing, motivation, install, quick start,
  configuration, and the documentation index.
- [AGENTS.md](./AGENTS.md) - repository-wide agent guidance, commands,
  dependency picture, code organization, and artifact rules.
- [docs/architecture.md](./docs/architecture.md) - code pipeline, docs
  pipeline, component responsibilities, and shared infrastructure.
- [docs/synthetic-examples.md](./docs/synthetic-examples.md) - small synthetic
  examples for Code Match, Docs Map, Section Match, and similarity behavior.
- [benchmarks/README.md](./benchmarks/README.md) - public benchmark harness,
  artifact locations, and refresh commands.
- [benchmarks/quality_report.md](./benchmarks/quality_report.md) - checked-in
  readable benchmark reference with TP/FP/FN explanations.
- [docs/analysis.md](./docs/analysis.md) - positioning, alternatives,
  benchmark notes, and product-readiness context.
- [docs/roadmap.md](./docs/roadmap.md) - forward-looking planning notes.
- [dryscope/skill/SKILL.md](./dryscope/skill/SKILL.md) - packaged agent skill
  instructions for using dryscope from another repo.

## Commands

- Use `uv` for Python-related commands in this repository.
- Prefer `uv run python` over calling `python` or `python3` directly.
- Prefer `uv run pytest` for tests and `uv run dryscope ...` for local CLI
  checks.
- Run focused tests for the area you changed, for example
  `uv run pytest tests/test_parser.py` or
  `uv run pytest tests/test_docs_pipeline.py`.
- Run the full suite with `uv run pytest` when changing shared behavior,
  CLI contracts, config, reports, or scoring.

## Dependency Picture

- CLI and terminal UX: `click` and `rich`.
- Code parsing: `tree-sitter` plus Python, Go, Java, JavaScript, and
  TypeScript grammars.
- Docs parsing: `mistune` for Markdown/MDX plus lightweight text handling for
  RST, AsciiDoc, TXT, and related docs.
- Similarity math: `numpy` cosine similarity plus token Jaccard and size-ratio
  filters.
- Embeddings: LiteLLM-backed API embeddings by default; optional
  `sentence-transformers` local embeddings.
- LLM review: shared backend over LiteLLM providers or the `claude -p` CLI,
  with `tenacity` retries.
- Persistence: SQLite cache for embeddings/review results and `.dryscope/runs`
  for docs report artifacts.

```text
dryscope.cli
  -> code parser/normalizer/embedder/similarity/reporter
  -> docs chunker/embeddings/taxonomy/pipeline/report
  -> shared config/cache/llm_backend/run_store/unified_report
```

## Code Organization

- `dryscope/cli.py` - command-line entry point and option wiring.
- `dryscope/code/` - Code Match and Code Review: parsing, normalization,
  embeddings, project profiles, verifier, policy, and reporting.
- `dryscope/docs/` - docs chunking, Section Match, Docs Map taxonomy/topics,
  Doc Pair Review, pipeline orchestration, and report generation.
- `dryscope/similarity.py` - shared cosine/Jaccard similarity and clustering.
- `dryscope/config.py` - defaults, `.dryscope.toml`, and CLI override merge.
- `dryscope/cache.py` - SQLite cache for embeddings and LLM results.
- `dryscope/llm_backend.py` - provider-neutral LLM calls.
- `dryscope/run_store.py` - saved docs report runs and cleanup.
- `dryscope/unified_report.py` - shared agent-consumable `findings[]` output.
- `dryscope/benchmark.py` and `benchmarks/` - public benchmark scoring,
  labels, runners, and generated reference report.
- `tests/` - focused unit and integration tests for parser, docs pipeline,
  reports, benchmarks, config, cache, and CLI behavior.

## Artifact Rules

- Keep generated caches, cloned benchmark repositories, and temporary scan
  outputs outside the repository tree.
- Durable benchmark inputs/results belong under `~/.dryscope/benchmarks`, not
  `/tmp`.
- The repository `.gitignore` excludes local `.dryscope/` runs. Do not check in
  generated run artifacts unless a file is explicitly intended as a reference,
  such as `benchmarks/quality_report.md`.
- If you change the benchmark quality report format, update
  `benchmarks/run_quality_report.py` and regenerate the checked-in
  `benchmarks/quality_report.md` from existing artifacts.

<!-- claude-insights:start -->
## Working with Claude

These working agreements come from a `/insights` analysis of past sessions. Keep them in mind on every task in this repo.

- When pre-commit or pre-push hooks fail, fix the underlying issues (line length, trailing whitespace, lint errors) properly. Do NOT skip hooks, amend silently, or work around them. Never run `git init`, rewrite history (rebase, force push), or skip flaky tests without explicit permission.
- When asked to fix a problem, diagnose the root cause before proposing a fix. Do not jump to surface-level changes (e.g., flipping a port without understanding the networking, attributing a CSS bug to line-height without investigating).
- If two approaches have failed for the same problem, stop and present options to the user instead of trying a third. Don't thrash.
- Never fabricate documentation content. If you don't know what a doc actually says, read the file first.
<!-- claude-insights:end -->
