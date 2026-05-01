"""Docs Map descriptor extraction and topic matching."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from dryscope.cache import Cache
from dryscope.config import DEFAULT_DOCS_MAP_FACET_DIMENSIONS, DEFAULT_DOCS_MAP_FACET_VALUES
from dryscope.docs.coding import _strip_code_fences, call_llm_cached
from dryscope.docs.embeddings import _get_sentence_transformer, _is_api_model, get_embedding
from dryscope.docs.models import Chunk
from dryscope.similarity import cosine_similarity_matrix

TOPICS_VERSION = "topics_v1"
DESCRIPTORS_VERSION = "doc_descriptors_v1"


def _document_content(chunks: list[Chunk], max_chars: int = 16000) -> str:
    """Build bounded document content from chunks."""
    content = "\n\n".join(c.content for c in chunks)
    if len(content) > max_chars:
        content = content[:max_chars]
    return content


def _document_headings(chunks: list[Chunk], max_headings: int = 40) -> list[str]:
    """Return a compact list of document headings."""
    headings: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        heading = " > ".join(chunk.heading_path).strip()
        if heading and heading not in seen:
            seen.add(heading)
            headings.append(heading)
        if len(headings) >= max_headings:
            break
    return headings


def _string_list(value, *, limit: int = 20) -> list[str]:
    """Normalize an arbitrary JSON value to a bounded string list."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _descriptor_fallback(doc_path: str, chunks: list[Chunk]) -> dict:
    """Build a deterministic descriptor if the LLM response is unavailable."""
    path_lower = doc_path.lower()
    role = "guide"
    if "/status/" in path_lower:
        role = "status"
    elif "/plans/" in path_lower or "/plan" in path_lower:
        role = "plan"
    elif "/research/" in path_lower:
        role = "research"
    elif "/architecture/" in path_lower or "adr" in path_lower:
        role = "architecture"
    elif "/reference" in path_lower or "api" in path_lower:
        role = "reference"

    lifecycle = "current"
    if "/history/" in path_lower:
        lifecycle = "historical"
    elif "/plans/" in path_lower:
        lifecycle = "proposed"

    title = chunks[0].heading_path[0] if chunks and chunks[0].heading_path else doc_path
    headings = _document_headings(chunks)
    about = [title] if title else []
    return {
        "document": doc_path,
        "title": title,
        "summary": "",
        "about": about[:8],
        "reader_intents": [],
        "doc_role": role,
        "audience": ["user"] if "/site/" in path_lower or "/user/" in path_lower else [],
        "lifecycle": lifecycle,
        "content_type": [],
        "surface": ["public"] if "/site/" in path_lower or "/user/" in path_lower else ["internal"],
        "canonicality": "supporting",
        "evidence": {
            "path": doc_path,
            "headings": headings[:12],
            "phrases": [],
        },
    }


def _descriptor_error_fallback(doc_path: str, chunks: list[Chunk], error: Exception) -> dict:
    """Build a descriptor fallback that records a per-document LLM failure."""
    descriptor = _descriptor_fallback(doc_path, chunks)
    descriptor["summary"] = "Descriptor extraction failed; using deterministic fallback."
    descriptor["extraction_error"] = f"{type(error).__name__}: {error}"[:500]
    return descriptor


def _normalize_descriptor(raw: dict, doc_path: str, chunks: list[Chunk]) -> dict:
    """Normalize an LLM descriptor into the expected schema."""
    fallback = _descriptor_fallback(doc_path, chunks)
    if not isinstance(raw, dict):
        return fallback

    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    descriptor = {
        "document": doc_path,
        "title": str(raw.get("title") or fallback["title"]).strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "about": _string_list(raw.get("about"), limit=12) or fallback["about"],
        "reader_intents": _string_list(raw.get("reader_intents"), limit=12),
        "doc_role": str(raw.get("doc_role") or fallback["doc_role"]).strip().lower(),
        "audience": _string_list(raw.get("audience"), limit=6),
        "lifecycle": str(raw.get("lifecycle") or fallback["lifecycle"]).strip().lower(),
        "content_type": _string_list(raw.get("content_type"), limit=8),
        "surface": _string_list(raw.get("surface"), limit=6) or fallback["surface"],
        "canonicality": str(raw.get("canonicality") or fallback["canonicality"]).strip().lower(),
        "facets": raw.get("facets") if isinstance(raw.get("facets"), dict) else {},
        "evidence": {
            "path": doc_path,
            "headings": _string_list(evidence.get("headings"), limit=12)
            or fallback["evidence"]["headings"],
            "phrases": _string_list(evidence.get("phrases"), limit=8),
        },
    }
    return descriptor


