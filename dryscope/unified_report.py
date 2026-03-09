"""Unified JSON and terminal reporters for combined code + docs output."""

from __future__ import annotations

import json

from dryscope import __version__
from dryscope.code.reporter import Cluster, Tier, format_terminal as code_format_terminal


def _code_cluster_to_finding(cluster: Cluster, finding_id: int) -> dict:
    """Convert a code Cluster to a unified finding dict."""
    d = cluster.to_dict()
    d["id"] = finding_id
    d["mode"] = "code"
    d["similarity"] = d.pop("max_similarity")
    d.pop("cluster_id", None)
    return d


def _doc_pair_to_finding(
    pair,
    finding_id: int,
    analysis: object | None = None,
) -> dict:
    """Convert a docs OverlapPair to a unified finding dict."""
    sections = []
    for chunk in (pair.chunk_a, pair.chunk_b):
        sections.append({
            "file": chunk.document_path,
            "heading": " > ".join(chunk.heading_path) if chunk.heading_path else "",
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "content": chunk.content[:500],
        })

    verdict = None
    verdict_reason = None
    if analysis is not None:
        # DocPairAnalysis has relationship and topics
        verdict = analysis.relationship
        if analysis.topics:
            verdict_reason = "; ".join(
                f"{t.name}: {t.action_for_other}" for t in analysis.topics
            )

    return {
        "id": finding_id,
        "mode": "docs",
        "similarity": round(pair.embedding_similarity, 4) if pair.embedding_similarity is not None else None,
        "files": sorted(set([pair.chunk_a.document_path, pair.chunk_b.document_path])),
        "sections": sections,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }


def format_unified_json(
    code_clusters: list[Cluster] | None = None,
    doc_pairs: list | None = None,
    doc_analyses: list | None = None,
) -> str:
    """Build unified JSON output combining code and docs findings.

    Args:
        code_clusters: Cluster objects from code pipeline, or None.
        doc_pairs: OverlapPair objects from docs pipeline, or None.
        doc_analyses: DocPairAnalysis objects for verdict/reason, or None.
    """
    findings: list[dict] = []
    fid = 0

    # Code findings
    code_summary = {"total": 0, "exact": 0, "near": 0, "structural": 0}
    if code_clusters is not None:
        for cluster in code_clusters:
            findings.append(_code_cluster_to_finding(cluster, fid))
            code_summary["total"] += 1
            code_summary[cluster.tier.value] += 1
            fid += 1

    # Docs findings
    docs_summary = {"total": 0}
    if doc_pairs is not None:
        # Build lookup from (doc_a, doc_b) -> analysis
        analysis_map: dict[tuple[str, str], object] = {}
        if doc_analyses:
            for a in doc_analyses:
                key = (a.doc_a_path, a.doc_b_path)
                analysis_map[key] = a
                # Also store reverse key
                analysis_map[(a.doc_b_path, a.doc_a_path)] = a

        for pair in doc_pairs:
            key = (pair.chunk_a.document_path, pair.chunk_b.document_path)
            analysis = analysis_map.get(key)
            findings.append(_doc_pair_to_finding(pair, fid, analysis))
            docs_summary["total"] += 1
            fid += 1

    # Build summary — only include sections that were scanned
    summary: dict = {}
    if code_clusters is not None:
        summary["code"] = code_summary
    if doc_pairs is not None:
        summary["docs"] = docs_summary

    output = {
        "dryscope_version": __version__,
        "findings": findings,
        "summary": summary,
    }

    return json.dumps(output, indent=2)


def format_unified_terminal(
    code_clusters: list[Cluster] | None = None,
    doc_pairs: list | None = None,
    doc_analyses: list | None = None,
) -> str:
    """Build unified terminal output combining code and docs sections.

    Delegates to existing formatters for each section.
    """
    parts: list[str] = []

    if code_clusters is not None:
        parts.append("=== Code Duplicates ===\n")
        parts.append(code_format_terminal(code_clusters))

    if doc_pairs is not None:
        if parts:
            parts.append("")
        parts.append("=== Documentation Overlap ===\n")
        if not doc_pairs:
            parts.append("No documentation overlap found.")
        else:
            parts.append(f"Found {len(doc_pairs)} overlapping section pair(s).\n")
            for pair in doc_pairs:
                sim = f"{pair.embedding_similarity:.4f}" if pair.embedding_similarity is not None else "N/A"
                file_a = pair.chunk_a.document_path
                file_b = pair.chunk_b.document_path
                heading_a = " > ".join(pair.chunk_a.heading_path) if pair.chunk_a.heading_path else "(no heading)"
                heading_b = " > ".join(pair.chunk_b.heading_path) if pair.chunk_b.heading_path else "(no heading)"
                parts.append(f"  sim={sim}")
                parts.append(f"    {file_a} :: {heading_a}")
                parts.append(f"    {file_b} :: {heading_b}")
                parts.append("")

    return "\n".join(parts)
