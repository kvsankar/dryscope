"""Regression tests for Doc Pair Review LLM failure handling."""

from dryscope.docs.coding import analyze_doc_pair
from dryscope.docs.models import Chunk, OverlapPair


def test_doc_pair_analysis_falls_back_when_llm_call_fails(monkeypatch) -> None:
    chunk_a = Chunk("/repo/docs/a.md", ["Install"], "Install content", 1, 3)
    chunk_b = Chunk("/repo/docs/b.md", ["Install"], "Install content", 1, 3)

    def fail_call(*args, **kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr("dryscope.docs.coding.call_llm_cached", fail_call)

    result = analyze_doc_pair(
        chunk_a.document_path,
        chunk_b.document_path,
        [chunk_a],
        [chunk_b],
        [OverlapPair(chunk_a, chunk_b, embedding_similarity=0.97)],
        model="test-model",
        cache=None,
    )

    assert result["relationship"] == "complementary"
    assert result["confidence"] == "low"
    assert result["topics"] == []
    assert "backend unavailable" in result["analysis_error"]
