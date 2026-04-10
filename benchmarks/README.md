# Public Benchmark Pack

This directory contains the checked-in, public-only benchmark harness for `dryscope`.

It exists to turn exploratory testing into a repeatable workflow:

- `public_repos.json` defines the public repositories used for benchmarking
- `public_labels.json` stores reviewed labels for a subset of findings
- `run_public_benchmark.py` clones the public repos, runs `dryscope`, and scores any findings that match the stored labels

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
python benchmarks/run_public_benchmark.py
```

Optional filters:

```bash
python benchmarks/run_public_benchmark.py --group public-moderate
python benchmarks/run_public_benchmark.py --group public-low-star
python benchmarks/run_public_benchmark.py --group public-claude-signal-2025
```

Outputs are written to `/tmp/dryscope-public-benchmark-results` by default.

## Label Semantics

Labels are intentionally simple:

- `real_refactor_candidate`
- `not_worth_refactoring`
- `uncertain`

The labels are stored against normalized unit signatures using repo-relative paths, so they remain stable across different clone locations.
