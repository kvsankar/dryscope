"""Project profile detection and exclusion rules.

Each profile detector checks for project markers (dependency files, config files,
directory structure) and returns a Profile with appropriate exclusion rules, or
None if the project doesn't match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Profile:
    """Exclusion rules for a detected project type."""

    name: str
    exclude_dirs: set[str] = field(default_factory=set)
    exclude_patterns: list[str] = field(default_factory=list)
    exclude_types: set[str] = field(default_factory=set)


# -- Detector functions --------------------------------------------------------
# Each returns a Profile if the project matches, None otherwise.
# Detectors receive the scan target path.


def _read_deps(path: Path) -> str:
    """Read combined dependency text from common dependency files."""
    texts: list[str] = []
    for name in ("requirements.txt", "requirements/*.txt", "Pipfile", "pyproject.toml", "setup.cfg"):
        for f in path.glob(name):
            try:
                texts.append(f.read_text(errors="ignore").lower())
            except OSError:
                pass
    return "\n".join(texts)


def detect_django(path: Path) -> Profile | None:
    """Detect Django projects."""
    has_manage_py = (path / "manage.py").exists()
    deps = _read_deps(path)
    has_django_dep = "django" in deps

    if not (has_manage_py or has_django_dep):
        return None

    return Profile(
        name="django",
        exclude_dirs={"migrations"},
        exclude_patterns=[],
        exclude_types={"TextChoices", "IntegerChoices"},
    )


def detect_flask(path: Path) -> Profile | None:
    """Detect Flask projects."""
    deps = _read_deps(path)
    if "flask" not in deps:
        return None

    return Profile(
        name="flask",
        exclude_dirs=set(),
        exclude_patterns=[],
        exclude_types=set(),
    )


def detect_pytest(path: Path) -> Profile | None:
    """Detect projects using pytest with factories."""
    deps = _read_deps(path)
    if "factory-boy" in deps or "factory_boy" in deps:
        return Profile(
            name="pytest-factories",
            exclude_dirs=set(),
            exclude_patterns=[],
            exclude_types={"DjangoModelFactory", "Factory"},
        )
    return None


# Registry of all detectors, in priority order
DETECTORS = [
    detect_django,
    detect_flask,
    detect_pytest,
]


def detect_profiles(path: str | Path) -> list[Profile]:
    """Run all detectors against a path and return matching profiles."""
    path = Path(path).resolve()

    # Walk up to find the project root (where dependency files live)
    project_root = path
    for candidate in [path, *path.parents]:
        if any((candidate / f).exists() for f in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "manage.py")):
            project_root = candidate
            break

    profiles: list[Profile] = []
    for detector in DETECTORS:
        profile = detector(project_root)
        if profile is not None:
            profiles.append(profile)

    return profiles


def merge_profiles(
    profiles: list[Profile],
    user_exclude_patterns: list[str] | None = None,
    user_exclude_types: set[str] | None = None,
) -> tuple[list[str] | None, set[str] | None, set[str]]:
    """Merge detected profiles with user-provided exclusions.

    Returns (exclude_patterns, exclude_types, extra_exclude_dirs).
    """
    extra_dirs: set[str] = set()
    patterns: list[str] = list(user_exclude_patterns) if user_exclude_patterns else []
    types: set[str] = set(user_exclude_types) if user_exclude_types else set()

    for p in profiles:
        extra_dirs |= p.exclude_dirs
        patterns.extend(p.exclude_patterns)
        types |= p.exclude_types

    return (
        patterns if patterns else None,
        types if types else None,
        extra_dirs,
    )
