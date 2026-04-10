"""CLI entry point for dryscope — unified code duplicate and doc overlap detection."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import click

from dryscope import __version__

SKILL_TEMPLATE = Path(__file__).parent / "skill" / "SKILL.md"
SKILL_DESTS = [
    Path.home() / ".claude" / "skills" / "dryscope",
    Path.home() / ".codex" / "skills" / "dryscope",
]


def _find_project_root() -> Path:
    """Find the project root containing pyproject.toml."""
    path = Path(__file__).resolve().parent
    while path != path.parent:
        if (path / "pyproject.toml").exists():
            return path
        path = path.parent
    raise FileNotFoundError("Could not find pyproject.toml")


def _find_git_root(scan_path: Path) -> Path:
    """Find the git root, falling back to scan_path."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(scan_path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            return Path(proc.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return scan_path


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version=__version__)
def main(ctx: click.Context) -> None:
    """dryscope — code duplicate and documentation overlap detection."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ─── Code scan ────────────────────────────────────────────────────────────


def _run_code_scan(
    path: str,
    settings: "Settings",
    exclude: tuple[str, ...],
    exclude_type: tuple[str, ...],
    verify: bool,
    llm_api_key: str | None,
    lang: str | None,
) -> list | None:
    """Run the code duplicate detection pipeline and return clusters.

    Returns a list of Cluster objects, or None if no units were found.
    """
    from dryscope.code.parser import parse_directory
    from dryscope.code.normalizer import normalize
    from dryscope.code.profiles import detect_profiles, merge_profiles
    from dryscope.code.embedder import Embedder
    from dryscope.similarity import find_duplicates, cluster_duplicates
    from dryscope.code.reporter import build_clusters

    threshold = settings.code_threshold
    min_lines = settings.code_min_lines
    min_tokens = settings.code_min_tokens
    max_cluster_size = settings.code_max_cluster_size
    model = settings.code_embedding_model
    llm_model = settings.model

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

    # Filter by language if specified
    if lang:
        lang_map = {"python": "python", "ts": "typescript", "tsx": "tsx", "typescript": "typescript"}
        target_lang = lang_map.get(lang)
        if target_lang:
            units = [u for u in units if u.lang == target_lang]

    if not units:
        click.echo("No code units found.", err=True)
        return None
    click.echo(f"Found {len(units)} code units.", err=True)

    click.echo("Normalizing...", err=True)
    normalized = [normalize(u.source, lang=u.lang) for u in units]

    # Filter by unique token count after normalization
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
            return None

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
        from dryscope.code.verifier import verify_clusters, VERDICT_NOISE
        from dryscope.code.policy import EscalationPolicy, should_escalate_cluster

        click.echo(f"Verifying {len(clusters)} clusters with {llm_model}...", err=True)
        results = verify_clusters(
            clusters,
            model=llm_model,
            max_workers=settings.concurrency,
            backend=settings.backend,
            api_key=llm_api_key,
            ollama_host=settings.ollama_host,
            cli_strip_api_key=settings.cli_strip_api_key,
            cli_permission_mode=settings.cli_permission_mode,
            cli_dangerously_skip_permissions=settings.cli_dangerously_skip_permissions,
        )

        verified: list = []
        noise_count = 0
        policy_drop_count = 0
        policy = EscalationPolicy(
            refactor_min_lines=settings.code_escalate_refactor_min_lines,
            refactor_min_actionability=settings.code_escalate_refactor_min_actionability,
            refactor_min_units=settings.code_escalate_refactor_min_units,
            keep_same_file_refactors=settings.code_keep_same_file_refactors,
        )
        for cluster, verdict, reason in results:
            cluster.verdict = verdict
            cluster.verdict_reason = reason
            if verdict == VERDICT_NOISE:
                noise_count += 1
            elif should_escalate_cluster(cluster, policy):
                verified.append(cluster)
            else:
                policy_drop_count += 1

        click.echo(
            f"LLM filtered {noise_count} noise clusters, policy dropped {policy_drop_count} "
            f"low-priority verified clusters, {len(verified)} remaining.",
            err=True,
        )
        clusters = verified

    return clusters


# ─── Docs scan ────────────────────────────────────────────────────────────


def _run_docs_scan(
    path: str,
    settings: "Settings",
    output_format: str,
    verify: bool,
    stage: str,
    resume: bool,
) -> None:
    """Run the documentation overlap detection pipeline."""
    from rich.console import Console

    from dryscope.docs.pipeline import run_pipeline
    from dryscope.run_store import RunStore

    scan_path = Path(path).resolve()
    err_console = Console(stderr=True)

    doc_stage = "full" if verify else stage

    project_root = _find_git_root(scan_path)

    if resume:
        store = RunStore.find_latest(project_root)
        if store is None:
            click.echo("No previous run found to resume.", err=True)
            store = RunStore(project_root)
    else:
        store = RunStore(project_root)

    run_pipeline(
        scan_path=scan_path,
        settings=settings,
        stage=doc_stage,
        output_format=output_format,
        skip_confirm=True,
        console=err_console,
        run_store=store,
    )

    store.update_latest_symlink()
    click.echo(f"Run saved to {store.run_dir}", err=True)


# ─── Unified scan command ─────────────────────────────────────────────────


@main.command()
@click.argument("path", type=click.Path(exists=True))
# Mode flags
@click.option("--code/--no-code", default=None, help="Scan for code duplicates")
@click.option("--docs/--no-docs", default=None, help="Scan for documentation overlap")
@click.option("--lang", type=click.Choice(["python", "ts", "tsx"]), default=None, help="Filter to specific language (code mode)")
# Shared options
@click.option("--threshold", "-t", default=0.90, type=click.FloatRange(0.0, 1.0), help="Similarity threshold (0.0-1.0)")
@click.option("--format", "-f", "output_format", type=click.Choice(["terminal", "json", "markdown", "html"]), default="terminal")
@click.option("--verify", is_flag=True, default=False, help="Use LLM to verify/analyze findings")
@click.option("--llm-model", default="claude-haiku-4-5-20251001", envvar="DRYSCOPE_LLM_MODEL", help="LLM model for --verify")
@click.option("--llm-api-key", default=None, help="API key for --verify")
# Code-specific options
@click.option("--min-lines", "-m", default=6, type=int, help="Minimum lines for a code unit")
@click.option("--min-tokens", default=0, type=int, help="Minimum unique normalized tokens")
@click.option("--max-cluster-size", default=15, type=int, help="Drop clusters larger than this")
@click.option("--exclude", "-e", multiple=True, help="Glob patterns to exclude")
@click.option("--exclude-type", multiple=True, help="Base class types to exclude")
@click.option("--embedding-model", "model", default="all-MiniLM-L6-v2", help="Sentence-transformer model name")
# Docs-specific options
@click.option("--stage", type=click.Choice(["similarity", "full"]), default="similarity", help="Docs pipeline stage")
@click.option("--resume", is_flag=True, default=False, help="Resume from latest docs run")
@click.option("--intra", is_flag=True, default=False, help="Include intra-document section overlap")
@click.option("--min-words", default=None, type=int, help="Minimum words per doc section")
@click.option("--threshold-intent", default=None, type=float, help="Intent overlap threshold (docs)")
@click.option("--concurrency", default=None, type=int, help="Max parallel LLM calls (docs)")
@click.option("--backend", type=click.Choice(["litellm", "cli", "ollama"]), default=None, help="LLM backend for --verify")
@click.option("--token-weight", default=None, type=float, help="Token Jaccard weight in hybrid similarity")
@click.pass_context
def scan(
    ctx: click.Context,
    path: str,
    code: bool | None,
    docs: bool | None,
    lang: str | None,
    threshold: float,
    output_format: str,
    verify: bool,
    llm_model: str,
    llm_api_key: str | None,
    min_lines: int,
    min_tokens: int,
    max_cluster_size: int,
    exclude: tuple[str, ...],
    exclude_type: tuple[str, ...],
    model: str,
    stage: str,
    resume: bool,
    intra: bool,
    min_words: int | None,
    threshold_intent: float | None,
    concurrency: int | None,
    backend: str | None,
    token_weight: float | None,
) -> None:
    """Scan PATH for code duplicates and/or documentation overlap.

    By default, scans for code duplicates (--code is implied).
    Use --docs to scan for documentation overlap instead.
    Use --code --docs to run both pipelines.
    """
    from dryscope.config import load_settings

    # Default: --code if neither flag is set
    if code is None and docs is None:
        code = True
        docs = False
    elif code is None:
        code = not docs  # --docs implies --no-code unless explicitly set
    elif docs is None:
        docs = not code  # --no-code implies --docs unless explicitly set

    if not code and not docs:
        click.echo("Error: must enable at least one of --code or --docs.", err=True)
        sys.exit(1)

    _explicit = lambda param: ctx.get_parameter_source(param) != click.core.ParameterSource.DEFAULT

    # Build a single Settings object with all CLI overrides
    scan_path = Path(path).resolve()
    settings = load_settings(
        scan_path,
        # Code overrides
        code_threshold=threshold if _explicit("threshold") else None,
        code_min_lines=min_lines if _explicit("min_lines") else None,
        code_min_tokens=min_tokens if _explicit("min_tokens") else None,
        code_max_cluster_size=max_cluster_size if _explicit("max_cluster_size") else None,
        code_embedding_model=model if _explicit("model") else None,
        # Docs overrides
        threshold=threshold if _explicit("threshold") else None,
        threshold_intent=threshold_intent,
        backend=backend,
        model=llm_model if _explicit("llm_model") else None,
        min_words=min_words,
        concurrency=concurrency,
        intra=intra if ctx.get_parameter_source("intra") != click.core.ParameterSource.DEFAULT else None,
        token_weight=token_weight,
    )

    code_clusters = None

    if code:
        if output_format not in ("terminal", "json"):
            click.echo(f"Error: --format {output_format} is not supported for code scan (use terminal or json).", err=True)
            sys.exit(1)

        code_clusters = _run_code_scan(
            path=path,
            settings=settings,
            exclude=exclude,
            exclude_type=exclude_type,
            verify=verify,
            llm_api_key=llm_api_key,
            lang=lang,
        )

    if docs:
        _run_docs_scan(
            path=path,
            settings=settings,
            output_format=output_format,
            verify=verify,
            stage=stage,
            resume=resume,
        )

    # Output code results via unified reporter
    if code and code_clusters is not None:
        from dryscope.unified_report import format_unified_json, format_unified_terminal

        if output_format == "json":
            click.echo(format_unified_json(code_clusters=code_clusters))
        else:
            click.echo(format_unified_terminal(code_clusters=code_clusters))
    elif code and code_clusters is None:
        # No units found — already reported to stderr
        if output_format == "json":
            from dryscope.unified_report import format_unified_json
            click.echo(format_unified_json(code_clusters=[]))


# ─── Install / Uninstall ──────────────────────────────────────────────────


@main.command()
def install() -> None:
    """Install dryscope as both a Claude Code and Codex skill."""
    if not SKILL_TEMPLATE.exists():
        click.echo(f"SKILL.md template not found at {SKILL_TEMPLATE}", err=True)
        sys.exit(1)

    project_root = _find_project_root()
    primary_dest = SKILL_DESTS[0]
    venv_dir = primary_dest / ".venv"
    dryscope_bin = venv_dir / "bin" / "dryscope"
    for dest in SKILL_DESTS:
        dest.mkdir(parents=True, exist_ok=True)

    click.echo(f"Creating venv at {venv_dir}...", err=True)
    subprocess.run(
        ["uv", "venv", str(venv_dir), "--python", ">=3.10"],
        check=True,
    )

    click.echo("Installing dryscope into skill venv...", err=True)
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_dir / "bin" / "python"), str(project_root)],
        check=True,
    )

    template = SKILL_TEMPLATE.read_text()
    rendered = template.replace("{{DRYSCOPE_BIN}}", str(dryscope_bin))
    for dest in SKILL_DESTS:
        (dest / "SKILL.md").write_text(rendered)

    for dest in SKILL_DESTS:
        click.echo(f"Installed dryscope skill to {dest}")
    click.echo(f"Binary: {dryscope_bin}")


@main.command()
def uninstall() -> None:
    """Remove the dryscope Claude Code and Codex skills."""
    removed = False
    for dest in SKILL_DESTS:
        if dest.exists():
            shutil.rmtree(dest)
            click.echo(f"Removed {dest}")
            removed = True
    if not removed:
        click.echo("dryscope skill not installed.", err=True)


# ─── Config init ──────────────────────────────────────────────────────────


@main.command("init")
def init_config() -> None:
    """Create a .dryscope.toml configuration file with defaults."""
    from dryscope.config import DEFAULT_CONFIG_TOML

    target = Path.cwd() / ".dryscope.toml"
    if target.exists():
        click.echo(f"{target} already exists.", err=True)
        sys.exit(1)

    target.write_text(DEFAULT_CONFIG_TOML)
    click.echo(f"Created {target}")


# ─── Cache management ─────────────────────────────────────────────────────


@main.group()
def cache() -> None:
    """Cache management commands."""
    pass


@cache.command("stats")
def cache_stats() -> None:
    """Show cache statistics."""
    from dryscope.cache import Cache
    from dryscope.config import Settings

    settings = Settings()
    db_path = settings.resolved_cache_path

    if not db_path.exists():
        click.echo("Cache database does not exist yet (no entries cached).")
        click.echo(f"Path: {db_path}")
        return

    cache_inst = Cache(db_path)
    stats = cache_inst.stats()
    cache_inst.close()

    click.echo(f"Path:       {db_path}")
    click.echo(f"Entries:    {stats.entry_count}")
    click.echo(f"Embeddings: {stats.embedding_count}")
    click.echo(f"Codings:    {stats.coding_count}")
    click.echo(f"DB size:    {stats.db_size_bytes:,} bytes")


@cache.command("clear")
def cache_clear() -> None:
    """Clear the cache database."""
    from dryscope.cache import Cache
    from dryscope.config import Settings

    settings = Settings()
    db_path = settings.resolved_cache_path

    if not db_path.exists():
        click.echo("Cache database does not exist. Nothing to clear.")
        return

    cache_inst = Cache(db_path)
    cache_inst.clear()
    cache_inst.close()
    click.echo("Cache cleared.")


if __name__ == "__main__":
    main()
