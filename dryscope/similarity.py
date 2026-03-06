"""Find duplicate clusters from embeddings using cosine similarity + Union-Find."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass
class DuplicatePair:
    """A pair of code units that are similar."""

    idx_a: int
    idx_b: int
    similarity: float


def _token_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Compute Jaccard-like similarity on token multisets (bag of tokens)."""
    if not tokens_a or not tokens_b:
        return 0.0
    counter_a = Counter(tokens_a)
    counter_b = Counter(tokens_b)
    intersection = sum((counter_a & counter_b).values())
    union = sum((counter_a | counter_b).values())
    return intersection / union if union > 0 else 0.0


class UnionFind:
    """Union-Find (disjoint set) for clustering."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def find_duplicates(
    embeddings: NDArray[np.float32],
    threshold: float = 0.90,
    line_counts: list[int] | None = None,
    max_size_ratio: float = 3.0,
    normalized_texts: list[str] | None = None,
    token_weight: float = 0.3,
) -> list[DuplicatePair]:
    """Find all pairs with combined similarity >= threshold.

    Uses a weighted combination of:
    - Embedding cosine similarity (captures semantic/structural similarity)
    - Token-level Jaccard similarity (captures content overlap)
    """
    n = embeddings.shape[0]
    if n < 2:
        return []

    sim_matrix = embeddings @ embeddings.T

    tokenized: list[list[str]] | None = None
    if normalized_texts is not None and token_weight > 0:
        tokenized = [text.split() for text in normalized_texts]

    if tokenized is not None:
        min_embed_sim = (threshold - token_weight) / (1 - token_weight)
    else:
        min_embed_sim = threshold

    pairs: list[DuplicatePair] = []
    for i in range(n):
        for j in range(i + 1, n):
            embed_sim = float(sim_matrix[i, j])
            if embed_sim < min_embed_sim:
                continue

            if line_counts is not None:
                lo, hi = sorted((line_counts[i], line_counts[j]))
                if lo > 0 and hi / lo > max_size_ratio:
                    continue

            if tokenized is not None:
                tok_sim = _token_similarity(tokenized[i], tokenized[j])
                combined = (1 - token_weight) * embed_sim + token_weight * tok_sim
            else:
                combined = embed_sim

            if combined >= threshold:
                pairs.append(DuplicatePair(idx_a=i, idx_b=j, similarity=combined))

    return pairs


def cluster_duplicates(
    n: int,
    pairs: list[DuplicatePair],
    max_cluster_size: int = 15,
) -> list[list[int]]:
    """Group duplicate pairs into clusters using Union-Find.

    Clusters exceeding max_cluster_size are dropped (they represent broad
    structural patterns, not actionable duplication).
    """
    if not pairs:
        return []

    uf = UnionFind(n)
    for pair in pairs:
        uf.union(pair.idx_a, pair.idx_b)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        clusters.setdefault(root, []).append(i)

    return [
        members for members in clusters.values()
        if 2 <= len(members) <= max_cluster_size
    ]
