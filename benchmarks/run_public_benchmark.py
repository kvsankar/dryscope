#!/usr/bin/env python3
"""Run the public dryscope benchmark pack and score any labeled findings."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from benchmarks.benchmark_paths import (
    benchmark_input_id,
    benchmark_input_stem,
    default_repos_dir,
    default_results_dir,
    prepare_output_dir,
)
from dryscope.benchmark import score_labeled_findings

DRYSCOPE_BIN = REPO_ROOT / ".venv" / "bin" / "dryscope"
DEFAULT_MANIFEST = Path(__file__).with_name("public_repos.json")
DEFAULT_LABELS = Path(__file__).with_name("public_labels.json")
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def _git_commit(path: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _git_dirty(path: Path) -> bool | None:
    proc = subprocess.run(
        ["git", "-C", str(path), "status", "--short"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return bool(proc.stdout.strip())


def _benchmark_metadata(repo: dict, repo_path: Path) -> dict:
    repo_name = repo.get("name", repo_path.name)
    repo_commit = _git_commit(repo_path)
    return {
        "dryscope_git_commit": _git_commit(REPO_ROOT),
        "dryscope_git_dirty": _git_dirty(REPO_ROOT),
        "repo_name": repo_name,
        "repo_git_commit": repo_commit,
        "repo_git_dirty": _git_dirty(repo_path),
        "repo_url": repo["url"],
        "repo_path": str(repo_path),
        "benchmark_input_id": benchmark_input_id(repo_name, repo_commit),
        "benchmark_input_stem": benchmark_input_stem(repo_name, repo_commit),
    }


def _run_json(args: list[str]) -> dict:
    proc = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--labels", default=str(DEFAULT_LABELS))
    parser.add_argument("--repos-dir", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument(
        "--group", action="append", default=[], help="Only run selected benchmark groups"
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Embedding model used for benchmark scans",
    )
    parser.add_argument(
        "--structural-only", action="store_true", help="Run Code Match only; skip Code Review"
    )
    parser.add_argument(
        "--verify-max-findings",
        type=int,
        default=None,
        help="Only verify the top N structural findings per repo",
    )
    parser.add_argument("--llm-model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--backend", default="cli", choices=["cli", "litellm"])
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--fresh-clone", action="store_true")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing benchmark output directory"
    )
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    labels = json.loads(Path(args.labels).read_text()).get("labels", [])
    repos_dir = (
        Path(args.repos_dir).expanduser()
        if args.repos_dir
        else default_repos_dir("code", tuple(args.group))
    )
    out_dir = (
        Path(args.out_dir).expanduser()
        if args.out_dir
        else default_results_dir("code", tuple(args.group))
    )
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
                rows.append(
                    {
                        "repo": repo["name"],
                        "group": repo["group"],
                        "clone_error": clone.stderr.strip(),
                    }
                )
                continue

        metadata = _benchmark_metadata(repo, dest)
        row = {"repo": repo["name"], "group": repo["group"], **metadata}
        input_stem = metadata["benchmark_input_stem"]
        try:
            structural = _run_json(
                [
                    str(DRYSCOPE_BIN),
                    "scan",
                    str(dest),
                    "--embedding-model",
                    args.embedding_model,
                    "-f",
                    "json",
                ]
            )
            verified = None
            if not args.structural_only:
                verified_cmd = [
                    str(DRYSCOPE_BIN),
                    "scan",
                    str(dest),
                    "--embedding-model",
                    args.embedding_model,
                    "--verify",
                    "--backend",
                    args.backend,
                    "--llm-model",
                    args.llm_model,
                    "--concurrency",
                    str(args.concurrency),
                    "-f",
                    "json",
                ]
                if args.verify_max_findings is not None:
                    verified_cmd.extend(["--max-findings", str(args.verify_max_findings)])
                verified = _run_json(verified_cmd)
        except RuntimeError as exc:
            row["run_error"] = str(exc)
            rows.append(row)
            continue

        structural["benchmark_metadata"] = metadata
        structural_findings = structural.get("findings", [])
        structural_output = f"{input_stem}_structural.json"
        (out_dir / structural_output).write_text(json.dumps(structural, indent=2))

        verdicts: dict[str, int] = {}
        row.update(
            {
                "structural_findings": len(structural_findings),
                "embedding_model": args.embedding_model,
                "structural_output": structural_output,
            }
        )
        if verified is not None:
            verified["benchmark_metadata"] = metadata
            verified_findings = verified.get("findings", [])
            score = score_labeled_findings(repo["name"], verified_findings, dest, labels)
            verify_output = f"{input_stem}_verify.json"
            (out_dir / verify_output).write_text(json.dumps(verified, indent=2))

            for finding in verified_findings:
                verdict = finding.get("verdict", "")
                verdicts[verdict] = verdicts.get(verdict, 0) + 1

            row.update(
                {
                    "verified_findings": len(verified_findings),
                    "verdicts": verdicts,
                    "label_score": score,
                    "verify_output": verify_output,
                }
            )
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
