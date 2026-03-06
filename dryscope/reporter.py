"""Format and output duplicate clusters with tiered classification."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from dryscope.parser import CodeUnit
from dryscope.similarity import DuplicatePair


class Tier(str, Enum):
    EXACT = "exact"      # normalized text match
    NEAR = "near"        # similarity >= 0.95
    STRUCTURAL = "structural"  # similarity < 0.95


@dataclass
class Cluster:
    """A cluster of similar code units with classification metadata."""

    cluster_id: int
    units: list[CodeUnit]
    max_similarity: float
    tier: Tier = Tier.STRUCTURAL
    is_cross_file: bool = False
    total_lines: int = 0
    files: list[str] = field(default_factory=list)
    actionability: float = 0.0

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "tier": self.tier.value,
            "max_similarity": round(self.max_similarity, 4),
            "is_cross_file": self.is_cross_file,
            "total_lines": self.total_lines,
            "files": self.files,
            "actionability": round(self.actionability, 2),
            "units": [
                {
                    "name": u.name,
                    "type": u.unit_type,
                    "file": u.file_path,
                    "start_line": u.start_line,
                    "end_line": u.end_line,
                    "lines": u.line_count,
                    "source": u.source,
                }
                for u in self.units
            ],
        }


def _classify_tier(
    indices: list[int],
    normalized_texts: list[str],
    max_similarity: float,
) -> Tier:
    """Classify a cluster into a tier based on normalized text equality and similarity."""
    texts = [normalized_texts[i] for i in indices]
    if len(set(texts)) == 1:
        return Tier.EXACT
    if max_similarity >= 0.95:
        return Tier.NEAR
    return Tier.STRUCTURAL


def _compute_actionability(cluster: Cluster) -> float:
    """Score how actionable a cluster is (higher = more worth refactoring).

    Factors:
    - Similarity (higher = more likely real duplication)
    - Total lines (larger duplicates = more value in refactoring)
    - Cross-file (stronger signal than same-file)
    - Production code (not test code)
    - Cluster precision (smaller clusters = more precise)
    """
    sim_score = cluster.max_similarity

    # Log-scale line score: 10 lines = 1.0, 100 lines = 2.0
    import math
    line_score = math.log10(max(cluster.total_lines, 1))

    cross_file_bonus = 1.5 if cluster.is_cross_file else 1.0

    # Production code bonus: penalize if all units are in test files
    test_count = sum(1 for u in cluster.units if "/test" in u.file_path or "test_" in u.file_path.split("/")[-1])
    prod_ratio = 1.0 - (test_count / len(cluster.units)) * 0.3

    # Precision: smaller clusters are more precise
    size_penalty = 1.0 / math.log2(max(len(cluster.units), 2))

    return sim_score * line_score * cross_file_bonus * prod_ratio * size_penalty


def build_clusters(
    units: list[CodeUnit],
    cluster_indices: list[list[int]],
    pairs: list[DuplicatePair],
    normalized_texts: list[str] | None = None,
) -> list[Cluster]:
    """Build classified Cluster objects from indices and pairs."""
    pair_sims: dict[tuple[int, int], float] = {}
    for p in pairs:
        key = (min(p.idx_a, p.idx_b), max(p.idx_a, p.idx_b))
        pair_sims[key] = max(pair_sims.get(key, 0.0), p.similarity)

    clusters: list[Cluster] = []
    for cid, indices in enumerate(cluster_indices):
        cluster_units = [units[i] for i in indices]

        max_sim = 0.0
        for i, a in enumerate(indices):
            for b in indices[i + 1:]:
                key = (min(a, b), max(a, b))
                max_sim = max(max_sim, pair_sims.get(key, 0.0))

        unique_files = sorted(set(u.file_path for u in cluster_units))
        total_lines = sum(u.line_count for u in cluster_units)

        tier = Tier.STRUCTURAL
        if normalized_texts is not None:
            tier = _classify_tier(indices, normalized_texts, max_sim)

        cluster = Cluster(
            cluster_id=cid,
            units=cluster_units,
            max_similarity=max_sim,
            tier=tier,
            is_cross_file=len(unique_files) > 1,
            total_lines=total_lines,
            files=unique_files,
        )
        cluster.actionability = _compute_actionability(cluster)
        clusters.append(cluster)

    # Sort by actionability (highest first)
    clusters.sort(key=lambda c: c.actionability, reverse=True)
    for i, c in enumerate(clusters):
        c.cluster_id = i

    return clusters


def format_json(clusters: list[Cluster]) -> str:
    """Output clusters as JSON with tier and metadata."""
    by_tier = {t.value: 0 for t in Tier}
    for c in clusters:
        by_tier[c.tier.value] += 1

    return json.dumps(
        {
            "summary": {
                "total_clusters": len(clusters),
                "by_tier": by_tier,
            },
            "duplicate_clusters": [c.to_dict() for c in clusters],
        },
        indent=2,
    )


_TIER_LABELS = {
    Tier.EXACT: "EXACT COPIES (normalized text identical — always refactor)",
    Tier.NEAR: "NEAR-IDENTICAL (similarity >= 0.95 — usually refactor)",
    Tier.STRUCTURAL: "STRUCTURAL SIMILARITY (0.85-0.95 — review needed)",
}


def _format_cluster(cluster: Cluster) -> list[str]:
    """Format a single cluster for terminal display."""
    lines: list[str] = []
    location = "cross-file" if cluster.is_cross_file else "same-file"
    lines.append(
        f"  Cluster {cluster.cluster_id}  "
        f"sim={cluster.max_similarity:.4f}  "
        f"{location}  "
        f"{cluster.total_lines} total lines  "
        f"score={cluster.actionability:.1f}"
    )
    for unit in cluster.units:
        lines.append(
            f"    {unit.unit_type} '{unit.name}' "
            f"at {unit.file_path}:{unit.start_line}-{unit.end_line} "
            f"({unit.line_count} lines)"
        )
    lines.append("")
    return lines


def format_terminal(clusters: list[Cluster]) -> str:
    """Pretty-print clusters grouped by tier, cross-file first within each tier."""
    if not clusters:
        return "No duplicate clusters found."

    lines: list[str] = []

    # Group by tier
    by_tier: dict[Tier, list[Cluster]] = {t: [] for t in Tier}
    for c in clusters:
        by_tier[c.tier].append(c)

    # Summary
    total = len(clusters)
    parts = [f"{len(by_tier[t])} {t.value}" for t in Tier if by_tier[t]]
    lines.append(f"Found {total} cluster(s): {', '.join(parts)}\n")

    for tier in Tier:
        tier_clusters = by_tier[tier]
        if not tier_clusters:
            continue

        lines.append(f"=== {_TIER_LABELS[tier]} ===\n")

        # Cross-file first, then same-file
        cross = [c for c in tier_clusters if c.is_cross_file]
        same = [c for c in tier_clusters if not c.is_cross_file]

        for c in cross + same:
            lines.extend(_format_cluster(c))

    return "\n".join(lines)
