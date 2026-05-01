"""Persistent run storage for dryscope outputs."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RUN_ID_FORMAT = "%Y%m%d-%H%M%S"


@dataclass(frozen=True)
class RunCleanupResult:
    """Summary of a run cleanup operation."""

    kept: list[Path]
    deleted: list[Path]
    would_delete: list[Path]


class RunStore:
    """Manages .dryscope/runs/<run_id>/ directories for persistent stage outputs."""

    def __init__(self, project_root: Path, run_id: str | None = None):
        self.project_root = project_root.resolve()
        self.run_id = run_id or datetime.now().strftime(RUN_ID_FORMAT)
        self.runs_dir = self.project_root / ".dryscope" / "runs"
        self.run_dir = self.runs_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def save_stage(self, filename: str, data: dict) -> Path:
        """Save stage output as JSON. Returns the written path."""
        path = self.run_dir / filename
        path.write_text(json.dumps(data, indent=2))
        return path

    def load_stage(self, filename: str) -> dict | None:
        """Load a previously saved stage output. Returns None if not found."""
        path = self.run_dir / filename
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def stage_exists(self, filename: str) -> bool:
        """Check whether a stage output file exists in this run."""
        return (self.run_dir / filename).exists()

    def update_latest_symlink(self) -> None:
        """Create/update .dryscope/latest symlink pointing to this run."""
        self._point_latest_at(self.project_root, self.run_dir)

    @staticmethod
    def _point_latest_at(project_root: Path, run_dir: Path | None) -> None:
        """Point .dryscope/latest at run_dir, or remove it when no runs remain."""
        project_root = project_root.resolve()
        latest = project_root / ".dryscope" / "latest"
        latest.parent.mkdir(parents=True, exist_ok=True)
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        if run_dir is None:
            return
        # Use relative symlink so the project is portable
        target = os.path.relpath(run_dir, latest.parent)
        latest.symlink_to(target)

    @staticmethod
    def _parse_run_time(run_dir: Path) -> datetime | None:
        """Parse the timestamp encoded in a run directory name."""
        try:
            return datetime.strptime(run_dir.name, RUN_ID_FORMAT)
        except ValueError:
            return None

    @classmethod
    def list_runs(cls, project_root: Path) -> list[Path]:
        """List run directories newest first."""
        runs_dir = project_root.resolve() / ".dryscope" / "runs"
        if not runs_dir.is_dir():
            return []

        def sort_key(path: Path) -> tuple[datetime, str]:
            parsed = cls._parse_run_time(path)
            if parsed is not None:
                return parsed, path.name
            return datetime.fromtimestamp(path.stat().st_mtime), path.name

        return sorted(
            (d for d in runs_dir.iterdir() if d.is_dir()),
            key=sort_key,
            reverse=True,
        )

    @classmethod
    def cleanup_runs(
        cls,
        project_root: Path,
        *,
        keep_last: int | None = None,
        keep_since: datetime | None = None,
        dry_run: bool = True,
    ) -> RunCleanupResult:
        """Delete old run directories while preserving requested reports.

        When both keep_last and keep_since are provided, the keep set is the
        union: a run is preserved if it is among the newest N runs or newer than
        the cutoff date.
        """
        project_root = project_root.resolve()
        runs = cls.list_runs(project_root)
        keep: set[Path] = set()

        if keep_last is not None:
            if keep_last < 0:
                raise ValueError("keep_last must be >= 0")
            keep.update(runs[:keep_last])

        if keep_since is not None:
            for run in runs:
                run_time = cls._parse_run_time(run)
                if run_time is None:
                    # Keep custom-named run directories unless explicitly cleaned by count.
                    keep.add(run)
                elif run_time >= keep_since:
                    keep.add(run)

        if keep_last is None and keep_since is None:
            raise ValueError("provide keep_last or keep_since")

        to_delete = [run for run in runs if run not in keep]
        deleted: list[Path] = []
        if not dry_run:
            for run in to_delete:
                shutil.rmtree(run)
                deleted.append(run)

            remaining = cls.list_runs(project_root)
            cls._point_latest_at(project_root, remaining[0] if remaining else None)

        return RunCleanupResult(
            kept=[run for run in runs if run in keep],
            deleted=deleted,
            would_delete=to_delete if dry_run else [],
        )

    @classmethod
    def find_latest(cls, project_root: Path) -> RunStore | None:
        """Find the most recent run, either via the 'latest' symlink or by directory name."""
        project_root = project_root.resolve()
        latest = project_root / ".dryscope" / "latest"
        if latest.is_symlink():
            target = latest.resolve()
            if target.is_dir():
                run_id = target.name
                return cls(project_root, run_id)

        run_dirs = cls.list_runs(project_root)
        if not run_dirs:
            return None
        return cls(project_root, run_dirs[0].name)
