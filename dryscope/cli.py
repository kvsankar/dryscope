"""CLI entry point for dryscope."""

from __future__ import annotations

import sys

import click

from dryscope import __version__
from dryscope.parser import parse_directory
from dryscope.normalizer import normalize
from dryscope.embedder import Embedder
from dryscope.similarity import find_duplicates, cluster_duplicates
from dryscope.reporter import build_clusters, format_json, format_terminal


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--threshold", "-t", default=0.85, type=float, help="Similarity threshold (0.0-1.0)")
@click.option("--min-lines", "-m", default=3, type=int, help="Minimum lines for a code unit")
@click.option("--format", "-f", "output_format", type=click.Choice(["terminal", "json"]), default="terminal")
@click.option("--model", default="all-MiniLM-L6-v2", help="Sentence-transformer model name")
@click.version_option(version=__version__)
def main(path: str, threshold: float, min_lines: int, output_format: str, model: str) -> None:
    """Detect duplicate code in Python files under PATH."""
    # 1. Parse
    click.echo(f"Parsing Python files in {path}...", err=True)
    units = parse_directory(path, min_lines=min_lines)
    if not units:
        click.echo("No code units found.", err=True)
        sys.exit(0)
    click.echo(f"Found {len(units)} code units.", err=True)

    # 2. Normalize
    click.echo("Normalizing...", err=True)
    normalized = [normalize(u.source) for u in units]

    # 3. Embed
    click.echo(f"Generating embeddings (model: {model})...", err=True)
    embedder = Embedder(model_name=model)
    embeddings = embedder.embed(normalized)

    # 4. Find duplicates
    click.echo(f"Finding duplicates (threshold: {threshold})...", err=True)
    line_counts = [u.line_count for u in units]
    pairs = find_duplicates(
        embeddings,
        threshold=threshold,
        line_counts=line_counts,
        normalized_texts=normalized,
    )
    clusters_idx = cluster_duplicates(len(units), pairs)

    # 5. Report
    clusters = build_clusters(units, clusters_idx, pairs)
    if output_format == "json":
        click.echo(format_json(clusters))
    else:
        click.echo(format_terminal(clusters))


if __name__ == "__main__":
    main()
