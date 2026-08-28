"""Tests for dryscope.code.embedder."""

from __future__ import annotations

import sys
import types

import pytest

from dryscope.code.embedder import (
    Embedder,
    EmbeddingConfigurationError,
    EmbeddingRequestError,
    _has_local_huggingface_cache,
    is_api_embedding_model,
    validate_embedding_configuration,
)


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


def test_api_embedding_model_detection():
    assert is_api_embedding_model("text-embedding-3-small") is True
    assert is_api_embedding_model("openai/text-embedding-3-small") is True
    assert is_api_embedding_model("voyage-3") is True
    assert is_api_embedding_model("all-MiniLM-L6-v2") is False


def test_embedder_uses_litellm_for_api_models(monkeypatch):
    captured: dict = {}
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class FakeLiteLLM:
        @staticmethod
        def embedding(**kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                data=[
                    {"embedding": [3.0, 0.0, 4.0]},
                    {"embedding": [0.0, 5.0, 0.0]},
                ]
            )

    monkeypatch.setitem(sys.modules, "litellm", FakeLiteLLM)

    vectors = Embedder("text-embedding-3-small").embed(["alpha", "beta"])

    assert captured == {
        "model": "text-embedding-3-small",
        "input": ["alpha", "beta"],
    }
    assert vectors.shape == (2, 3)
    assert vectors[0].tolist() == pytest.approx([0.6, 0.0, 0.8])
    assert vectors[1].tolist() == pytest.approx([0.0, 1.0, 0.0])


def test_missing_api_embedding_credentials_explain_codex_boundary(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)

    with pytest.raises(EmbeddingConfigurationError) as raised:
        validate_embedding_configuration("text-embedding-3-small")

    message = str(raised.value)
    assert "requires OPENAI_API_KEY or OPENAI_ADMIN_KEY" in message
    assert "codex-cli" in message
    assert "do not supply embeddings" in message
    assert "all-MiniLM-L6-v2" in message


def test_api_embedding_provider_failure_is_wrapped_without_raw_detail(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class FakeLiteLLM:
        @staticmethod
        def embedding(**_kwargs):
            raise ValueError("provider detail that should not reach the user")

    monkeypatch.setitem(sys.modules, "litellm", FakeLiteLLM)

    with pytest.raises(EmbeddingRequestError) as raised:
        Embedder("text-embedding-3-small").embed(["alpha"])

    message = str(raised.value)
    assert "failed via LiteLLM (ValueError)" in message
    assert "provider detail" not in message
    assert "all-MiniLM-L6-v2" in message


def test_missing_sentence_transformers_has_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(RuntimeError, match=r"dryscope\[local-embeddings\]"):
        Embedder("all-MiniLM-L6-v2")


def test_local_model_load_failure_is_wrapped_without_raw_detail(monkeypatch):
    class FakeSentenceTransformer:
        def __init__(self, *_args, **_kwargs):
            raise ValueError("private loader detail")

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    with pytest.raises(EmbeddingConfigurationError) as raised:
        Embedder("all-MiniLM-L6-v2")

    message = str(raised.value)
    assert "could not be loaded (ValueError)" in message
    assert "dryscope[local-embeddings]" in message
    assert "private loader detail" not in message


def test_local_encode_failure_is_wrapped_without_raw_detail(monkeypatch):
    class FakeSentenceTransformer:
        def __init__(self, *_args, **_kwargs):
            pass

        def encode(self, *_args, **_kwargs):
            raise ValueError("private encode detail")

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    embedder = Embedder("all-MiniLM-L6-v2")

    with pytest.raises(EmbeddingRequestError) as raised:
        embedder.embed(["alpha"])

    message = str(raised.value)
    assert "Local embedding generation" in message
    assert "failed (ValueError)" in message
    assert "private encode detail" not in message
