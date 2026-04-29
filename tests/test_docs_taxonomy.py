"""Tests for documentation topic taxonomy normalization."""

import json
from types import SimpleNamespace

from dryscope.docs.taxonomy import (
    build_canonical_taxonomy,
    build_information_architecture,
    normalize_topic_text,
    topic_similarity,
)
from dryscope.docs.topics import embed_topics


def test_normalize_topic_text_removes_formatting_noise() -> None:
    assert normalize_topic_text(" Context-Window & Token Budgets! ") == "context window and token budgets"


def test_topic_similarity_combines_string_and_token_overlap() -> None:
    assert topic_similarity("context window management", "context-window management") == 1.0
    assert topic_similarity("context window management", "release notes") < 0.5


def test_build_canonical_taxonomy_merges_raw_topic_variants() -> None:
    taxonomy = build_canonical_taxonomy(
        {
            "/docs/a.md": [
                "context window management",
                "agent permissions and safety",
            ],
            "/docs/b.md": [
                "context-window management",
                "agent permission safety",
            ],
            "/docs/c.md": [
                "context windows management",
                "evaluation workflow",
            ],
        }
    )

    assert taxonomy.raw_to_canonical["context-window management"] == "context window management"
    assert taxonomy.raw_to_canonical["context windows management"] == "context window management"
    assert taxonomy.doc_topics["/docs/b.md"][0] == "context window management"

    context_topic = taxonomy.canonical_topics["context window management"]
    assert context_topic.documents == {"/docs/a.md", "/docs/b.md", "/docs/c.md"}
    assert context_topic.mention_count == 3


def test_build_canonical_taxonomy_tracks_co_occurrence() -> None:
    taxonomy = build_canonical_taxonomy(
        {
            "/docs/a.md": ["context window management", "agent permissions"],
            "/docs/b.md": ["context window management", "agent permissions"],
            "/docs/c.md": ["context window management", "evaluation workflow"],
        }
    )

    assert taxonomy.co_occurrence == [
        {
            "topics": ["agent permissions", "context window management"],
            "count": 2,
        }
    ]


def test_taxonomy_serializes_topic_document_clusters_without_size_cap() -> None:
    taxonomy = build_canonical_taxonomy(
        {
            "/docs/a.md": ["shared architecture topic"],
            "/docs/b.md": ["shared architecture topic"],
            "/docs/c.md": ["shared architecture topic"],
            "/docs/d.md": ["single document topic"],
        }
    )

    data = taxonomy.to_dict()

    assert data["topic_document_clusters"] == [
        {
            "topic": "shared architecture topic",
            "documents": ["/docs/a.md", "/docs/b.md", "/docs/c.md"],
            "document_count": 3,
            "mention_count": 3,
            "aliases": ["shared architecture topic"],
        }
    ]


def test_build_canonical_taxonomy_uses_llm_mapping(monkeypatch) -> None:
    from dryscope.docs import coding

    def fake_call_llm_cached(*args, **kwargs) -> str:
        return json.dumps({
            "mappings": [
                {
                    "raw": "context window management",
                    "canonical": "context engineering",
                    "is_new": True,
                },
                {
                    "raw": "prompt context budgeting",
                    "canonical": "context engineering",
                    "is_new": False,
                },
            ]
        })

    monkeypatch.setattr(coding, "call_llm_cached", fake_call_llm_cached)

    taxonomy = build_canonical_taxonomy(
        {
            "/docs/a.md": ["context window management"],
            "/docs/b.md": ["prompt context budgeting"],
        },
        llm_model="fake-model",
        backend="cli",
        llm_batch_size=10,
        llm_min_document_count=1,
    )

    assert taxonomy.method == "llm"
    assert taxonomy.raw_to_canonical["context window management"] == "context engineering"
    assert taxonomy.raw_to_canonical["prompt context budgeting"] == "context engineering"
    assert taxonomy.canonical_topics["context engineering"].documents == {"/docs/a.md", "/docs/b.md"}


