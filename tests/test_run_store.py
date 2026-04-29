"""Tests for dryscope run storage cleanup."""

from datetime import datetime
from pathlib import Path

from dryscope.run_store import RunStore


def _make_run(project_root: Path, run_id: str) -> Path:
    run_dir = project_root / ".dryscope" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.html").write_text(run_id)
    return run_dir


def test_cleanup_runs_keep_last_deletes_older_and_updates_latest(tmp_path: Path) -> None:
    _make_run(tmp_path, "20260401-000000")
    _make_run(tmp_path, "20260402-000000")
    newest = _make_run(tmp_path, "20260403-000000")
    RunStore(tmp_path, "20260401-000000").update_latest_symlink()

    result = RunStore.cleanup_runs(tmp_path, keep_last=1, dry_run=False)

    assert [path.name for path in result.deleted] == ["20260402-000000", "20260401-000000"]
    assert newest.exists()
    assert not (tmp_path / ".dryscope" / "runs" / "20260401-000000").exists()
    assert (tmp_path / ".dryscope" / "latest").resolve() == newest


def test_cleanup_runs_keep_since_keeps_cutoff_and_newer(tmp_path: Path) -> None:
    old = _make_run(tmp_path, "20260331-235959")
    cutoff = _make_run(tmp_path, "20260401-000000")
    newer = _make_run(tmp_path, "20260415-000000")

    result = RunStore.cleanup_runs(
        tmp_path,
        keep_since=datetime(2026, 4, 1),
        dry_run=True,
    )

    assert [path.name for path in result.kept] == [newer.name, cutoff.name]
    assert [path.name for path in result.would_delete] == [old.name]
    assert old.exists()


def test_cleanup_runs_combines_keep_last_and_keep_since_as_union(tmp_path: Path) -> None:
    very_old = _make_run(tmp_path, "20260101-000000")
    old = _make_run(tmp_path, "20260201-000000")
    recent = _make_run(tmp_path, "20260401-000000")

    result = RunStore.cleanup_runs(
        tmp_path,
        keep_last=1,
        keep_since=datetime(2026, 2, 1),
        dry_run=True,
    )

    assert [path.name for path in result.kept] == [recent.name, old.name]
    assert [path.name for path in result.would_delete] == [very_old.name]
