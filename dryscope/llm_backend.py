"""LLM backend abstraction: litellm or CLI (claude -p)."""

from __future__ import annotations

import json
import os
import subprocess


def completion(
    prompt: str,
    model: str,
    backend: str,
    *,
    api_key: str | None = None,
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