def descriptor_labels(descriptor: dict) -> list[str]:
    """Return Docs Map labels from a rich descriptor for canonical normalization."""
    labels: list[str] = []
    for key in ("about", "reader_intents"):
        labels.extend(str(item).strip() for item in descriptor.get(key, []) if str(item).strip())
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        norm = label.lower()
        if norm not in seen:
            seen.add(norm)
            result.append(label)
    return result[:24]


def extract_document_descriptor(
    doc_path: str,
    chunks: list[Chunk],
    model: str,
    cache: Cache | None,
    backend: str = "litellm",
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
    facet_dimensions: list[str] | None = None,
    facet_values: dict[str, list[str]] | None = None,
) -> dict:
    """Extract a rich IA descriptor for one document via LLM."""
    content = _document_content(chunks)
    headings = _document_headings(chunks)
    facet_dimensions = facet_dimensions or list(DEFAULT_DOCS_MAP_FACET_DIMENSIONS)
    facet_values = facet_values or DEFAULT_DOCS_MAP_FACET_VALUES
    facet_seed = {
        "facet_dimensions": facet_dimensions,
        "suggested_values": {
            name: facet_values.get(name, []) for name in facet_dimensions if facet_values.get(name)
        },
        "custom_dimensions": [
            name for name in facet_dimensions if name not in DEFAULT_DOCS_MAP_FACET_VALUES
        ],
    }
    cache_key_raw = f"{doc_path}|{content}|{model}|{DESCRIPTORS_VERSION}|{json.dumps(facet_seed, sort_keys=True)}"
    cache_key = hashlib.sha256(cache_key_raw.encode()).hexdigest()

    prompt = f"""You are a documentation information architect. Extract a rich IA descriptor for this document.

DOCUMENT: {doc_path}

HEADINGS:
{json.dumps(headings, indent=2)}

CONTENT:
{content}

---

Return ONLY valid JSON with this shape:
{{
  "title": "document title",
  "summary": "1-2 sentence factual summary",
  "about": ["stable subject labels, 3-8 words each"],
  "reader_intents": ["what a reader is trying to accomplish"],
  "doc_role": "guide|reference|tutorial|spec|plan|status|research|changelog|architecture|decision|overview|troubleshooting",
  "audience": ["user|contributor|maintainer|operator|internal|agent"],
  "lifecycle": "current|proposed|historical|deprecated|draft|unknown",
  "content_type": ["concept|workflow|api|troubleshooting|decision|benchmark|example|architecture|requirements"],
  "surface": ["public|internal|generated|extension|package|integration"],
  "canonicality": "primary|supporting|archive|duplicate|index|unknown",
  "facets": {{"custom_dimension_name": ["value"]}},
  "evidence": {{
    "headings": ["heading strings that support the classification"],
    "phrases": ["short phrases from the document that support the descriptor"]
  }}
}}

Facet seed suggestions:
{json.dumps(facet_seed, indent=2)}

Rules:
- Keep labels generic and reusable across repositories.
- Use the document path, headings, and body together.
- Distinguish subject/aboutness from reader intent and document role.
- Prefer the seeded dimensions when supported by evidence, but omit unsupported values.
- Put any configured dimension not represented by a top-level schema field under "facets".
- Do not invent product-specific facet names.
- Maximum 12 about labels and 12 reader intents."""

    try:
        text = call_llm_cached(
            model,
            prompt,
            cache,
            cache_key,
            DESCRIPTORS_VERSION,
            backend,
            ollama_host=ollama_host,
            cli_strip_api_key=cli_strip_api_key,
            cli_permission_mode=cli_permission_mode,
            cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
        )
    except Exception as exc:
        return _descriptor_error_fallback(doc_path, chunks, exc)

    try:
        data = json.loads(_strip_code_fences(text))
    except (json.JSONDecodeError, ValueError, TypeError):
        data = {}
    return _normalize_descriptor(data, doc_path, chunks)


