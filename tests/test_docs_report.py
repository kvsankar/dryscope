"""Regression tests for docs report rendering."""

import json
from pathlib import Path

from dryscope.config import Settings
from dryscope.docs.models import AnalysisResult, Chunk, DocPairAnalysis, Document, OverlapPair, TopicAnalysis
from dryscope.docs.report import build_recommendations, render_html, render_json, render_markdown, serialize_doc_pair_review_stage


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


def test_render_outputs_include_topic_taxonomy() -> None:
    result, _ = _make_analysis()
    result.document_descriptors = {
        "/tmp/project/docs/a.md": {
            "doc_role": "guide",
            "lifecycle": "current",
            "about": ["context window management"],
        }
    }
    result.topic_taxonomy = {
        "canonical_topics": [
            {
                "name": "context window management",
                "aliases": ["context-window management"],
                "documents": ["/tmp/project/docs/a.md", "/tmp/project/docs/b.md"],
                "document_count": 2,
                "mention_count": 3,
            }
        ],
        "raw_to_canonical": {
            "context-window management": "context window management",
        },
        "doc_topics": {
            "/tmp/project/docs/a.md": ["context window management"],
        },
        "co_occurrence": [],
        "docs_map": {
            "method": "llm",
            "topic_tree": [
                {
                    "id": "docs_map_01",
                    "label": "context engineering",
                    "description": "Context-related docs.",
                    "children": [
                        {
                            "id": "docs_map_01_01",
                            "label": "context windows",
                            "description": "Managing context budgets.",
                            "topics": ["context window management"],
                            "documents": ["docs/a.md", "docs/b.md"],
                            "document_count": 2,
                        }
                    ],
                }
            ],
            "facets": {
                "doc_role": {
                    "description": "Doc roles.",
                    "values": [{"value": "guide", "documents": ["docs/a.md"], "evidence": ["guide"]}],
                }
            },
            "diagnostics": [
                {
                    "kind": "fragmented_intent",
                    "severity": "medium",
                    "message": "Context is split.",
                    "recommendation": "Consolidate.",
                }
            ],
        },
    }

    markdown = render_markdown(result, [], None)
    json_report = render_json(result, [], None)

    assert "Run Overview" in markdown
    assert "Docs Track Summary" in markdown
    assert "Docs Map" in markdown
    assert "Docs Map Clusters" in markdown
    assert "context engineering" in markdown
    assert "Docs Map Taxonomy" in markdown
    assert "context window management" in markdown
    assert '"report_structure"' in json_report
    assert '"document_descriptors"' in json_report
    assert '"docs_map"' in json_report
    assert '"topic_taxonomy"' not in json_report
    assert '"topic_document_clusters"' not in json_report
    data = json.loads(json_report)
    section_ids = [section["id"] for section in data["report_structure"]]
    assert section_ids == [
        "run_overview",
        "docs_map",
        "docs_map_clusters",
        "docs_section_match",
        "docs_pair_review",
        "docs_map_taxonomy",
        "methodology",
    ]
    run_overview = data["report_structure"][0]["data"]
    assert "overview" in run_overview
    assert "scanned_documents" in run_overview
    taxonomy = data["report_structure"][5]["data"]
    assert taxonomy["document_descriptors"]
    assert "documents" not in taxonomy["canonical_topics"][0]


