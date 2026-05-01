"""Helpers for running and scoring public dryscope benchmarks."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable


ACTIONABLE_CODE_LABELS = {"real_refactor_candidate"}
NON_ACTIONABLE_CODE_LABELS = {"not_worth_refactoring"}
ACTIONABLE_DOCS_LABELS = {"useful_section_match", "useful_docs_map_candidate", "useful_doc_pair_review"}
NON_ACTIONABLE_DOCS_LABELS = {"intentional_repetition", "not_actionable"}


def finding_signature(finding: dict, repo_root: str | Path) -> tuple[tuple[str, str], ...]:
    """Return a stable signature for a finding using repo-relative unit paths.

    The signature is the sorted tuple of ``(relative_path, unit_name)`` pairs.
    This makes labels resilient to different clone and artifact locations.
    """
    root = Path(repo_root).resolve()
    items: list[tuple[str, str]] = []
    for unit in finding.get("units", []):
        unit_path = Path(unit["file"])
        if unit_path.is_absolute():
            try:
                rel_path = unit_path.resolve().relative_to(root).as_posix()
            except ValueError:
                rel_path = unit_path.as_posix()
        else:
            rel_path = unit_path.as_posix()
        items.append((rel_path, unit["name"]))
    return tuple(sorted(items))


def build_label_index(labels: list[dict]) -> dict[tuple[str, tuple[tuple[str, str], ...]], dict]:
    """Index benchmark labels by ``(repo, signature)``."""
    index: dict[tuple[str, tuple[tuple[str, str], ...]], dict] = {}
    for label in labels:
        signature = tuple(sorted((item["path"], item["name"]) for item in label["units"]))
        index[(label["repo"], signature)] = label
    return index


def score_labeled_findings(
    repo_name: str,
    findings: list[dict],
    repo_root: str | Path,
    labels: list[dict],
) -> dict:
    """Score findings against any stored public labels for that repo."""
    label_index = build_label_index(labels)
    matched: list[dict] = []
    label_counts: Counter[str] = Counter()

    for finding in findings:
        signature = finding_signature(finding, repo_root)
        label = label_index.get((repo_name, signature))
        if label is None:
            continue
        matched.append({
            "label": label["label"],
            "units": list(signature),
            "verdict": finding.get("verdict"),
            "tier": finding.get("tier"),
        })
        label_counts[label["label"]] += 1

    return {
        "matched_count": len(matched),
        "matched_labels": dict(label_counts),
        "matched_findings": matched,
    }


def _safe_divide(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _unit_matches(actual: dict, expected: dict) -> bool:
    actual_name = str(actual.get("name", ""))
    expected_name = str(expected.get("name", ""))
    if actual_name != expected_name:
        return False

    actual_path = Path(str(actual.get("file", ""))).as_posix()
    expected_path = Path(str(expected.get("path", ""))).as_posix()
    return actual_path == expected_path or actual_path.endswith(f"/{expected_path}")


def finding_matches_label_units(finding: dict, expected_units: Iterable[dict]) -> bool:
    """Return whether a code finding contains exactly the expected labeled units.

    Benchmark outputs may contain absolute clone paths while labels are stored
    repo-relative. Matching by path suffix keeps quality scoring independent of
    where the benchmark repos were cloned.
    """
    actual_units = list(finding.get("units", []))
    expected = list(expected_units)
    if len(actual_units) != len(expected):
        return False

    unmatched = actual_units[:]
    for expected_unit in expected:
        for i, actual in enumerate(unmatched):
            if _unit_matches(actual, expected_unit):
                unmatched.pop(i)
                break
        else:
            return False
    return not unmatched


def _quality_counts_to_metrics(counts: dict) -> dict:
    tp = counts["true_positives"]
    fp = counts["false_positives"]
    fn = counts["false_negatives"]
    precision = _safe_divide(tp, tp + fp)
    recall = _safe_divide(tp, tp + fn)
    return {
        **counts,
        "labeled_precision": precision,
        "curated_recall": recall,
        "f1": _f1(precision, recall),
    }


def _label_quality_kind(
    label_name: str,
    positive_labels: set[str],
    negative_labels: set[str],
) -> str | None:
    if label_name in positive_labels:
        return "positive"
    if label_name in negative_labels:
        return "negative"
    return None


def score_code_quality(
    repo_name: str,
    findings: list[dict],
    labels: list[dict],
    *,
    positive_labels: set[str] | None = None,
    negative_labels: set[str] | None = None,
    k_values: tuple[int, ...] = (5, 10, 15),
) -> dict:
    """Score Code Review output against curated positive/negative labels.

    Unlabeled surfaced findings are intentionally not counted as false
    positives. The precision denominator is only labeled surfaced findings.
    Recall is over curated positive labels for the repo.
    """
    positive_labels = positive_labels or ACTIONABLE_CODE_LABELS
    negative_labels = negative_labels or NON_ACTIONABLE_CODE_LABELS
    repo_labels = [label for label in labels if label.get("repo") == repo_name]
    scored_labels = [
        label for label in repo_labels
        if _label_quality_kind(str(label.get("label", "")), positive_labels, negative_labels)
    ]
    positive_gold = [
        label for label in scored_labels
        if str(label.get("label")) in positive_labels
    ]

    matched_label_ids: set[int] = set()
    true_positive_items: list[dict] = []
    false_positive_items: list[dict] = []

    for rank, finding in enumerate(findings, start=1):
        for idx, label in enumerate(scored_labels):
            if idx in matched_label_ids:
                continue
            if not finding_matches_label_units(finding, label.get("units", [])):
                continue
            matched_label_ids.add(idx)
            item = {
                "rank": rank,
                "label": label["label"],
                "units": label.get("units", []),
                "verdict": finding.get("verdict"),
                "tier": finding.get("tier"),
            }
            if label["label"] in positive_labels:
                true_positive_items.append(item)
            else:
                false_positive_items.append(item)
            break

    false_negative_items = [
        {
            "label": label["label"],
            "units": label.get("units", []),
        }
        for idx, label in enumerate(scored_labels)
        if idx not in matched_label_ids and label["label"] in positive_labels
    ]

    counts = {
        "gold_positive_count": len(positive_gold),
        "gold_negative_count": len(scored_labels) - len(positive_gold),
        "surfaced_findings_count": len(findings),
        "labeled_surfaced_count": len(true_positive_items) + len(false_positive_items),
        "true_positives": len(true_positive_items),
        "false_positives": len(false_positive_items),
        "false_negatives": len(false_negative_items),
    }
    metrics = _quality_counts_to_metrics(counts)
    metrics["precision_at_k"] = {}
    metrics["recall_at_k"] = {}
    for k in k_values:
        tp_at_k = sum(1 for item in true_positive_items if item["rank"] <= k)
        fp_at_k = sum(1 for item in false_positive_items if item["rank"] <= k)
        metrics["precision_at_k"][str(k)] = _safe_divide(tp_at_k, tp_at_k + fp_at_k)
        metrics["recall_at_k"][str(k)] = _safe_divide(tp_at_k, len(positive_gold))
    metrics["true_positive_items"] = true_positive_items
    metrics["false_positive_items"] = false_positive_items
    metrics["false_negative_items"] = false_negative_items
    return metrics


def docs_section_signature(section_pair: dict) -> tuple[tuple[str, int], tuple[str, int]]:
    """Return a stable signature for a Section Match pair."""
    chunk_a = section_pair.get("chunk_a", {})
    chunk_b = section_pair.get("chunk_b", {})
    sections = (
        (Path(str(chunk_a.get("file", ""))).as_posix(), int(chunk_a.get("line_start", 0))),
        (Path(str(chunk_b.get("file", ""))).as_posix(), int(chunk_b.get("line_start", 0))),
    )
    return tuple(sorted(sections))


def _docs_label_signature(label: dict) -> tuple[tuple[str, int], tuple[str, int]]:
    sections = label.get("sections", [])
    if len(sections) != 2:
        raise ValueError("docs section labels must contain exactly two sections")
    return tuple(sorted(
        (Path(str(section["path"])).as_posix(), int(section["line_start"]))
        for section in sections
    ))


def score_docs_section_quality(
    repo_name: str,
    section_pairs: list[dict],
    labels: list[dict],
    *,
    positive_labels: set[str] | None = None,
    negative_labels: set[str] | None = None,
    k_values: tuple[int, ...] = (5, 10, 15),
) -> dict:
    """Score Section Match output against curated docs labels."""
    positive_labels = positive_labels or ACTIONABLE_DOCS_LABELS
    negative_labels = negative_labels or NON_ACTIONABLE_DOCS_LABELS
    repo_labels = [
        label for label in labels
        if label.get("repo") == repo_name and label.get("track") == "docs-section-match"
    ]
    scored_labels = [
        label for label in repo_labels
        if _label_quality_kind(str(label.get("label", "")), positive_labels, negative_labels)
    ]
    positive_gold = [label for label in scored_labels if label["label"] in positive_labels]
    label_index = {_docs_label_signature(label): label for label in scored_labels}

    matched_signatures: set[tuple[tuple[str, int], tuple[str, int]]] = set()
    true_positive_items: list[dict] = []
    false_positive_items: list[dict] = []

    for rank, pair in enumerate(section_pairs, start=1):
        signature = docs_section_signature(pair)
        label = label_index.get(signature)
        if label is None or signature in matched_signatures:
            continue
        matched_signatures.add(signature)
        item = {
            "rank": rank,
            "label": label["label"],
            "sections": label.get("sections", []),
            "similarity": pair.get("embedding_similarity"),
        }
        if label["label"] in positive_labels:
            true_positive_items.append(item)
        else:
            false_positive_items.append(item)

    false_negative_items = [
        {
            "label": label["label"],
            "sections": label.get("sections", []),
        }
        for label in positive_gold
        if _docs_label_signature(label) not in matched_signatures
    ]

    counts = {
        "gold_positive_count": len(positive_gold),
        "gold_negative_count": len(scored_labels) - len(positive_gold),
        "surfaced_findings_count": len(section_pairs),
        "labeled_surfaced_count": len(true_positive_items) + len(false_positive_items),
        "true_positives": len(true_positive_items),
        "false_positives": len(false_positive_items),
        "false_negatives": len(false_negative_items),
    }
    metrics = _quality_counts_to_metrics(counts)
    metrics["precision_at_k"] = {}
    metrics["recall_at_k"] = {}
    for k in k_values:
        tp_at_k = sum(1 for item in true_positive_items if item["rank"] <= k)
        fp_at_k = sum(1 for item in false_positive_items if item["rank"] <= k)
        metrics["precision_at_k"][str(k)] = _safe_divide(tp_at_k, tp_at_k + fp_at_k)
        metrics["recall_at_k"][str(k)] = _safe_divide(tp_at_k, len(positive_gold))
    metrics["true_positive_items"] = true_positive_items
    metrics["false_positive_items"] = false_positive_items
    metrics["false_negative_items"] = false_negative_items
    return metrics
