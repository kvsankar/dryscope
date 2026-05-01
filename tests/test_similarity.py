"""Tests for dryscope.similarity — cosine similarity, Union-Find, and clustering."""

import numpy as np
import pytest

from dryscope.similarity import (
    DuplicatePair,
    UnionFind,
    _token_similarity,
    cluster_duplicates,
    find_duplicates,
)

# ── UnionFind ───────────────────────────────────────────────────────────


class TestUnionFind:
    def test_initial_elements_are_their_own_root(self):
        uf = UnionFind(5)
        for i in range(5):
            assert uf.find(i) == i

    def test_union_merges_sets(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        assert uf.find(0) == uf.find(1)

    def test_union_transitivity(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.find(0) == uf.find(2)

    def test_disjoint_sets_remain_separate(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(3, 4)
        assert uf.find(0) != uf.find(3)

    def test_union_idempotent(self):
        uf = UnionFind(3)
        uf.union(0, 1)
        root_before = uf.find(0)
        uf.union(0, 1)
        assert uf.find(0) == root_before

    def test_path_compression(self):
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(2, 3)
        root = uf.find(3)
        # After find with path compression, parent should point closer to root
        assert uf.find(3) == root
        assert uf.find(0) == root


# ── find_duplicates ─────────────────────────────────────────────────────


class TestFindDuplicates:
    def _make_embeddings(self, vectors: list[list[float]]) -> np.ndarray:
        arr = np.array(vectors, dtype=np.float32)
        # Normalize rows
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms

    def test_identical_vectors_are_duplicates(self):
        vecs = self._make_embeddings(
            [
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        )
        pairs = find_duplicates(vecs, threshold=0.90)
        assert len(pairs) >= 1
        assert pairs[0].idx_a == 0
        assert pairs[0].idx_b == 1

    def test_orthogonal_vectors_not_duplicates(self):
        vecs = self._make_embeddings(
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        pairs = find_duplicates(vecs, threshold=0.90)
        assert len(pairs) == 0

    def test_single_vector_returns_empty(self):
        vecs = self._make_embeddings([[1.0, 0.0, 0.0]])
        pairs = find_duplicates(vecs, threshold=0.90)
        assert pairs == []

    def test_threshold_affects_result(self):
        vecs = self._make_embeddings(
            [
                [1.0, 0.1, 0.0],
                [1.0, 0.2, 0.0],
            ]
        )
        # With low threshold should find pair
        pairs_low = find_duplicates(vecs, threshold=0.5)
        assert len(pairs_low) >= 1
        # With very high threshold may not
        pairs_high = find_duplicates(vecs, threshold=1.0)
        assert len(pairs_high) == 0

    def test_size_ratio_filter(self):
        vecs = self._make_embeddings(
            [
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
            ]
        )
        # Line counts with ratio > 3 should be filtered
        pairs = find_duplicates(vecs, threshold=0.90, line_counts=[10, 40], max_size_ratio=3.0)
        assert len(pairs) == 0

    def test_size_ratio_within_range(self):
        vecs = self._make_embeddings(
            [
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
            ]
        )
        pairs = find_duplicates(vecs, threshold=0.90, line_counts=[10, 20], max_size_ratio=3.0)
        assert len(pairs) == 1


# ── cluster_duplicates ──────────────────────────────────────────────────


class TestClusterDuplicates:
    def test_no_pairs_returns_empty(self):
        clusters = cluster_duplicates(5, [])
        assert clusters == []

    def test_single_pair_creates_one_cluster(self):
        pairs = [DuplicatePair(idx_a=0, idx_b=1, similarity=0.95)]
        clusters = cluster_duplicates(3, pairs)
        assert len(clusters) == 1
        assert sorted(clusters[0]) == [0, 1]

    def test_transitive_pairs_merge(self):
        pairs = [
            DuplicatePair(idx_a=0, idx_b=1, similarity=0.95),
            DuplicatePair(idx_a=1, idx_b=2, similarity=0.92),
        ]
        clusters = cluster_duplicates(4, pairs)
        assert len(clusters) == 1
        assert sorted(clusters[0]) == [0, 1, 2]

    def test_disjoint_pairs_create_separate_clusters(self):
        pairs = [
            DuplicatePair(idx_a=0, idx_b=1, similarity=0.95),
            DuplicatePair(idx_a=2, idx_b=3, similarity=0.92),
        ]
        clusters = cluster_duplicates(5, pairs)
        assert len(clusters) == 2

    def test_max_cluster_size_drops_large_clusters(self):
        # Create a big cluster of 5 elements
        pairs = [DuplicatePair(idx_a=i, idx_b=i + 1, similarity=0.95) for i in range(4)]
        clusters = cluster_duplicates(5, pairs, max_cluster_size=3)
        assert len(clusters) == 0  # cluster of 5 exceeds max_cluster_size=3


# ── DuplicatePair ───────────────────────────────────────────────────────


# ── _token_similarity ──────────────────────────────────────────────────


class TestTokenSimilarity:
    def test_token_similarity_identical(self):
        assert _token_similarity(["a", "b"], ["a", "b"]) == 1.0

    def test_token_similarity_disjoint(self):
        assert _token_similarity(["a"], ["b"]) == 0.0

    def test_token_similarity_partial(self):
        # Jaccard on multisets: intersection={a,b}=2, union={a,b,c,d}=4 => 2/4=0.5
        result = _token_similarity(["a", "b", "c"], ["a", "b", "d"])
        assert result == pytest.approx(0.5)

    def test_token_similarity_empty(self):
        assert _token_similarity([], []) == 0.0


# ── find_duplicates with normalized_texts ──────────────────────────────


class TestFindDuplicatesHybrid:
    def _make_embeddings(self, vectors: list[list[float]]) -> np.ndarray:
        arr = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms

    def test_find_duplicates_with_normalized_texts(self):
        # Two identical embedding vectors but different tokens should still match
        vecs = self._make_embeddings(
            [
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        )
        texts = ["VAR_0 = VAR_1 + VAR_2", "VAR_0 = VAR_1 + VAR_2", "something else entirely"]
        pairs = find_duplicates(vecs, threshold=0.90, normalized_texts=texts, token_weight=0.3)
        assert len(pairs) >= 1
        # The identical pair should have combined sim = 0.7*1.0 + 0.3*1.0 = 1.0
        assert pairs[0].similarity == pytest.approx(1.0)

    def test_find_duplicates_token_weight_zero(self):
        # With token_weight=0, result should be pure embedding similarity
        vecs = self._make_embeddings(
            [
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
            ]
        )
        texts = ["completely different", "not at all the same"]
        pairs = find_duplicates(vecs, threshold=0.90, normalized_texts=texts, token_weight=0.0)
        assert len(pairs) == 1
        # Pure cosine similarity of identical vectors = 1.0
        assert pairs[0].similarity == pytest.approx(1.0)


# ── DuplicatePair ───────────────────────────────────────────────────────


class TestDuplicatePair:
    def test_fields(self):
        pair = DuplicatePair(idx_a=0, idx_b=1, similarity=0.95)
        assert pair.idx_a == 0
        assert pair.idx_b == 1
        assert pair.similarity == 0.95
