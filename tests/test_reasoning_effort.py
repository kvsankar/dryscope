"""Tests for the LLM reasoning-effort setting."""

import sys
from types import SimpleNamespace

import pytest

from dryscope import llm_backend
from dryscope.cache import Cache
from dryscope.config import load_settings
from dryscope.docs import coding


def _fake_codex_run(captured: dict):
    def fake_run(cmd, input, capture_output, text, timeout):
        captured["cmd"] = cmd
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w", encoding="utf-8") as handle:
            handle.write("ok")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


class TestCodexReasoningEffort:
    def test_passes_effort_as_codex_config(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(llm_backend.subprocess, "run", _fake_codex_run(captured))
        result = llm_backend.completion("prompt", "gpt-luna", "codex-cli", reasoning_effort="high")
        assert result == "ok"
        cmd = captured["cmd"]
        assert cmd[cmd.index("-c") + 1] == 'model_reasoning_effort="high"'
        assert cmd[-1] == "-"

    def test_omits_effort_when_unset(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(llm_backend.subprocess, "run", _fake_codex_run(captured))
        llm_backend.completion("prompt", "gpt-luna", "codex-cli")
        assert not any("model_reasoning_effort" in part for part in captured["cmd"])

    def test_resolves_the_codex_launcher_on_windows(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(llm_backend.subprocess, "run", _fake_codex_run(captured))
        monkeypatch.setattr(llm_backend, "_WINDOWS", True)
        monkeypatch.setattr(llm_backend.shutil, "which", lambda name: r"C:\tools\codex.cmd")
        llm_backend.completion("prompt", "gpt-luna", "codex-cli")
        assert captured["cmd"][0] == r"C:\tools\codex.cmd"


class TestOtherBackendsAndEffort:
    def test_litellm_passes_effort(self, monkeypatch):
        captured: dict = {}

        class FakeLiteLLM:
            @staticmethod
            def completion(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
                )

        monkeypatch.setitem(sys.modules, "litellm", FakeLiteLLM)
        llm_backend.completion("prompt", "openai/gpt-luna", "litellm", reasoning_effort="medium")
        assert captured["reasoning_effort"] == "medium"

    @pytest.mark.parametrize("backend", ["cli", "ollama"])
    def test_backends_without_effort_refuse_it(self, backend):
        with pytest.raises(ValueError, match="reasoning effort"):
            llm_backend.completion("prompt", "some-model", backend, reasoning_effort="high")

    def test_model_identity_includes_effort(self):
        assert llm_backend.model_identity("codex-cli", "gpt-luna") == "gpt-luna"
        assert llm_backend.model_identity("codex-cli", "gpt-luna", "high") == "gpt-luna|effort=high"
        assert (
            llm_backend.model_identity("codex-cli", None, "low")
            == "codex-cli:configured-default|effort=low"
        )


class TestReasoningEffortSettings:
    def test_cli_override(self, tmp_path):
        settings = load_settings(tmp_path, backend="codex-cli", reasoning_effort="high")
        assert settings.reasoning_effort == "high"
        assert settings.llm_model_identity == "codex-cli:configured-default|effort=high"

    def test_toml_value(self, tmp_path):
        (tmp_path / ".dryscope.toml").write_text(
            '[llm]\nbackend = "codex-cli"\nreasoning_effort = "low"\n', encoding="utf-8"
        )
        assert load_settings(tmp_path).reasoning_effort == "low"

    def test_default_is_unset(self, tmp_path):
        assert load_settings(tmp_path).reasoning_effort is None

    def test_invalid_value_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="reasoning_effort"):
            load_settings(tmp_path, backend="codex-cli", reasoning_effort="extreme")

    def test_backend_without_effort_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="reasoning_effort"):
            load_settings(tmp_path, backend="cli", reasoning_effort="high")


class TestCachedCallsCarryEffort:
    def test_effort_reaches_completion_and_separates_cache_entries(self, monkeypatch, tmp_path):
        seen: list = []

        def fake_completion(prompt, model, backend, **kwargs):
            seen.append(kwargs.get("reasoning_effort"))
            return f"answer-{kwargs.get('reasoning_effort')}"

        monkeypatch.setattr(coding, "completion", fake_completion)
        with Cache(tmp_path / "cache.db") as cache:
            low = coding.call_llm_cached(
                "gpt-luna", "p", cache, "k", "v1", backend="codex-cli", reasoning_effort="low"
            )
            high = coding.call_llm_cached(
                "gpt-luna", "p", cache, "k", "v1", backend="codex-cli", reasoning_effort="high"
            )
            low_again = coding.call_llm_cached(
                "gpt-luna", "p", cache, "k", "v1", backend="codex-cli", reasoning_effort="low"
            )
        assert (low, high, low_again) == ("answer-low", "answer-high", "answer-low")
        assert seen == ["low", "high"]
