"""Secure loading of provider credentials for Dryscope commands."""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

ENV_FILE_OVERRIDE = "DRYSCOPE_ENV_FILE"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvironmentFileError(RuntimeError):
    """Raised when an explicitly configured environment file is unsafe or invalid."""


def _platform_family() -> str:
    """Return the config-directory family for the current runtime."""
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "unix"


def _xdg_config_home() -> Path | None:
    """Return an explicitly configured absolute XDG root, when available."""
    value = os.environ.get("XDG_CONFIG_HOME")
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else None


def user_env_file() -> Path:
    """Return the platform-conventional per-user Dryscope environment file."""
    override = os.environ.get(ENV_FILE_OVERRIDE)
    if override:
        return Path(override).expanduser()

    xdg_root = _xdg_config_home()
    if xdg_root is not None:
        return xdg_root / "dryscope" / "env"

    platform = _platform_family()
    if platform == "windows":
        appdata = os.environ.get("APPDATA")
        appdata_root = Path(appdata).expanduser() if appdata else None
        root = (
            appdata_root
            if appdata_root is not None and appdata_root.is_absolute()
            else Path.home() / "AppData" / "Roaming"
        )
    elif platform == "macos":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path.home() / ".config"
    return root / "dryscope" / "env"


def _user_env_candidates() -> tuple[Path, ...]:
    """Return user-file candidates in precedence order.

    macOS and Windows retain the original ``~/.config`` location as a
    migration fallback. Explicit DRYSCOPE_ENV_FILE and XDG_CONFIG_HOME values
    remain authoritative and therefore do not fall through to another path.
    """
    primary = user_env_file()
    if os.environ.get(ENV_FILE_OVERRIDE) or _xdg_config_home() is not None:
        return (primary,)

    legacy = Path.home() / ".config" / "dryscope" / "env"
    if _platform_family() in {"macos", "windows"} and legacy != primary:
        return (primary, legacy)
    return (primary,)


def _display_path(path: Path) -> str:
    """Render a user path without exposing an expanded home directory."""
    try:
        return f"~/{path.resolve().relative_to(Path.home().resolve())}"
    except (OSError, ValueError):
        return str(path)


def _validate_private_file(path: Path) -> None:
    """Require a regular file and enforce current-user POSIX permissions."""
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise EnvironmentFileError(
            f"Cannot read Dryscope environment file {_display_path(path)} ({type(exc).__name__})."
        ) from None
    if not stat.S_ISREG(file_stat.st_mode):
        raise EnvironmentFileError(
            f"Dryscope environment path {_display_path(path)} is not a regular file."
        )
    if os.name != "nt" and stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise EnvironmentFileError(
            f"Dryscope environment file {_display_path(path)} is accessible by other users; "
            f"run `chmod 600 {_display_path(path)}`."
        )
    getuid = getattr(os, "getuid", None)
    if getuid is not None and file_stat.st_uid != getuid():
        raise EnvironmentFileError(
            f"Dryscope environment file {_display_path(path)} is not owned by the current user."
        )


def _parse_env_file(path: Path, *, strict: bool) -> dict[str, str]:
    """Parse simple KEY=VALUE lines without evaluating shell syntax."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EnvironmentFileError(
            f"Cannot read Dryscope environment file {_display_path(path)} ({type(exc).__name__})."
        ) from None

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            if strict:
                raise EnvironmentFileError(
                    f"Invalid Dryscope environment entry at {_display_path(path)}:{line_number}; "
                    "expected KEY=VALUE."
                )
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not _ENV_NAME.fullmatch(key):
            if strict:
                raise EnvironmentFileError(
                    f"Invalid environment variable name at {_display_path(path)}:{line_number}."
                )
            continue
        if value[:1] in {"'", '"'}:
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                if strict:
                    raise EnvironmentFileError(
                        f"Unterminated quoted value at {_display_path(path)}:{line_number}."
                    )
                continue
            value = value[1:-1]
        values[key] = value
    return values


def _load_file(path: Path, *, strict: bool, require_private: bool) -> None:
    """Load a single file without overriding existing process variables."""
    if require_private:
        _validate_private_file(path)
    values = _parse_env_file(path, strict=strict)
    for key, value in values.items():
        os.environ.setdefault(key, value)


def _find_project_env(scan_path: Path | None) -> Path | None:
    """Find the nearest project .env, retaining the historical fallback behavior."""
    candidate = scan_path or Path.cwd()
    candidate = candidate if candidate.is_dir() else candidate.parent
    try:
        candidate = candidate.resolve()
    except OSError:
        pass
    while True:
        env_path = candidate / ".env"
        if env_path.is_file():
            return env_path
        parent = candidate.parent
        if parent == candidate:
            return None
        candidate = parent


def load_environment(scan_path: Path | None = None) -> None:
    """Load user and project environment fallbacks for a Dryscope operation.

    Already-set process variables always win. The secure user file is loaded
    next, followed by the historical nearest-project ``.env`` fallback.
    """
    candidates = _user_env_candidates()
    configured = candidates[0]
    selected = next((candidate for candidate in candidates if candidate.exists()), None)
    if selected is not None:
        _load_file(selected, strict=True, require_private=True)
    elif os.environ.get(ENV_FILE_OVERRIDE):
        raise EnvironmentFileError(
            f"Configured Dryscope environment file {_display_path(configured)} does not exist."
        )

    project_env = _find_project_env(scan_path)
    if project_env is not None and project_env != selected:
        _load_file(project_env, strict=False, require_private=False)
