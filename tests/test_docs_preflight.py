"""Regression coverage for documentation-preflight behavior and provenance."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from dryscope.config import Settings
from dryscope.docs.chunker import chunk_file, detect_boilerplate_headings
from dryscope.docs.embeddings import find_similarity_bands
from dryscope.docs.models import (
    AnalysisResult,
    Chunk,
    DocPairAnalysis,
    Document,
    OverlapPair,
    TopicAnalysis,
)
from dryscope.docs.pipeline import run_pipeline
from dryscope.docs.report import render_json, render_markdown, serialize_section_match_stage
from dryscope.docs.taxonomy import TopicTaxonomy, build_canonical_taxonomy, build_docs_map


def _chunk(path: str, heading: str, content: str, line: int = 1) -> Chunk:
    return Chunk(path, [heading], content, line, line)


def test_hybrid_scores_expose_components_and_bounded_candidate_band() -> None:
    same_a = _chunk(
        "docs/a.md", "# Install", "install package safely with pinned local dependencies"
    )
    same_b = _chunk("docs/b.md", "# Setup", "install package safely with pinned local dependencies")
    semantic_a = _chunk("docs/c.md", "# Publication", "release readiness signing artifacts checks")
    semantic_b = _chunk(
        "docs/d.md", "# Hardening", "deployment safety provenance verification gates"
    )
    chunks = [same_a, same_b, semantic_a, semantic_b]
    embeddings = {
        same_a.id: [0.0, 1.0],
        same_b.id: [0.0, 1.0],
        semantic_a.id: [1.0, 0.0],
        semantic_b.id: [0.7, math.sqrt(0.51)],
    }

    strict, candidates = find_similarity_bands(
        chunks,
        embeddings,
        threshold=0.9,
        candidate_threshold=0.6,
        max_candidates=10,
        min_content_words=1,
        token_weight=0.3,
    )

    exact = next(pair for pair in strict if pair.chunk_a is same_a and pair.chunk_b is same_b)
    semantic = next(
        pair for pair in candidates if pair.chunk_a is semantic_a and pair.chunk_b is semantic_b
    )
    assert exact.embedding_cosine == 1.0
    assert exact.token_similarity == 1.0
    assert exact.combined_score == 1.0
    assert exact.embedding_similarity == exact.combined_score
    assert exact.confidence == "strict-match"
    assert semantic.embedding_cosine == 0.7
    assert semantic.token_similarity == 0.0
    assert semantic.combined_score == pytest.approx(0.49)
    assert semantic.confidence == "semantic-candidate"


def test_boilerplate_headings_do_not_flood_candidate_band() -> None:
    chunks = [
        _chunk(f"docs/{index}.md", "# Overview", f"generic overview boilerplate number {index}")
        for index in range(6)
    ]
    embeddings = {chunk.id: [1.0, 0.0] for chunk in chunks}
    boilerplate = detect_boilerplate_headings(chunks, num_documents=len(chunks))

    strict, candidates = find_similarity_bands(
        chunks,
        embeddings,
        threshold=0.9,
        candidate_threshold=0.6,
        min_content_words=1,
        boilerplate_headings=boilerplate,
    )

    assert strict == []
    assert candidates == []


def test_large_table_and_list_sections_get_line_accurate_secondary_chunks(tmp_path) -> None:
    table_rows = [
        f"| G{index} | publication readiness implementation parity restart priority "
        f"ownership validation evidence item {index} with enough bounded context |"
        for index in range(1, 7)
    ]
    list_rows = [
        f"- [ ] G{index}: validate publication hardening implementation parity and restart "
        f"priority ownership with detailed verification evidence for work item {index}"
        for index in range(7, 13)
    ]
    source_lines = [
        "# Roadmap",
        "",
        "## Open Register",
        "",
        "| ID | Work |",
        "|---|---|",
        *table_rows,
        "",
        "## Priority Buckets",
        "",
        *list_rows,
    ]
    path = tmp_path / "roadmap.md"
    path.write_text("\n".join(source_lines))

    chunks = chunk_file(path)
    table_chunks = [chunk for chunk in chunks if chunk.kind == "table-row"]
    list_chunks = [chunk for chunk in chunks if chunk.kind == "list-item"]

    assert len(table_chunks) == 6
    assert len(list_chunks) == 6
    assert [chunk.line_start for chunk in table_chunks] == list(range(7, 13))
    assert [chunk.line_start for chunk in list_chunks] == list(range(16, 22))
    for chunk in [*table_chunks, *list_chunks]:
        assert chunk.line_end >= chunk.line_start
        assert chunk.content == "\n".join(source_lines[chunk.line_start - 1 : chunk.line_end])
        assert chunk.parent_id
        assert chunk.heading_path[0] == "# Roadmap"


def _synonym_mapping_prompt(prompt: str) -> tuple[list[str], list[dict]]:
    existing_text = prompt.split("Existing canonical topics:\n", 1)[1].split(
        "\n\nTopic groups to map:\n", 1
    )[0]
    groups_text = prompt.split("Topic groups to map:\n", 1)[1].split(
        "\n\nRespond with ONLY valid JSON:", 1
    )[0]
    return json.loads(existing_text), json.loads(groups_text)


def test_serial_and_parallel_taxonomy_canonicalization_merge_same_synonyms(monkeypatch) -> None:
    from dryscope.docs import coding

    canonical = {
        "publication readiness": "publication hardening",
        "publication hardening": "publication hardening",
        "implementation parity": "core feature parity",
        "core feature parity": "core feature parity",
        "restart priorities": "priority execution buckets",
        "priority execution buckets": "priority execution buckets",
        "web runtime performance": "performance optimization",
        "performance optimization": "performance optimization",
    }
    calls: list[list[str]] = []

    def fake_call(_model, prompt, *_args, **_kwargs) -> str:
        existing, groups = _synonym_mapping_prompt(prompt)
        calls.append(existing)
        return json.dumps(
            {
                "mappings": [
                    {"raw": group["raw"], "canonical": canonical[group["raw"]]} for group in groups
                ]
            }
        )

    monkeypatch.setattr(coding, "call_llm_cached", fake_call)
    doc_topics = {f"/docs/{index}.md": [label] for index, label in enumerate(canonical, start=1)}

    serial = build_canonical_taxonomy(
        doc_topics,
        llm_model="fake-model",
        backend="cli",
        llm_batch_size=1,
        llm_concurrency=1,
    )
    serial_mapping = serial.raw_to_canonical
    calls.clear()
    parallel_requested = build_canonical_taxonomy(
        doc_topics,
        llm_model="fake-model",
        backend="cli",
        llm_batch_size=1,
        llm_concurrency=8,
    )

    assert parallel_requested.raw_to_canonical == serial_mapping
    assert len(parallel_requested.canonical_topics) == 4
    assert calls[0] == []
    assert all(len(existing) < len(canonical) for existing in calls)


def test_codex_default_model_executes_all_llm_stages(tmp_path, monkeypatch) -> None:
    from dryscope.docs import pipeline, taxonomy, topics

    roadmap = tmp_path / "roadmap.md"
    status = tmp_path / "status.md"
    roadmap.write_text(
        "# Roadmap\n\nPublication hardening and core feature parity remain owned by this roadmap."
    )
    status.write_text(
        "# Status\n\nRestart priorities reference publication readiness and implementation parity."
    )
    calls: list[tuple[str, str | None]] = []

    def fake_embed(chunks, *_args, **_kwargs):
        return {chunk.id: [1.0, 0.0] for chunk in chunks}

    def fake_bands(chunks, *_args, **_kwargs):
        pair = OverlapPair(
            chunks[0],
            next(chunk for chunk in chunks if chunk.document_path != chunks[0].document_path),
            embedding_similarity=0.65,
            embedding_cosine=0.72,
            token_similarity=0.48,
            combined_similarity=0.65,
            confidence="semantic-candidate",
        )
        return [], [pair]

    def fake_descriptors(documents, model, *_args, **_kwargs):
        calls.append(("descriptors", model))
        return {
            path: {
                "title": Path(path).stem,
                "about": ["publication readiness"],
                "reader_intents": ["understand restart priorities"],
            }
            for path in documents
        }

    def fake_taxonomy(doc_topics, *, llm_model, llm_enabled, **_kwargs):
        calls.append(("taxonomy", llm_model))
        assert llm_enabled is True
        return TopicTaxonomy(
            {}, {}, {path: ["publication hardening"] for path in doc_topics}, [], "llm"
        )

    def fake_docs_map(_taxonomy, *, llm_model, llm_enabled, **_kwargs):
        calls.append(("ia", llm_model))
        assert llm_enabled is True
        return {
            "method": "llm",
            "topic_tree": [],
            "facets": {},
            "diagnostics": [],
            "stage_status": {"status": "completed", "fallback": None},
        }

    def fake_doc_pairs(_groups, _chunks, model, *_args, **_kwargs):
        calls.append(("doc-pair-review", model))
        analysis = DocPairAnalysis(
            str(roadmap),
            str(status),
            "Owns the roadmap.",
            "Records status.",
            "complementary",
            [
                TopicAnalysis(
                    "publication-hardening", str(roadmap), "brief-reference", "Ownership differs."
                )
            ],
            "high",
        )
        return [analysis], [], [], []

    monkeypatch.setattr(pipeline, "embed_chunks", fake_embed)
    monkeypatch.setattr(pipeline, "find_similarity_bands", fake_bands)
    monkeypatch.setattr(pipeline, "run_doc_pair_pipeline", fake_doc_pairs)
    monkeypatch.setattr(pipeline, "_output_results", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(topics, "run_document_descriptor_extraction", fake_descriptors)
    monkeypatch.setattr(
        topics, "embed_topics", lambda labels, *_args: {label: [1.0] for label in labels}
    )
    monkeypatch.setattr(
        topics,
        "find_intent_doc_pairs",
        lambda *_args: {(min(str(roadmap), str(status)), max(str(roadmap), str(status))): []},
    )
    monkeypatch.setattr(taxonomy, "build_canonical_taxonomy", fake_taxonomy)
    monkeypatch.setattr(taxonomy, "build_docs_map", fake_docs_map)

    settings = Settings(
        backend="codex-cli",
        model=None,
        docs_embedding_model="all-MiniLM-L6-v2",
        cache_enabled=False,
        concurrency=1,
    )
    result = run_pipeline(
        tmp_path,
        settings,
        stage="docs-report-pack",
        skip_confirm=True,
        console=Console(stderr=True),
    )

    assert calls == [
        ("descriptors", None),
        ("taxonomy", None),
        ("ia", None),
        ("doc-pair-review", None),
    ]
    assert result.stage_status["docs-map"]["status"] == "completed"
    assert result.stage_status["docs-pair-review"]["status"] == "completed"


def test_timed_out_ia_is_degraded_not_clean(monkeypatch, tmp_path) -> None:
    from dryscope.docs import coding

    monkeypatch.setattr(
        coding,
        "call_llm_cached",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="codex exec", timeout=1)
        ),
    )
    taxonomy_data = build_canonical_taxonomy(
        {"/docs/a.md": ["publication hardening"], "/docs/b.md": ["publication hardening"]}
    ).to_dict()
    docs_map = build_docs_map(
        taxonomy_data,
        llm_model=None,
        llm_enabled=True,
        backend="codex-cli",
        llm_timeout=1,
    )
    result = AnalysisResult(
        topic_taxonomy={**taxonomy_data, "docs_map": docs_map},
        stage_status={"docs-map": docs_map["stage_status"]},
    )

    report = json.loads(
        render_json(result, [], None, settings=Settings(backend="codex-cli"), project_root=tmp_path)
    )

    assert docs_map["stage_status"]["status"] == "degraded"
    assert docs_map["stage_status"]["exception_category"] == "TimeoutExpired"
    assert report["summary"]["outcome"]["status"] == "degraded"
    assert "not clean-negative evidence" in report["summary"]["outcome"]["statement"].lower()


def test_dashboard_and_summary_count_doc_relationships_and_suggestions(tmp_path) -> None:
    roadmap = _chunk(str(tmp_path / "roadmap.md"), "# Roadmap", "canonical roadmap ownership")
    status = _chunk(str(tmp_path / "status.md"), "# Status", "status references roadmap")
    analysis = DocPairAnalysis(
        roadmap.document_path,
        status.document_path,
        "Roadmap purpose",
        "Status purpose",
        "complementary",
        [
            TopicAnalysis(
                "publication-hardening", roadmap.document_path, "brief-reference", "Link."
            ),
            TopicAnalysis("core-feature-parity", roadmap.document_path, "brief-reference", "Link."),
        ],
        "high",
    )
    result = AnalysisResult(
        documents=[
            Document(roadmap.document_path, [roadmap]),
            Document(status.document_path, [status]),
        ],
        chunks=[roadmap, status],
        doc_pair_analyses=[analysis],
        stage_status={
            "docs-section-match": {"status": "completed", "fallback": None},
            "docs-pair-review": {"status": "completed", "fallback": None},
        },
    )

    markdown = render_markdown(
        result,
        [],
        None,
        settings=Settings(),
        project_root=tmp_path,
        stages_run=["docs-section-match", "docs-pair-review"],
    )
    report = json.loads(
        render_json(
            result,
            [],
            None,
            settings=Settings(),
            project_root=tmp_path,
            stages_run=["docs-section-match", "docs-pair-review"],
        )
    )

    assert "Doc Relationships" in markdown
    assert "Doc Suggestions" in markdown
    assert report["summary"]["document_intent_relationships_found"] == 1
    assert report["summary"]["document_level_suggestions_found"] == 2
    assert report["summary"]["recommendations_count"] == 2


def test_provenance_records_scope_scoring_and_timeout(tmp_path) -> None:
    path = tmp_path / "docs" / "a.md"
    path.parent.mkdir()
    path.write_text("# A\n\nA bounded documentation section for provenance testing.")
    chunk = chunk_file(path)[0]
    result = AnalysisResult(
        documents=[Document(str(path), [chunk])],
        chunks=[chunk],
        stage_status={"docs-section-match": {"status": "completed", "fallback": None}},
    )
    settings = Settings(
        threshold_similarity=0.83,
        docs_candidate_threshold=0.61,
        token_weight=0.25,
        include_intra=True,
        min_content_words=7,
        llm_timeout=42,
        backend="codex-cli",
        model=None,
    )

    stage = serialize_section_match_stage(result, [], settings, tmp_path)
    metadata = stage["metadata"]
    config = metadata["config"]

    assert metadata["dryscope_version"]
    assert metadata["dryscope_source_revision"]
    assert metadata["input_files"] == ["docs/a.md"]
    assert config["threshold_similarity"] == 0.83
    assert config["threshold_label"] == "hybrid-similarity"
    assert config["candidate_threshold"] == 0.61
    assert config["token_weight"] == 0.25
    assert config["include_intra"] is True
    assert config["min_words"] == 7
    assert config["llm_timeout_seconds"] == 42
    assert config["effective_model_identity"] == "codex-cli:configured-default"
    assert stage["stage_status"]["status"] == "completed"


def test_installed_copy_recovers_revision_from_local_direct_url(tmp_path, monkeypatch) -> None:
    from dryscope.docs import report

    install_source = tmp_path / "canonical-source"
    install_source.mkdir()
    monkeypatch.setattr(report, "_installation_origin", lambda: install_source.as_uri())
    monkeypatch.setattr(
        report,
        "_git_commit",
        lambda root: "source-revision" if root == install_source else None,
    )
    monkeypatch.setattr(
        report,
        "_git_dirty",
        lambda root: True if root == install_source else None,
    )

    metadata = report._build_metadata(Settings(), tmp_path, result=AnalysisResult())

    assert metadata["installation_origin"] == "local-source"
    assert metadata["dryscope_source_path"] is None
    assert metadata["dryscope_source_type"] == "installed-package"
    assert metadata["dryscope_source_revision"] == "source-revision"
    assert metadata["dryscope_source_dirty"] is True


def test_report_and_stage_provenance_do_not_serialize_private_machine_paths(
    tmp_path, monkeypatch
) -> None:
    from dryscope.docs import report

    project_root = tmp_path / "private-workspace"
    document_path = project_root / "docs" / "a.md"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("# A\n\nPrivate path provenance must not leak into reports.")
    chunk = chunk_file(document_path)[0]
    result = AnalysisResult(
        documents=[Document(str(document_path), [chunk])],
        chunks=[chunk],
        stage_status={"docs-section-match": {"status": "completed", "fallback": None}},
    )
    private_home = "/" + "/".join(("home", "example"))
    private_origin = f"file://{private_home}/private/dryscope"
    monkeypatch.setattr(report, "_installation_origin", lambda: private_origin)

    outputs = [
        render_json(
            result,
            [],
            None,
            settings=Settings(),
            project_root=project_root,
            stages_run=["docs-section-match"],
        ),
        render_markdown(
            result,
            [],
            None,
            settings=Settings(),
            project_root=project_root,
            stages_run=["docs-section-match"],
        ),
        json.dumps(serialize_section_match_stage(result, [], Settings(), project_root)),
        json.dumps(report.render_final_report(result, [], None, Settings(), project_root)),
    ]

    for output in outputs:
        assert str(project_root) not in output
        assert private_home not in output
        assert "file:" + "///" not in output
        assert "docs/a.md" in output

    metadata = json.loads(outputs[0])["metadata"]
    assert metadata["project_root"] == "."
    assert metadata["dryscope_source_path"] is None
    assert metadata["installation_origin"] == "local-source"


def test_roadmap_status_fixture_surfaces_complementary_ownership_candidate(tmp_path) -> None:
    roadmap = _chunk(
        str(tmp_path / "roadmap.md"),
        "# Unified Open Register",
        "publication hardening core feature parity canonical ownership priority buckets",
    )
    status = _chunk(
        str(tmp_path / "project-status.md"),
        "# Restart Order",
        "publication readiness implementation parity restart priorities current evidence",
    )
    pair = OverlapPair(
        roadmap,
        status,
        embedding_similarity=0.55,
        embedding_cosine=0.68,
        token_similarity=0.25,
        combined_similarity=0.55,
        confidence="semantic-candidate",
    )
    analysis = DocPairAnalysis(
        roadmap.document_path,
        status.document_path,
        "Owns priorities and canonical work.",
        "Preserves restart evidence.",
        "complementary",
        [
            TopicAnalysis(
                "publication-hardening",
                roadmap.document_path,
                "brief-reference",
                "The roadmap owns the durable work; status keeps restart evidence.",
            )
        ],
        "high",
    )
    result = AnalysisResult(
        documents=[
            Document(roadmap.document_path, [roadmap]),
            Document(status.document_path, [status]),
        ],
        chunks=[roadmap, status],
        candidate_overlaps=[pair],
        doc_pair_analyses=[analysis],
        stage_status={
            "docs-section-match": {"status": "completed", "fallback": None},
            "docs-pair-review": {"status": "completed", "fallback": None},
        },
    )

    markdown = render_markdown(
        result,
        [],
        None,
        settings=Settings(),
        project_root=tmp_path,
        stages_run=["docs-section-match", "docs-pair-review"],
    )

    assert "semantic candidates" in markdown
    assert "complementary (high confidence)" in markdown
    assert "publication-hardening" in markdown
    assert "brief-reference" in markdown


def test_strict_zero_is_none_above_threshold_not_no_overlap(tmp_path) -> None:
    result = AnalysisResult(
        stage_status={"docs-section-match": {"status": "completed", "fallback": None}}
    )

    markdown = render_markdown(
        result,
        [],
        None,
        settings=Settings(),
        project_root=tmp_path,
        stages_run=["docs-section-match"],
    )

    assert "No section candidates were above the configured strict threshold" in markdown
    assert "not a claim that the scanned documents have no overlap" in markdown