def test_serialize_doc_pair_review_stage_handles_missing_canonical() -> None:
    _, analyses = _make_analysis()

    payload = serialize_doc_pair_review_stage(
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


def test_section_match_recommendations_are_labeled_in_report() -> None:
    result = AnalysisResult(
        documents=[
            Document(
                path="/tmp/project/docs/a.md",
                chunks=[Chunk("/tmp/project/docs/a.md", ["Flow"], "repeat me please", 1, 4)],
            ),
            Document(
                path="/tmp/project/docs/b.md",
                chunks=[Chunk("/tmp/project/docs/b.md", ["Flow"], "repeat me please", 1, 4)],
            ),
        ],
    )
    result.chunks = [chunk for doc in result.documents for chunk in doc.chunks]
    pair = _pair("/tmp/project/docs/a.md", "/tmp/project/docs/b.md", 1, 1, 0.99)

    markdown = render_markdown(
        result,
        [pair],
        suggestions=None,
        settings=Settings(),
        project_root=Path("/tmp/project"),
        stages_run=["docs-section-match"],
    )

    assert "## 2. Docs Map" not in markdown
    assert "## Recommendations" not in markdown
    assert "## 2. Section Match" in markdown
    assert "### 2.1. Section Match Recommendations" in markdown
    assert "These recommendations are derived from the matched section pairs" in markdown
    assert "Matched Section Pairs" in markdown
    assert "Section Match Recs" in markdown


def test_dashboard_reflects_all_tracks_that_ran() -> None:
    result, _ = _make_analysis()
    result.document_descriptors = {
        "/tmp/project/docs/a.md": {
            "about": ["context window management"],
            "reader_intents": ["understand context windows"],
        }
    }
    result.topic_taxonomy = {
        "canonical_topics": [
            {
                "name": "context window management",
                "aliases": ["context window management"],
                "documents": ["/tmp/project/docs/a.md", "/tmp/project/docs/b.md"],
                "document_count": 2,
                "mention_count": 2,
            }
        ],
        "topic_document_clusters": [
            {
                "topic": "context window management",
                "documents": ["/tmp/project/docs/a.md", "/tmp/project/docs/b.md"],
                "document_count": 2,
                "mention_count": 2,
                "aliases": ["context window management"],
            }
        ],
        "docs_map": {
            "method": "llm",
            "topic_tree": [{"label": "context engineering", "children": []}],
            "facets": {"doc_role": {"values": []}},
            "diagnostics": [],
        },
    }
    pair = _pair("/tmp/project/docs/a.md", "/tmp/project/docs/b.md", 1, 1, 0.99)

    markdown = render_markdown(
        result,
        [pair],
        suggestions=None,
        settings=Settings(),
        project_root=Path("/tmp/project"),
        stages_run=["docs-section-match", "docs-map"],
    )

    assert "Docs Map Groups" in markdown
    assert "Docs Map Clusters" in markdown
    assert "Matched Section Pairs" in markdown
    assert "Section Match Recs" in markdown
    assert "Docs Map:" in markdown
    assert "Section Match:" in markdown


def test_html_wraps_sections_and_renders_diagnostics_table() -> None:
    result, _ = _make_analysis()
    result.topic_taxonomy = {
        "canonical_topics": [],
        "raw_to_canonical": {},
        "doc_topics": {},
        "co_occurrence": [],
        "docs_map": {
            "method": "llm",
            "topic_tree": [],
            "facets": {},
            "diagnostics": [
                {
                    "kind": "mixed_lifecycle",
                    "severity": "low",
                    "message": "Lifecycle values are mixed.",
                    "recommendation": "Use constraint_type: accepted|deferred|unresolved.",
                }
            ],
        },
    }

    markdown = render_markdown(result, [], None)
    html = render_html(markdown)

    assert 'class="report-section"' in html
    assert "<table>" in html
    assert "accepted|deferred|unresolved" in html
    assert "| low |" not in html


def test_report_uses_full_collapsible_lists_without_samples() -> None:
    result, _ = _make_analysis()
    result.documents.append(
        Document(
            path="/tmp/project/docs/b.md",
            chunks=[Chunk("/tmp/project/docs/b.md", ["Intro"], "hello", 1, 3)],
        )
    )
    result.topic_taxonomy = {
        "canonical_topics": [
            {
                "name": "context window management",
                "aliases": [f"alias-{i}" for i in range(1, 10)],
                "documents": [
                    "/tmp/project/docs/a.md",
                    "/tmp/project/docs/b.md",
                    "/tmp/project/docs/c.md",
                    "/tmp/project/docs/d.md",
                    "/tmp/project/docs/e.md",
                    "/tmp/project/docs/f.md",
                    "/tmp/project/docs/g.md",
                ],
                "document_count": 7,
                "mention_count": 9,
            }
        ],
        "topic_document_clusters": [
            {
                "topic": "context window management",
                "aliases": [f"alias-{i}" for i in range(1, 10)],
                "documents": [
                    "/tmp/project/docs/a.md",
                    "/tmp/project/docs/b.md",
                    "/tmp/project/docs/c.md",
                    "/tmp/project/docs/d.md",
                    "/tmp/project/docs/e.md",
                    "/tmp/project/docs/f.md",
                    "/tmp/project/docs/g.md",
                ],
                "document_count": 7,
                "mention_count": 9,
            }
        ],
        "docs_map": {
            "method": "llm",
            "topic_tree": [
                {
                    "label": "context engineering",
                    "children": [
                        {
                            "label": "context windows",
                            "topics": ["context window management"],
                            "documents": [f"docs/{name}.md" for name in "abcdefg"],
                            "document_count": 7,
                        }
                    ],
                }
            ],
            "facets": {},
            "diagnostics": [],
        },
    }

    pair = _pair("/tmp/project/docs/a.md", "/tmp/project/docs/b.md", 1, 1, 0.99)
    markdown = render_markdown(
        result,
        [pair],
        suggestions=None,
        settings=Settings(),
        project_root=Path("/tmp/project"),
        stages_run=["docs-section-match", "docs-map"],
    )
    html = render_html(markdown)
    json_report = render_json(
        result,
        [pair],
        suggestions=None,
        settings=Settings(),
        project_root=Path("/tmp/project"),
        stages_run=["docs-section-match", "docs-map"],
    )
    data = json.loads(json_report)

    assert "Sample docs" not in markdown
    assert "+1 more" not in markdown
    assert "docs/g.md" in markdown
    assert "alias-9" in markdown
    assert 'class="report-list"' in html
    assert 'id="rec-table"' not in html
    assert "documents" not in data
    assert "run_overview" not in data
    assert "stages_run" not in data
    assert "topic_taxonomy" not in data
    assert "topic_document_clusters" not in data
    assert "docs_map" not in data
    assert "similarity_pairs" not in data
    section_by_id = {section["id"]: section for section in data["report_structure"]}
    cluster_docs = section_by_id["docs_map_clusters"]["data"][0]["documents"]
    assert "/tmp/project/docs/g.md" in cluster_docs
    pair_rows = section_by_id["docs_section_match"]["children"][1]["data"]
    assert len(pair_rows) == 1
