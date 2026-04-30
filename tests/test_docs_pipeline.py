"""Tests for docs pipeline scaling helpers."""

import json

import pytest
from rich.console import Console

from dryscope.config import Settings
from dryscope.docs.models import AnalysisResult, Chunk, Document, OverlapPair
from dryscope.docs.pipeline import (
    _filter_doc_chunks_map,
    _group_pairs_by_doc_pair,
    _output_results,
    _rank_doc_paths_by_similarity_evidence,
    _restrict_doc_pair_groups,
    _should_skip_intent_extraction,
    run_pipeline,
)


def _pair(doc_a: str, doc_b: str, line_a: int, line_b: int, similarity: float) -> OverlapPair:
    chunk_a = Chunk(doc_a, ["A"], "alpha beta gamma", line_a, line_a + 1)
    chunk_b = Chunk(doc_b, ["B"], "alpha beta gamma", line_b, line_b + 1)
    return OverlapPair(chunk_a=chunk_a, chunk_b=chunk_b, embedding_similarity=similarity)


def test_rank_doc_paths_by_similarity_evidence_prefers_stronger_and_more_frequent_docs() -> None:
    groups = _group_pairs_by_doc_pair([
        _pair("/docs/a.md", "/docs/b.md", 1, 1, 0.99),
        _pair("/docs/a.md", "/docs/b.md", 10, 10, 0.95),
        _pair("/docs/a.md", "/docs/c.md", 20, 20, 0.92),
        _pair("/docs/d.md", "/docs/e.md", 30, 30, 0.91),
    ])

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
    groups = _group_pairs_by_doc_pair([
        _pair("/docs/a.md", "/docs/b.md", 1, 1, 0.99),
        _pair("/docs/a.md", "/docs/c.md", 10, 10, 0.97),
        _pair("/docs/b.md", "/docs/c.md", 20, 20, 0.91),
    ])

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
    groups = _group_pairs_by_doc_pair([
        _pair("/docs/a.md", "/docs/b.md", 1, 1, 0.99),
    ])

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
