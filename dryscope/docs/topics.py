"""Intent overlap detection via LLM topic extraction + embedding matching."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from dryscope.cache import Cache
from dryscope.docs.coding import call_llm_cached, _strip_code_fences
from dryscope.docs.embeddings import _get_sentence_transformer
from dryscope.docs.models import Chunk
from dryscope.similarity import UnionFind, cosine_similarity_matrix


TOPICS_VERSION = "topics_v1"


def extract_topics(
    doc_path: str,
    chunks: list[Chunk],
    model: str,
    cache: Cache | None,
    backend: str = "litellm",
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> list[str]:
    """Extract granular topic phrases from a document via LLM.

    Builds document content from chunks (truncated to 16k chars),
    asks the LLM for specific topic phrases, and caches the result.

    Returns a list of topic strings (3-8 words each, max 15).
    """
    content = "\n\n".join(c.content for c in chunks)
    if len(content) > 16000:
        content = content[:16000]

    cache_key_raw = f"{content}|{model}|{TOPICS_VERSION}"
    cache_key = hashlib.sha256(cache_key_raw.encode()).hexdigest()

    prompt = f"""You are a documentation analyst. Extract the specific, granular topics covered in this document.

DOCUMENT: {doc_path}

{content}

---

Respond with ONLY a JSON array of topic strings. Each topic should be:
- A specific phrase (3-8 words) describing a concrete topic covered
- Granular enough to distinguish from related topics
- Maximum 15 topics

Example: ["pre-commit hook configuration", "ESLint rule setup", "Python type checking with mypy"]

