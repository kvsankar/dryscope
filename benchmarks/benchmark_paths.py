"""Shared filesystem defaults for benchmark artifacts."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
import re


def benchmark_root() -> Path:
    override = os.environ.get("DRYSCOPE_BENCHMARK_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".dryscope" / "benchmarks"


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.@+-]+", "-", value).strip("-") or "unnamed"


def short_commit(commit: str | None) -> str:
    return commit[:12] if commit else "unknown"


def benchmark_input_id(repo_name: str, commit: str | None) -> str:
    return f"{repo_name}@{commit or 'unknown'}"


def benchmark_input_stem(repo_name: str, commit: str | None) -> str:
    return safe_name(f"{repo_name}@{short_commit(commit)}")


def track_name(kind: str, groups: list[str] | tuple[str, ...] = ()) -> str:
    if not groups:
        return safe_name(kind)

    cleaned = [_clean_group(group) for group in groups]
    if kind == "docs" and len(cleaned) == 1 and cleaned[0].startswith("docs-"):
        return safe_name(cleaned[0])
    return safe_name(f"{kind}-{'-'.join(cleaned)}")


def _clean_group(group: str) -> str:
    if group.startswith("public-docs-"):
        return f"docs-{group.removeprefix('public-docs-')}"
    if group.startswith("public-"):
        return group.removeprefix("public-")
    return group


def new_run_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%z")


def default_repos_dir(kind: str, groups: list[str] | tuple[str, ...] = ()) -> Path:
    return benchmark_root() / "repos" / track_name(kind, groups)


def results_parent(kind: str, groups: list[str] | tuple[str, ...] = ()) -> Path:
    return benchmark_root() / "results" / track_name(kind, groups)


def default_results_dir(kind: str, groups: list[str] | tuple[str, ...] = ()) -> Path:
    return results_parent(kind, groups) / new_run_id()


def latest_results_dir(kind: str, groups: list[str] | tuple[str, ...] = ()) -> Path:
    parent = results_parent(kind, groups)
    if not parent.exists():
        return parent / "latest"
    candidates = [path for path in parent.iterdir() if path.is_dir()]
    if not candidates:
        return parent / "latest"
    return max(candidates, key=lambda path: path.stat().st_mtime)


def default_quality_report_dir() -> Path:
    return benchmark_root() / "reports" / "quality" / new_run_id()


def prepare_output_dir(path: Path, *, overwrite: bool) -> Path:
    path = path.expanduser()
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise SystemExit(
                f"Output directory is not empty: {path}\n"
                "Choose a new --out-dir, or pass --overwrite to replace this benchmark output."
            )
        _clear_output_dir(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clear_output_dir(path: Path) -> None:
    root = benchmark_root().resolve()
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise SystemExit(
            f"Refusing to clear output directory outside DRYSCOPE_BENCHMARK_ROOT: {path}"
        )
    shutil.rmtree(path)
