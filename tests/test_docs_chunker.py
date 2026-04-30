"""Regression tests for documentation file discovery and chunking."""

from dryscope.config import DEFAULT_INCLUDE
from dryscope.docs.chunker import chunk_file, discover_files


def test_default_include_covers_mdx() -> None:
    assert "*.mdx" in DEFAULT_INCLUDE


def test_discover_files_includes_mdx(tmp_path) -> None:
    doc = tmp_path / "guide.mdx"
    doc.write_text("# Guide\n\nThis is a real MDX documentation page.\n")

    files = discover_files(tmp_path, DEFAULT_INCLUDE, [])

    assert files == [doc]


def test_chunk_file_treats_mdx_as_markdown(tmp_path) -> None:
    doc = tmp_path / "guide.mdx"
    doc.write_text("# Intro\n\nFirst section.\n\n## Details\n\nSecond section.\n")

    chunks = chunk_file(doc)

    assert [chunk.heading_path for chunk in chunks] == [["# Intro"], ["# Intro", "## Details"]]
