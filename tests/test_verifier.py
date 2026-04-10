"""Tests for dryscope.code.verifier and code verify backend plumbing."""

import numpy as np

from dryscope.cli import _run_code_scan
from dryscope.code.parser import CodeUnit
from dryscope.code.reporter import Cluster, Tier
from dryscope.config import Settings


def _make_units() -> list[CodeUnit]:
    return [
        CodeUnit(
            name="a",
            unit_type="function",
            source="def a():\n    return 1\n",
            file_path="a.py",
            start_line=1,
            end_line=2,
        ),
        CodeUnit(
            name="b",
            unit_type="function",
            source="def b():\n    return 2\n",
            file_path="b.py",
            start_line=1,
            end_line=2,
        ),
    ]


class DummyEmbedder:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def embed(self, texts):
        return np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)


def test_run_code_scan_passes_backend_to_verifier(monkeypatch):
    import dryscope.code.normalizer as normalizer
    import dryscope.code.parser as parser
    import dryscope.code.reporter as reporter
    import dryscope.code.verifier as verifier
    import dryscope.similarity as similarity
    import dryscope.code.embedder as embedder
    import dryscope.code.profiles as profiles

    monkeypatch.setattr(parser, "parse_directory", lambda *args, **kwargs: _make_units())
    monkeypatch.setattr(normalizer, "normalize", lambda source, lang="python": source)
    monkeypatch.setattr(embedder, "Embedder", DummyEmbedder)
    monkeypatch.setattr(profiles, "detect_profiles", lambda path: [])
    monkeypatch.setattr(profiles, "merge_profiles", lambda p, up, ut: (None, None, None))

    captured: dict = {}

    def fake_verify(clusters, model, max_workers=1, backend="litellm", api_key=None,
                    cli_strip_api_key=True, cli_permission_mode=None,
                    cli_dangerously_skip_permissions=False):
        captured["max_workers"] = max_workers
        captured["backend"] = backend
        captured["cli_strip_api_key"] = cli_strip_api_key
        captured["cli_permission_mode"] = cli_permission_mode
        captured["cli_dangerously_skip_permissions"] = cli_dangerously_skip_permissions
        return [(cluster, "review", "ok") for cluster in clusters]

    monkeypatch.setattr(verifier, "verify_clusters", fake_verify)

    settings = Settings(
        concurrency=4,
        backend="cli",
        cli_permission_mode="bypassPermissions",
        cli_dangerously_skip_permissions=True,
    )

    clusters = _run_code_scan(
        path=".",
        settings=settings,
        exclude=(),
        exclude_type=(),
        verify=True,
        llm_api_key=None,
        lang=None,
    )

    assert clusters is not None
    assert captured["max_workers"] == 4
    assert captured["backend"] == "cli"
    assert captured["cli_strip_api_key"] is True
    assert captured["cli_permission_mode"] == "bypassPermissions"
    assert captured["cli_dangerously_skip_permissions"] is True


def test_format_cluster_context_marks_examples_tests_and_benches():
    from dryscope.code.verifier import _format_cluster_context

    cluster = Cluster(
        cluster_id=0,
        units=[
            CodeUnit(
                name="a",
                unit_type="function",
                source="function a() {}",
                file_path="examples/app/test_a.bench.ts",
                start_line=1,
                end_line=1,
                lang="typescript",
            ),
            CodeUnit(
                name="b",
                unit_type="function",
                source="function b() {}",
                file_path="examples/app/test_b.bench.ts",
                start_line=1,
                end_line=1,
                lang="typescript",
            ),
        ],
        max_similarity=0.99,
        tier=Tier.EXACT,
        is_cross_file=True,
        total_lines=2,
        files=["examples/app/test_a.bench.ts", "examples/app/test_b.bench.ts"],
        actionability=1.0,
    )

    context = _format_cluster_context(cluster)

    assert "example/demo/sample" in context
    assert "test/spec" in context
    assert "benchmark" in context


def test_verify_cluster_includes_context_in_prompt(monkeypatch):
    import dryscope.code.verifier as verifier

    captured: dict = {}

    def fake_completion(prompt, model, backend, **kwargs):
        captured["prompt"] = prompt
        return '{"verdict":"noise","reason":"example duplication"}'

    monkeypatch.setattr(verifier, "llm_completion", fake_completion)

    cluster = Cluster(
        cluster_id=3,
        units=[
            CodeUnit(
                name="Page",
                unit_type="function",
                source="export function Page() { return null; }",
                file_path="examples/app-router/page.tsx",
                start_line=1,
                end_line=1,
                lang="tsx",
            ),
            CodeUnit(
                name="Page",
                unit_type="function",
                source="export function Page() { return null; }",
                file_path="examples/app-pages-router/page.tsx",
                start_line=1,
                end_line=1,
                lang="tsx",
            ),
        ],
        max_similarity=1.0,
        tier=Tier.EXACT,
        is_cross_file=True,
        total_lines=2,
        files=["examples/app-pages-router/page.tsx", "examples/app-router/page.tsx"],
        actionability=1.0,
    )

    verdict, reason = verifier.verify_cluster(cluster, model="test-model", backend="litellm")

    assert verdict == "noise"
    assert reason == "example duplication"
    assert "Context: all units are in example/demo/sample paths" in captured["prompt"]
