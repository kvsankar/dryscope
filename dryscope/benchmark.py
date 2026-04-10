"""Helpers for running and scoring public dryscope benchmarks."""

from __future__ import annotations

from collections import Counter
from pathlib import Path


def finding_signature(finding: dict, repo_root: str | Path) -> tuple[tuple[str, str], ...]:
    """Return a stable signature for a finding using repo-relative unit paths.

    The signature is the sorted tuple of ``(relative_path, unit_name)`` pairs.
    This makes labels resilient to different clone locations under ``/tmp``.
    """
    root = Path(repo_root).resolve()
    items: list[tuple[str, str]] = []
    for unit in finding.get("units", []):
        unit_path = Path(unit["file"]).resolve()
        try:
            rel_path = unit_path.relative_to(root).as_posix()
        except ValueError:
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
