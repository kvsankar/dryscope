"""Tests for dryscope.cli — CLI entry point."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dryscope import __version__
from dryscope.cli import main

FIXTURES = str(Path(__file__).parent / "fixtures")


@pytest.fixture
def runner():
    return CliRunner()


class TestScanHelp:
    def test_scan_help_exits_0(self, runner):
        result = runner.invoke(main, ["scan", "--help"])
        assert result.exit_code == 0
        assert "Scan PATH" in result.output


class TestScanCode:
    def test_scan_code_produces_output(self, runner):
        result = runner.invoke(main, ["scan", FIXTURES, "--code"])
        # Should complete without error (exit 0)
        assert result.exit_code == 0

    def test_scan_code_json_produces_valid_json(self, runner):
        result = runner.invoke(main, ["scan", FIXTURES, "--code", "-f", "json"])
        assert result.exit_code == 0
        # Output mixes stderr messages with JSON; extract the JSON object
        output = result.output
        json_start = output.index("{")
        json_str = output[json_start:]
        data = json.loads(json_str)
        assert "dryscope_version" in data
        assert "findings" in data


class TestScanErrors:
    def test_format_markdown_errors_for_code(self, runner):
        result = runner.invoke(main, ["scan", FIXTURES, "--code", "-f", "markdown"])
        assert result.exit_code != 0

    def test_threshold_out_of_range(self, runner):
        result = runner.invoke(main, ["scan", FIXTURES, "--code", "-t", "1.5"])
        assert result.exit_code != 0


class TestVersion:
    def test_version_shows_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output
