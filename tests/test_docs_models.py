"""Tests for dryscope.docs.models — data models for document overlap detection."""

from dryscope.docs.models import Chunk


class TestChunkId:
    def test_id_uniqueness_different_files(self):
        """Same content in different files should produce different IDs."""
        chunk_a = Chunk(
            document_path="docs/a.md",
            heading_path=["# Setup"],
            content="Install the package with pip.",
            line_start=1,
            line_end=5,
        )
        chunk_b = Chunk(
            document_path="docs/b.md",
            heading_path=["# Setup"],
            content="Install the package with pip.",
            line_start=1,
            line_end=5,
        )
        assert chunk_a.id != chunk_b.id

    def test_id_stability(self):
        """Same content, file, and line should produce the same ID."""
        chunk_1 = Chunk(
            document_path="docs/a.md",
            heading_path=["# Intro"],
            content="Hello world",
            line_start=10,
            line_end=15,
        )
        chunk_2 = Chunk(
            document_path="docs/a.md",
            heading_path=["# Intro"],
            content="Hello world",
            line_start=10,
            line_end=15,
        )
        assert chunk_1.id == chunk_2.id

    def test_id_is_hex_string(self):
        chunk = Chunk(
            document_path="f.md",
            heading_path=[],
            content="test",
            line_start=1,
            line_end=1,
        )
        assert isinstance(chunk.id, str)
        assert len(chunk.id) == 16
        # Should be valid hex
        int(chunk.id, 16)

    def test_different_line_start_different_id(self):
        """Same content and file but different line_start should differ
        because the id hash includes content (which is the same), but
        the formula uses line_start."""
        chunk_a = Chunk(
            document_path="f.md",
            heading_path=[],
            content="same content",
            line_start=1,
            line_end=5,
        )
        chunk_b = Chunk(
            document_path="f.md",
            heading_path=[],
            content="same content",
            line_start=10,
            line_end=15,
        )
        assert chunk_a.id != chunk_b.id
