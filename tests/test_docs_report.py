"""Regression tests for docs report rendering."""

from pathlib import Path

from dryscope.config import Settings
from dryscope.docs.models import AnalysisResult, Chunk, DocPairAnalysis, Document, TopicAnalysis
from dryscope.docs.report import render_json, render_markdown, serialize_coding_stage


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
