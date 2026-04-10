"""Tests for dryscope.llm_backend."""

import os
import json
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


class TestOllamaCompletion:
    def test_ollama_completion_posts_to_local_api(self, monkeypatch):
        captured: dict = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"message": {"content": "ok"}}).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(llm_backend.urllib.request, "urlopen", fake_urlopen)

        result = llm_backend.completion(
            "prompt",
            "qwen2.5:3b",
            "ollama",
            ollama_host="http://localhost:11434",
        )

        assert result == "ok"
        assert captured["url"] == "http://localhost:11434/api/chat"
        assert captured["body"]["model"] == "qwen2.5:3b"
        assert captured["body"]["messages"][0]["content"] == "prompt"


class TestCodexCliCompletion:
    def test_codex_cli_completion_reads_output_file(self, monkeypatch, tmp_path):
        captured: dict = {}
        out_file = tmp_path / "out.txt"

        class FakeTmpFile:
            name = str(out_file)

            def __enter__(self):
                out_file.write_text("")
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_named_tempfile(mode="w+", delete=False):
            return FakeTmpFile()

        def fake_run(cmd, input, capture_output, text, timeout):
            captured["cmd"] = cmd
            captured["input"] = input
            out_file.write_text("ok")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(llm_backend.tempfile, "NamedTemporaryFile", fake_named_tempfile)
        monkeypatch.setattr(llm_backend.subprocess, "run", fake_run)

        result = llm_backend.completion(
            "prompt",
            "gpt-5.4",
            "codex-cli",
        )

        assert result == "ok"
        assert captured["cmd"][:4] == ["codex", "exec", "--skip-git-repo-check", "--sandbox"]
        assert "read-only" in captured["cmd"]
        assert "--output-last-message" in captured["cmd"]
        assert "-m" in captured["cmd"]
        assert "gpt-5.4" in captured["cmd"]
        assert captured["input"] == "prompt"
