"""Generate vector embeddings for normalized code units."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray


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


def _has_local_huggingface_cache(model_name: str) -> bool:
    """Return True if the sentence-transformer model already exists in HF cache."""
    safe_name = model_name.replace("/", "--")
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{safe_name}"
    snapshots = cache_dir / "snapshots"
    return snapshots.exists() and any(snapshots.iterdir())


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
            raise RuntimeError(
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
            try:
                import litellm
            except ImportError as exc:
                raise RuntimeError(
                    "API embedding model requires LiteLLM. Install dryscope with "
                    "API embedding support or install `litellm`."
                ) from exc
            response = litellm.embedding(model=self.model_name, input=texts)
            embeddings = np.array(
                [item["embedding"] for item in response.data],
                dtype=np.float32,
            )
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1
            return (embeddings / norms).astype(np.float32)

        embeddings = self.model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,  # pre-normalize for fast dot-product similarity
        )
        return embeddings.astype(np.float32)
