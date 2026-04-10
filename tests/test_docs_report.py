"""Regression tests for docs report rendering."""

from pathlib import Path

from dryscope.config import Settings
from dryscope.docs.models import AnalysisResult, Chunk, DocPairAnalysis, Document, OverlapPair, TopicAnalysis
from dryscope.docs.report import build_recommendations, render_json, render_markdown, serialize_coding_stage


def _make_analysis() -> tuple[AnalysisResult, list[DocPairAnalysis]]:
    chunk = Chunk(
        document_path="/tmp/project/docs/a.md",
        heading_path=["Intro"],
        content="hello",
        line_start=1,
        line_end=3,
    )
    doc = Document(path="/tmp/project/docs/a.md", chunks=[chunk])
    analysis = DocPairAnalysis(
        doc_a_path="/tmp/project/docs/a.md",
        doc_b_path="/tmp/project/docs/b.md",
        doc_a_purpose="A doc",
        doc_b_purpose="B doc",
        relationship="complementary",
        topics=[
            TopicAnalysis(
                name="shared-topic",
                canonical=None,
                action_for_other="keep",
                reason="LLM omitted a canonical target.",
            )
        ],
    )
    return AnalysisResult(documents=[doc], chunks=[chunk], doc_pair_analyses=[analysis]), [analysis]


def test_render_markdown_handles_missing_canonical() -> None:
    result, _ = _make_analysis()

    content = render_markdown(result, [], None)

    assert "(unspecified)" in content
    assert "shared-topic" in content


def test_render_json_handles_missing_canonical() -> None:
    result, _ = _make_analysis()

    content = render_json(result, [], None)

    assert '"canonical": null' in content
    assert '"canonical_name": "(unspecified)"' in content


def test_serialize_coding_stage_handles_missing_canonical() -> None:
    _, analyses = _make_analysis()

    payload = serialize_coding_stage(
        codes=[],
        categories=[],
        suggestions=None,
        settings=Settings(),
        project_root=Path("/tmp/project"),
        analyses=analyses,
    )

    topic = payload["doc_pair_analyses"][0]["topics"][0]
    assert topic["canonical"] is None
    assert topic["action_for_other"] == "keep"


def _pair(doc_a: str, doc_b: str, line_a: int, line_b: int, similarity: float) -> OverlapPair:
    return OverlapPair(
        chunk_a=Chunk(doc_a, ["Flow"], "repeat me please", line_a, line_a + 3),
        chunk_b=Chunk(doc_b, ["Flow"], "repeat me please", line_b, line_b + 3),
        embedding_similarity=similarity,
    )


def test_build_recommendations_merges_dense_file_family() -> None:
    pair1 = _pair("/tmp/project/docs/flows/a.txt", "/tmp/project/docs/flows/b.txt", 1, 1, 0.99)
    pair2 = _pair("/tmp/project/docs/flows/a.txt", "/tmp/project/docs/flows/c.txt", 10, 1, 0.98)
    pair3 = _pair("/tmp/project/docs/flows/b.txt", "/tmp/project/docs/flows/c.txt", 10, 10, 0.97)
    recs = build_recommendations(
        [pair1, pair2, pair3],
        suggestions=None,
        project_root=Path("/tmp/project"),
    )

    assert len(recs) == 1
    assert len(recs[0]["affected_files"]) == 3
    assert "family of 3 documents" in recs[0]["action_detail"]


def test_build_recommendations_keeps_simple_pairwise_overlap() -> None:
    pair1 = _pair("/tmp/project/docs/a.txt", "/tmp/project/docs/b.txt", 1, 1, 0.99)
    recs = build_recommendations(
        [pair1],
        suggestions=None,
        project_root=Path("/tmp/project"),
    )

    assert len(recs) == 1
    assert len(recs[0]["affected_files"]) == 2
