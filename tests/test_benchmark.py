"""Tests for public benchmark helpers."""

import importlib.util
import json
from pathlib import Path

from dryscope.benchmark import build_label_index, finding_signature, score_labeled_findings


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


def test_public_benchmark_has_ai_generated_duplicate_group():
    manifest = json.loads((REPO_ROOT / "benchmarks" / "public_repos.json").read_text())
    repos = manifest["repos"]
    names = [repo["name"] for repo in repos]

    assert len(names) == len(set(names))
    ai_generated = {repo["name"] for repo in repos if repo["group"] == "public-ai-generated-duplicates"}
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


def test_public_benchmark_pins_local_embedding_model():
    path = REPO_ROOT / "benchmarks" / "run_public_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_public_benchmark", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.DEFAULT_EMBEDDING_MODEL == "all-MiniLM-L6-v2"


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
    assert "dryscope_git_dirty" in metadata
    assert "repo_git_dirty" in metadata
