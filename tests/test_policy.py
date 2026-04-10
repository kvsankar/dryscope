"""Tests for deterministic post-verification code escalation policy."""

from dryscope.code.parser import CodeUnit
from dryscope.code.policy import EscalationPolicy, should_escalate_cluster
from dryscope.code.reporter import Cluster, Tier


def _make_cluster(
    *,
    verdict: str,
    is_cross_file: bool,
    total_lines: int,
    actionability: float,
    unit_count: int = 2,
) -> Cluster:
    units = []
    for idx in range(unit_count):
        units.append(
            CodeUnit(
                name=f"f{idx}",
                unit_type="function",
                source="def f():\n    return 1\n",
                file_path=f"a{idx}.py" if is_cross_file else "a.py",
                start_line=1,
                end_line=2,
            )
        )
    return Cluster(
        cluster_id=0,
        units=units,
        max_similarity=0.95,
        tier=Tier.NEAR,
        is_cross_file=is_cross_file,
        total_lines=total_lines,
        files=sorted({u.file_path for u in units}),
        actionability=actionability,
        verdict=verdict,
        verdict_reason="test",
    )


def test_review_clusters_always_escalate():
    cluster = _make_cluster(
        verdict="review",
        is_cross_file=False,
        total_lines=8,
        actionability=0.5,
    )
    assert should_escalate_cluster(cluster, EscalationPolicy()) is True


def test_noise_clusters_never_escalate():
    cluster = _make_cluster(
        verdict="noise",
        is_cross_file=True,
        total_lines=200,
        actionability=5.0,
    )
    assert should_escalate_cluster(cluster, EscalationPolicy()) is False


def test_refactor_cluster_with_many_copies_escalates_even_same_file():
    cluster = _make_cluster(
        verdict="refactor",
        is_cross_file=False,
        total_lines=18,
        actionability=0.8,
        unit_count=3,
    )
    assert should_escalate_cluster(cluster, EscalationPolicy()) is True


def test_same_file_refactor_dropped_by_default_if_not_large_enough():
    cluster = _make_cluster(
        verdict="refactor",
        is_cross_file=False,
        total_lines=30,
        actionability=1.9,
    )
    assert should_escalate_cluster(cluster, EscalationPolicy()) is False


def test_cross_file_refactor_escalates_when_large_enough():
    cluster = _make_cluster(
        verdict="refactor",
        is_cross_file=True,
        total_lines=45,
        actionability=1.0,
    )
    assert should_escalate_cluster(cluster, EscalationPolicy()) is True


def test_cross_file_refactor_escalates_when_actionable_enough():
    cluster = _make_cluster(
        verdict="refactor",
        is_cross_file=True,
        total_lines=20,
        actionability=2.2,
    )
    assert should_escalate_cluster(cluster, EscalationPolicy()) is True


def test_same_file_refactor_can_be_enabled_via_policy():
    cluster = _make_cluster(
        verdict="refactor",
        is_cross_file=False,
        total_lines=45,
        actionability=1.0,
    )
    policy = EscalationPolicy(keep_same_file_refactors=True)
    assert should_escalate_cluster(cluster, policy) is True
