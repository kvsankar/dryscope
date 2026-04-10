"""Generate vector embeddings for normalized code units."""

from __future__ import annotations

import os
import sys
from pathlib import Path
import numpy as np
from numpy.typing import NDArray


def _has_local_huggingface_cache(model_name: str) -> bool:
    """Return True if the sentence-transformer model already exists in HF cache."""
    safe_name = model_name.replace("/", "--")
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{safe_name}"
    snapshots = cache_dir / "snapshots"
    return snapshots.exists() and any(snapshots.iterdir())


class Embedder:
    """Generates embeddings using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # Lazy import to avoid slow startup when not needed
        from sentence_transformers import SentenceTransformer

        # Suppress noisy "UNEXPECTED key" / "LOAD REPORT" from model loader
        # Must redirect at OS fd level — the C library writes directly
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        try:
            kwargs = {"device": "cpu"}
            if _has_local_huggingface_cache(model_name):
                kwargs["local_files_only"] = True
            try:
                self.model = SentenceTransformer(model_name, **kwargs)
            except Exception:
                if kwargs.get("local_files_only"):
                    kwargs.pop("local_files_only", None)
                    self.model = SentenceTransformer(model_name, **kwargs)
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

        embeddings = self.model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,  # pre-normalize for cosine similarity via dot product
        )
        return embeddings.astype(np.float32)
