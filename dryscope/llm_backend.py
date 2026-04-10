"""LLM backend abstraction: litellm, CLI (claude -p), or Ollama."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request


def completion(
    prompt: str,
    model: str,
    backend: str,
    *,
    api_key: str | None = None,
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> str:
    """Get a completion from the LLM.

    Args:
        prompt: The user message to send.
        model: Model name (used by litellm backend, ignored by cli).
        backend: "litellm" or "cli".
        api_key: Optional provider API key for litellm.
        ollama_host: Optional Ollama base URL. Defaults to ``OLLAMA_HOST`` or
            ``http://localhost:11434``.
        cli_strip_api_key: Whether to remove ANTHROPIC_API_KEY for Claude CLI.
        cli_permission_mode: Optional Claude CLI permission mode.
        cli_dangerously_skip_permissions: Whether to pass Claude CLI bypass flag.

    Returns:
        The assistant's response text.
    """
    if backend == "cli":
        return _cli_completion(
            prompt,
            model,
            cli_strip_api_key=cli_strip_api_key,
            cli_permission_mode=cli_permission_mode,
            cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
        )
    if backend == "ollama":
        return _ollama_completion(prompt, model, ollama_host=ollama_host)
    return _litellm_completion(prompt, model, api_key=api_key)


def _litellm_completion(prompt: str, model: str, api_key: str | None = None) -> str:
    """Call LLM via litellm."""
    import litellm

    kwargs: dict = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    if api_key:
        kwargs["api_key"] = api_key
    response = litellm.completion(**kwargs)
    return response.choices[0].message.content


def _cli_completion(
    prompt: str,
    model: str | None = None,
    *,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> str:
    """Call LLM via ``claude -p --output-format json``.

    Inherits the user's OAuth / API key configuration from Claude Code.
    If model is provided, passes --model to claude CLI.
    """
    cmd = ["claude", "-p", "--output-format", "json"]
    if model:
        cmd.extend(["--model", model])
    if cli_permission_mode:
        cmd.extend(["--permission-mode", cli_permission_mode])
    if cli_dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    env = os.environ.copy()
    if cli_strip_api_key:
        env.pop("ANTHROPIC_API_KEY", None)
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"claude CLI returned non-JSON output: {result.stdout[:200]!r}"
        ) from exc
    return data.get("result") or data.get("content", result.stdout)


def _ollama_completion(
    prompt: str,
    model: str,
    *,
    ollama_host: str | None = None,
) -> str:
    """Call LLM via the local Ollama chat API."""
    host = (ollama_host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    url = f"{host}/api/chat"
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ollama API failed ({exc.code}): {detail[:300]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"ollama API unavailable at {host}: {exc.reason}"
        ) from exc

    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    raise RuntimeError(f"ollama API returned unexpected response: {payload!r}")
