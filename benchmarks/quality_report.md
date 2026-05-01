# Benchmark Quality Report

This report is the readable companion to `quality_report.json`. It scores
generated benchmark outputs against curated public labels and is intended
as shortlist-quality evidence, not as a broad precision/recall claim over
every possible duplicate in a repository.

## How To Read This

`dryscope` is a narrowing tool, so the report uses a practical 2x2 rather
than pretending every possible non-duplicate code unit or doc section can
be enumerated.

Rows are the curated truth. Columns are dryscope's output.

| Curated truth / dryscope output | Surfaced finding (predicted positive) | Not surfaced (predicted negative) |
| --- | --- | --- |
| Actionable duplicate or overlap (actual positive) | **TP**: dryscope found a curated actionable item. | **FN**: dryscope missed a curated actionable item. |
| Non-actionable item (actual negative) | **FP**: dryscope surfaced an item curated as not actionable. | **TN**: dryscope correctly ignored it; not reported because the negative space is too large to enumerate meaningfully. |

Unlabeled surfaced findings are not counted as false positives. The checked-in
public labels are intentionally sparse, so these numbers describe the
reviewed slice of benchmark output.

Precision reads down the surfaced column: `TP / (TP + FP)`. Recall reads
across the actionable row: `TP / (TP + FN)`.

## Metric Notes

| Metric | Direction | How to read it |
| --- | --- | --- |
| TP | higher is better | Surfaced findings that match actionable curated labels. |
| FP | lower is better | Surfaced findings that match curated non-actionable labels. |
| FN | lower is better | Actionable curated labels that dryscope missed. |
| Labeled precision | higher is better | `TP / (TP + FP)` over surfaced findings that have curated labels. |
| Curated recall | higher is better | `TP / (TP + FN)` over curated actionable labels. |
| F1 | higher is better | Harmonic mean of labeled precision and curated recall. |
| P@K / R@K | higher is better | Top-of-shortlist precision and recall for `K = 5, 10, 15`. |
| Labeled surfaced | no direct quality direction | Count of surfaced findings that had curated labels and were eligible for TP/FP scoring. |
| Gold + / Gold - | no direct quality direction | Curated positive and negative labels available for the benchmark repos. |

`n/a` means the denominator for that metric is zero.

## Aggregate Summary

| Track | TP | FP | FN | Labeled precision | Curated recall | F1 | P@5 | R@5 | Labeled surfaced | Gold + | Gold - |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Code Review | 11 | 7 | 2 | 0.61 | 0.85 | 0.71 | 0.61 | 0.85 | 18 | 13 | 13 |
| Section Match | 3 | 3 | 0 | 0.50 | 1.00 | 0.67 | 0.50 | 1.00 | 6 | 3 | 3 |

## Code Review By Repo

| Benchmark input | TP | FP | FN | Labeled precision | Curated recall | F1 | Labeled surfaced | Gold + | Gold - |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MonkeyType@15e7bca60146 | 0 | 0 | 1 | n/a | 0.00 | n/a | 0 | 1 | 0 |
| silverbullet@c96651d0b2f0 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| opennextjs-aws@566bdd9048f5 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| tsdoc@2dd8912e50b8 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 4 |
| vue-loader@698636508e08 | 0 | 1 | 0 | 0.00 | n/a | n/a | 1 | 0 | 1 |
| PptxGenJS@3c9ec1b687c1 | 0 | 1 | 0 | 0.00 | n/a | n/a | 1 | 0 | 1 |
| sparkhub@19f9c87f3456 | 1 | 2 | 0 | 0.33 | 1.00 | 0.50 | 3 | 1 | 4 |
| Personal-Knowledge-Vault@80b1dd1b4dd9 | 2 | 2 | 0 | 0.50 | 1.00 | 0.67 | 4 | 2 | 2 |
| pocket-pick@d8243d35036c | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| svelte-claude-skills@0152f42ed6e9 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| axios@ad68e1a484b5 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| downshift@f1862ed0633a | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| react-modal@e66ab51b65e6 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| jsoup@9c5fbf700efb | 0 | 0 | 1 | n/a | 0.00 | n/a | 0 | 1 | 0 |
| HikariCP@bba167f0a289 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| cobra@ad460ea8f249 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| chi@a54874f0e2f1 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| resty@814366549975 | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 | 1 | 1 | 0 |
| gson@8260eddffe41 | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 | 1 | 1 | 0 |
| CLI-Anything-WEB@3975e59981dd | 2 | 0 | 0 | 1.00 | 1.00 | 1.00 | 2 | 2 | 0 |
| nanowave@ea7fec5b5e03 | 2 | 0 | 0 | 1.00 | 1.00 | 1.00 | 2 | 2 | 0 |
| ClaudeCode_generated_app@f9a68f75a8fc | 2 | 0 | 0 | 1.00 | 1.00 | 1.00 | 2 | 2 | 0 |
| VibesOS@13766a0ddbed | 0 | 1 | 0 | 0.00 | n/a | n/a | 1 | 0 | 1 |

## Section Match By Repo

| Benchmark input | TP | FP | FN | Labeled precision | Curated recall | F1 | Labeled surfaced | Gold + | Gold - |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fastapi-en@d8a2c1edaa79 | 2 | 0 | 0 | 1.00 | 1.00 | 1.00 | 2 | 2 | 0 |
| astro-en@ca20646143b5 | 0 | 2 | 0 | 0.00 | n/a | n/a | 2 | 0 | 2 |
| react-dev@abe931a8cb3a | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| rust-book@05d114287b7d | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| prometheus-docs@92c512e9931c | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| docker-manuals@b8ab8689b162 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
| godot-tutorials@3d7872c870d7 | 1 | 1 | 0 | 0.50 | 1.00 | 0.67 | 2 | 1 | 1 |
| pandas-doc@ce92ae8187f0 | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |
