"""Data models for document overlap detection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A section of a document, typically split by headings."""

    document_path: str
    heading_path: list[str]
    content: str
    line_start: int
    line_end: int
    id: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.id = hashlib.sha256(f"{self.document_path}:{self.line_start}:{self.content}".encode()).hexdigest()[:16]


@dataclass
class OverlapPair:
    """A pair of chunks identified as potentially overlapping."""

    chunk_a: Chunk
    chunk_b: Chunk
    embedding_similarity: float | None = None
    shared_codes: list[str] = field(default_factory=list)


@dataclass
class Code:
    """A qualitative code assigned by LLM analysis."""

    name: str
    category: str = ""
    chunks: list[Chunk] = field(default_factory=list)
    canonical_doc: str | None = None


@dataclass
class Category:
    """A group of related codes."""

    name: str
    codes: list[Code] = field(default_factory=list)


@dataclass
class Document:
    """A parsed document with its chunks."""

    path: str
    chunks: list[Chunk] = field(default_factory=list)


@dataclass
class TopicAnalysis:
    """A single overlap topic identified between two documents."""

    name: str                  # kebab-case topic label
    canonical: str | None      # path of canonical document, if specified
    action_for_other: str      # "consolidate" | "link" | "brief-reference" | "keep"
    reason: str
    chunks_a: list[Chunk] = field(default_factory=list)
    chunks_b: list[Chunk] = field(default_factory=list)


@dataclass
class IntentMatch:
    """A topic match between two documents indicating intent overlap."""

    doc_a_path: str
    doc_b_path: str
    topic_a: str
    topic_b: str
    similarity: float


@dataclass
class DocPairAnalysis:
    """LLM analysis of overlap between two documents."""

    doc_a_path: str
    doc_b_path: str
    doc_a_purpose: str
    doc_b_purpose: str
    relationship: str          # "subset" | "complementary" | "stale-copy" | "divergent-versions" | "different-audiences" | "fragmented"
    topics: list[TopicAnalysis] = field(default_factory=list)
    confidence: str = "medium" # "high" | "medium" | "low"
    overlap_pairs: list[OverlapPair] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Complete analysis output from the pipeline."""

    documents: list[Document] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    overlaps: list[OverlapPair] = field(default_factory=list)
    codes: list[Code] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    doc_pair_analyses: list[DocPairAnalysis] = field(default_factory=list)
    document_descriptors: dict[str, dict] = field(default_factory=dict)
    topic_taxonomy: dict | None = None
