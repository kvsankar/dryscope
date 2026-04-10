"""LLM-based verification of duplicate clusters.

Uses litellm for provider-agnostic LLM calls. Supports any model that litellm
supports (Anthropic, OpenAI, Azure, Bedrock, Ollama, etc.). Auth is handled
via environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) or a .env
file in the current directory.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dryscope.code.reporter import Cluster
from dryscope.llm_backend import completion as llm_completion


def _load_dotenv() -> None:
    """Load .env file, searching current dir then upward to find one."""
    env_file = None
    candidate = Path.cwd()
    while True:
        if (candidate / ".env").exists():
            env_file = candidate / ".env"
            break
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent

    if env_file is None:
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value

logger = logging.getLogger(__name__)

VERDICT_REFACTOR = "refactor"
VERDICT_REVIEW = "review"
VERDICT_NOISE = "noise"

SYSTEM_PROMPT = """\
You are a code review assistant. You will be shown a cluster of code units \
that a duplicate detection tool flagged as similar. Your job is to classify \
whether this cluster represents genuine duplication worth refactoring.

Respond with a JSON object containing exactly two keys:
- "verdict": one of "refactor", "review", or "noise"
- "reason": a one-sentence explanation

Definitions:
- "refactor": These units contain genuinely duplicated logic that should be \
extracted into a shared function/class/mixin. The similarity is in the actual \
behavior, not just the structural shape.
- "review": These units might share refactorable logic, but it's ambiguous. \
A human should look at them.
- "noise": These units are only similar because they follow the same \
framework pattern, language convention, or are structurally trivial. \
Examples: Django serializers with similar Meta classes, factory-boy factories, \
exception subclasses, tiny test classes with one method, small config classes. \
This is NOT duplication worth refactoring.

Be strict. If the similarity is mainly due to framework boilerplate or \
structural shape rather than shared business logic, classify as "noise".

Bias toward "noise" when the duplicated code is small, low-payoff, or mainly \
would save a few lines while adding indirection.
Bias toward "noise" or "review" for same-file helper pairs unless the \
duplicated logic is substantial and clearly reduces maintenance risk.
Bias toward "noise" for compatibility layers, adapter variants, or mirrored \
implementations that are intentionally separate.
Bias toward "noise" when public API helpers look similar but intentionally \
encode different validation rules, escaping rules, or domain semantics.

Intentional duplication in examples, demos, benchmarks, mirrored fixtures, or \
parallel framework/router variants is usually "noise" unless it exposes a \
substantive shared runtime helper that the project would realistically want to \
extract."""

USER_TEMPLATE = """\
Cluster {cluster_id} — {unit_count} code units, similarity={similarity:.4f}

{context_text}

{units_text}

Classify this cluster. Respond ONLY with the JSON object."""


_EXAMPLE_MARKERS = {"example", "examples", "demo", "demos", "sample", "samples"}
_TEST_MARKERS = {"test", "tests", "spec", "specs", "__tests__"}
_BENCH_MARKERS = {"bench", "benches", "benchmark", "benchmarks"}


def _path_markers(path: str) -> set[str]:
    """Return path-role markers inferred from the file path."""
    path_obj = Path(path)
    parts = {part.lower() for part in path_obj.parts}
    filename = path_obj.name.lower()
    markers: set[str] = set()
    if parts & _EXAMPLE_MARKERS:
        markers.add("example")
    if parts & _TEST_MARKERS or any(token in filename for token in (".test.", ".spec.", "test_", "_test")):
        markers.add("test")
    if parts & _BENCH_MARKERS or any(token in filename for token in (".bench.", ".benchmark.")):
        markers.add("benchmark")
    return markers


def _format_cluster_context(cluster: Cluster) -> str:
    """Summarize path-based context that affects refactor value."""
    unit_markers = [_path_markers(unit.file_path) for unit in cluster.units]
    notes: list[str] = []

    if unit_markers and all("example" in markers for markers in unit_markers):
        notes.append(
            "- Context: all units are in example/demo/sample paths; mirrored example code is often intentional."
        )
    if unit_markers and all("test" in markers for markers in unit_markers):
        notes.append(
            "- Context: all units are in test/spec paths; shared test scaffolding is lower priority than production logic."
        )
    if unit_markers and all("benchmark" in markers for markers in unit_markers):
        notes.append(
            "- Context: all units are in benchmark paths; bench helpers are usually low-value refactor targets."
        )

    return "\n".join(notes) if notes else "No special path context."


def _format_cluster_for_llm(cluster: Cluster) -> str:
    """Format a cluster's source code for LLM verification."""
    parts: list[str] = []
    for i, unit in enumerate(cluster.units):
        parts.append(
            f"--- Unit {i + 1}: {unit.unit_type} '{unit.name}' "
            f"at {unit.file_path}:{unit.start_line}-{unit.end_line} ---\n"
            f"{unit.source}"
        )
    return "\n\n".join(parts)


