"""Canonical topic taxonomy helpers for documentation analysis."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from dryscope.config import DEFAULT_DOCS_MAP_FACET_DIMENSIONS, DEFAULT_DOCS_MAP_FACET_VALUES
from dryscope.terminology import DOCS_MAP

_TOPIC_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "into",
    "using",
    "about",
    "documentation",
    "docs",
    "guide",
    "guides",
    "reference",
    "overview",
    "status",
    "plan",
    "plans",
}

TAXONOMY_LLM_VERSION = "taxonomy_llm_v2"
DOCS_MAP_LLM_VERSION = "docs_map_v1"


def normalize_topic_text(text: str) -> str:
    """Normalize a topic label for matching."""
    value = text.lower().strip()
    value = value.replace("&", " and ")
    value = re.sub(r"[^\w\s-]", " ", value)
    value = re.sub(r"[-\s]+", " ", value).strip()
    return value


def topic_similarity(a: str, b: str) -> float:
    """Compute deterministic string similarity for normalized topic labels."""
    norm_a = normalize_topic_text(a)
    norm_b = normalize_topic_text(b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0

    seq_score = SequenceMatcher(None, norm_a, norm_b).ratio()
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    token_score = (
        len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if tokens_a and tokens_b else 0.0
    )
    return max(seq_score, token_score)


@dataclass
class CanonicalTopic:
    """A canonical topic and the raw topic labels mapped to it."""

    name: str
    aliases: set[str] = field(default_factory=set)
    documents: set[str] = field(default_factory=set)
    mention_count: int = 0

    def add(self, raw_topic: str, doc_path: str, count: int = 1) -> None:
        self.aliases.add(raw_topic)
        self.documents.add(doc_path)
        self.mention_count += count


@dataclass
class TopicTaxonomy:
    """Corpus-level canonical topic view."""

    canonical_topics: dict[str, CanonicalTopic]
    raw_to_canonical: dict[str, str]
    doc_topics: dict[str, list[str]]
    co_occurrence: list[dict]
    method: str = "deterministic"

    def to_dict(self) -> dict:
        """Serialize the taxonomy for reports and run-store stages."""
        canonical_topics = [
            {
                "name": topic.name,
                "aliases": sorted(topic.aliases),
                "documents": sorted(topic.documents),
                "document_count": len(topic.documents),
                "mention_count": topic.mention_count,
            }
            for topic in sorted(
                self.canonical_topics.values(),
                key=lambda t: (-len(t.documents), -t.mention_count, t.name),
            )
        ]
        topic_document_clusters = [
            {
                "topic": topic["name"],
                "documents": topic["documents"],
                "document_count": topic["document_count"],
                "mention_count": topic["mention_count"],
                "aliases": topic["aliases"],
            }
            for topic in canonical_topics
            if topic["document_count"] >= 2
        ]
        return {
            "canonical_topics": canonical_topics,
            "topic_document_clusters": topic_document_clusters,
            "raw_to_canonical": dict(sorted(self.raw_to_canonical.items())),
            "doc_topics": dict(sorted(self.doc_topics.items())),
            "co_occurrence": self.co_occurrence,
            "method": self.method,
        }


def _choose_canonical_label(raw_topic: str) -> str:
    """Choose a stable display label for a new canonical topic."""
    return normalize_topic_text(raw_topic)


def _best_canonical_match(
    raw_topic: str,
    canonical_topics: dict[str, CanonicalTopic],
    candidate_names: set[str],
    threshold: float,
) -> str | None:
    """Find the strongest existing canonical match for a raw topic."""
    best_name: str | None = None
    best_score = 0.0
    for name in candidate_names:
        topic = canonical_topics[name]
        candidates = [name, *topic.aliases]
        score = max(topic_similarity(raw_topic, candidate) for candidate in candidates)
        if score > best_score:
            best_name = name
            best_score = score
    return best_name if best_score >= threshold else None


def _topic_tokens(text: str) -> set[str]:
    """Return useful normalized tokens for fuzzy candidate lookup."""
    return {
        token
        for token in normalize_topic_text(text).split()
        if len(token) >= 4 and token not in _TOPIC_STOPWORDS
    }


def _compact_doc_path(path: str) -> str:
    """Keep enough path context for the LLM without sending absolute paths."""
    parts = Path(path).parts
    return "/".join(parts[-4:]) if len(parts) > 4 else str(Path(path))


def _collect_topic_stats(
    doc_topics: dict[str, list[str]],
) -> tuple[Counter[str], dict[str, set[str]]]:
    """Collect raw topic frequencies and document memberships."""
    raw_counts: Counter[str] = Counter()
    raw_docs: dict[str, set[str]] = defaultdict(set)
    for doc_path, topics in doc_topics.items():
        seen_in_doc: set[str] = set()
        for topic in topics:
            raw = topic.strip()
            if not raw:
                continue
            raw_counts[raw] += 1
            seen_in_doc.add(raw)
        for raw in seen_in_doc:
            raw_docs[raw].add(doc_path)
    return raw_counts, raw_docs


def _build_deterministic_raw_mapping(
    raw_counts: Counter[str],
    raw_docs: dict[str, set[str]],
    fuzzy_threshold: float,
) -> dict[str, str]:
    """Build a deterministic raw-topic to preliminary-canonical mapping."""
    canonical_topics: dict[str, CanonicalTopic] = {}
    raw_to_canonical: dict[str, str] = {}
    norm_to_canonical: dict[str, str] = {}
    token_index: dict[str, set[str]] = defaultdict(set)

    sorted_raw_topics = sorted(
        raw_counts,
        key=lambda t: (-len(raw_docs[t]), -raw_counts[t], normalize_topic_text(t), t),
    )

    for raw in sorted_raw_topics:
        norm = normalize_topic_text(raw)
        exact = norm_to_canonical.get(norm)
        tokens = _topic_tokens(raw)
        candidate_names: set[str] = set()
        for token in tokens:
            candidate_names.update(token_index.get(token, set()))
        canonical_name = exact or _best_canonical_match(
            raw,
            canonical_topics,
            candidate_names,
            fuzzy_threshold,
        )
        if canonical_name is None:
            canonical_name = _choose_canonical_label(raw)
            canonical_topics[canonical_name] = CanonicalTopic(name=canonical_name)
            norm_to_canonical[normalize_topic_text(canonical_name)] = canonical_name
            for token in _topic_tokens(canonical_name):
                token_index[token].add(canonical_name)

        raw_to_canonical[raw] = canonical_name
        norm_to_canonical[norm] = canonical_name
        for token in tokens:
            token_index[token].add(canonical_name)
        canonical_topics[canonical_name].aliases.add(raw)

    return raw_to_canonical


def _build_taxonomy_from_mapping(
    doc_topics: dict[str, list[str]],
    raw_to_canonical: dict[str, str],
    raw_counts: Counter[str],
    raw_docs: dict[str, set[str]],
    max_co_occurrence: int,
    method: str,
) -> TopicTaxonomy:
    """Construct a TopicTaxonomy from a raw-topic mapping."""
    canonical_topics: dict[str, CanonicalTopic] = {}
    for raw, canonical in raw_to_canonical.items():
        canonical_name = normalize_topic_text(canonical)
        if not canonical_name:
            canonical_name = _choose_canonical_label(raw)
        topic = canonical_topics.setdefault(canonical_name, CanonicalTopic(name=canonical_name))
        topic.aliases.add(raw)
        topic.mention_count += raw_counts[raw]
        topic.documents.update(raw_docs[raw])

    canonical_doc_topics: dict[str, list[str]] = {}
    for doc_path, topics in doc_topics.items():
        seen: set[str] = set()
        canonical_list: list[str] = []
        for raw in topics:
            canonical = raw_to_canonical.get(raw.strip())
            if canonical:
                canonical = normalize_topic_text(canonical)
            if canonical and canonical not in seen:
                seen.add(canonical)
                canonical_list.append(canonical)
        canonical_doc_topics[doc_path] = canonical_list

    co_counts: Counter[tuple[str, str]] = Counter()
    for topics in canonical_doc_topics.values():
        unique_topics = sorted(set(topics))
        for i, topic_a in enumerate(unique_topics):
            for topic_b in unique_topics[i + 1 :]:
                co_counts[(topic_a, topic_b)] += 1

    co_occurrence = [
        {"topics": [topic_a, topic_b], "count": count}
        for (topic_a, topic_b), count in co_counts.most_common(max_co_occurrence)
        if count >= 2
    ]

    return TopicTaxonomy(
        canonical_topics=canonical_topics,
        raw_to_canonical=raw_to_canonical,
        doc_topics=canonical_doc_topics,
        co_occurrence=co_occurrence,
        method=method,
    )


def _preliminary_groups(
    raw_to_preliminary: dict[str, str],
    raw_counts: Counter[str],
    raw_docs: dict[str, set[str]],
) -> list[dict]:
    """Build compact preliminary topic groups for LLM canonicalization."""
    groups: dict[str, dict] = {}
    for raw, preliminary in raw_to_preliminary.items():
        group = groups.setdefault(
            preliminary,
            {
                "raw": preliminary,
                "aliases": [],
                "document_count": 0,
                "mention_count": 0,
                "sample_documents": [],
            },
        )
        group["aliases"].append(raw)
        group["mention_count"] += raw_counts[raw]

    prelim_docs: dict[str, set[str]] = defaultdict(set)
    for raw, preliminary in raw_to_preliminary.items():
        prelim_docs[preliminary].update(raw_docs[raw])
    for preliminary, docs in prelim_docs.items():
        groups[preliminary]["document_count"] = len(docs)
        groups[preliminary]["aliases"] = sorted(set(groups[preliminary]["aliases"]))[:8]
        groups[preliminary]["sample_documents"] = [
            _compact_doc_path(doc) for doc in sorted(docs)[:3]
        ]

    return sorted(
        groups.values(),
        key=lambda g: (-g["document_count"], -g["mention_count"], normalize_topic_text(g["raw"])),
    )


def _parse_mapping_response(text: str) -> dict[str, str]:
    """Parse LLM topic mapping JSON into {raw_group: canonical}."""
    from dryscope.docs.coding import _strip_code_fences

    try:
        data = json.loads(_strip_code_fences(text))
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}
    mappings = data.get("mappings") if isinstance(data, dict) else None
    if not isinstance(mappings, list):
        return {}

    result: dict[str, str] = {}
    for item in mappings:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("raw") or "").strip()
        canonical = str(item.get("canonical") or "").strip()
        if raw and canonical:
            result[raw] = normalize_topic_text(canonical)
    return result


def _parse_json_object_response(text: str) -> dict:
    """Parse an LLM JSON-object response."""
    from dryscope.docs.coding import _strip_code_fences

    try:
        data = json.loads(_strip_code_fences(text))
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _cluster_groups_with_llm(
    groups: list[dict],
    *,
    model: str,
    cache: object | None,
    backend: str,
    batch_size: int,
    existing_limit: int,
    ollama_host: str | None,
    cli_strip_api_key: bool,
    cli_permission_mode: str | None,
    cli_dangerously_skip_permissions: bool,
    concurrency: int = 1,
) -> dict[str, str]:
    """Cluster preliminary topic groups into canonical topic names via LLM."""
    from dryscope.docs.coding import call_llm_cached

    group_to_canonical: dict[str, str] = {}
    canonical_counts: Counter[str] = Counter()
    batches = [
        (batch_start, groups[batch_start : batch_start + batch_size])
        for batch_start in range(0, len(groups), batch_size)
    ]

    def _map_batch(batch_start: int, batch: list[dict], existing: list[str]) -> dict[str, str]:
        existing = [
            normalize_topic_text(name)
            for name in existing[:existing_limit]
            if normalize_topic_text(name)
        ]
        payload = {
            "existing_canonical_topics": existing,
            "topic_groups": batch,
        }
        prompt = f"""You are normalizing topic labels for a Docs Map tool.

