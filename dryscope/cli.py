"""CLI entry point for dryscope."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import click

from dryscope import __version__
from dryscope.parser import parse_directory
from dryscope.normalizer import normalize
from dryscope.profiles import detect_profiles, merge_profiles
from dryscope.embedder import Embedder
from dryscope.similarity import find_duplicates, cluster_duplicates
from dryscope.reporter import build_clusters, format_json, format_terminal

SKILL_TEMPLATE = Path(__file__).parent / "skill" / "SKILL.md"
SKILL_DEST = Path.home() / ".claude" / "skills" / "dryscope"


def _find_project_root() -> Path:
    """Find the project root containing pyproject.toml."""
    path = Path(__file__).resolve().parent
    while path != path.parent:
        if (path / "pyproject.toml").exists():
            return path
        path = path.parent
    raise FileNotFoundError("Could not find pyproject.toml")


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version=__version__)
def main(ctx: click.Context) -> None:
    """dryscope — code duplicate detection using tree-sitter and embeddings."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--threshold", "-t", default=0.90, type=float, help="Similarity threshold (0.0-1.0)")
@click.option("--min-lines", "-m", default=6, type=int, help="Minimum lines for a code unit")
@click.option("--min-tokens", default=0, type=int, help="Minimum unique normalized tokens for a code unit")
@click.option("--max-cluster-size", default=15, type=int, help="Drop clusters larger than this")
@click.option("--exclude", "-e", multiple=True, help="Glob patterns to exclude (e.g. '*/tests/*')")
@click.option("--exclude-type", multiple=True, help="Base class types to exclude (e.g. TextChoices)")
@click.option("--format", "-f", "output_format", type=click.Choice(["terminal", "json"]), default="terminal")
@click.option("--model", default="all-MiniLM-L6-v2", help="Sentence-transformer model name")
@click.option("--verify", is_flag=True, default=False, help="Use LLM to verify clusters (requires litellm)")
@click.option("--llm-model", default="gpt-4o-mini", envvar="DRYSCOPE_LLM_MODEL", help="LLM model for --verify (any litellm model)")
@click.option("--llm-api-key", default=None, help="API key for --verify (overrides provider env var)")
def scan(
    path: str,
    threshold: float,
    min_lines: int,
    min_tokens: int,
    max_cluster_size: int,
    exclude: tuple[str, ...],
    exclude_type: tuple[str, ...],
    output_format: str,
    model: str,
    verify: bool,
    llm_model: str,
    llm_api_key: str | None,
) -> None:
    """Scan PATH for duplicate code."""
    # Detect project profiles and merge exclusions
    profiles = detect_profiles(path)
    if profiles:
        names = ", ".join(p.name for p in profiles)
        click.echo(f"Detected project profile(s): {names}", err=True)

    user_patterns = list(exclude) if exclude else None
    user_types = set(exclude_type) if exclude_type else None
    exclude_patterns, exclude_types, extra_dirs = merge_profiles(
        profiles, user_patterns, user_types,
    )

    click.echo(f"Parsing source files in {path}...", err=True)
    units = parse_directory(
        path,
        min_lines=min_lines,
        exclude_patterns=exclude_patterns,
        exclude_types=exclude_types,
        exclude_dirs=extra_dirs,
    )
    if not units:
        click.echo("No code units found.", err=True)
        sys.exit(0)
    click.echo(f"Found {len(units)} code units.", err=True)

    click.echo("Normalizing...", err=True)
    normalized = [normalize(u.source, lang=u.lang) for u in units]

    # P0: Filter by unique token count after normalization
    if min_tokens > 0:
        filtered = [
            (u, n) for u, n in zip(units, normalized)
            if len(set(n.split())) >= min_tokens
        ]
        removed = len(units) - len(filtered)
        if removed:
            click.echo(f"Filtered {removed} units with < {min_tokens} unique tokens.", err=True)
            units, normalized = zip(*filtered) if filtered else ([], [])
            units, normalized = list(units), list(normalized)
        if not units:
            click.echo("No code units remaining after token filter.", err=True)
            sys.exit(0)

    click.echo(f"Generating embeddings (model: {model})...", err=True)
    embedder = Embedder(model_name=model)
    embeddings = embedder.embed(normalized)

    click.echo(f"Finding duplicates (threshold: {threshold})...", err=True)
    line_counts = [u.line_count for u in units]
    pairs = find_duplicates(
        embeddings,
        threshold=threshold,
        line_counts=line_counts,
        normalized_texts=normalized,
    )
    clusters_idx = cluster_duplicates(len(units), pairs, max_cluster_size=max_cluster_size)

    clusters = build_clusters(units, clusters_idx, pairs, normalized_texts=normalized)

    # LLM verification pass
    if verify:
        try:
            import litellm  # noqa: F401
        except ImportError:
            click.echo(
                "Error: --verify requires litellm. Install with: pip install 'dryscope[verify]'",
                err=True,
            )
            sys.exit(1)

        from dryscope.verifier import verify_clusters, VERDICT_NOISE

        click.echo(f"Verifying {len(clusters)} clusters with {llm_model}...", err=True)
        results = verify_clusters(clusters, model=llm_model, api_key=llm_api_key)

        verified: list = []
        noise_count = 0
        for cluster, verdict, reason in results:
            cluster.verdict = verdict
            cluster.verdict_reason = reason
            if verdict == VERDICT_NOISE:
                noise_count += 1
            else:
                verified.append(cluster)

        click.echo(f"LLM filtered {noise_count} noise clusters, {len(verified)} remaining.", err=True)
        clusters = verified

    if output_format == "json":
        click.echo(format_json(clusters))
    else:
        click.echo(format_terminal(clusters))


@main.command()
def install() -> None:
    """Install dryscope as a Claude Code skill with its own venv."""
    claude_dir = Path.home() / ".claude"
    if not claude_dir.exists():
        click.echo("~/.claude/ not found. Is Claude Code installed?", err=True)
        sys.exit(1)

    if not SKILL_TEMPLATE.exists():
        click.echo(f"SKILL.md template not found at {SKILL_TEMPLATE}", err=True)
        sys.exit(1)

    project_root = _find_project_root()
    venv_dir = SKILL_DEST / ".venv"
    dryscope_bin = venv_dir / "bin" / "dryscope"

    SKILL_DEST.mkdir(parents=True, exist_ok=True)

    click.echo(f"Creating venv at {venv_dir}...", err=True)
    subprocess.run(
        ["uv", "venv", str(venv_dir), "--python", ">=3.10"],
        check=True,
    )

    click.echo("Installing dryscope into skill venv...", err=True)
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_dir / "bin" / "python"), f"{project_root}[verify]"],
        check=True,
    )

    template = SKILL_TEMPLATE.read_text()
    rendered = template.replace("{{DRYSCOPE_BIN}}", str(dryscope_bin))
    (SKILL_DEST / "SKILL.md").write_text(rendered)

    click.echo(f"Installed dryscope skill to {SKILL_DEST}")
    click.echo(f"Binary: {dryscope_bin}")


@main.command()
def uninstall() -> None:
    """Remove the dryscope Claude Code skill and its venv."""
    if SKILL_DEST.exists():
        shutil.rmtree(SKILL_DEST)
        click.echo(f"Removed {SKILL_DEST}")
    else:
        click.echo("dryscope skill not installed.", err=True)


if __name__ == "__main__":
    main()
