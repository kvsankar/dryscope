"""Tests for public benchmark helpers."""

from pathlib import Path

from dryscope.benchmark import build_label_index, finding_signature, score_labeled_findings


def test_finding_signature_uses_repo_relative_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sub = repo / "src"
    sub.mkdir()
    target = sub / "app.py"
    target.write_text("pass\n")

    finding = {
        "units": [
            {"file": str(target), "name": "main"},
            {"file": str(target), "name": "helper"},
        ]
    }

    assert finding_signature(finding, repo) == (
        ("src/app.py", "helper"),
        ("src/app.py", "main"),
    )


def test_score_labeled_findings_matches_public_labels(tmp_path):
    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    target = src / "app.py"
    target.write_text("pass\n")

    findings = [
        {
            "verdict": "refactor",
            "tier": "exact",
            "units": [
                {"file": str(target), "name": "main"},
                {"file": str(target), "name": "helper"},
            ],
        }
    ]
    labels = [
        {
            "repo": "demo",
            "label": "real_refactor_candidate",
            "units": [
                {"path": "src/app.py", "name": "helper"},
                {"path": "src/app.py", "name": "main"},
            ],
        }
    ]

    score = score_labeled_findings("demo", findings, repo, labels)

    assert score["matched_count"] == 1
    assert score["matched_labels"] == {"real_refactor_candidate": 1}
    assert score["matched_findings"][0]["verdict"] == "refactor"


def test_build_label_index_normalizes_signature_order():
    labels = [
        {
            "repo": "demo",
            "label": "uncertain",
            "units": [
                {"path": "b.py", "name": "b"},
                {"path": "a.py", "name": "a"},
            ],
        }
    ]
    index = build_label_index(labels)
    assert ("demo", (("a.py", "a"), ("b.py", "b"))) in index