def test_build_canonical_taxonomy_parallel_llm_batches(monkeypatch) -> None:
    from dryscope.docs import coding

    def fake_call_llm_cached(*args, **kwargs) -> str:
        return json.dumps({
            "mappings": [
                {"raw": "alpha one", "canonical": "alpha topic", "is_new": True},
                {"raw": "alpha two", "canonical": "alpha topic", "is_new": False},
                {"raw": "beta one", "canonical": "beta topic", "is_new": True},
                {"raw": "beta two", "canonical": "beta topic", "is_new": False},
            ]
        })

    monkeypatch.setattr(coding, "call_llm_cached", fake_call_llm_cached)

    taxonomy = build_canonical_taxonomy(
        {
            "/docs/a.md": ["alpha one"],
            "/docs/b.md": ["alpha two"],
            "/docs/c.md": ["beta one"],
            "/docs/d.md": ["beta two"],
        },
        llm_model="fake-model",
        backend="cli",
        llm_batch_size=1,
        llm_concurrency=2,
    )

    assert taxonomy.method == "llm"
    assert taxonomy.canonical_topics["alpha topic"].documents == {"/docs/a.md", "/docs/b.md"}
    assert taxonomy.canonical_topics["beta topic"].documents == {"/docs/c.md", "/docs/d.md"}


def test_build_information_architecture_uses_llm(monkeypatch) -> None:
    from dryscope.docs import coding

    taxonomy = build_canonical_taxonomy(
        {
            "/docs/user/getting-started.md": ["install workflow", "quickstart workflow"],
            "/docs/user/tutorial.md": ["quickstart workflow"],
            "/docs/reference/api.md": ["api reference"],
        }
    ).to_dict()

    def fake_call_llm_cached(*args, **kwargs) -> str:
        return json.dumps(
            {
                "method": "llm",
                "topic_tree": [
                    {
                        "id": "ia_01",
                        "label": "getting started",
                        "description": "Entry-point docs.",
                        "children": [
                            {
                                "id": "ia_01_01",
                                "label": "quickstart workflows",
                                "description": "First successful usage path.",
                                "topics": ["quickstart workflow", "install workflow"],
                                "documents": ["user/getting-started.md"],
                                "document_count": 2,
                            }
                        ],
                    }
                ],
                "facets": {
                    "doc_role": {
                        "description": "Observed doc types.",
                        "values": [
                            {
                                "value": "guide",
                                "documents": ["user/getting-started.md"],
                                "evidence": ["getting started path"],
                            }
                        ],
                    }
                },
                "diagnostics": [
                    {
                        "kind": "fragmented_intent",
                        "severity": "medium",
                        "message": "Quickstart appears in multiple files.",
                        "topics": ["quickstart workflow"],
                        "documents": ["user/getting-started.md", "user/tutorial.md"],
                        "recommendation": "Choose one primary quickstart.",
                    }
                ],
            }
        )

    monkeypatch.setattr(coding, "call_llm_cached", fake_call_llm_cached)

    descriptors = {
        "/docs/user/getting-started.md": {
            "title": "Getting Started",
            "summary": "Intro guide.",
            "about": ["install workflow"],
            "reader_intents": ["start using the package"],
            "doc_role": "guide",
            "audience": ["user"],
            "lifecycle": "current",
            "content_type": ["workflow"],
            "surface": ["public"],
            "canonicality": "primary",
            "evidence": {"headings": ["Getting Started"], "phrases": ["install"]},
        }
    }

    ia = build_information_architecture(
        taxonomy,
        document_descriptors=descriptors,
        llm_model="fake-model",
        backend="cli",
    )

    assert ia["method"] == "llm"
    assert ia["topic_tree"][0]["label"] == "getting started"
    assert ia["facets"]["doc_role"]["values"][0]["value"] == "guide"
    assert ia["diagnostics"][0]["kind"] == "fragmented_intent"
    assert ia["source_summary"]["documents"] == 3
    assert ia["source_summary"]["document_descriptors"] == 1


def test_embed_topics_uses_api_embedding_models(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeLiteLLM:
        @staticmethod
        def embedding(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[{"embedding": [1.0, 2.0, 3.0]}])

    monkeypatch.setitem(__import__("sys").modules, "litellm", FakeLiteLLM)

    result = embed_topics(["alpha", "beta"], "text-embedding-3-small")

    assert result == {
        "alpha": [1.0, 2.0, 3.0],
        "beta": [1.0, 2.0, 3.0],
    }
    assert [call["input"] for call in calls] == [["alpha"], ["beta"]]
    assert all(call["model"] == "text-embedding-3-small" for call in calls)