The input topic groups came from per-document topic extraction plus deterministic
pre-normalization. For each topic group, map it to either an existing canonical
topic or a new durable canonical topic.

The output will be used to cluster documents by shared reader intent, so optimize
for organization buckets: topics that would naturally live in the same guide,
concept page, reference narrative, or status/workstream should share one canonical
name even when the raw labels use different wording.

Canonical names should be:
- lowercase
- 3-8 words
- specific enough to be actionable
- broad enough to merge spelling variants, singular/plural variants, near synonyms,
  and narrow raw labels with the same documentation intent
- not tied to one file name, status document, or date unless the topic is truly that artifact

Merge aggressively when labels describe the same documentation concept or would
belong under the same docs navigation bucket. For a corpus of a few hundred docs,
prefer a controlled vocabulary on the order of 80-180 canonical topics rather
than thousands of near-unique labels.

Do not merge different concepts just because they share broad words like
"documentation", "api", "runtime", "eclipse", "performance", or "plan".

Existing canonical topics:
{json.dumps(existing, indent=2)}

Topic groups to map:
{json.dumps(batch, indent=2)}

Respond with ONLY valid JSON:
{{
  "mappings": [
    {{"raw": "exact raw topic group name from input", "canonical": "canonical topic name", "is_new": true}}
  ]
}}"""

        cache_key = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
            + model.encode()
            + TAXONOMY_LLM_VERSION.encode()
        ).hexdigest()
        try:
            text = call_llm_cached(
                model,
                prompt,
                cache,
                cache_key,
                TAXONOMY_LLM_VERSION,
                backend,
                ollama_host=ollama_host,
                cli_strip_api_key=cli_strip_api_key,
                cli_permission_mode=cli_permission_mode,
                cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
            )
            batch_mapping = _parse_mapping_response(text)
        except Exception:
            print(
                f"warning: topic canonicalization batch {batch_start // batch_size + 1} "
                "failed; falling back to deterministic labels for that batch",
                file=sys.stderr,
            )
            batch_mapping = {}
        return {
            group["raw"]: batch_mapping.get(group["raw"], normalize_topic_text(group["raw"]))
            for group in batch
        }

    seed_existing = [group["raw"] for group in groups[:existing_limit]]
    if concurrency > 1 and len(batches) > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_map_batch, batch_start, batch, seed_existing): batch_start
                for batch_start, batch in batches
            }
            for future in as_completed(futures):
                batch_mapping = future.result()
                group_to_canonical.update(batch_mapping)
                canonical_counts.update(batch_mapping.values())
    else:
        for batch_start, batch in batches:
            existing = [
                name
                for name, _count in sorted(
                    canonical_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:existing_limit]
            ]
            batch_mapping = _map_batch(batch_start, batch, existing)
            group_to_canonical.update(batch_mapping)
            canonical_counts.update(batch_mapping.values())

    reconciled = _reconcile_canonical_names(group_to_canonical.values())
    return {
        raw: reconciled.get(canonical, canonical) for raw, canonical in group_to_canonical.items()
    }


def _reconcile_canonical_names(canonical_names: object) -> dict[str, str]:
    """Deterministically merge near-identical canonical labels across batches."""
    counts = Counter(
        normalize_topic_text(str(name))
        for name in canonical_names
        if normalize_topic_text(str(name))
    )
    sorted_names = sorted(counts, key=lambda name: (-counts[name], name))
    canonical_topics: dict[str, CanonicalTopic] = {}
    mapping: dict[str, str] = {}
    norm_to_canonical: dict[str, str] = {}
    token_index: dict[str, set[str]] = defaultdict(set)

    for name in sorted_names:
        exact = norm_to_canonical.get(name)
        tokens = _topic_tokens(name)
        candidate_names: set[str] = set()
        for token in tokens:
            candidate_names.update(token_index.get(token, set()))
        canonical = exact or _best_canonical_match(
            name,
            canonical_topics,
            candidate_names,
            threshold=0.9,
        )
        if canonical is None:
            canonical = name
            canonical_topics[canonical] = CanonicalTopic(name=canonical)
            norm_to_canonical[canonical] = canonical
            for token in _topic_tokens(canonical):
                token_index[token].add(canonical)
        mapping[name] = canonical
        canonical_topics[canonical].aliases.add(name)
    return mapping


def build_canonical_taxonomy(
    doc_topics: dict[str, list[str]],
    *,
    fuzzy_threshold: float = 0.86,
    max_co_occurrence: int = 30,
    llm_model: str | None = None,
    cache: object | None = None,
    backend: str = "litellm",
    llm_batch_size: int = 100,
    llm_existing_limit: int = 200,
    llm_min_document_count: int = 1,
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
    llm_concurrency: int = 1,
) -> TopicTaxonomy:
    """Normalize raw per-document topics into a corpus-level canonical taxonomy.

    This mirrors the useful part of the book builder's Docs Map:
    deterministic exact/fuzzy matching first, then optional LLM clustering that
    maps preliminary topic groups into durable canonical topics.
    """
    raw_counts, raw_docs = _collect_topic_stats(doc_topics)
    raw_to_preliminary = _build_deterministic_raw_mapping(
        raw_counts,
        raw_docs,
        fuzzy_threshold,
    )

    if not llm_model:
        return _build_taxonomy_from_mapping(
            doc_topics,
            raw_to_preliminary,
            raw_counts,
            raw_docs,
            max_co_occurrence,
            method="deterministic",
        )

    groups = _preliminary_groups(raw_to_preliminary, raw_counts, raw_docs)
    llm_groups = [
        group for group in groups if int(group.get("document_count") or 0) >= llm_min_document_count
    ]
    group_to_canonical = _cluster_groups_with_llm(
        llm_groups,
        model=llm_model,
        cache=cache,
        backend=backend,
        batch_size=llm_batch_size,
        existing_limit=llm_existing_limit,
        ollama_host=ollama_host,
        cli_strip_api_key=cli_strip_api_key,
        cli_permission_mode=cli_permission_mode,
        cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
        concurrency=llm_concurrency,
    )
    raw_to_canonical = {
        raw: group_to_canonical.get(preliminary, preliminary)
        for raw, preliminary in raw_to_preliminary.items()
    }
    return _build_taxonomy_from_mapping(
        doc_topics,
        raw_to_canonical,
        raw_counts,
        raw_docs,
        max_co_occurrence,
        method="llm",
    )


def _docs_map_topic_cluster_payload(
    taxonomy: dict,
    *,
    max_topic_coverage_clusters: int,
    max_single_doc_topics: int,
) -> tuple[list[dict], list[dict]]:
    """Build compact topic evidence for IA discovery."""
    clusters: list[dict] = []
    singles: list[dict] = []
    for topic in taxonomy.get("canonical_topics", []):
        documents = [_compact_doc_path(str(doc)) for doc in topic.get("documents", [])[:8]]
        record = {
            "topic": topic.get("name"),
            "document_count": topic.get("document_count", 0),
            "mention_count": topic.get("mention_count", 0),
            "aliases": topic.get("aliases", [])[:5],
            "sample_documents": documents,
        }
        if int(topic.get("document_count") or 0) >= 2:
            clusters.append(record)
        else:
            singles.append(record)

    clusters.sort(
        key=lambda c: (
            -int(c.get("document_count") or 0),
            -int(c.get("mention_count") or 0),
            str(c.get("topic") or ""),
        )
    )
    singles.sort(key=lambda c: (-int(c.get("mention_count") or 0), str(c.get("topic") or "")))
    return clusters[:max_topic_coverage_clusters], singles[:max_single_doc_topics]


def _docs_map_document_payload(
    taxonomy: dict,
    *,
    max_documents: int,
    document_descriptors: dict[str, dict] | None = None,
) -> list[dict]:
    """Build compact document-to-topic evidence for IA discovery."""
    if document_descriptors:
        records = []
        for doc, descriptor in sorted(document_descriptors.items()):
            records.append(
                {
                    "document": _compact_doc_path(str(doc)),
                    "title": descriptor.get("title"),
                    "about": descriptor.get("about", [])[:12],
                    "reader_intents": descriptor.get("reader_intents", [])[:12],
                    "doc_role": descriptor.get("doc_role"),
                    "audience": descriptor.get("audience", []),
                    "lifecycle": descriptor.get("lifecycle"),
                    "content_type": descriptor.get("content_type", []),
                    "surface": descriptor.get("surface", []),
                    "canonicality": descriptor.get("canonicality"),
                    "canonical_labels": taxonomy.get("doc_topics", {}).get(doc, [])[:12],
                }
            )
        return records[:max_documents]

    doc_topics = taxonomy.get("doc_topics", {})
    records = [
        {
            "document": _compact_doc_path(str(doc)),
            "topics": list(topics)[:12],
        }
        for doc, topics in sorted(doc_topics.items())
    ]
    return records[:max_documents]


def _descriptor_facet_payload(
    document_descriptors: dict[str, dict] | None,
    facet_dimensions: list[str] | None = None,
) -> dict:
    """Aggregate generic facet values from document descriptors."""
    if not document_descriptors:
        return {}
    known_multi_value = {
        "doc_role": False,
        "audience": True,
        "lifecycle": False,
        "content_type": True,
        "surface": True,
        "canonicality": False,
    }
    if facet_dimensions is None:
        facet_dimensions = list(DEFAULT_DOCS_MAP_FACET_DIMENSIONS)
    summaries: dict[str, dict[str, dict]] = {facet: {} for facet in facet_dimensions}
    for doc, descriptor in document_descriptors.items():
        compact_doc = _compact_doc_path(str(doc))
        extra_facets = (
            descriptor.get("facets") if isinstance(descriptor.get("facets"), dict) else {}
        )
        for facet in facet_dimensions:
            is_multi = known_multi_value.get(facet, True)
            raw_value = descriptor.get(facet)
            if raw_value is None:
                raw_value = extra_facets.get(facet)
            values = raw_value if is_multi and isinstance(raw_value, list) else [raw_value]
            for value in values:
                label = str(value or "").strip().lower()
                if not label:
                    continue
                bucket = summaries[facet].setdefault(
                    label,
                    {
                        "value": label,
                        "document_count": 0,
                        "sample_documents": [],
                        "sample_about": [],
                    },
                )
                bucket["document_count"] += 1
                if len(bucket["sample_documents"]) < 8:
                    bucket["sample_documents"].append(compact_doc)
                for about in descriptor.get("about", [])[:3]:
                    if about not in bucket["sample_about"] and len(bucket["sample_about"]) < 8:
                        bucket["sample_about"].append(about)

    return {
        facet: sorted(
            values.values(),
            key=lambda item: (-int(item["document_count"]), item["value"]),
        )
        for facet, values in summaries.items()
        if values
    }


def _fallback_docs_map(taxonomy: dict, method: str) -> dict:
    """Build a deterministic fallback Docs Map shape when no LLM is available."""
    clusters, _singles = _docs_map_topic_cluster_payload(
        taxonomy,
        max_topic_coverage_clusters=80,
        max_single_doc_topics=0,
    )
    parents: dict[str, dict] = {}
    for cluster in clusters:
        topic = str(cluster.get("topic") or "")
        tokens = [t for t in _topic_tokens(topic) if t not in _TOPIC_STOPWORDS]
        parent_label = tokens[0] if tokens else "general documentation"
        parent = parents.setdefault(
            parent_label,
            {
                "id": f"docs_map_{len(parents) + 1:02d}",
                "label": parent_label,
                "description": "Deterministically grouped by shared topic vocabulary.",
                "children": [],
            },
        )
        parent["children"].append(
            {
                "id": f"{parent['id']}_{len(parent['children']) + 1:02d}",
                "label": topic,
                "description": "Canonical topic coverage cluster.",
                "topics": [topic],
                "documents": cluster.get("sample_documents", []),
                "document_count": cluster.get("document_count", 0),
            }
        )

    return {
        "method": method,
        "topic_tree": sorted(
            parents.values(),
            key=lambda p: (-sum(c.get("document_count", 0) for c in p["children"]), p["label"]),
        ),
        "facets": {},
        "diagnostics": [],
        "limits": {
            "note": "LLM Docs Map discovery was unavailable; this is a vocabulary-based fallback.",
        },
    }


def build_docs_map(
    taxonomy: dict,
    *,
    document_descriptors: dict[str, dict] | None = None,
    facet_dimensions: list[str] | None = None,
    facet_values: dict[str, list[str]] | None = None,
    llm_model: str | None = None,
    cache: object | None = None,
    backend: str = "litellm",
    max_topic_coverage_clusters: int = 160,
    max_single_doc_topics: int = 40,
    max_documents: int = 120,
    ollama_host: str | None = None,
    cli_strip_api_key: bool = True,
    cli_permission_mode: str | None = None,
    cli_dangerously_skip_permissions: bool = False,
) -> dict:
    """Infer a generic Docs Map view from topic evidence.

    The returned structure is a candidate Docs Map, not an authoritative site map:
    parent/child topic groups, generic facets, and diagnostics with evidence.
    """
    topic_coverage_clusters, single_doc_topics = _docs_map_topic_cluster_payload(
        taxonomy,
        max_topic_coverage_clusters=max_topic_coverage_clusters,
        max_single_doc_topics=max_single_doc_topics,
    )
    facet_dimensions = facet_dimensions or list(DEFAULT_DOCS_MAP_FACET_DIMENSIONS)
    facet_values = facet_values or DEFAULT_DOCS_MAP_FACET_VALUES
    documents = _docs_map_document_payload(
        taxonomy,
        max_documents=max_documents,
        document_descriptors=document_descriptors,
    )
    descriptor_facets = _descriptor_facet_payload(
        document_descriptors,
        facet_dimensions=facet_dimensions,
    )
    facet_seed = {
        "facet_dimensions": facet_dimensions,
        "suggested_values": {
            name: facet_values.get(name, []) for name in facet_dimensions if facet_values.get(name)
        },
    }
    payload = {
        "topic_coverage_clusters": topic_coverage_clusters,
        "single_document_topics_sample": single_doc_topics,
        "co_occurrence": taxonomy.get("co_occurrence", [])[:80],
        "descriptor_facets": descriptor_facets,
        "facet_seed_suggestions": facet_seed,
        "documents": documents,
        "summary": {
            "canonical_topics": len(taxonomy.get("canonical_topics", [])),
            "topic_document_clusters": len(taxonomy.get("topic_document_clusters", [])),
            "documents": len(taxonomy.get("doc_topics", {})),
            "document_descriptors": len(document_descriptors or {}),
        },
    }

    if not llm_model:
        return _fallback_docs_map(taxonomy, method="deterministic")

    from dryscope.docs.coding import call_llm_cached

    prompt = f"""You are building a Docs Map for a documentation corpus.

