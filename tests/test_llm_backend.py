"""Tests for dryscope.llm_backend."""

import os
from types import SimpleNamespace

from dryscope import llm_backend


class TestCliCompletion:
    def test_cli_completion_adds_permission_flags(self, monkeypatch):
        captured: dict = {}

        def fake_run(cmd, input, capture_output, text, timeout, env):
            captured["cmd"] = cmd
            captured["env"] = env
            return SimpleNamespace(returncode=0, stdout='{"result":"ok"}', stderr="")

        monkeypatch.setattr(llm_backend.subprocess, "run", fake_run)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")

        result = llm_backend.completion(
            "prompt",
            "claude-haiku-4-5-20251001",
            "cli",
            cli_permission_mode="bypassPermissions",
            cli_dangerously_skip_permissions=True,
        )

        assert result == "ok"
        assert "--permission-mode" in captured["cmd"]
        assert "bypassPermissions" in captured["cmd"]
        assert "--dangerously-skip-permissions" in captured["cmd"]
        assert "ANTHROPIC_API_KEY" not in captured["env"]

    def test_cli_completion_can_keep_api_key(self, monkeypatch):
        captured: dict = {}

        def fake_run(cmd, input, capture_output, text, timeout, env):
            captured["env"] = env
            return SimpleNamespace(returncode=0, stdout='{"result":"ok"}', stderr="")

        monkeypatch.setattr(llm_backend.subprocess, "run", fake_run)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "keep-me")

        result = llm_backend.completion(
            "prompt",
            "claude-haiku-4-5-20251001",
            "cli",
            cli_strip_api_key=False,
        )

        assert result == "ok"
        assert captured["env"]["ANTHROPIC_API_KEY"] == "keep-me"


class TestLiteLLMCompletion:
    def test_litellm_completion_passes_api_key(self, monkeypatch):
        captured: dict = {}

        class FakeLiteLLM:
            @staticmethod
            def completion(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
                )

        monkeypatch.setitem(__import__("sys").modules, "litellm", FakeLiteLLM)

        result = llm_backend.completion(
            "prompt",
            "claude-haiku-4-5-20251001",
            "litellm",
            api_key="secret",
        )

        assert result == "ok"
        assert captured["api_key"] == "secret"