def _parse_verdict(response_text: str) -> tuple[str, str]:
    """Parse the LLM response into (verdict, reason)."""
    text = response_text.strip()

    # Try to extract JSON from the response
    # Handle cases where the LLM wraps JSON in markdown code blocks
    if "```" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

    try:
        data = json.loads(text)
        verdict = data.get("verdict", "review").lower()
        reason = data.get("reason", "")
    except (json.JSONDecodeError, AttributeError):
        # Fallback: look for keywords in the response
        lower = text.lower()
        if "noise" in lower:
            verdict = VERDICT_NOISE
        elif "refactor" in lower:
            verdict = VERDICT_REFACTOR
        else:
            verdict = VERDICT_REVIEW
        reason = text[:200]

    if verdict not in (VERDICT_REFACTOR, VERDICT_REVIEW, VERDICT_NOISE):
        verdict = VERDICT_REVIEW

    return verdict, reason


def verify_cluster(
    cluster: Cluster,
    model: str,
    backend: str = "litellm",
    api_key: str | None = None,
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> tuple[str, str]:
    """Verify a single cluster using an LLM.

    Returns (verdict, reason).
    """
    units_text = _format_cluster_for_llm(cluster)
    user_msg = USER_TEMPLATE.format(
        cluster_id=cluster.cluster_id,
        unit_count=len(cluster.units),
        similarity=cluster.max_similarity,
        context_text=_format_cluster_context(cluster),
        units_text=units_text,
    )

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"{user_msg}"
    )

    response_text = llm_completion(
        prompt,
        model,
        backend,
        api_key=api_key,
        ollama_host=ollama_host,
        cli_strip_api_key=cli_strip_api_key,
        cli_permission_mode=cli_permission_mode,
        cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
    )
    return _parse_verdict(response_text)


def verify_clusters(
    clusters: list[Cluster],
    model: str,
    max_workers: int = 1,
    backend: str = "litellm",
    api_key: str | None = None,
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> list[tuple[Cluster, str, str]]:
    """Verify all clusters in parallel.

    Returns list of (cluster, verdict, reason).
    """
    _load_dotenv()
    results: list[tuple[Cluster, str, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_cluster = {
            executor.submit(
                verify_cluster,
                cluster,
                model,
                backend,
                api_key,
                ollama_host,
                cli_strip_api_key,
                cli_permission_mode,
                cli_dangerously_skip_permissions,
            ): cluster
            for cluster in clusters
        }

        for future in as_completed(future_to_cluster):
            cluster = future_to_cluster[future]
            try:
                verdict, reason = future.result()
            except Exception as e:
                logger.warning("LLM verification failed for cluster %d: %s", cluster.cluster_id, e)
                verdict, reason = VERDICT_REVIEW, f"verification error: {e}"
            results.append((cluster, verdict, reason))

    # Preserve original ordering
    cluster_order = {id(c): i for i, c in enumerate(clusters)}
    results.sort(key=lambda r: cluster_order[id(r[0])])
    return results
