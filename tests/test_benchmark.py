"""Tests for public benchmark helpers."""

import importlib.util
import json
from pathlib import Path

from dryscope.benchmark import (
    build_label_index,
    docs_section_signature,
    finding_matches_label_units,
    finding_signature,
    score_code_quality,
    score_docs_section_quality,
    score_labeled_findings,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_finding_signature_preserves_relative_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    finding = {
        "units": [
            {"file": "src/app.py", "name": "main"},
            {"file": "src/app.py", "name": "helper"},
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


def test_finding_matches_label_units_by_path_suffix():
    finding = {
        "units": [
            {"file": "/tmp/clone/src/app.py", "name": "main"},
            {"file": "/tmp/clone/src/app.py", "name": "helper"},
        ]
    }

    assert finding_matches_label_units(
        finding,
        [
            {"path": "src/app.py", "name": "helper"},
            {"path": "src/app.py", "name": "main"},
        ],
    )


def test_score_code_quality_reports_tp_fp_fn():
    findings = [
        {
            "verdict": "review",
            "tier": "exact",
            "units": [
                {"file": "/tmp/clone/src/app.py", "name": "main"},
                {"file": "/tmp/clone/src/app.py", "name": "helper"},
            ],
        },
        {
            "verdict": "review",
            "tier": "exact",
            "units": [
                {"file": "/tmp/clone/src/noise.py", "name": "a"},
                {"file": "/tmp/clone/src/noise.py", "name": "b"},
            ],
        },
    ]
    labels = [
        {
            "repo": "demo",
            "label": "real_refactor_candidate",
            "units": [
                {"path": "src/app.py", "name": "main"},
                {"path": "src/app.py", "name": "helper"},
            ],
        },
        {
            "repo": "demo",
            "label": "not_worth_refactoring",
            "units": [
                {"path": "src/noise.py", "name": "a"},
                {"path": "src/noise.py", "name": "b"},
            ],
        },
        {
            "repo": "demo",
            "label": "real_refactor_candidate",
            "units": [
                {"path": "src/missed.py", "name": "a"},
                {"path": "src/missed.py", "name": "b"},
            ],
        },
    ]

    score = score_code_quality("demo", findings, labels)

    assert score["true_positives"] == 1
    assert score["false_positives"] == 1
    assert score["false_negatives"] == 1
    assert score["labeled_precision"] == 0.5
    assert score["curated_recall"] == 0.5


def test_docs_section_signature_is_order_independent():
    pair = {
        "chunk_a": {"file": "b.md", "line_start": 20},
        "chunk_b": {"file": "a.md", "line_start": 10},
    }

    assert docs_section_signature(pair) == (("a.md", 10), ("b.md", 20))


def test_score_docs_section_quality_reports_tp_fp_fn():
    pairs = [
        {
            "chunk_a": {"file": "a.md", "line_start": 10},
            "chunk_b": {"file": "b.md", "line_start": 20},
            "embedding_similarity": 1.0,
        },
        {
            "chunk_a": {"file": "template-a.md", "line_start": 1},
            "chunk_b": {"file": "template-b.md", "line_start": 1},
            "embedding_similarity": 0.99,
        },
    ]
    labels = [
        {
            "repo": "docs",
            "track": "docs-section-match",
            "label": "useful_section_match",
            "sections": [
                {"path": "b.md", "line_start": 20},
                {"path": "a.md", "line_start": 10},
            ],
        },
        {
            "repo": "docs",
            "track": "docs-section-match",
            "label": "intentional_repetition",
            "sections": [
                {"path": "template-a.md", "line_start": 1},
                {"path": "template-b.md", "line_start": 1},
            ],
        },
        {
            "repo": "docs",
            "track": "docs-section-match",
            "label": "useful_section_match",
            "sections": [
                {"path": "missed-a.md", "line_start": 1},
                {"path": "missed-b.md", "line_start": 1},
            ],
        },
    ]

    score = score_docs_section_quality("docs", pairs, labels)

    assert score["true_positives"] == 1
    assert score["false_positives"] == 1
    assert score["false_negatives"] == 1


def test_public_benchmark_has_ai_generated_duplicate_group():
    manifest = json.loads((REPO_ROOT / "benchmarks" / "public_repos.json").read_text())
    repos = manifest["repos"]
    names = [repo["name"] for repo in repos]

    assert len(names) == len(set(names))
    ai_generated = {
        repo["name"] for repo in repos if repo["group"] == "public-ai-generated-duplicates"
    }
    assert ai_generated == {
        "CLI-Anything-WEB",
        "nanowave",
        "ClaudeCode_generated_app",
        "VibesOS",
    }


def test_public_docs_benchmark_has_default_group():
    manifest = json.loads((REPO_ROOT / "benchmarks" / "public_docs_repos.json").read_text())
    repos = manifest["repos"]
    names = [repo["name"] for repo in repos]

    assert len(names) == len(set(names))
    default_docs = {repo["name"] for repo in repos if repo["group"] == "public-docs-default"}
    assert default_docs == {
        "fastapi-en",
        "astro-en",
        "react-dev",
        "rust-book",
        "prometheus-docs",
    }
    assert all(repo["docs_path"] for repo in repos)


def test_public_docs_labels_use_known_schema():
    labels = json.loads((REPO_ROOT / "benchmarks" / "public_docs_labels.json").read_text())[
        "labels"
    ]

    assert labels
    assert {label["track"] for label in labels} == {"docs-section-match"}
    assert all(len(label["sections"]) == 2 for label in labels)


def test_public_benchmark_pins_local_embedding_model():
    path = REPO_ROOT / "benchmarks" / "run_public_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_public_benchmark", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.DEFAULT_EMBEDDING_MODEL == "all-MiniLM-L6-v2"


def test_benchmark_artifact_paths_are_durable_and_run_specific(monkeypatch, tmp_path):
    from benchmarks import benchmark_paths

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DRYSCOPE_BENCHMARK_ROOT", raising=False)

    root = tmp_path / ".dryscope" / "benchmarks"

    assert benchmark_paths.benchmark_root() == root
    assert benchmark_paths.default_repos_dir("code") == root / "repos" / "code"
    assert (
        benchmark_paths.default_repos_dir("docs", ("public-docs-default",))
        == root / "repos" / "docs-default"
    )
    assert (
        benchmark_paths.default_results_dir("code", ("public-ai-generated-duplicates",)).parent
        == root / "results" / "code-ai-generated-duplicates"
    )
    assert benchmark_paths.default_quality_report_dir().parent == root / "reports" / "quality"


def test_public_benchmark_metadata_records_commits(tmp_path):
    path = REPO_ROOT / "benchmarks" / "run_public_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_public_benchmark", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    metadata = module._benchmark_metadata({"url": "https://example.invalid/repo.git"}, REPO_ROOT)

    assert metadata["dryscope_git_commit"]
    assert metadata["repo_git_commit"]
    assert metadata["benchmark_input_id"] == f"dryscope@{metadata['repo_git_commit']}"
    assert metadata["benchmark_input_stem"].startswith("dryscope@")
    assert "dryscope_git_dirty" in metadata
    assert "repo_git_dirty" in metadata
