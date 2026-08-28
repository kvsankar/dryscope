"""Tests for secure provider credential environment loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import dryscope.environment as environment
from dryscope.environment import (
    ENV_FILE_OVERRIDE,
    EnvironmentFileError,
    load_environment,
    user_env_file,
)


def _write_private(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o600)
    return path


def test_linux_user_env_file_uses_xdg_config_home(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(environment, "_platform_family", lambda: "unix")

    assert user_env_file() == tmp_path / "xdg" / "dryscope" / "env"


def test_user_env_file_falls_back_to_home_config(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(environment, "_platform_family", lambda: "unix")

    assert user_env_file() == tmp_path / ".config" / "dryscope" / "env"


def test_wsl_uses_linux_config_convention(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "ExampleLinux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "wsl-config"))
    monkeypatch.setattr(environment, "_platform_family", lambda: "unix")

    assert user_env_file() == tmp_path / "wsl-config" / "dryscope" / "env"


def test_macos_uses_application_support(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(environment, "_platform_family", lambda: "macos")

    assert user_env_file() == tmp_path / "Library" / "Application Support" / "dryscope" / "env"


def test_windows_uses_roaming_appdata(monkeypatch, tmp_path) -> None:
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(environment, "_platform_family", lambda: "windows")

    assert user_env_file() == appdata / "dryscope" / "env"


def test_windows_without_absolute_appdata_uses_home_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", "relative-appdata")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(environment, "_platform_family", lambda: "windows")

    assert user_env_file() == tmp_path / "AppData" / "Roaming" / "dryscope" / "env"


def test_absolute_xdg_config_home_overrides_native_macos_path(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "portable-config"))
    monkeypatch.setattr(environment, "_platform_family", lambda: "macos")

    assert user_env_file() == tmp_path / "portable-config" / "dryscope" / "env"


def test_relative_xdg_config_home_is_ignored(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative-config")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(environment, "_platform_family", lambda: "unix")

    assert user_env_file() == tmp_path / ".config" / "dryscope" / "env"


def test_override_selects_explicit_env_file(monkeypatch, tmp_path) -> None:
    selected = tmp_path / "credentials.env"
    monkeypatch.setenv(ENV_FILE_OVERRIDE, str(selected))

    assert user_env_file() == selected


def test_macos_loads_legacy_home_config_when_native_file_is_absent(
    monkeypatch, tmp_path
) -> None:
    legacy = _write_private(
        tmp_path / ".config" / "dryscope" / "env",
        "OPENAI_API_KEY=legacy-value\n",
    )
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(environment, "_platform_family", lambda: "macos")

    load_environment()

    assert legacy.is_file()
    assert os.environ["OPENAI_API_KEY"] == "legacy-value"


def test_macos_native_file_wins_over_legacy_file(monkeypatch, tmp_path) -> None:
    _write_private(
        tmp_path / "Library" / "Application Support" / "dryscope" / "env",
        "OPENAI_API_KEY=native-value\n",
    )
    _write_private(
        tmp_path / ".config" / "dryscope" / "env",
        "OPENAI_API_KEY=legacy-value\n",
    )
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(environment, "_platform_family", lambda: "macos")

    load_environment()

    assert os.environ["OPENAI_API_KEY"] == "native-value"


def test_windows_loads_roaming_appdata_file(monkeypatch, tmp_path) -> None:
    appdata = tmp_path / "AppData" / "Roaming"
    _write_private(
        appdata / "dryscope" / "env",
        "OPENAI_API_KEY=windows-value\r\n",
    )
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(environment, "_platform_family", lambda: "windows")

    load_environment()

    assert os.environ["OPENAI_API_KEY"] == "windows-value"


def test_user_file_loads_simple_exported_and_quoted_values(monkeypatch, tmp_path) -> None:
    env_file = _write_private(
        tmp_path / "dryscope.env",
        "# provider credentials\n"
        "OPENAI_API_KEY='from-file'\n"
        'export ANTHROPIC_API_KEY="anthropic-file"\n',
    )
    monkeypatch.setenv(ENV_FILE_OVERRIDE, str(env_file))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    load_environment()

    assert os.environ["OPENAI_API_KEY"] == "from-file"
    assert os.environ["ANTHROPIC_API_KEY"] == "anthropic-file"


def test_process_environment_wins_over_user_and_project_files(monkeypatch, tmp_path) -> None:
    user_file = _write_private(
        tmp_path / "dryscope.env",
        "OPENAI_API_KEY=user-file\nANTHROPIC_API_KEY=user-anthropic\n",
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(
        "OPENAI_API_KEY=project-file\nVOYAGE_API_KEY=project-voyage\n"
    )
    monkeypatch.setenv(ENV_FILE_OVERRIDE, str(user_file))
    monkeypatch.setenv("OPENAI_API_KEY", "process-value")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)

    load_environment(project)

    environment = os.environ
    assert environment["OPENAI_API_KEY"] == "process-value"
    assert environment["ANTHROPIC_API_KEY"] == "user-anthropic"
    assert environment["VOYAGE_API_KEY"] == "project-voyage"


@pytest.mark.skipif(os.name == "nt", reason="Windows credentials are protected with ACLs")
def test_insecure_user_file_is_rejected_without_exposing_value(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "dryscope.env"
    env_file.write_text("OPENAI_API_KEY=do-not-print-this\n")
    env_file.chmod(0o644)
    monkeypatch.setenv(ENV_FILE_OVERRIDE, str(env_file))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(EnvironmentFileError) as raised:
        load_environment()

    message = str(raised.value)
    assert "chmod 600" in message
    assert "do-not-print-this" not in message
    assert "OPENAI_API_KEY" not in os.environ


def test_invalid_user_file_is_fail_closed(monkeypatch, tmp_path) -> None:
    env_file = _write_private(
        tmp_path / "dryscope.env",
        "OPENAI_API_KEY=must-not-load\nthis is invalid\n",
    )
    monkeypatch.setenv(ENV_FILE_OVERRIDE, str(env_file))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(EnvironmentFileError, match="expected KEY=VALUE"):
        load_environment()

    assert "OPENAI_API_KEY" not in os.environ


def test_missing_explicit_override_is_actionable(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "missing.env"
    monkeypatch.setenv(ENV_FILE_OVERRIDE, str(missing))

    with pytest.raises(EnvironmentFileError, match="does not exist"):
        load_environment()