JSON array:"""

    text = call_llm_cached(
        model,
        prompt,
        cache,
        cache_key,
        TOPICS_VERSION,
        backend,
        cli_strip_api_key=cli_strip_api_key,
        cli_permission_mode=cli_permission_mode,
        cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
    )

    try:
        text = _strip_code_fences(text)
        topics = json.loads(text)
        if isinstance(topics, list) and all(isinstance(t, str) for t in topics):
            return topics[:15]
    except (json.JSONDecodeError, IndexError, ValueError):
        pass
    return []


def embed_topics(
    topics: list[str],
    model_name: str,
    cache: Cache | None = None,
) -> dict[str, list[float]]:
    """Embed topic strings using sentence-transformers.

    Checks cache first, batch-encodes uncached topics.
    Returns mapping: topic string -> embedding vector.
    """
    if not topics:
        return {}

    result: dict[str, list[float]] = {}
    uncached: list[str] = []

    for topic in topics:
        if cache is not None:
            cached = cache.get_embedding(topic, model_name)
            if cached is not None:
                result[topic] = cached
                continue
        uncached.append(topic)

    if uncached:
        embedder = _get_sentence_transformer(model_name)
        vectors = embedder.embed(uncached)
        for j, topic in enumerate(uncached):
            vec = vectors[j].tolist()
            result[topic] = vec
            if cache is not None:
                cache.set_embedding(topic, model_name, vec)

    return result


def _compute_topic_matches(
    topics_a: list[str],
    topics_b: list[str],
    topic_embeddings: dict[str, list[float]],
    threshold: float,
) -> list[dict]:
    """Find matched topic pairs above threshold via cosine similarity."""
    vecs_a = [topic_embeddings[t] for t in topics_a if t in topic_embeddings]
    vecs_b = [topic_embeddings[t] for t in topics_b if t in topic_embeddings]
    filtered_a = [t for t in topics_a if t in topic_embeddings]
    filtered_b = [t for t in topics_b if t in topic_embeddings]
    if not vecs_a or not vecs_b:
        return []
    mat_a = np.array(vecs_a)
    mat_b = np.array(vecs_b)
    sim_matrix = cosine_similarity_matrix(mat_a, mat_b)
    matches = []
    for ai in range(len(filtered_a)):
        for bi in range(len(filtered_b)):
            sim = float(sim_matrix[ai, bi])
            if sim >= threshold:
                matches.append({
                    "topic_a": filtered_a[ai],
                    "topic_b": filtered_b[bi],
                    "similarity": sim,
                })
    return matches


def find_intent_doc_pairs(
    doc_topics: dict[str, list[str]],
    topic_embeddings: dict[str, list[float]],
    threshold: float = 0.8,
) -> dict[tuple[str, str], list[dict]]:
    """Find document pairs with matching topics via cosine similarity.

    For each document pair, computes topic-topic cosine similarity matrix.
    Returns dict mapping (doc_a, doc_b) -> list of matched topic dicts.
    Only pairs with at least one topic match above threshold are returned.
    """
    doc_paths = sorted(doc_topics.keys())
    result: dict[tuple[str, str], list[dict]] = {}

    for i in range(len(doc_paths)):
        for j in range(i + 1, len(doc_paths)):
            doc_a, doc_b = doc_paths[i], doc_paths[j]
            topics_a = doc_topics[doc_a]
            topics_b = doc_topics[doc_b]

            if not topics_a or not topics_b:
                continue

            matches = _compute_topic_matches(
                topics_a, topics_b, topic_embeddings, threshold
            )

            if matches:
                matches.sort(key=lambda m: -m["similarity"])
                key = (min(doc_a, doc_b), max(doc_a, doc_b))
                result[key] = matches

    return result


def cluster_documents_by_topic(
    doc_topics: dict[str, list[str]],
    topic_embeddings: dict[str, list[float]],
    threshold: float = 0.8,
    max_cluster_size: int = 10,
) -> list[dict]:
    """Cluster documents that share similar topics using Union-Find.

    Groups documents into clusters where at least one topic pair exceeds
    the similarity threshold. Clusters larger than max_cluster_size are
    dropped as broad structural patterns rather than actionable overlap.

    Returns a list of cluster dicts, each containing:
      - "documents": list of document paths in the cluster
      - "shared_topics": list of matched topic pairs with similarity
      - "label": a short label derived from the most common matched topic
    """
    doc_paths = sorted(doc_topics.keys())
    if len(doc_paths) < 2:
        return []

    n = len(doc_paths)
    uf = UnionFind(n)

    # Track matched topics per pair for labeling
    pair_topics: dict[tuple[int, int], list[dict]] = {}

    for i in range(n):
        for j in range(i + 1, n):
            topics_a = doc_topics[doc_paths[i]]
            topics_b = doc_topics[doc_paths[j]]
            if not topics_a or not topics_b:
                continue

            matches = _compute_topic_matches(
                topics_a, topics_b, topic_embeddings, threshold
            )

            if matches:
                uf.union(i, j)
                pair_topics[(i, j)] = matches

    # Collect clusters
    clusters_map: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        clusters_map.setdefault(root, []).append(i)

    result = []
    for members in clusters_map.values():
        if len(members) < 2 or len(members) > max_cluster_size:
            continue

        docs = [doc_paths[m] for m in members]

        # Collect all shared topics for this cluster
        shared = []
        member_set = set(members)
        for (i, j), topics in pair_topics.items():
            if i in member_set and j in member_set:
                shared.extend(topics)
        shared.sort(key=lambda m: -m["similarity"])

        # Derive label from most frequently matched topic
        topic_counts: Counter = Counter()
        for m in shared:
            topic_counts[m["topic_a"]] += 1
            topic_counts[m["topic_b"]] += 1
        label = topic_counts.most_common(1)[0][0] if topic_counts else "unknown"

        result.append({
            "documents": docs,
            "shared_topics": shared[:20],  # cap for readability
            "label": label,
        })

    # Sort clusters by size descending
    result.sort(key=lambda c: -len(c["documents"]))
    return result


def run_topic_extraction(
    documents: dict[str, list[Chunk]],
    model: str,
    cache: Cache | None,
    backend: str = "litellm",
    concurrency: int = 1,
    on_progress: "callable | None" = None,
    prior_topics: dict[str, list[str]] | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> dict[str, list[str]]:
    """Orchestrate parallel topic extraction across all documents.

    Returns dict mapping doc_path -> list of topic strings.
    """
    if prior_topics is None:
        prior_topics = {}

    result: dict[str, list[str]] = {}
    pending: list[str] = []

    for doc_path in documents:
        if doc_path in prior_topics:
            result[doc_path] = prior_topics[doc_path]
        else:
            pending.append(doc_path)

    total = len(documents)
    done_count = len(result)

    if on_progress and done_count > 0:
        on_progress(done_count, total)

    if not pending:
        return result

    callback_lock = threading.Lock()

    def _extract_one(doc_path: str) -> tuple[str, list[str]]:
        chunks = documents[doc_path]
        topics = extract_topics(
            doc_path,
            chunks,
            model,
            cache,
            backend,
            cli_strip_api_key=cli_strip_api_key,
            cli_permission_mode=cli_permission_mode,
            cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
        )
        return doc_path, topics

    if concurrency > 1 and pending:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_extract_one, doc_path): doc_path
                for doc_path in pending
            }
            for future in as_completed(futures):
                doc_path, topics = future.result()
                with callback_lock:
                    result[doc_path] = topics
                    done_count += 1
                    if on_progress:
                        on_progress(done_count, total)
    else:
        for doc_path in pending:
            _, topics = _extract_one(doc_path)
            result[doc_path] = topics
            done_count += 1
            if on_progress:
                on_progress(done_count, total)

    return result