You are given rich per-document Docs Map descriptors, discovered canonical labels, their
document coverage, co-occurrence signals, and a compact document-label inventory.
Build a domain-agnostic candidate Docs Map. Do not assume any
product-specific taxonomy in advance; infer labels from the evidence.

Design principles:
- Build a hierarchical topic tree with broad parent topics and specific child topics.
- Allow documents and topics to belong to multiple conceptual areas when the evidence supports it.
- Keep facets separate from the topic tree. Facets should be generic dimensions that
  can apply to any docs repo.
- Prefer useful reader/navigation intent over implementation folder structure.
- Preserve evidence: every child topic and diagnostic should cite supporting topics
  and/or documents from the input.
- Use document descriptors for facets. Canonical labels are mainly for grouping
  aboutness and reader intent, not for inferring lifecycle/audience/role alone.
- Use descriptor_facets as the main evidence for facet dimensions and values.
- Avoid vague parent labels such as "general", "miscellaneous", "documentation", or "overview"
  unless the corpus evidence truly has no stronger label.

Facet seed suggestions:
{json.dumps(facet_seed, indent=2)}

Treat these as generic suggestions, not mandatory output. Include a facet only
when descriptor_facets or document evidence supports it. You may return additional
generic facets if the evidence strongly supports them.

Input evidence:
{json.dumps(payload, indent=2)}

