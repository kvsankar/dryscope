"""Format and output duplicate clusters."""

from __future__ import annotations

import json
from dataclasses import dataclass

from dryscope.parser import CodeUnit
from dryscope.similarity import DuplicatePair


@dataclass
class Cluster:
    """A cluster of similar code units."""

    cluster_id: int
    units: list[CodeUnit]
    max_similarity: float

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "max_similarity": round(self.max_similarity, 4),
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


def build_clusters(
    units: list[CodeUnit],
    cluster_indices: list[list[int]],
    pairs: list[DuplicatePair],
) -> list[Cluster]:
    """Build Cluster objects from indices and pairs."""
    # Build a lookup for max similarity within each cluster
    pair_sims: dict[tuple[int, int], float] = {}
    for p in pairs:
        key = (min(p.idx_a, p.idx_b), max(p.idx_a, p.idx_b))
        pair_sims[key] = max(pair_sims.get(key, 0.0), p.similarity)

    clusters: list[Cluster] = []
    for cid, indices in enumerate(cluster_indices):
        cluster_units = [units[i] for i in indices]
        max_sim = 0.0
        for i, a in enumerate(indices):
            for b in indices[i + 1 :]:
                key = (min(a, b), max(a, b))
                max_sim = max(max_sim, pair_sims.get(key, 0.0))
        clusters.append(Cluster(cluster_id=cid, units=cluster_units, max_similarity=max_sim))

    # Sort by highest similarity first
    clusters.sort(key=lambda c: c.max_similarity, reverse=True)
    for i, c in enumerate(clusters):
        c.cluster_id = i

    return clusters


def format_json(clusters: list[Cluster]) -> str:
    """Output clusters as JSON."""
    return json.dumps(
        {"duplicate_clusters": [c.to_dict() for c in clusters], "total_clusters": len(clusters)},
        indent=2,
    )


def format_terminal(clusters: list[Cluster]) -> str:
    """Pretty-print clusters for terminal display."""
    if not clusters:
        return "No duplicate clusters found."

    lines: list[str] = []
    lines.append(f"Found {len(clusters)} duplicate cluster(s):\n")

    for cluster in clusters:
        lines.append(f"--- Cluster {cluster.cluster_id} (similarity: {cluster.max_similarity:.4f}) ---")
        for unit in cluster.units:
            lines.append(f"  {unit.unit_type} '{unit.name}' at {unit.file_path}:{unit.start_line}-{unit.end_line} ({unit.line_count} lines)")
        lines.append("")

    return "\n".join(lines)
