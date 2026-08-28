"""Tests for docs pipeline scaling helpers."""

import json
from io import StringIO

import pytest
from rich.console import Console

from dryscope.code.embedder import EmbeddingConfigurationError
from dryscope.config import Settings
from dryscope.docs.models import AnalysisResult, Chunk, Document, OverlapPair
from dryscope.docs.pipeline import (
    _filter_doc_chunks_map,
    _group_pairs_by_doc_pair,
    _load_docs_map_stage,
    _output_results,
    _rank_doc_paths_by_similarity_evidence,
    _restrict_doc_pair_groups,
    _should_skip_intent_extraction,
    run_pipeline,
)
from dryscope.run_store import RunStore


def _pair(doc_a: str, doc_b: str, line_a: int, line_b: int, similarity: float) -> OverlapPair:
    chunk_a = Chunk(doc_a, ["A"], "alpha beta gamma", line_a, line_a + 1)
    chunk_b = Chunk(doc_b, ["B"], "alpha beta gamma", line_b, line_b + 1)
    return OverlapPair(chunk_a=chunk_a, chunk_b=chunk_b, embedding_similarity=similarity)


def test_rank_doc_paths_by_similarity_evidence_prefers_stronger_and_more_frequent_docs() -> None:
    groups = _group_pairs_by_doc_pair(
        [
            _pair("/docs/a.md", "/docs/b.md", 1, 1, 0.99),
            _pair("/docs/a.md", "/docs/b.md", 10, 10, 0.95),
            _pair("/docs/a.md", "/docs/c.md", 20, 20, 0.92),
            _pair("/docs/d.md", "/docs/e.md", 30, 30, 0.91),
        ]
    )

    ranked = _rank_doc_paths_by_similarity_evidence(groups)

    assert ranked[:3] == ["/docs/a.md", "/docs/b.md", "/docs/c.md"]


def test_filter_doc_chunks_map_keeps_only_allowed_docs() -> None:
    doc_chunks_map = {
        "/docs/a.md": [Chunk("/docs/a.md", ["A"], "one two three", 1, 2)],
        "/docs/b.md": [Chunk("/docs/b.md", ["B"], "one two three", 1, 2)],
    }

    filtered = _filter_doc_chunks_map(doc_chunks_map, {"/docs/b.md"})

    assert list(filtered) == ["/docs/b.md"]


def test_restrict_doc_pair_groups_by_allowed_docs_and_max_pairs() -> None:
    groups = _group_pairs_by_doc_pair(
        [
            _pair("/docs/a.md", "/docs/b.md", 1, 1, 0.99),
            _pair("/docs/a.md", "/docs/c.md", 10, 10, 0.97),
            _pair("/docs/b.md", "/docs/c.md", 20, 20, 0.91),
        ]
    )

    filtered = _restrict_doc_pair_groups(
        groups,
        allowed_docs={"/docs/a.md", "/docs/b.md", "/docs/c.md"},
        max_pairs=2,
    )

    assert list(filtered) == [
        ("/docs/a.md", "/docs/b.md"),
        ("/docs/a.md", "/docs/c.md"),
    ]


def test_should_skip_intent_extraction_for_large_corpus_without_similarity_pairs() -> None:
    settings = Settings(docs_intent_skip_without_similarity_min_docs=3)
    doc_chunks_map = {
        "/docs/a.md": [Chunk("/docs/a.md", ["A"], "one two three", 1, 2)],
        "/docs/b.md": [Chunk("/docs/b.md", ["B"], "one two three", 1, 2)],
        "/docs/c.md": [Chunk("/docs/c.md", ["C"], "one two three", 1, 2)],
    }

    assert _should_skip_intent_extraction(doc_chunks_map, {}, settings) is True


