"""Generate vector embeddings for normalized code units."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray


class EmbeddingError(RuntimeError):
    """Base class for concise, user-facing embedding failures."""


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when an embedding model cannot run with the current setup."""


class EmbeddingRequestError(EmbeddingError):
    """Raised when an embedding provider request fails."""


def is_api_embedding_model(model_name: str) -> bool:
    """Return True when model_name should be resolved through LiteLLM embeddings."""
    name = model_name.lower()
    api_prefixes = (
        "text-embedding-",
        "voyage-",
        "embed-",
        "cohere/",
        "openai/",
        "azure/",
        "bedrock/",
    )
    return any(name.startswith(prefix) for prefix in api_prefixes)


def _required_embedding_credentials(model_name: str) -> tuple[str, ...]:
    """Return well-known credentials for API embedding models when unambiguous."""
    name = model_name.lower()
    if name.startswith(("text-embedding-", "openai/")):
        return ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY")
    if name.startswith("voyage-"):
        return ("VOYAGE_API_KEY",)
    if name.startswith(("cohere/", "embed-")):
        return ("COHERE_API_KEY",)
    if name.startswith("azure/"):
        return ("AZURE_API_KEY", "AZURE_OPENAI_API_KEY")
    return ()


def _embedding_remediation(model_name: str) -> str:
    """Return the shared API/local remediation for embedding failures."""
    return (
        f"Configure credentials for embedding model {model_name!r}, or install "
        "`dryscope[local-embeddings]` and pass "
        "`--embedding-model all-MiniLM-L6-v2`. LLM backends such as "
        "`codex-cli` authenticate completion/review calls only; they do not supply embeddings."
    )


def _local_embedding_remediation(model_name: str) -> str:
    """Return concise setup guidance for local embedding failures."""
    return (
        f"Check that local model {model_name!r} is available and that "
        "`dryscope[local-embeddings]` is installed. The first use may require "
        "network access to download the model."
    )


def validate_embedding_configuration(model_name: str) -> None:
    """Fail before concurrent API calls when a known provider credential is absent."""
    if not is_api_embedding_model(model_name):
        return
    credentials = _required_embedding_credentials(model_name)
    if credentials and not any(os.environ.get(name) for name in credentials):
        names = " or ".join(credentials)
        raise EmbeddingConfigurationError(
            f"Embedding model {model_name!r} requires {names}. "
            + _embedding_remediation(model_name)
        )


def embed_api_texts(texts: list[str], model_name: str) -> list[list[float]]:
    """Embed a batch through LiteLLM with concise, provider-neutral failures."""
    validate_embedding_configuration(model_name)
    try:
        import litellm
    except ImportError as exc:
        raise EmbeddingConfigurationError(
            "API embedding models require LiteLLM. Install the standard Dryscope package. "
            + _embedding_remediation(model_name)
        ) from exc

    # Avoid LiteLLM's repeated feedback/debug banners; Dryscope reports one
    # actionable stage error instead.
    litellm_runtime: Any = litellm
    litellm_runtime.suppress_debug_info = True
    try:
        response = litellm.embedding(model=model_name, input=texts)
        vectors = [list(item["embedding"]) for item in response.data]
        if len(vectors) != len(texts):
            raise ValueError(
                f"provider returned {len(vectors)} vectors for {len(texts)} input texts"
            )
        return vectors
    except Exception as exc:
        raise EmbeddingRequestError(
            f"Embedding request for model {model_name!r} failed via LiteLLM "
            f"({type(exc).__name__}). Check provider credentials and network access. "
            + _embedding_remediation(model_name)
        ) from None


def _has_local_huggingface_cache(model_name: str) -> bool:
    """Return True if the sentence-transformer model already exists in HF cache."""
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    model_ids = [model_name]
    if "/" not in model_name:
        model_ids.append(f"sentence-transformers/{model_name}")
    return any(
        (snapshots := cache_root / f"models--{model_id.replace('/', '--')}" / "snapshots").exists()
        and any(snapshots.iterdir())
        for model_id in model_ids
    )


class Embedder:
    """Generates embeddings through API models or local sentence-transformers."""

    def __init__(self, model_name: str = "text-embedding-3-small"):
        self.model_name = model_name
        self.model: Any = None
        if is_api_embedding_model(model_name):
            return

        # Lazy import to avoid slow startup when not needed
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingConfigurationError(
                "Local embedding model requires the optional local embedding stack. "
                "Install dryscope with `dryscope[local-embeddings]`, or use an API "
                "embedding model such as `text-embedding-3-small`."
            ) from exc

        # Suppress noisy "UNEXPECTED key" / "LOAD REPORT" from model loader
        # Must redirect at OS fd level — the C library writes directly
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        try:
            local_files_only = _has_local_huggingface_cache(model_name)
            try:
                self.model = SentenceTransformer(
                    model_name,
                    device="cpu",
                    local_files_only=local_files_only,
                )
            except Exception:
                if local_files_only:
                    self.model = SentenceTransformer(model_name, device="cpu")
                else:
                    raise
        except Exception as exc:
            raise EmbeddingConfigurationError(
                f"Local embedding model {model_name!r} could not be loaded "
                f"({type(exc).__name__}). {_local_embedding_remediation(model_name)}"
            ) from None
        finally:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            os.close(devnull_fd)

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        """Embed a batch of texts, returning an (N, D) array of float32 vectors."""
        if not texts:
            return np.empty((0, 0), dtype=np.float32)

        if is_api_embedding_model(self.model_name):
            embeddings = np.array(embed_api_texts(texts, self.model_name), dtype=np.float32)
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1
            return (embeddings / norms).astype(np.float32)

        try:
            embeddings = self.model.encode(
                texts,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,  # pre-normalize for fast dot-product similarity
            )
            return embeddings.astype(np.float32)
        except Exception as exc:
            raise EmbeddingRequestError(
                f"Local embedding generation with model {self.model_name!r} failed "
                f"({type(exc).__name__}). {_local_embedding_remediation(self.model_name)}"
            ) from None
