"""Tests for dryscope.unified_report — unified JSON and terminal reporters."""

import json

from dryscope.code.parser import CodeUnit
from dryscope.code.reporter import Cluster, Tier
from dryscope.docs.models import Chunk, OverlapPair
from dryscope.unified_report import format_unified_json, format_unified_terminal


def _make_cluster(cluster_id=0, tier=Tier.EXACT, similarity=0.98) -> Cluster:
    """Helper to create a Cluster with minimal data."""
    unit_a = CodeUnit(
        name="func_a", unit_type="function",
        source="def func_a():\n    return 1",
        file_path="a.py", start_line=1, end_line=2,
    )
    unit_b = CodeUnit(
        name="func_b", unit_type="function",
        source="def func_b():\n    return 1",
        file_path="b.py", start_line=1, end_line=2,
    )
    return Cluster(
        cluster_id=cluster_id,
        units=[unit_a, unit_b],
        max_similarity=similarity,
        tier=tier,
        is_cross_file=True,
        total_lines=4,
        files=["a.py", "b.py"],
        actionability=1.5,
    )


# ── format_unified_json ─────────────────────────────────────────────────


class TestFormatUnifiedJson:
    def test_with_code_clusters(self):
        clusters = [_make_cluster()]
        result = format_unified_json(code_clusters=clusters)
        data = json.loads(result)
        assert "dryscope_version" in data
        assert data["report_pack"] == {
            "label": "Code Report Pack",
            "slug": "code-report-pack",
        }
        assert data["track"] == "Code Match"
        assert data["track_slug"] == "code-match"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["mode"] == "code"
        assert data["findings"][0]["tier"] == "exact"
        assert data["summary"]["code"]["total"] == 1
        assert data["summary"]["code"]["exact"] == 1

    def test_with_empty_clusters(self):
        result = format_unified_json(code_clusters=[])
        data = json.loads(result)
        assert data["findings"] == []
        assert data["summary"]["code"]["total"] == 0

    def test_with_verified_code_clusters_uses_code_review_track(self):
        cluster = _make_cluster()
        cluster.verdict = "review"
        result = format_unified_json(code_clusters=[cluster])
        data = json.loads(result)
        assert data["track"] == "Code Review"
        assert data["track_slug"] == "code-review"

    def test_none_clusters_no_code_summary(self):
        result = format_unified_json(code_clusters=None)
        data = json.loads(result)
        assert "code" not in data["summary"]
        assert data["findings"] == []

    def test_multiple_clusters(self):
        clusters = [
            _make_cluster(cluster_id=0, tier=Tier.EXACT, similarity=0.99),
            _make_cluster(cluster_id=1, tier=Tier.NEAR, similarity=0.96),
        ]
        result = format_unified_json(code_clusters=clusters)
        data = json.loads(result)
        assert len(data["findings"]) == 2
        assert data["summary"]["code"]["total"] == 2

    def test_finding_fields(self):
        clusters = [_make_cluster()]
        result = format_unified_json(code_clusters=clusters)
        data = json.loads(result)
        finding = data["findings"][0]
        assert "id" in finding
        assert "similarity" in finding
        assert "is_cross_file" in finding
        assert "units" in finding
        assert len(finding["units"]) == 2


# ── format_unified_terminal ─────────────────────────────────────────────


class TestFormatUnifiedTerminal:
    def test_with_code_clusters(self):
        clusters = [_make_cluster()]
        result = format_unified_terminal(code_clusters=clusters)
        assert "Code Match" in result

    def test_none_clusters_no_output(self):
        result = format_unified_terminal(code_clusters=None)
        assert "Code Match" not in result

    def test_empty_clusters_shows_no_duplicates(self):
        result = format_unified_terminal(code_clusters=[])
        assert "Code Match" in result
        assert "No Code Match clusters found" in result

    def test_doc_pairs_none(self):
        result = format_unified_terminal(doc_pairs=None)
        assert "Section Match" not in result

    def test_doc_pairs_empty(self):
        result = format_unified_terminal(doc_pairs=[])
        assert "Section Match" in result
        assert "No matched documentation sections found" in result


# ── format_unified_json with doc_pairs ─────────────────────────────────


class TestFormatUnifiedJsonWithDocPairs:
    def test_format_unified_json_with_doc_pairs(self):
        chunk_a = Chunk(
            document_path="docs/guide.md",
            heading_path=["Getting Started", "Installation"],
            content="Install the package using pip install dryscope.",
            line_start=10,
            line_end=15,
        )
        chunk_b = Chunk(
            document_path="docs/readme.md",
            heading_path=["Setup"],
            content="Install dryscope with pip install dryscope.",
            line_start=5,
            line_end=8,
        )
        pair = OverlapPair(chunk_a=chunk_a, chunk_b=chunk_b, embedding_similarity=0.92)

        result = format_unified_json(doc_pairs=[pair])
        data = json.loads(result)

        assert len(data["findings"]) == 1
        finding = data["findings"][0]
        assert finding["mode"] == "docs"
        assert finding["similarity"] == 0.92
        assert len(finding["sections"]) == 2

        section_a = finding["sections"][0]
        assert section_a["file"] == "docs/guide.md"
        assert "Installation" in section_a["heading"]
        assert "Install" in section_a["content"]

        section_b = finding["sections"][1]
        assert section_b["file"] == "docs/readme.md"
        assert section_b["heading"] == "Setup"

        assert data["summary"]["docs"]["total"] == 1