def test_should_not_skip_intent_extraction_when_similarity_pairs_exist() -> None:
    settings = Settings(docs_intent_skip_without_similarity_min_docs=3)
    doc_chunks_map = {
        "/docs/a.md": [Chunk("/docs/a.md", ["A"], "one two three", 1, 2)],
        "/docs/b.md": [Chunk("/docs/b.md", ["B"], "one two three", 1, 2)],
        "/docs/c.md": [Chunk("/docs/c.md", ["C"], "one two three", 1, 2)],
    }
    groups = _group_pairs_by_doc_pair(
        [
            _pair("/docs/a.md", "/docs/b.md", 1, 1, 0.99),
        ]
    )

    assert _should_skip_intent_extraction(doc_chunks_map, groups, settings) is False


def test_should_not_skip_intent_extraction_for_small_negative_repo() -> None:
    settings = Settings(docs_intent_skip_without_similarity_min_docs=4)
    doc_chunks_map = {
        "/docs/a.md": [Chunk("/docs/a.md", ["A"], "one two three", 1, 2)],
        "/docs/b.md": [Chunk("/docs/b.md", ["B"], "one two three", 1, 2)],
        "/docs/c.md": [Chunk("/docs/c.md", ["C"], "one two three", 1, 2)],
    }

    assert _should_skip_intent_extraction(doc_chunks_map, {}, settings) is False


def test_run_pipeline_rejects_unknown_stage(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unknown docs stage"):
        run_pipeline(tmp_path, Settings(), stage="similarity", console=Console(stderr=True))


def test_embedding_failure_is_persisted_as_degraded_report(monkeypatch, tmp_path) -> None:
    (tmp_path / "a.md").write_text(
        "# A\n\n## Details\n\nEnough words to create a documentation section for embedding failure coverage.\n"
    )
    (tmp_path / "b.md").write_text(
        "# B\n\n## Details\n\nEnough other words to create a second documentation section for coverage.\n"
    )
    monkeypatch.setattr(
        "dryscope.docs.pipeline.embed_chunks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            EmbeddingConfigurationError(
                "Embedding model requires OPENAI_API_KEY; use all-MiniLM-L6-v2."
            )
        ),
    )
    report_path = tmp_path / "degraded.json"
    console_output = StringIO()
    store = RunStore(tmp_path)

    result = run_pipeline(
        tmp_path,
        Settings(cache_enabled=False),
        stage="docs-section-match",
        output_format="json",
        output_file=str(report_path),
        console=Console(file=console_output, force_terminal=False, color_system=None),
        run_store=store,
    )

    status = result.stage_status["docs-section-match"]
    assert status["status"] == "degraded"
    assert status["exception_category"] == "EmbeddingConfigurationError"
    assert status["fallback"] == "no Section Match pairs or semantic candidates"
    assert status["unavailable_conclusions"]
    assert "Traceback" not in console_output.getvalue()
    assert console_output.getvalue().count("OPENAI_API_KEY") == 1
    assert "all-MiniLM-L6-v2" in console_output.getvalue()

    report = json.loads(report_path.read_text())
    assert report["summary"]["outcome"]["status"] == "degraded"
    saved = store.load_stage("docs_section_match.json")
    assert saved is not None
    assert saved["stage_status"]["status"] == "degraded"


