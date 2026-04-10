"""Deterministic post-verification policy for escalating code clusters."""

from __future__ import annotations

from dataclasses import dataclass

from dryscope.code.reporter import Cluster
from dryscope.code.verifier import VERDICT_REFACTOR, VERDICT_REVIEW


@dataclass(frozen=True)
class EscalationPolicy:
    """Thresholds controlling which verified clusters reach expensive models."""

    refactor_min_lines: int = 40
    refactor_min_actionability: float = 2.0
    refactor_min_units: int = 3
    keep_same_file_refactors: bool = False


def should_escalate_cluster(cluster: Cluster, policy: EscalationPolicy) -> bool:
    """Return whether a verified cluster should be kept for expensive follow-up.

    Rules:
    - Always keep "review" clusters for human/strong-model inspection.
    - Never keep non-refactor/non-review clusters.
    - Keep refactor clusters with many copies, because repeated duplication can
      be worthwhile even within one file.
    - Otherwise require cross-file evidence unless same-file refactors are
      explicitly enabled.
    - Then require either enough total duplicated lines or enough actionability.
    """
    if cluster.verdict == VERDICT_REVIEW:
        return True
    if cluster.verdict != VERDICT_REFACTOR:
        return False
    if len(cluster.units) >= policy.refactor_min_units:
        return True

    if not cluster.is_cross_file and not policy.keep_same_file_refactors:
        return False

    if cluster.total_lines >= policy.refactor_min_lines:
        return True
    if cluster.actionability >= policy.refactor_min_actionability:
        return True
    return False
