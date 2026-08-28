"""Tests for dryscope.cli — CLI entry point."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from dryscope import __version__
from dryscope.cli import _find_install_source, main
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
        normalized = " ".join(result.output.split())
        assert "API models require provider credentials independently of --backend" in normalized
        assert "does not configure or authenticate embeddings" in normalized


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

    def test_missing_api_embedding_key_is_concise(self, runner, monkeypatch, tmp_path):
        monkeypatch.delenv("DRYSCOPE_ENV_FILE", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)

        result = runner.invoke(
            main,
            ["scan", FIXTURES, "--code", "--embedding-model", "text-embedding-3-small"],
        )

        assert result.exit_code == 1
        assert "Error: Embedding model 'text-embedding-3-small' requires" in result.output
        assert "codex-cli" in result.output
        assert "Traceback" not in result.output

    def test_api_embedding_key_loads_from_xdg_env_without_entering_output(
        self, runner, monkeypatch, tmp_path
    ):
        import sys
        import types

        secret = "test-openai-key-from-xdg"
        config_file = tmp_path / "config" / "dryscope" / "env"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(f"OPENAI_API_KEY={secret}\n")
        config_file.chmod(0o600)
        monkeypatch.delenv("DRYSCOPE_ENV_FILE", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
        observed: dict[str, str] = {}

        class FakeLiteLLM:
            suppress_debug_info = False

            @staticmethod
            def embedding(**kwargs):
                observed["key"] = os.environ["OPENAI_API_KEY"]
                return types.SimpleNamespace(
                    data=[{"embedding": [1.0, 0.0]} for _ in kwargs["input"]]
                )

        monkeypatch.setitem(sys.modules, "litellm", FakeLiteLLM)

        result = runner.invoke(
            main,
            [
                "scan",
                FIXTURES,
                "--code",
                "--embedding-model",
                "text-embedding-3-small",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        assert observed["key"] == secret
        assert secret not in result.output

    def test_local_embedding_loader_failure_is_concise(self, runner, monkeypatch):
        import sys
        import types

        class FakeSentenceTransformer:
            def __init__(self, *_args, **_kwargs):
                raise ValueError("private loader detail")

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
        )

        result = runner.invoke(
            main,
            ["scan", FIXTURES, "--code", "--embedding-model", "all-MiniLM-L6-v2"],
        )

        assert result.exit_code == 1
        assert (
            "Error: Local embedding model 'all-MiniLM-L6-v2' could not be loaded" in result.output
        )
        assert "dryscope[local-embeddings]" in result.output
        assert "private loader detail" not in result.output
        assert "Traceback" not in result.output


class TestScanDocs:
    def test_section_match_uses_openai_key_from_xdg_env(self, runner, tmp_path, monkeypatch):
        import sys
        import types

        secret = "test-docs-openai-key-from-xdg"
        config_file = tmp_path / "config" / "dryscope" / "env"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(f"OPENAI_API_KEY={secret}\n")
        config_file.chmod(0o600)
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / ".dryscope.toml").write_text("[cache]\nenabled = false\n")
        (corpus / "a.md").write_text(
            "# Alpha\n\nShared documentation content for the first API embedding section.\n"
        )
        (corpus / "b.md").write_text(
            "# Beta\n\nShared documentation content for the second API embedding section.\n"
        )
        monkeypatch.delenv("DRYSCOPE_ENV_FILE", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
        observed: dict[str, str] = {}

        class FakeLiteLLM:
            suppress_debug_info = False

            @staticmethod
            def embedding(**kwargs):
                observed["key"] = os.environ["OPENAI_API_KEY"]
                return types.SimpleNamespace(
                    data=[{"embedding": [1.0, 0.0]} for _ in kwargs["input"]]
                )

        monkeypatch.setitem(sys.modules, "litellm", FakeLiteLLM)

        result = runner.invoke(
            main,
            [
                "scan",
                str(corpus),
                "--docs",
                "--stage",
                "docs-section-match",
                "--embedding-model",
                "text-embedding-3-small",
                "--min-words",
                "1",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        assert observed["key"] == secret
        assert secret not in result.output
        report, _end = json.JSONDecoder().raw_decode(result.output[result.output.index("{") :])
        assert report["metadata"]["config"]["embedding_model"] == "text-embedding-3-small"

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


class TestInstallSource:
    def test_ignores_unrelated_cwd_project(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "other-project"\n')
        monkeypatch.chdir(tmp_path)

        source = Path(_find_install_source())

        assert source.name == "dryscope"
        assert (source / "dryscope" / "cli.py").is_file()

    def test_prefers_intended_dryscope_checkout(self, tmp_path, monkeypatch):
        checkout = tmp_path / "dryscope-source"
        (checkout / "dryscope").mkdir(parents=True)
        (checkout / "pyproject.toml").write_text('[project]\nname = "dryscope"\n')
        (checkout / "dryscope" / "cli.py").write_text("# source marker\n")
        monkeypatch.chdir(checkout)

        assert _find_install_source() == str(checkout)

    def test_install_reinstalls_only_dryscope(self, runner, tmp_path, monkeypatch):
        import dryscope.cli as cli

        template = tmp_path / "SKILL.md"
        template.write_text("binary={{DRYSCOPE_BIN}}\n")
        venv = tmp_path / "skill-venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").write_text("")
        destinations = (tmp_path / "claude", tmp_path / "codex")
        commands = []

        monkeypatch.setattr(cli, "SKILL_TEMPLATE", template)
        monkeypatch.setattr(cli, "SHARED_SKILL_VENV", venv)
        monkeypatch.setattr(cli, "SKILL_DESTS", destinations)
        monkeypatch.setattr(cli, "_find_install_source", lambda: "/source/dryscope")
        monkeypatch.setattr(
            cli.subprocess,
            "run",
            lambda command, **_kwargs: commands.append(command) or SimpleNamespace(returncode=0),
        )

        result = runner.invoke(main, ["install"])

        assert result.exit_code == 0
        assert commands == [
            [
                "uv",
                "pip",
                "install",
                "--reinstall-package",
                "dryscope",
                "--python",
                str(venv / "bin" / "python"),
                "/source/dryscope",
            ]
        ]
        assert (
            "binary=" + str(venv / "bin" / "dryscope") in (destinations[1] / "SKILL.md").read_text()
        )


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

        result = runner.invoke(
            main, ["reports", "clean", str(tmp_path), "--keep-last", "1", "--force"]
        )

        assert result.exit_code == 0
        assert "Deleted: 2" in result.output
        assert "Latest: 20260403-000000" in result.output
        assert newest.exists()
        assert not (tmp_path / ".dryscope" / "runs" / "20260401-000000").exists()

    def test_reports_clean_keep_since(self, runner, tmp_path):
        self._make_run(tmp_path, "20260331-000000")
        self._make_run(tmp_path, "20260401-000000")
        self._make_run(tmp_path, "20260402-000000")

        result = runner.invoke(
            main, ["reports", "clean", str(tmp_path), "--keep-since", "2026-04-01"]
        )

        assert result.exit_code == 0
        assert "Would delete: 1" in result.output
        assert "20260331-000000" in result.output

    def test_reports_clean_requires_policy(self, runner, tmp_path):
        result = runner.invoke(main, ["reports", "clean", str(tmp_path)])

        assert result.exit_code != 0
        assert "provide --keep-last, --keep-since, or --keep-days" in result.output
