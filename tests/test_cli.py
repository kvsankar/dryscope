"""Tests for dryscope.cli — CLI entry point."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dryscope import __version__
from dryscope.cli import main
from dryscope.code.parser import CodeUnit
from dryscope.code.reporter import Cluster, Tier
from dryscope.docs.models import AnalysisResult, Chunk, OverlapPair

FIXTURES = str(Path(__file__).parent / "fixtures")


@pytest.fixture
def runner():
    return CliRunner()


class TestScanHelp:
    def test_scan_help_exits_0(self, runner):
        result = runner.invoke(main, ["scan", "--help"])
        assert result.exit_code == 0
        assert "Scan PATH" in result.output


class TestProgressiveHelp:
    def test_top_level_help_points_to_topics(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "dryscope help output" in result.output
        assert "dryscope help json" in result.output

    def test_help_lists_topics(self, runner):
        result = runner.invoke(main, ["help"])
        assert result.exit_code == 0
        assert "Help Topics" in result.output
        assert "output" in result.output
        assert "json" in result.output

    def test_help_output_topic(self, runner):
        result = runner.invoke(main, ["help", "output"])
        assert result.exit_code == 0
        assert "Output Formats" in result.output
        assert "markdown" in result.output

    def test_help_option_topic_alias(self, runner):
        result = runner.invoke(main, ["--help", "json"])
        assert result.exit_code == 0
        assert "JSON Output" in result.output
        assert "docs/json-output.md" in result.output

    def test_help_option_command_path(self, runner):
        result = runner.invoke(main, ["--help", "reports", "clean"])
        assert result.exit_code == 0
        assert "Clean old .dryscope/runs" in result.output

    def test_partial_command_help(self, runner):
        result = runner.invoke(main, ["reports", "clean", "--help"])
        assert result.exit_code == 0
        assert "--keep-last" in result.output


class TestScanCode:
    def test_scan_code_produces_output(self, runner):
        result = runner.invoke(
            main,
            ["scan", FIXTURES, "--code", "--embedding-model", "all-MiniLM-L6-v2"],
        )
        # Should complete without error (exit 0)
        assert result.exit_code == 0

    def test_scan_code_json_produces_valid_json(self, runner):
        result = runner.invoke(
            main,
            [
                "scan",
                FIXTURES,
                "--code",
                "-f",
                "json",
                "--embedding-model",
                "all-MiniLM-L6-v2",
            ],
        )
        assert result.exit_code == 0
        # Output mixes stderr messages with JSON; extract the JSON object
        output = result.output
        json_start = output.index("{")
        json_str = output[json_start:]
        data = json.loads(json_str)
        assert "dryscope_version" in data
        assert "findings" in data


class TestScanDocs:
    def test_embedding_model_option_applies_to_docs(self, runner, tmp_path, monkeypatch):
        captured = {}

        def fake_run_docs_scan(**kwargs):
            captured["embedding_model"] = kwargs["settings"].docs_embedding_model

        monkeypatch.setattr("dryscope.cli._run_docs_scan", fake_run_docs_scan)

        result = runner.invoke(
            main,
            [
                "scan",
                str(tmp_path),
                "--docs",
                "--embedding-model",
                "all-MiniLM-L6-v2",
            ],
        )

        assert result.exit_code == 0
        assert captured["embedding_model"] == "all-MiniLM-L6-v2"

    def test_llm_max_doc_pairs_option_applies_to_docs(self, runner, tmp_path, monkeypatch):
        captured = {}

        def fake_run_docs_scan(**kwargs):
            captured["llm_max_doc_pairs"] = kwargs["settings"].docs_llm_max_doc_pairs

        monkeypatch.setattr("dryscope.cli._run_docs_scan", fake_run_docs_scan)

        result = runner.invoke(
            main,
            [
                "scan",
                str(tmp_path),
                "--docs",
                "--stage",
                "docs-report-pack",
                "--llm-max-doc-pairs",
                "25",
            ],
        )

        assert result.exit_code == 0
        assert captured["llm_max_doc_pairs"] == 25

    def test_exclude_option_applies_to_docs(self, runner, tmp_path, monkeypatch):
        captured = {}

        def fake_run_docs_scan(**kwargs):
            captured["exclude"] = kwargs["settings"].exclude

        monkeypatch.setattr("dryscope.cli._run_docs_scan", fake_run_docs_scan)

        result = runner.invoke(
            main,
            [
                "scan",
                str(tmp_path),
                "--docs",
                "-e",
                "drafts/**",
                "-e",
                "*.tmp.md",
            ],
        )

        assert result.exit_code == 0
        assert "node_modules" in captured["exclude"]
        assert "drafts/**" in captured["exclude"]
        assert "*.tmp.md" in captured["exclude"]

    def test_combined_json_emits_single_unified_payload(self, runner, tmp_path, monkeypatch):
        captured = {}

        unit_a = CodeUnit(
            name="parse_a",
            unit_type="function",
            source="def parse_a():\n    return 1",
            file_path="a.py",
            start_line=1,
            end_line=2,
        )
        unit_b = CodeUnit(
            name="parse_b",
            unit_type="function",
            source="def parse_b():\n    return 1",
            file_path="b.py",
            start_line=1,
            end_line=2,
        )
        cluster = Cluster(
            cluster_id=0,
            units=[unit_a, unit_b],
            max_similarity=0.99,
            tier=Tier.NEAR,
            is_cross_file=True,
            total_lines=4,
            files=["a.py", "b.py"],
            actionability=1.0,
        )

        def fake_run_code_scan(**kwargs):
            return [cluster]

        def fake_run_docs_scan(**kwargs):
            captured["emit_output"] = kwargs["emit_output"]
            result = AnalysisResult()
            chunk_a = Chunk("docs/a.md", ["Configuration"], "API_KEY setup", 1, 5)
            chunk_b = Chunk("docs/b.md", ["Configuration"], "API_KEY setup", 8, 12)
            result.overlaps = [OverlapPair(chunk_a, chunk_b, embedding_similarity=0.95)]
            return result

        monkeypatch.setattr("dryscope.cli._run_code_scan", fake_run_code_scan)
        monkeypatch.setattr("dryscope.cli._run_docs_scan", fake_run_docs_scan)

        result = runner.invoke(main, ["scan", str(tmp_path), "--code", "--docs", "-f", "json"])

        assert result.exit_code == 0
        assert captured["emit_output"] is False
        data = json.loads(result.output)
        assert data["summary"]["code"]["total"] == 1
        assert data["summary"]["docs"]["total"] == 1
        assert [finding["mode"] for finding in data["findings"]] == ["code", "docs"]


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


class TestReportsClean:
    def _make_run(self, root: Path, run_id: str) -> Path:
        run_dir = root / ".dryscope" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "report.html").write_text(run_id)
        return run_dir

    def test_reports_clean_defaults_to_dry_run(self, runner, tmp_path):
        self._make_run(tmp_path, "20260401-000000")
        self._make_run(tmp_path, "20260402-000000")
        self._make_run(tmp_path, "20260403-000000")

        result = runner.invoke(main, ["reports", "clean", str(tmp_path), "--keep-last", "1"])

        assert result.exit_code == 0
        assert "Would delete: 2" in result.output
        assert "Dry run only" in result.output
        assert (tmp_path / ".dryscope" / "runs" / "20260401-000000").exists()

    def test_reports_clean_force_deletes_old_runs(self, runner, tmp_path):
        self._make_run(tmp_path, "20260401-000000")
        self._make_run(tmp_path, "20260402-000000")
        newest = self._make_run(tmp_path, "20260403-000000")

        result = runner.invoke(main, ["reports", "clean", str(tmp_path), "--keep-last", "1", "--force"])

        assert result.exit_code == 0
        assert "Deleted: 2" in result.output
        assert "Latest: 20260403-000000" in result.output
        assert newest.exists()
        assert not (tmp_path / ".dryscope" / "runs" / "20260401-000000").exists()

    def test_reports_clean_keep_since(self, runner, tmp_path):
        self._make_run(tmp_path, "20260331-000000")
        self._make_run(tmp_path, "20260401-000000")
        self._make_run(tmp_path, "20260402-000000")

        result = runner.invoke(main, ["reports", "clean", str(tmp_path), "--keep-since", "2026-04-01"])

        assert result.exit_code == 0
        assert "Would delete: 1" in result.output
        assert "20260331-000000" in result.output

    def test_reports_clean_requires_policy(self, runner, tmp_path):
        result = runner.invoke(main, ["reports", "clean", str(tmp_path)])

        assert result.exit_code != 0
        assert "provide --keep-last, --keep-since, or --keep-days" in result.output