def extract_topics(
    doc_path: str,
    chunks: list[Chunk],
    model: str,
    cache: Cache | None,
    backend: str = "litellm",
    ollama_host: str | None = None,
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

    try:
        text = call_llm_cached(
            model,
            prompt,
            cache,
            cache_key,
            TOPICS_VERSION,
            backend,
            ollama_host=ollama_host,
            cli_strip_api_key=cli_strip_api_key,
            cli_permission_mode=cli_permission_mode,
            cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
        )
    except Exception:
        return []

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
    """Embed topic strings using API embeddings or local sentence-transformers.

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
        if _is_api_model(model_name):
            for topic in uncached:
                result[topic] = get_embedding(topic, model_name, cache)
        else:
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
                matches.append(
                    {
                        "topic_a": filtered_a[ai],
                        "topic_b": filtered_b[bi],
                        "similarity": sim,
                    }
                )
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

            matches = _compute_topic_matches(topics_a, topics_b, topic_embeddings, threshold)

            if matches:
                matches.sort(key=lambda m: -m["similarity"])
                key = (min(doc_a, doc_b), max(doc_a, doc_b))
                result[key] = matches

    return result


def run_topic_extraction(
    documents: dict[str, list[Chunk]],
    model: str,
    cache: Cache | None,
    backend: str = "litellm",
    concurrency: int = 1,
    on_progress: callable | None = None,
    prior_topics: dict[str, list[str]] | None = None,
    ollama_host: str | None = None,
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
            ollama_host=ollama_host,
            cli_strip_api_key=cli_strip_api_key,
            cli_permission_mode=cli_permission_mode,
            cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
        )
        return doc_path, topics

    if concurrency > 1 and pending:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(_extract_one, doc_path): doc_path for doc_path in pending}
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


def run_document_descriptor_extraction(
    documents: dict[str, list[Chunk]],
    model: str,
    cache: Cache | None,
    backend: str = "litellm",
    concurrency: int = 1,
    on_progress: callable | None = None,
    prior_descriptors: dict[str, dict] | None = None,
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
    facet_dimensions: list[str] | None = None,
    facet_values: dict[str, list[str]] | None = None,
) -> dict[str, dict]:
    """Orchestrate parallel Docs Map descriptor extraction across all documents."""
    if prior_descriptors is None:
        prior_descriptors = {}

    result: dict[str, dict] = {}
    pending: list[str] = []

    for doc_path in documents:
        if doc_path in prior_descriptors:
            result[doc_path] = prior_descriptors[doc_path]
        else:
            pending.append(doc_path)

    total = len(documents)
    done_count = len(result)

    if on_progress and done_count > 0:
        on_progress(done_count, total)

    if not pending:
        return result

    callback_lock = threading.Lock()

    def _extract_one(doc_path: str) -> tuple[str, dict]:
        chunks = documents[doc_path]
        descriptor = extract_document_descriptor(
            doc_path,
            chunks,
            model,
            cache,
            backend,
            ollama_host=ollama_host,
            cli_strip_api_key=cli_strip_api_key,
            cli_permission_mode=cli_permission_mode,
            cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
            facet_dimensions=facet_dimensions,
            facet_values=facet_values,
        )
        return doc_path, descriptor

    if concurrency > 1 and pending:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(_extract_one, doc_path): doc_path for doc_path in pending}
            for future in as_completed(futures):
                doc_path, descriptor = future.result()
                with callback_lock:
                    result[doc_path] = descriptor
                    done_count += 1
                    if on_progress:
                        on_progress(done_count, total)
    else:
        for doc_path in pending:
            _, descriptor = _extract_one(doc_path)
            result[doc_path] = descriptor
            done_count += 1
            if on_progress:
                on_progress(done_count, total)

    return result
