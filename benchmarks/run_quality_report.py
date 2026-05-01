#!/usr/bin/env python3
"""Summarize benchmark output quality from curated public labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from benchmarks.benchmark_paths import (
    default_quality_report_dir,
    latest_results_dir,
    prepare_output_dir,
)
from dryscope.benchmark import score_code_quality, score_docs_section_quality

DEFAULT_CODE_RESULTS = latest_results_dir("code")
DEFAULT_DOCS_RESULTS = [
    latest_results_dir("docs", ("public-docs-default",)),
    latest_results_dir("docs", ("public-docs-stress",)),
]
DEFAULT_CODE_LABELS = Path(__file__).with_name("public_labels.json")
DEFAULT_DOCS_LABELS = Path(__file__).with_name("public_docs_labels.json")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_labels(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return _load_json(path).get("labels", [])


def _aggregate(rows: list[dict]) -> dict:
    counts = {
        "gold_positive_count": 0,
        "gold_negative_count": 0,
        "surfaced_findings_count": 0,
        "labeled_surfaced_count": 0,
        "true_positives": 0,
        "false_positives": 0,
        "false_negatives": 0,
    }
    for row in rows:
        for key in counts:
            counts[key] += row.get(key, 0) or 0

    tp = counts["true_positives"]
    fp = counts["false_positives"]
    fn = counts["false_negatives"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    aggregate = {
        **counts,
        "labeled_precision": precision,
        "curated_recall": recall,
        "f1": f1,
    }
    aggregate["precision_at_k"] = {}
    aggregate["recall_at_k"] = {}
    for k in (5, 10, 15):
        tp_at_k = sum(
            1
            for row in rows
            for item in row.get("true_positive_items", [])
            if item.get("rank", 0) <= k
        )
        fp_at_k = sum(
            1
            for row in rows
            for item in row.get("false_positive_items", [])
            if item.get("rank", 0) <= k
        )
        aggregate["precision_at_k"][str(k)] = (
            tp_at_k / (tp_at_k + fp_at_k) if tp_at_k + fp_at_k else None
        )
        aggregate["recall_at_k"][str(k)] = (
            tp_at_k / counts["gold_positive_count"] if counts["gold_positive_count"] else None
        )
    return aggregate


def _quality_summary(
    code_results_dir: Path,
    docs_results_dirs: list[Path],
    code_labels: list[dict],
    docs_labels: list[dict],
) -> dict:
    code_summary_path = code_results_dir / "summary.json"
    code_rows: list[dict] = []
    code_metadata = None
    if code_summary_path.exists():
        code_summary = _load_json(code_summary_path)
        code_metadata = code_summary.get("benchmark_metadata")
        for repo in code_summary.get("repos", []):
            repo_name = repo["repo"]
            output_name = repo.get("verify_output") or repo.get("structural_output")
            output_path = code_results_dir / output_name if output_name else None
            if not output_path or not output_path.exists():
                output_path = code_results_dir / f"{repo_name}_verify.json"
            if not output_path.exists():
                output_path = code_results_dir / f"{repo_name}_structural.json"
            if not output_path.exists():
                continue
            findings = _load_json(output_path).get("findings", [])
            row = {
                "repo": repo_name,
                "group": repo.get("group"),
                "benchmark_input_id": repo.get("benchmark_input_id"),
                "benchmark_input_stem": repo.get("benchmark_input_stem"),
                "repo_git_commit": repo.get("repo_git_commit"),
                **score_code_quality(repo_name, findings, code_labels),
            }
            code_rows.append(row)

    docs_rows: list[dict] = []
    docs_metadata: list[dict] = []
    for docs_dir in docs_results_dirs:
        summary_path = docs_dir / "summary.json"
        if not summary_path.exists():
            continue
        summary = _load_json(summary_path)
        docs_metadata.append(
            {
                "results_dir": str(docs_dir),
                "benchmark_metadata": summary.get("benchmark_metadata"),
            }
        )
        for repo in summary.get("repos", []):
            repo_name = repo["repo"]
            artifact_dir = Path(repo.get("artifact_dir", str(Path("artifacts") / repo_name)))
            output_path = docs_dir / artifact_dir / "docs_section_match.json"
            if not output_path.exists():
                continue
            section_pairs = _load_json(output_path).get("matched_section_pairs", [])
            row = {
                "repo": repo_name,
                "group": repo.get("group"),
                "results_dir": str(docs_dir),
                "benchmark_input_id": repo.get("benchmark_input_id"),
                "benchmark_input_stem": repo.get("benchmark_input_stem"),
                "repo_git_commit": repo.get("repo_git_commit"),
                **score_docs_section_quality(repo_name, section_pairs, docs_labels),
            }
            docs_rows.append(row)

    return {
        "metric_notes": {
            "labeled_precision": "TP / (TP + FP) over surfaced findings that have curated labels; unlabeled findings are not counted as false positives.",
            "curated_recall": "TP / (TP + FN) over curated positive labels for the benchmark repos.",
            "true_negatives": "Not reported because the non-duplicate search space is too large to enumerate meaningfully.",
        },
        "code_review": {
            "benchmark_metadata": code_metadata,
            "aggregate": _aggregate(code_rows),
            "by_repo": code_rows,
        },
        "docs_section_match": {
            "benchmark_metadata": docs_metadata,
            "aggregate": _aggregate(docs_rows),
            "by_repo": docs_rows,
        },
    }


def _fmt_metric(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _markdown_table(title: str, rows: list[dict]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| Benchmark input | TP | FP | FN | Labeled precision | Curated recall | F1 | Labeled surfaced | Gold + | Gold - |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not rows:
        lines.append("| _No benchmark rows found_ | 0 | 0 | 0 | n/a | n/a | n/a | 0 | 0 | 0 |")
        lines.append("")
        return lines
    for row in rows:
        lines.append(
            "| {repo} | {tp} | {fp} | {fn} | {precision} | {recall} | {f1} | {labeled} | {gold_pos} | {gold_neg} |".format(
                repo=row.get("benchmark_input_stem") or row["repo"],
                tp=row["true_positives"],
                fp=row["false_positives"],
                fn=row["false_negatives"],
                precision=_fmt_metric(row["labeled_precision"]),
                recall=_fmt_metric(row["curated_recall"]),
                f1=_fmt_metric(row["f1"]),
                labeled=row["labeled_surfaced_count"],
                gold_pos=row["gold_positive_count"],
                gold_neg=row["gold_negative_count"],
            )
        )
    lines.append("")
    return lines


def _render_markdown(report: dict) -> str:
    has_rows = bool(report["code_review"]["by_repo"] or report["docs_section_match"]["by_repo"])
    lines = [
        "# Benchmark Quality Report",
        "",
        "This report is the readable companion to `quality_report.json`. It scores",
        "generated benchmark outputs against curated public labels and is intended",
        "as shortlist-quality evidence, not as a broad precision/recall claim over",
        "every possible duplicate in a repository.",
        "",
    ]
    if not has_rows:
        lines.extend(
            [
                "> Note: this generated report did not find benchmark result rows in the",
                "> configured input artifact directories, so the tables below show the",
                "> presenter shape with empty values. Run the public benchmark harnesses",
                "> first, then regenerate this report to populate real metrics.",
                "",
            ]
        )
    lines.extend(
        [
            "## How To Read This",
            "",
            "`dryscope` is a narrowing tool, so the report uses a practical 2x2 rather",
            "than pretending every possible non-duplicate code unit or doc section can",
            "be enumerated.",
            "",
            "Rows are the curated truth. Columns are dryscope's output.",
            "",
            "| Curated truth / dryscope output | Surfaced finding (predicted positive) | Not surfaced (predicted negative) |",
            "| --- | --- | --- |",
            "| Actionable duplicate or overlap (actual positive) | **TP**: dryscope found a curated actionable item. | **FN**: dryscope missed a curated actionable item. |",
            "| Non-actionable item (actual negative) | **FP**: dryscope surfaced an item curated as not actionable. | **TN**: dryscope correctly ignored it; not reported because the negative space is too large to enumerate meaningfully. |",
            "",
            "Unlabeled surfaced findings are not counted as false positives. The checked-in",
            "public labels are intentionally sparse, so these numbers describe the",
            "reviewed slice of benchmark output.",
            "",
            "Precision reads down the surfaced column: `TP / (TP + FP)`. Recall reads",
            "across the actionable row: `TP / (TP + FN)`.",
            "",
            "## Metric Notes",
            "",
            "| Metric | Direction | How to read it |",
            "| --- | --- | --- |",
            "| TP | higher is better | Surfaced findings that match actionable curated labels. |",
            "| FP | lower is better | Surfaced findings that match curated non-actionable labels. |",
            "| FN | lower is better | Actionable curated labels that dryscope missed. |",
            "| Labeled precision | higher is better | `TP / (TP + FP)` over surfaced findings that have curated labels. |",
            "| Curated recall | higher is better | `TP / (TP + FN)` over curated actionable labels. |",
            "| F1 | higher is better | Harmonic mean of labeled precision and curated recall. |",
            "| P@K / R@K | higher is better | Top-of-shortlist precision and recall for `K = 5, 10, 15`. |",
            "| Labeled surfaced | no direct quality direction | Count of surfaced findings that had curated labels and were eligible for TP/FP scoring. |",
            "| Gold + / Gold - | no direct quality direction | Curated positive and negative labels available for the benchmark repos. |",
            "",
            "`n/a` means the denominator for that metric is zero.",
            "",
            "## Aggregate Summary",
            "",
            "| Track | TP | FP | FN | Labeled precision | Curated recall | F1 | P@5 | R@5 | Labeled surfaced | Gold + | Gold - |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for title, key in (("Code Review", "code_review"), ("Section Match", "docs_section_match")):
        agg = report[key]["aggregate"]
        lines.append(
            "| {title} | {tp} | {fp} | {fn} | {precision} | {recall} | {f1} | {p5} | {r5} | {labeled} | {gold_pos} | {gold_neg} |".format(
                title=title,
                tp=agg["true_positives"],
                fp=agg["false_positives"],
                fn=agg["false_negatives"],
                precision=_fmt_metric(agg["labeled_precision"]),
                recall=_fmt_metric(agg["curated_recall"]),
                f1=_fmt_metric(agg["f1"]),
                p5=_fmt_metric(agg["precision_at_k"]["5"]),
                r5=_fmt_metric(agg["recall_at_k"]["5"]),
                labeled=agg["labeled_surfaced_count"],
                gold_pos=agg["gold_positive_count"],
                gold_neg=agg["gold_negative_count"],
            )
        )
    lines.append("")
    lines.extend(_markdown_table("Code Review By Repo", report["code_review"]["by_repo"]))
    lines.extend(_markdown_table("Section Match By Repo", report["docs_section_match"]["by_repo"]))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-results-dir", default=str(DEFAULT_CODE_RESULTS))
    parser.add_argument(
        "--docs-results-dir",
        action="append",
        default=[],
        help="Docs benchmark results directory; can be supplied multiple times.",
    )
    parser.add_argument("--code-labels", default=str(DEFAULT_CODE_LABELS))
    parser.add_argument("--docs-labels", default=str(DEFAULT_DOCS_LABELS))
    parser.add_argument("--out-dir", default=str(default_quality_report_dir()))
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing quality report directory"
    )
    parser.add_argument(
        "--reference-md",
        default=None,
        help="Also write the Markdown report to a reference path, such as benchmarks/quality_report.md.",
    )
    args = parser.parse_args()

    docs_dirs = [Path(path) for path in args.docs_results_dir] or DEFAULT_DOCS_RESULTS
    report = _quality_summary(
        Path(args.code_results_dir),
        docs_dirs,
        _load_labels(Path(args.code_labels)),
        _load_labels(Path(args.docs_labels)),
    )

    out_dir = prepare_output_dir(Path(args.out_dir), overwrite=args.overwrite)
    markdown = _render_markdown(report)
    (out_dir / "quality_report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "quality_report.md").write_text(markdown)
    if args.reference_md:
        reference_path = Path(args.reference_md)
        reference_path.parent.mkdir(parents=True, exist_ok=True)
        reference_path.write_text(markdown)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
