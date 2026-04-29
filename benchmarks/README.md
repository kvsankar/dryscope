# Public Benchmark Pack

This directory contains the checked-in, public-only benchmark harness for `dryscope`.

It exists to turn exploratory testing into a repeatable workflow:

- `public_repos.json` defines the public repositories used for benchmarking
- `public_labels.json` stores reviewed labels for a subset of findings
- `run_public_benchmark.py` clones the public repos, runs `dryscope`, and scores any findings that match the stored labels

This benchmark pack is intentionally conservative:
- it is for repeatable public regression checks
- it is not a dump of every public repo used during exploratory testing

Additional public repos may still appear in README examples or blog posts if they were used as one-off validation cases.

## Privacy Rule

Only public repositories belong in this directory.

Do not add:

- private repo URLs
- private repo names
- labels or notes derived from private repos

Private-repo evaluation can still be done locally, but it should stay out of the checked-in benchmark pack and public docs.

## Running

Use the local virtualenv binary:

```bash
uv run python benchmarks/run_public_benchmark.py
```

Optional filters:

```bash
uv run python benchmarks/run_public_benchmark.py --group public-moderate
uv run python benchmarks/run_public_benchmark.py --group public-low-star
uv run python benchmarks/run_public_benchmark.py --group public-claude-signal-2025
uv run python benchmarks/run_public_benchmark.py --group public-new-languages
uv run python benchmarks/run_public_benchmark.py --group public-new-languages-stress
uv run python benchmarks/run_public_benchmark.py --group public-ai-generated-duplicates
```

Outputs are written to `/tmp/dryscope-public-benchmark-results` by default.

For a bounded verified pass over the AI-generated group:

```bash
uv run python benchmarks/run_public_benchmark.py --group public-ai-generated-duplicates --verify-max-findings 15
```

By default the public benchmark harness pins structural scans to
`all-MiniLM-L6-v2` so benchmark results do not depend on API embedding
credentials. Run it from the development environment, or install
`dryscope[local-embeddings]`, because the lightweight default install does not
include local sentence-transformers. Use `--embedding-model` to test another
embedding backend.

Use `--structural-only` when you only need candidate counts and saved structural
JSON outputs. Omit it when you want the full LLM verification and label scoring
pass. Use `--verify-max-findings 15` for a bounded verification pass over the
highest-ranked candidates in each repo.

## Label Semantics

Labels are intentionally simple:

- `real_refactor_candidate`
- `not_worth_refactoring`
- `uncertain`

The labels are stored against normalized unit signatures using repo-relative paths, so they remain stable across different clone locations.

## New-Language Group

The `public-new-languages` group is a representative regression pack for newly
added code languages:

- JavaScript / JSX:
  - `axios`
  - `downshift`
  - `react-modal`
- Java:
  - `jsoup`
  - `HikariCP`
- Go:
  - `cobra`
  - `chi`
  - `resty`

This group is intentionally not the heaviest possible set. During exploratory
testing, some popular Java libraries behaved more like stress benchmarks than
routine regression checks. Those are better kept as separate one-off scale
tests than added to the default public pack.

The `public-new-languages-stress` group currently contains:

- `gson`

Use it when you want a heavier Java-scale check, not for fast routine
regression runs.

## AI-Generated Duplicate Group

The `public-ai-generated-duplicates` group is for the product positioning around
AI preflight and repo narrowing. These repos were selected because exploratory
scans produced more than a token number of duplicate-code candidates:

- `CLI-Anything-WEB`
- `nanowave`
- `ClaudeCode_generated_app`
- `VibesOS`

Use this group when checking whether dryscope finds useful repeated code shapes
in agent-created, agent-oriented, or vibe-coded repositories.

A structural-only run on April 29, 2026 with `all-MiniLM-L6-v2` produced:

| Repo | Structural findings | Verified findings from top 15 |
| --- | ---: | ---: |
| `CLI-Anything-WEB` | 94 | 5 |
| `nanowave` | 82 | 10 |
| `ClaudeCode_generated_app` | 51 | 6 |
| `VibesOS` | 23 | 4 |

This group is intentionally not part of a "find every duplicate" claim. It
checks the product story that dryscope can narrow agent-created or
agent-oriented repositories to concrete repeated implementation shapes worth
reviewing.

The same April 29, 2026 run matched reviewed labels for:

- `CLI-Anything-WEB`: 1 `real_refactor_candidate`
- `nanowave`: 2 `real_refactor_candidate`
- `ClaudeCode_generated_app`: 2 `real_refactor_candidate`
- `VibesOS`: 1 `not_worth_refactoring` example that the verifier still kept as
  `refactor`, making it a useful false-positive regression case
