"""Generate vector embeddings for normalized code units."""

from __future__ import annotations

import os
import sys
import numpy as np
from numpy.typing import NDArray


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
            self.model = SentenceTransformer(model_name, device="cpu")
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
