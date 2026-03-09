"""Persistent run storage for dryscope outputs."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


class RunStore:
    """Manages .dryscope/runs/<run_id>/ directories for persistent stage outputs."""

    def __init__(self, project_root: Path, run_id: str | None = None):
        self.project_root = project_root.resolve()
        self.run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
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
        latest = self.project_root / ".dryscope" / "latest"
        # Use relative symlink so the project is portable
        target = os.path.relpath(self.run_dir, latest.parent)
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(target)

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

        runs_dir = project_root / ".dryscope" / "runs"
        if not runs_dir.is_dir():
            return None
        run_dirs = sorted(
            (d for d in runs_dir.iterdir() if d.is_dir()),
            key=lambda d: d.name,
            reverse=True,
        )
        if not run_dirs:
            return None
        return cls(project_root, run_dirs[0].name)