def test_docs_map_can_continue_after_section_embedding_degrades(monkeypatch, tmp_path) -> None:
    (tmp_path / "a.md").write_text(
        "# A\n\n## Details\n\nEnough words to create a documentation section for degraded coverage.\n"
    )
    monkeypatch.setattr(
        "dryscope.docs.pipeline.embed_chunks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            EmbeddingConfigurationError("Embedding setup unavailable.")
        ),
    )
    docs_map_calls = 0

    def fake_docs_map_stage(result, *_args, **_kwargs):
        nonlocal docs_map_calls
        docs_map_calls += 1
        result.topic_taxonomy = {
            "docs_map": {
                "method": "llm",
                "topic_tree": [],
                "facets": {},
                "diagnostics": [{"kind": "navigation_gap", "message": "Review navigation."}],
            }
        }
        result.stage_status["docs-map"] = {"status": "completed", "fallback": None}
        return {}, {}

    monkeypatch.setattr("dryscope.docs.pipeline._run_docs_map_stage", fake_docs_map_stage)
    report_path = tmp_path / "full-report.json"

    result = run_pipeline(
        tmp_path,
        Settings(cache_enabled=False),
        stage="docs-report-pack",
        output_format="json",
        output_file=str(report_path),
        console=Console(file=StringIO(), force_terminal=False, color_system=None),
    )

    assert docs_map_calls == 1
    assert result.stage_status["docs-section-match"]["status"] == "degraded"
    assert result.stage_status["docs-map"]["status"] == "completed"
    assert result.stage_status["docs-pair-review"]["status"] == "skipped"
    assert result.stage_status["docs-pair-review"]["unavailable_conclusions"]
    outcome = json.loads(report_path.read_text())["summary"]["outcome"]
    assert outcome["status"] == "degraded"
    assert "1 Docs Map diagnostic" in outcome["statement"]


def test_resume_retries_degraded_docs_map_without_restoring_stale_section_status(
    tmp_path,
) -> None:
    doc_path = tmp_path / "a.md"
    doc_path.write_text("# A\n\nEnough documentation content for a resumable stage.\n")
    document = Document(str(doc_path), [])
    store = RunStore(tmp_path)
    saved = {
        "descriptor_based": True,
        "document_descriptors": {"a.md": {"about": ["publication hardening"]}},
        "topic_taxonomy": {"canonical_topics": []},
        "doc_topics": {"a.md": ["publication hardening"]},
        "intent_matches": [],
        "stage_status": {
            "docs-section-match": {
                "status": "degraded",
                "unavailable_conclusions": ["stale Section Match conclusion"],
            },
            "document-descriptors": {"status": "completed", "fallback": None},
            "canonical-taxonomy": {"status": "completed", "fallback": None},
            "ia-synthesis": {"status": "completed", "fallback": None},
            "intent-matching": {
                "status": "degraded",
                "unavailable_conclusions": ["embedding-based intent relationships"],
            },
            "docs-map": {
                "status": "degraded",
                "unavailable_conclusions": ["embedding-based intent relationships"],
            },
        },
    }
    store.save_stage("docs_map.json", saved)
    result = AnalysisResult(
        documents=[document],
        stage_status={"docs-section-match": {"status": "completed", "fallback": None}},
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None)

    resumed, _topics, _intent, _saved = _load_docs_map_stage(result, store, console)

    assert resumed is False
    assert result.stage_status["docs-section-match"]["status"] == "completed"
    assert "retrying" in output.getvalue()

    saved["stage_status"]["intent-matching"] = {"status": "completed", "fallback": None}
    saved["stage_status"]["docs-map"] = {"status": "completed", "fallback": None}
    store.save_stage("docs_map.json", saved)

    resumed, doc_topics, intent_evidence, _saved = _load_docs_map_stage(result, store, console)

    assert resumed is True
    assert doc_topics == {str(doc_path): ["publication hardening"]}
    assert intent_evidence == {}
    assert result.stage_status["docs-section-match"]["status"] == "completed"


def test_output_results_json_stdout_is_parseable(capsys, tmp_path) -> None:
    chunk = Chunk(
        document_path=str(tmp_path / "docs" / "a.md"),
        heading_path=["Intro"],
        content="alpha beta gamma",
        line_start=1,
        line_end=2,
    )
    result = AnalysisResult(documents=[Document(path=chunk.document_path, chunks=[chunk])])
    result.chunks = [chunk]

    _output_results(
        result,
        [],
        None,
        "json",
        None,
        Console(stderr=True),
        settings=Settings(),
        scan_path=tmp_path,
        stages_run=["docs-section-match"],
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["summary"]["documents_scanned"] == 1
