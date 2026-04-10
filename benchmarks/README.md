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
python benchmarks/run_public_benchmark.py
```

Optional filters:

```bash
python benchmarks/run_public_benchmark.py --group public-moderate
python benchmarks/run_public_benchmark.py --group public-low-star
python benchmarks/run_public_benchmark.py --group public-claude-signal-2025
python benchmarks/run_public_benchmark.py --group public-new-languages
```

Outputs are written to `/tmp/dryscope-public-benchmark-results` by default.

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
- Java:
  - `jsoup`
- Go:
  - `cobra`
  - `chi`

This group is intentionally not the heaviest possible set. During exploratory
testing, some popular Java libraries behaved more like stress benchmarks than
routine regression checks. Those are better kept as separate one-off scale
tests than added to the default public pack.
