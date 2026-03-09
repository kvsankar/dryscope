"""LLM backend abstraction: litellm or CLI (claude -p)."""

from __future__ import annotations

import json
import subprocess


def completion(prompt: str, model: str, backend: str) -> str:
    """Get a completion from the LLM.

    Args:
        prompt: The user message to send.
        model: Model name (used by litellm backend, ignored by cli).
        backend: "litellm" or "cli".

    Returns:
        The assistant's response text.
    """
    if backend == "cli":
        return _cli_completion(prompt, model)
    return _litellm_completion(prompt, model)


def _litellm_completion(prompt: str, model: str) -> str:
    """Call LLM via litellm."""
    import litellm

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def _cli_completion(prompt: str, model: str | None = None) -> str:
    """Call LLM via ``claude -p --output-format json``.

    Inherits the user's OAuth / API key configuration from Claude Code.
    If model is provided, passes --model to claude CLI.
    """
    cmd = ["claude", "-p", "--output-format", "json"]
    if model:
        cmd.extend(["--model", model])
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
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
