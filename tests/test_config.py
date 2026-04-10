"""Tests for dryscope.config — configuration management."""

from pathlib import Path

import pytest

from dryscope.config import (
    DEFAULT_INCLUDE,
    Settings,
    find_config_file,
    load_settings,
    load_toml,
)


# ── Settings defaults ───────────────────────────────────────────────────


class TestSettingsDefaults:
    def test_default_code_threshold(self):
        s = Settings()
        assert s.code_threshold == 0.90

    def test_default_code_min_lines(self):
        s = Settings()
        assert s.code_min_lines == 6

    def test_default_code_min_tokens(self):
        s = Settings()
        assert s.code_min_tokens == 0

    def test_default_include(self):
        s = Settings()
        assert s.include == list(DEFAULT_INCLUDE)

    def test_default_cache_enabled(self):
        s = Settings()
        assert s.cache_enabled is True

    def test_resolved_cache_path(self):
        s = Settings()
        resolved = s.resolved_cache_path
        assert isinstance(resolved, Path)
        assert "~" not in str(resolved)

    def test_default_model(self):
        s = Settings()
        assert s.model == "claude-haiku-4-5-20251001"

    def test_default_concurrency(self):
        s = Settings()
        assert s.concurrency == 8

    def test_default_cli_strip_api_key(self):
        s = Settings()
        assert s.cli_strip_api_key is True


# ── load_settings ───────────────────────────────────────────────────────


class TestLoadSettings:
    def test_load_with_no_config_file(self, tmp_path):
        # tmp_path has no .dryscope.toml
        s = load_settings(tmp_path)
        assert s.code_threshold == 0.90
        assert s.code_min_lines == 6

    def test_cli_overrides(self, tmp_path):
        s = load_settings(tmp_path, code_threshold=0.80, code_min_lines=10)
        assert s.code_threshold == 0.80
        assert s.code_min_lines == 10

    def test_docs_overrides(self, tmp_path):
        s = load_settings(tmp_path, threshold=0.75, min_words=20)
        assert s.threshold_similarity == 0.75
        assert s.min_content_words == 20


# ── load_toml ───────────────────────────────────────────────────────────


class TestLoadToml:
    def test_nonexistent_file_returns_empty(self, tmp_path):
        result = load_toml(tmp_path / "nonexistent.toml")
        assert result == {}

    def test_valid_toml(self, tmp_path):
        toml_file = tmp_path / ".dryscope.toml"
        toml_file.write_text(
            '[code]\nmin_lines = 10\nthreshold = 0.85\n\n'
            '[docs]\ninclude = ["*.md"]\n'
        )
        data = load_toml(toml_file)
        assert data["code"]["min_lines"] == 10
        assert data["code"]["threshold"] == 0.85
        assert data["docs"]["include"] == ["*.md"]

    def test_toml_applied_to_settings(self, tmp_path):
        toml_file = tmp_path / ".dryscope.toml"
        toml_file.write_text('[code]\nmin_lines = 12\nthreshold = 0.80\n')
        s = load_settings(tmp_path)
        assert s.code_min_lines == 12
        assert s.code_threshold == 0.80


# ── find_config_file ────────────────────────────────────────────────────


class TestFindConfigFile:
    def test_no_config_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = find_config_file(tmp_path)
        assert result is None

    def test_finds_config_in_scan_path(self, tmp_path):
        config = tmp_path / ".dryscope.toml"
        config.write_text('[code]\nmin_lines = 5\n')
        result = find_config_file(tmp_path)
        assert result is not None
        assert result == config

    def test_finds_config_for_file_path(self, tmp_path):
        config = tmp_path / ".dryscope.toml"
        config.write_text('[code]\nmin_lines = 5\n')
        some_file = tmp_path / "foo.py"
        some_file.write_text("pass")
        result = find_config_file(some_file)
        assert result is not None
        assert result == config


# ── Code and docs sections ──────────────────────────────────────────────


class TestSections:
    def test_code_section_from_toml(self, tmp_path):
        toml_file = tmp_path / ".dryscope.toml"
        toml_file.write_text(
            '[code]\nmin_lines = 8\nthreshold = 0.88\nembedding_model = "custom-model"\n'
        )
        s = load_settings(tmp_path)
        assert s.code_min_lines == 8
        assert s.code_threshold == 0.88
        assert s.code_embedding_model == "custom-model"

    def test_docs_section_from_toml(self, tmp_path):
        toml_file = tmp_path / ".dryscope.toml"
        toml_file.write_text(
            '[docs]\ninclude = ["*.rst"]\nthreshold_similarity = 0.75\nmin_content_words = 25\n'
        )
        s = load_settings(tmp_path)
        assert s.include == ["*.rst"]
        assert s.threshold_similarity == 0.75
        assert s.min_content_words == 25

    def test_llm_section_from_toml(self, tmp_path):
        toml_file = tmp_path / ".dryscope.toml"
        toml_file.write_text(
            '[llm]\nmodel = "gpt-4o"\nbackend = "litellm"\nmax_cost = 10.0\nconcurrency = 4\n'
        )
        s = load_settings(tmp_path)
        assert s.model == "gpt-4o"
        assert s.backend == "litellm"
        assert s.max_cost == 10.0
        assert s.concurrency == 4

    def test_llm_cli_options_from_toml(self, tmp_path):
        toml_file = tmp_path / ".dryscope.toml"
        toml_file.write_text(
            '[llm]\nbackend = "cli"\ncli_strip_api_key = false\ncli_permission_mode = "bypassPermissions"\n'
            'cli_dangerously_skip_permissions = true\n'
        )
        s = load_settings(tmp_path)
        assert s.backend == "cli"
        assert s.cli_strip_api_key is False
        assert s.cli_permission_mode == "bypassPermissions"
        assert s.cli_dangerously_skip_permissions is True

    def test_cache_section_from_toml(self, tmp_path):
        toml_file = tmp_path / ".dryscope.toml"
        toml_file.write_text(
            '[cache]\nenabled = false\npath = "/tmp/dryscope.db"\n'
        )
        s = load_settings(tmp_path)
        assert s.cache_enabled is False
        assert s.cache_path == "/tmp/dryscope.db"
