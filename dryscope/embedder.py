"""Generate vector embeddings for normalized code units."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


class Embedder:
    """Generates embeddings using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # Lazy import to avoid slow startup when not needed
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

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
