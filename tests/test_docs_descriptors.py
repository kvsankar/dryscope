"""Tests for rich documentation IA descriptors."""

from dryscope.docs.models import Chunk
from dryscope.docs.topics import _descriptor_fallback, descriptor_labels


def test_descriptor_labels_combines_about_and_reader_intents() -> None:
    descriptor = {
        "about": ["kernel loading", "ephemeris data"],
        "reader_intents": ["load kernels in an application", "kernel loading"],
    }

    assert descriptor_labels(descriptor) == [
        "kernel loading",
        "ephemeris data",
        "load kernels in an application",
    ]


def test_descriptor_fallback_infers_role_and_lifecycle_from_path() -> None:
    chunks = [
        Chunk(
            "/repo/docs/history/status/2026-01-01-api-audit.md",
            ["API Audit"],
            "Audit content",
            1,
            2,
        )
    ]

    descriptor = _descriptor_fallback(chunks[0].document_path, chunks)

    assert descriptor["doc_role"] == "status"
    assert descriptor["lifecycle"] == "historical"
    assert descriptor["about"] == ["API Audit"]
