"""Embedding-based semantic similarity via sentence-transformers (local) or litellm (API)."""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from dryscope.cache import Cache
from dryscope.code.embedder import Embedder, is_api_embedding_model
from dryscope.docs.models import Chunk, OverlapPair
from dryscope.similarity import cosine_similarity_matrix


def _token_jaccard(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity on token multisets (bag of words).

    Uses lowercased word tokens. Returns 0.0 if either text is empty.
    """
    tokens_a = text_a.lower().split()
    tokens_b = text_b.lower().split()
    if not tokens_a or not tokens_b:
        return 0.0
    counter_a = Counter(tokens_a)
    counter_b = Counter(tokens_b)
    intersection = sum((counter_a & counter_b).values())
    union = sum((counter_a | counter_b).values())
    return intersection / union if union > 0 else 0.0


# ─── Sentence-transformers lazy singleton ─────────────────────────────

_st_model = None
_st_model_name = None
_st_lock = threading.Lock()


def _get_sentence_transformer(model_name: str):
    """Lazily load a sentence-transformers model singleton."""
    global _st_model, _st_model_name
    with _st_lock:
        if _st_model is None or _st_model_name != model_name:
            _st_model = Embedder(model_name)
            _st_model_name = model_name
        return _st_model


def _is_api_model(model_name: str) -> bool:
    """Backward-compatible alias for API embedding model detection."""
    return is_api_embedding_model(model_name)


# ─── Existing litellm-based helpers ────────────────────────────────────


def get_embedding(text: str, model: str, cache: Cache | None = None) -> list[float]:
    """Get embedding vector for text via litellm, using cache if available."""
    if cache is not None:
        cached = cache.get_embedding(text, model)
        if cached is not None:
            return cached

    try:
        import litellm
    except ImportError as exc:
        raise RuntimeError(
            "API embedding model requires LiteLLM. Install dryscope with "
            "API embedding support or install `litellm`."
        ) from exc
    response = litellm.embedding(model=model, input=[text])
    vector = response.data[0]["embedding"]

    if cache is not None:
        cache.set_embedding(text, model, vector)

    return vector


def refine_with_embeddings(
    pairs: list[OverlapPair],
    model: str,
    threshold: float = 0.85,
    cache: Cache | None = None,
    on_progress: Callable[..., None] | None = None,
    concurrency: int = 1,
) -> list[OverlapPair]:
    """Refine candidate pairs using embedding similarity.

    Only embeds chunks involved in the provided pairs (cost optimization).
    Returns pairs that pass the embedding similarity threshold.
    """
    # Collect unique chunks to embed
    chunks_to_embed: dict[str, Chunk] = {}
    for pair in pairs:
        chunks_to_embed[pair.chunk_a.id] = pair.chunk_a
        chunks_to_embed[pair.chunk_b.id] = pair.chunk_b

    # Compute embeddings
    embeddings: dict[str, list[float]] = {}
    total = len(chunks_to_embed)
    items = list(chunks_to_embed.items())

    if concurrency > 1 and items:
        progress_lock = threading.Lock()
        done_count = 0

        def _embed_one(chunk_id: str, chunk: Chunk) -> tuple[str, list[float]]:
            return chunk_id, get_embedding(chunk.content, model, cache)

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_embed_one, chunk_id, chunk): chunk_id for chunk_id, chunk in items
            }
            for future in as_completed(futures):
                chunk_id, vector = future.result()
                embeddings[chunk_id] = vector
                with progress_lock:
                    done_count += 1
                    if on_progress:
                        on_progress(done_count, total)
    else:
        for i, (chunk_id, chunk) in enumerate(items):
            embeddings[chunk_id] = get_embedding(chunk.content, model, cache)
            if on_progress:
                on_progress(i + 1, total)

    # Compute similarity for each pair (numpy dot product on L2-normalized vectors)
    refined: list[OverlapPair] = []
    for pair in pairs:
        vec_a = np.array(embeddings[pair.chunk_a.id])
        vec_b = np.array(embeddings[pair.chunk_b.id])
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        if norm_a == 0 or norm_b == 0:
            sim = 0.0
        else:
            sim = float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
        pair.embedding_similarity = sim
        if sim >= threshold:
            refined.append(pair)

    refined.sort(key=lambda p: -(p.embedding_similarity or 0))
    return refined


# ─── New v0.5 functions: embed_chunks + find_similar_pairs ─────────────


def embed_chunks(
    chunks: list[Chunk],
    model_name: str,
    cache: Cache | None = None,
    on_progress: Callable[..., None] | None = None,
    concurrency: int = 1,
) -> dict[str, list[float]]:
    """Embed all chunks. sentence-transformers for local models, litellm for API models.

    Returns dict mapping chunk.id -> embedding vector.
    """
    if not chunks:
        return {}

    embeddings: dict[str, list[float]] = {}

    if _is_api_model(model_name):
        # API path: use litellm with concurrency and cache
        total = len(chunks)
        if concurrency > 1:
            progress_lock = threading.Lock()
            done_count = 0

            def _embed_one(chunk: Chunk) -> tuple[str, list[float]]:
                return chunk.id, get_embedding(chunk.content, model_name, cache)

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(_embed_one, chunk): chunk for chunk in chunks}
                for future in as_completed(futures):
                    chunk_id, vector = future.result()
                    embeddings[chunk_id] = vector
                    with progress_lock:
                        done_count += 1
                        if on_progress:
                            on_progress(done_count, total)
        else:
            for i, chunk in enumerate(chunks):
                embeddings[chunk.id] = get_embedding(chunk.content, model_name, cache)
                if on_progress:
                    on_progress(i + 1, total)
    else:
        # Sentence-transformers path: batch encode locally
        # Check cache first for each chunk
        uncached_chunks: list[Chunk] = []

        for chunk in chunks:
            if cache is not None:
                cached = cache.get_embedding(chunk.content, model_name)
                if cached is not None:
                    embeddings[chunk.id] = cached
                    continue
            uncached_chunks.append(chunk)

        if uncached_chunks:
            embedder = _get_sentence_transformer(model_name)
            texts = [c.content for c in uncached_chunks]
            vectors = embedder.embed(texts)  # returns numpy array

            for j, chunk in enumerate(uncached_chunks):
                vec = vectors[j].tolist()
                embeddings[chunk.id] = vec
                if cache is not None:
                    cache.set_embedding(chunk.content, model_name, vec)

        if on_progress:
            on_progress(len(chunks), len(chunks))

    return embeddings


def find_similar_pairs(
    chunks: list[Chunk],
    embeddings: dict[str, list[float]],
    threshold: float = 0.7,
    min_content_words: int = 15,
    boilerplate_headings: set[str] | None = None,
    include_intra: bool = False,
    token_weight: float = 0.3,
) -> list[OverlapPair]:
    """Cosine similarity matrix -> pairs above threshold.

    Uses hybrid similarity: (1 - token_weight) * embedding_cosine + token_weight * token_jaccard.
    This reduces false positives where embeddings match on topic but actual words differ
    (e.g., structurally similar README sections with different content).

    Set token_weight=0 for pure embedding similarity (previous behavior).

    By default only returns cross-document pairs.  When include_intra=True,
    also returns same-document pairs (different sections within one file).

    Returns OverlapPair objects with embedding_similarity set to the combined score.
    """
    filtered = _filter_embedded_chunks(chunks, embeddings, min_content_words)

    if len(filtered) < 2:
        return []

    # Build matrix and compute cosine similarity via shared helper
    matrix = np.array([embeddings[c.id] for c in filtered])
    sim_matrix = cosine_similarity_matrix(matrix)

    # Pre-compute minimum embedding similarity needed for hybrid to reach threshold
    if token_weight > 0:
        min_embed_sim = (threshold - token_weight) / (1 - token_weight)
    else:
        min_embed_sim = threshold

    # Find pairs above threshold
    pairs: list[OverlapPair] = []
    for i in range(len(filtered)):
        for j in range(i + 1, len(filtered)):
            chunk_a = filtered[i]
            chunk_b = filtered[j]
            if not _should_compare_chunks(chunk_a, chunk_b, include_intra, boilerplate_headings):
                continue

            embed_sim = float(sim_matrix[i, j])
            # Early exit: if embedding alone can't reach threshold even with perfect token match
            if embed_sim < min_embed_sim:
                continue

            if token_weight > 0:
                tok_sim = _token_jaccard(chunk_a.content, chunk_b.content)
                combined = (1 - token_weight) * embed_sim + token_weight * tok_sim
            else:
                combined = embed_sim

            if combined >= threshold:
                pairs.append(
                    OverlapPair(
                        chunk_a=chunk_a,
                        chunk_b=chunk_b,
                        embedding_similarity=combined,
                    )
                )

    # Sort by similarity descending
    pairs.sort(key=lambda p: -(p.embedding_similarity or 0))
    return pairs


def _filter_embedded_chunks(
    chunks: list[Chunk],
    embeddings: dict[str, list[float]],
    min_content_words: int,
) -> list[Chunk]:
    """Keep chunks with embeddings and enough words for section matching."""
    filtered: list[Chunk] = []
    for chunk in chunks:
        if chunk.id not in embeddings:
            continue
        if min_content_words > 0 and len(chunk.content.split()) < min_content_words:
            continue
        filtered.append(chunk)
    return filtered


def _is_boilerplate_chunk(chunk: Chunk, boilerplate_headings: set[str] | None) -> bool:
    if not boilerplate_headings or not chunk.heading_path:
        return False
    return chunk.heading_path[-1].lower().strip() in boilerplate_headings


def _should_compare_chunks(
    chunk_a: Chunk,
    chunk_b: Chunk,
    include_intra: bool,
    boilerplate_headings: set[str] | None,
) -> bool:
    same_doc = chunk_a.document_path == chunk_b.document_path
    if same_doc and not include_intra:
        return False
    if same_doc and chunk_a.line_start == chunk_b.line_start:
        return False
    return not (
        _is_boilerplate_chunk(chunk_a, boilerplate_headings)
        and _is_boilerplate_chunk(chunk_b, boilerplate_headings)
    )