Respond with ONLY valid JSON:
{{
  "method": "llm",
  "topic_tree": [
    {{
      "id": "docs_map_01",
      "label": "parent topic label",
      "description": "why this parent exists",
      "children": [
        {{
          "id": "docs_map_01_01",
          "label": "child topic label",
          "description": "reader intent or content area",
          "topics": ["canonical topic name from input"],
          "documents": ["sample document path from input"],
          "document_count": 0
        }}
      ]
    }}
  ],
  "facets": {{
    "doc_role": {{
      "description": "how this facet appears in the corpus",
      "values": [
        {{"value": "guide", "documents": ["sample document path"], "evidence": ["short signal"]}}
      ]
    }}
  }},
  "diagnostics": [
    {{
      "kind": "overloaded_branch|fragmented_intent|mixed_lifecycle|orphan_topic|weak_label|split_candidate",
      "severity": "high|medium|low",
      "message": "specific IA issue",
      "topics": ["canonical topic name"],
      "documents": ["sample document path"],
      "recommendation": "what to change or inspect"
    }}
  ],
  "notes": ["short caveat or interpretation note"]
}}"""

    cache_key = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
        + llm_model.encode()
        + DOCS_MAP_LLM_VERSION.encode()
    ).hexdigest()
    try:
        text = call_llm_cached(
            llm_model,
            prompt,
            cache,
            cache_key,
            DOCS_MAP_LLM_VERSION,
            backend,
            ollama_host=ollama_host,
            cli_strip_api_key=cli_strip_api_key,
            cli_permission_mode=cli_permission_mode,
            cli_dangerously_skip_permissions=cli_dangerously_skip_permissions,
        )
        ia = _parse_json_object_response(text)
    except Exception as exc:
        print(
            f"warning: {DOCS_MAP} LLM pass failed; "
            f"falling back to deterministic {DOCS_MAP} grouping "
            f"({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        ia = {}

    if not ia:
        return _fallback_docs_map(taxonomy, method="deterministic-fallback")

    ia.setdefault("method", "llm")
    ia.setdefault("topic_tree", [])
    ia.setdefault("facets", {})
    ia.setdefault("diagnostics", [])
    ia["source_summary"] = payload["summary"]
    ia["limits"] = {
        "topic_coverage_clusters_sent": len(topic_coverage_clusters),
        "single_document_topics_sent": len(single_doc_topics),
        "documents_sent": len(documents),
    }
    return ia
