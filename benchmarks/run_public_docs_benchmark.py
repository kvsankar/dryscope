#!/usr/bin/env python3
"""Run the public docs benchmark pack and save report artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from benchmarks.benchmark_paths import default_repos_dir, default_results_dir, prepare_output_dir
from benchmarks.run_public_benchmark import _benchmark_metadata, _git_commit, _git_dirty

DRYSCOPE_BIN = REPO_ROOT / ".venv" / "bin" / "dryscope"
DEFAULT_MANIFEST = Path(__file__).with_name("public_docs_repos.json")
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_STAGE = "docs-report-pack"


def _run_json(args: list[str]) -> dict:
    proc = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout)


def _copy_report_artifacts(repo_root: Path, artifact_dir: Path, metadata: dict) -> None:
    latest = repo_root / ".dryscope" / "latest"
    if not latest.exists():
        return
    run_dir = latest.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for path in run_dir.iterdir():
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md", ".html"}:
            target = artifact_dir / path.name
            shutil.copy2(path, target)
            if target.name == "report.json":
                report = json.loads(target.read_text())
                report["benchmark_metadata"] = metadata
                target.write_text(json.dumps(report, indent=2))
    (artifact_dir / "benchmark_metadata.json").write_text(json.dumps(metadata, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--repos-dir", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--group", action="append", default=[], help="Only run selected benchmark groups")
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Embedding model used for docs scans",
    )
    parser.add_argument(
        "--stage",
        default=DEFAULT_STAGE,
        choices=["docs-section-match", "docs-report-pack"],
        help="Docs track stage to run",
    )
    parser.add_argument("--llm-model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--backend", default="cli", choices=["cli", "codex-cli", "litellm", "ollama"])
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--llm-max-doc-pairs", type=int, default=250)
    parser.add_argument("--fresh-clone", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing benchmark output directory")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    repos_dir = (
        Path(args.repos_dir).expanduser()
        if args.repos_dir
        else default_repos_dir("docs", tuple(args.group))
    )
    out_dir = (
        Path(args.out_dir).expanduser()
        if args.out_dir
        else default_results_dir("docs", tuple(args.group))
    )
    artifact_root = out_dir / "artifacts"
    repos_dir.mkdir(parents=True, exist_ok=True)
    out_dir = prepare_output_dir(out_dir, overwrite=args.overwrite)

    rows: list[dict] = []
    for repo in manifest["repos"]:
        if args.group and repo["group"] not in args.group:
            continue

        dest = repos_dir / repo["name"]
        if args.fresh_clone and dest.exists():
            shutil.rmtree(dest)
        if not dest.exists():
            clone = subprocess.run(
                ["git", "clone", "--depth", "1", repo["url"], str(dest)],
                capture_output=True,
                text=True,
            )
            if clone.returncode != 0:
                rows.append({
                    "repo": repo["name"],
                    "group": repo["group"],
                    "clone_error": clone.stderr.strip(),
                    "dryscope_git_commit": _git_commit(REPO_ROOT),
                    "dryscope_git_dirty": _git_dirty(REPO_ROOT),
                    "repo_url": repo["url"],
                })
                continue

        metadata = _benchmark_metadata(repo, dest)
        input_stem = metadata["benchmark_input_stem"]
        scan_path = dest / repo["docs_path"]
        row = {
            "repo": repo["name"],
            "group": repo["group"],
            "docs_path": repo["docs_path"],
            "stage": args.stage,
            "embedding_model": args.embedding_model,
            **metadata,
        }
        if not scan_path.exists():
            row["run_error"] = f"docs_path not found: {repo['docs_path']}"
            rows.append(row)
            continue

        cmd = [
            str(DRYSCOPE_BIN), "scan", str(scan_path),
            "--docs",
            "--stage", args.stage,
            "--embedding-model", args.embedding_model,
            "--backend", args.backend,
            "--llm-model", args.llm_model,
            "--concurrency", str(args.concurrency),
            "--llm-max-doc-pairs", str(args.llm_max_doc_pairs),
            "-f", "json",
        ]
        try:
            report = _run_json(cmd)
        except RuntimeError as exc:
            row["run_error"] = str(exc)
            rows.append(row)
            continue

        report["benchmark_metadata"] = metadata
        summary = report.get("summary", {})
        report_output = f"{input_stem}.json"
        artifact_dir = artifact_root / input_stem
        row.update({
            "documents_scanned": summary.get("documents_scanned"),
            "chunks_analyzed": summary.get("chunks_analyzed"),
            "matched_section_pairs_found": summary.get("matched_section_pairs_found"),
            "section_match_recommendations_found": summary.get("section_match_recommendations_found"),
            "report_output": report_output,
            "artifact_dir": str(Path("artifacts") / input_stem),
        })
        (out_dir / report_output).write_text(json.dumps(report, indent=2))
        _copy_report_artifacts(dest, artifact_dir, metadata)
        rows.append(row)

    summary = {
        "benchmark_metadata": {
            "dryscope_git_commit": _git_commit(REPO_ROOT),
            "dryscope_git_dirty": _git_dirty(REPO_ROOT),
            "repos_dir": str(repos_dir),
            "results_dir": str(out_dir),
            "run_id": out_dir.name,
        },
        "repos": rows,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
