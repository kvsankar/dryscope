"""Tests for dryscope.code.embedder."""

from __future__ import annotations

import sys
import types

from dryscope.code.embedder import Embedder, _has_local_huggingface_cache


def test_has_local_huggingface_cache_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert _has_local_huggingface_cache("sentence-transformers/all-MiniLM-L6-v2") is False


def test_embedder_prefers_local_files_when_cached(tmp_path, monkeypatch):
    snapshots = (
        tmp_path
        / ".cache"
        / "huggingface"
        / "hub"
        / "models--all-MiniLM-L6-v2"
        / "snapshots"
        / "abc123"
    )
    snapshots.mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    calls: list[dict] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            calls.append({"model_name": model_name, **kwargs})

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    Embedder("all-MiniLM-L6-v2")

    assert calls[0]["local_files_only"] is True
    assert calls[0]["device"] == "cpu"
