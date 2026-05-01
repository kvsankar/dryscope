"""CLI entry point for dryscope — Code Match and docs track scanning."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from dryscope import __version__
from dryscope.help_topics import OUTPUT_FORMATS, get_topic, render_topic, topic_summaries
from dryscope.terminology import (
    CODE_MATCH,
    CODE_REVIEW,
    DOCS_MAP,
    DOCS_PAIR_REVIEW,
    DOCS_REPORT_PACK_SLUG,
    DOCS_SECTION_MATCH,
    DOCS_SECTION_MATCH_SLUG,
)

if TYPE_CHECKING:
    from dryscope.config import Settings
    from dryscope.docs.models import AnalysisResult

SKILL_TEMPLATE = Path(__file__).parent / "skill" / "SKILL.md"
SKILL_DESTS = [
    Path.home() / ".claude" / "skills" / "dryscope",
    Path.home() / ".codex" / "skills" / "dryscope",
]
SHARED_SKILL_VENV = (
    Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    / "dryscope"
    / "skill-venv"
)
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
OUTPUT_FORMAT_CHOICES = [name for name, _modes, _meaning in OUTPUT_FORMATS]


class DryscopeGroup(click.Group):
    """Click group with topic aliases such as `dryscope --help json`."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        arg_list = list(sys.argv[1:] if args is None else args)
        if arg_list and arg_list[0] in ("--help", "-h") and len(arg_list) > 1:
            text = _render_help_target(self, arg_list[1:], prog_name or "dryscope")
            if text is None:
                click.echo(f"Unknown help topic or command: {' '.join(arg_list[1:])}", err=True)
                click.echo("Run `dryscope help` to list topics.", err=True)
                if standalone_mode:
                    raise SystemExit(2)
                return 2
            click.echo(text)
            return None
        return super().main(
            args=args,
            prog_name=prog_name,
            complete_var=complete_var,
            standalone_mode=standalone_mode,
            windows_expand_args=windows_expand_args,
            **extra,
        )


def _render_help_target(group: click.Group, path: list[str], prog_name: str) -> str | None:
    """Render a topic or command help target from `dryscope --help TARGET`."""
    if not path:
        return None
    topic = get_topic(path[0])
    if topic is not None and len(path) == 1:
        return render_topic(topic.name)
    return _render_command_help(group, path, prog_name)


def _render_command_help(group: click.Group, path: list[str], prog_name: str) -> str | None:
    """Render nested Click command help for a path like `reports clean`."""
    command: click.Command = group
    parent_ctx = click.Context(group, info_name=prog_name)
    ctx = parent_ctx
    for token in path:
        if not isinstance(command, click.Group):
            return None
        subcommand = command.get_command(ctx, token)
        if subcommand is None:
            return None
        command = subcommand
        ctx = click.Context(command, info_name=token, parent=ctx)
    return command.get_help(ctx)


def _find_project_root(start: Path | None = None) -> Path:
    """Find the nearest project root containing pyproject.toml."""
    path = (start or Path(__file__).resolve().parent).resolve()
    while path != path.parent:
        if (path / "pyproject.toml").exists():
            return path
        path = path.parent
    raise FileNotFoundError("Could not find pyproject.toml")


def _find_install_source() -> str:
    """Resolve the package source to install into the shared skill venv."""
    try:
        return str(_find_project_root(Path.cwd()))
    except FileNotFoundError:
        try:
            return str(_find_project_root())
        except FileNotFoundError:
            return f"dryscope=={__version__}"


def _find_git_root(scan_path: Path) -> Path:
    """Find the git root, falling back to scan_path."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(scan_path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return Path(proc.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return scan_path


@click.group(
    cls=DryscopeGroup,
    invoke_without_command=True,
    context_settings=CONTEXT_SETTINGS,
)
@click.pass_context
@click.version_option(version=__version__)
def main(ctx: click.Context) -> None:
    """dryscope - Code Match, Code Review, and docs track scanning.

    Start with `dryscope scan PATH`.

    \b
    Progressive help:
      dryscope help
      dryscope help tracks
      dryscope help output
      dryscope help json

    \b
    Topic aliases also work as `dryscope --help json`.
    Command help works at every command level, for example
    `dryscope scan --help` and `dryscope reports clean --help`.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command("help", context_settings=CONTEXT_SETTINGS)
@click.argument("topic", nargs=-1)
def help_topic(topic: tuple[str, ...]) -> None:
    """Show progressive help topics."""
    if not topic:
        click.echo(topic_summaries())
        return

    topic_name = "-".join(topic)
    found = get_topic(topic_name) or get_topic(topic[0])
    if found is None:
        raise click.UsageError(f"unknown help topic: {' '.join(topic)}\n\n{topic_summaries()}")
    click.echo(render_topic(found.name))


# ─── Code scan ────────────────────────────────────────────────────────────


def _profile_exclusions(
    path: str,
    exclude: tuple[str, ...],
    exclude_type: tuple[str, ...],
) -> tuple[list[str] | None, set[str] | None, set[str]]:
    from dryscope.code.profiles import detect_profiles, merge_profiles

    profiles = detect_profiles(path)
    if profiles:
        names = ", ".join(p.name for p in profiles)
        click.echo(f"Detected project profile(s): {names}", err=True)

    user_patterns = list(exclude) if exclude else None
    user_types = set(exclude_type) if exclude_type else None
    return merge_profiles(profiles, user_patterns, user_types)


def _filter_units_by_lang(units: list, lang: str | None) -> list:
    if not lang:
        return units
    lang_map = {
        "python": "python",
        "ts": "typescript",
        "tsx": "tsx",
        "typescript": "typescript",
    }
    target_lang = lang_map.get(lang)
    return [u for u in units if u.lang == target_lang] if target_lang else units


def _filter_units_by_tokens(
    units: list,
    normalized: list[str],
    min_tokens: int,
) -> tuple[list, list[str]] | None:
    if min_tokens <= 0:
        return units, normalized

    filtered = [
        (u, n) for u, n in zip(units, normalized, strict=True) if len(set(n.split())) >= min_tokens
    ]
    removed = len(units) - len(filtered)
    if removed:
        click.echo(f"Filtered {removed} units with < {min_tokens} unique tokens.", err=True)
    if not filtered:
        click.echo("No code units remaining after token filter.", err=True)
        return None

    kept_units, kept_normalized = zip(*filtered, strict=True)
    return list(kept_units), list(kept_normalized)


def _verify_code_clusters(
    clusters: list,
    settings: Settings,
    llm_api_key: str | None,
) -> list:
    from dryscope.code.policy import EscalationPolicy, should_escalate_cluster
    from dryscope.code.verifier import VERDICT_NOISE, verify_clusters

    click.echo(
        f"{CODE_REVIEW}: verifying {len(clusters)} clusters with {settings.model}...", err=True
    )
    results = verify_clusters(
        clusters,
        model=settings.model,
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
    return verified


def _run_code_scan(
    path: str,
    settings: Settings,
    exclude: tuple[str, ...],
    exclude_type: tuple[str, ...],
    verify: bool,
    llm_api_key: str | None,
    lang: str | None,
    max_findings: int | None = None,
) -> list | None:
    """Run Code Match and return clusters.

    Returns a list of Cluster objects, or None if no units were found.
    """
    from dryscope.code.embedder import Embedder
    from dryscope.code.normalizer import normalize
    from dryscope.code.parser import parse_directory
    from dryscope.code.reporter import build_clusters
    from dryscope.similarity import cluster_duplicates, find_duplicates

    threshold = settings.code_threshold
    min_lines = settings.code_min_lines
    min_tokens = settings.code_min_tokens
    max_cluster_size = settings.code_max_cluster_size
    model = settings.code_embedding_model

    exclude_patterns, exclude_types, extra_dirs = _profile_exclusions(path, exclude, exclude_type)

    click.echo(f"Parsing source files in {path}...", err=True)
    units = parse_directory(
        path,
        min_lines=min_lines,
        exclude_patterns=exclude_patterns,
        exclude_types=exclude_types,
        exclude_dirs=extra_dirs,
    )

    units = _filter_units_by_lang(units, lang)

    if not units:
        click.echo("No code units found.", err=True)
        return None
    click.echo(f"Found {len(units)} code units.", err=True)

    click.echo("Normalizing...", err=True)
    normalized = [normalize(u.source, lang=u.lang) for u in units]

    filtered_units = _filter_units_by_tokens(units, normalized, min_tokens)
    if filtered_units is None:
        return None
    units, normalized = filtered_units

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
    if max_findings is not None and len(clusters) > max_findings:
        click.echo(f"Limiting to top {max_findings} clusters.", err=True)
        clusters = clusters[:max_findings]

    # Code Review pass
    if verify:
        clusters = _verify_code_clusters(clusters, settings, llm_api_key)

    return clusters


# ─── Docs scan ────────────────────────────────────────────────────────────


def _run_docs_scan(
    path: str,
    settings: Settings,
    output_format: str,
    verify: bool,
    stage: str,
    resume: bool,
    emit_output: bool = True,
) -> AnalysisResult:
    """Run the docs track pipeline."""
    from rich.console import Console

    from dryscope.docs.pipeline import run_pipeline
    from dryscope.run_store import RunStore

    scan_path = Path(path).resolve()
    err_console = Console(stderr=True)

    doc_stage = DOCS_REPORT_PACK_SLUG if verify else stage

    project_root = _find_git_root(scan_path)

    if resume:
        store = RunStore.find_latest(project_root)
        if store is None:
            click.echo("No previous run found to resume.", err=True)
            store = RunStore(project_root)
    else:
        store = RunStore(project_root)

    output_file = None
    if not emit_output:
        output_file = str(store.run_dir / f"scan_output.{output_format}")

    result = run_pipeline(
        scan_path=scan_path,
        settings=settings,
        stage=doc_stage,
        output_format=output_format,
        output_file=output_file,
        skip_confirm=True,
        console=err_console,
        run_store=store,
    )

    store.update_latest_symlink()
    click.echo(f"Run saved to {store.run_dir}", err=True)
    return result


# ─── Unified scan command ─────────────────────────────────────────────────


def _resolve_scan_modes(code: bool | None, docs: bool | None) -> tuple[bool, bool]:
    if code is None and docs is None:
        return True, False
    if code is None:
        return not bool(docs), bool(docs)
    if docs is None:
        return bool(code), not bool(code)
    return bool(code), bool(docs)


def _explicit(ctx: click.Context, param: str) -> bool:
    return ctx.get_parameter_source(param) != click.core.ParameterSource.DEFAULT


def _explicit_flag(ctx: click.Context, param: str) -> bool | None:
    if ctx.get_parameter_source(param) == click.core.ParameterSource.DEFAULT:
        return None
    return bool(ctx.params[param])


def _load_scan_settings(
    ctx: click.Context,
    path: str,
    threshold: float,
    min_lines: int,
    min_tokens: int,
    max_cluster_size: int,
    model: str,
    llm_model: str,
    exclude: tuple[str, ...],
    threshold_intent: float | None,
    backend: str | None,
    min_words: int | None,
    llm_max_doc_pairs: int | None,
    concurrency: int | None,
    token_weight: float | None,
) -> Settings:
    from dryscope.config import load_settings

    return load_settings(
        Path(path).resolve(),
        code_threshold=threshold if _explicit(ctx, "threshold") else None,
        code_min_lines=min_lines if _explicit(ctx, "min_lines") else None,
        code_min_tokens=min_tokens if _explicit(ctx, "min_tokens") else None,
        code_max_cluster_size=max_cluster_size if _explicit(ctx, "max_cluster_size") else None,
        code_embedding_model=model if _explicit(ctx, "model") else None,
        docs_embedding_model=model if _explicit(ctx, "model") else None,
        threshold=threshold if _explicit(ctx, "threshold") else None,
        exclude=exclude if exclude else None,
        threshold_intent=threshold_intent,
        backend=backend,
        model=llm_model if _explicit(ctx, "llm_model") else None,
        min_words=min_words,
        llm_max_doc_pairs=llm_max_doc_pairs,
        concurrency=concurrency,
        intra=_explicit_flag(ctx, "intra"),
        token_weight=token_weight,
    )


def _validate_scan_modes(code: bool, docs: bool, output_format: str) -> None:
    if not code and not docs:
        click.echo("Error: must enable at least one of --code or --docs.", err=True)
        sys.exit(1)
    if code and output_format not in ("terminal", "json"):
        click.echo(
            f"Error: --format {output_format} is not supported for code scan (use terminal or json).",
            err=True,
        )
        sys.exit(1)


def _emit_scan_output(
    code: bool,
    output_format: str,
    code_clusters: list | None,
    docs_result: AnalysisResult | None,
) -> None:
    if code and output_format == "json":
        from dryscope.unified_report import format_unified_json

        click.echo(
            format_unified_json(
                code_clusters=code_clusters or [],
                doc_pairs=docs_result.overlaps if docs_result is not None else None,
                doc_analyses=docs_result.doc_pair_analyses if docs_result is not None else None,
            )
        )
    elif code and code_clusters is not None:
        from dryscope.unified_report import format_unified_terminal

        click.echo(format_unified_terminal(code_clusters=code_clusters))


@main.command(context_settings=CONTEXT_SETTINGS)
@click.argument("path", type=click.Path(exists=True))
# Mode flags
@click.option("--code/--no-code", default=None, help=f"Run {CODE_MATCH}")
@click.option(
    "--docs/--no-docs",
    default=None,
    help=f"Run docs tracks ({DOCS_SECTION_MATCH}; {DOCS_REPORT_PACK_SLUG} adds {DOCS_MAP} and {DOCS_PAIR_REVIEW})",
)
@click.option(
    "--lang",
    type=click.Choice(["python", "go", "java", "js", "jsx", "ts", "tsx"]),
    default=None,
    help="Filter to specific language (code mode)",
)
# Shared options
@click.option(
    "--threshold",
    "-t",
    default=0.90,
    type=click.FloatRange(0.0, 1.0),
    help="Similarity threshold (0.0-1.0)",
)
@click.option(
    "--format", "-f", "output_format", type=click.Choice(OUTPUT_FORMAT_CHOICES), default="terminal"
)
@click.option(
    "--verify",
    is_flag=True,
    default=False,
    help=f"Run {CODE_REVIEW} for code; run {DOCS_REPORT_PACK_SLUG} for docs",
)
@click.option(
    "--llm-model",
    default="claude-haiku-4-5-20251001",
    envvar="DRYSCOPE_LLM_MODEL",
    help="LLM model for --verify",
)
@click.option("--llm-api-key", default=None, help="API key for --verify")
# Code-specific options
@click.option("--min-lines", "-m", default=6, type=int, help="Minimum lines for a code unit")
@click.option("--min-tokens", default=0, type=int, help="Minimum unique normalized tokens")
@click.option("--max-cluster-size", default=15, type=int, help="Drop clusters larger than this")
@click.option(
    "--max-findings",
    default=None,
    type=int,
    help=f"Limit {CODE_MATCH}/{CODE_REVIEW} to the top N code findings",
)
@click.option("--exclude", "-e", multiple=True, help="Glob patterns to exclude")
@click.option("--exclude-type", multiple=True, help="Base class types to exclude")
@click.option(
    "--embedding-model", "model", default="text-embedding-3-small", help="Embedding model name"
)
# Docs-specific options
@click.option(
    "--stage",
    type=click.Choice([DOCS_SECTION_MATCH_SLUG, DOCS_REPORT_PACK_SLUG]),
    default=DOCS_SECTION_MATCH_SLUG,
    help=f"Docs stage: {DOCS_SECTION_MATCH_SLUG}={DOCS_SECTION_MATCH}; {DOCS_REPORT_PACK_SLUG}={DOCS_MAP}+{DOCS_SECTION_MATCH}+{DOCS_PAIR_REVIEW}",
)
@click.option("--resume", is_flag=True, default=False, help="Resume from latest docs run")
@click.option("--intra", is_flag=True, default=False, help="Include intra-document section overlap")
@click.option("--min-words", default=None, type=int, help="Minimum words per doc section")
@click.option("--threshold-intent", default=None, type=float, help="Docs Map topic-pair threshold")
@click.option(
    "--llm-max-doc-pairs",
    default=None,
    type=int,
    help=f"Maximum document pairs for {DOCS_PAIR_REVIEW}",
)
@click.option("--concurrency", default=None, type=int, help="Max parallel LLM calls (docs)")
@click.option(
    "--backend",
    type=click.Choice(["litellm", "cli", "codex-cli", "ollama"]),
    default=None,
    help="LLM backend for --verify",
)
@click.option(
    "--token-weight", default=None, type=float, help="Token Jaccard weight in hybrid similarity"
)
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
    max_findings: int | None,
    exclude: tuple[str, ...],
    exclude_type: tuple[str, ...],
    model: str,
    stage: str,
    resume: bool,
    intra: bool,
    min_words: int | None,
    threshold_intent: float | None,
    llm_max_doc_pairs: int | None,
    concurrency: int | None,
    backend: str | None,
    token_weight: float | None,
) -> None:
    """Scan PATH with Code Match and/or docs tracks.

    By default, runs Code Match (--code is implied).
    Use --docs to run docs analysis tracks instead.
    Use --code --docs to run both pipelines.

    \b
    More detail:
      dryscope help tracks
      dryscope help output
      dryscope help json
    """
    code, docs = _resolve_scan_modes(code, docs)
    _validate_scan_modes(code, docs, output_format)

    # Build a single Settings object with all CLI overrides
    settings = _load_scan_settings(
        ctx,
        path,
        threshold,
        min_lines,
        min_tokens,
        max_cluster_size,
        model,
        llm_model,
        exclude,
        threshold_intent,
        backend,
        min_words,
        llm_max_doc_pairs,
        concurrency,
        token_weight,
    )

    code_clusters = None
    docs_result = None

    if code:
        code_clusters = _run_code_scan(
            path=path,
            settings=settings,
            exclude=exclude,
            exclude_type=exclude_type,
            verify=verify,
            llm_api_key=llm_api_key,
            lang=lang,
            max_findings=max_findings,
        )

    if docs:
        docs_result = _run_docs_scan(
            path=path,
            settings=settings,
            output_format=output_format,
            verify=verify,
            stage=stage,
            resume=resume,
            emit_output=not (code and output_format == "json"),
        )

    _emit_scan_output(code, output_format, code_clusters, docs_result)


# ─── Install / Uninstall ──────────────────────────────────────────────────


@main.command(context_settings=CONTEXT_SETTINGS)
def install() -> None:
    """Install dryscope as both a Claude Code and Codex skill."""
    if not SKILL_TEMPLATE.exists():
        click.echo(f"SKILL.md template not found at {SKILL_TEMPLATE}", err=True)
        sys.exit(1)

    install_source = _find_install_source()
    venv_dir = SHARED_SKILL_VENV
    dryscope_bin = venv_dir / "bin" / "dryscope"
    for dest in SKILL_DESTS:
        dest.mkdir(parents=True, exist_ok=True)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)

    if (venv_dir / "bin" / "python").exists():
        click.echo(f"Using existing venv at {venv_dir}...", err=True)
    else:
        click.echo(f"Creating venv at {venv_dir}...", err=True)
        subprocess.run(
            ["uv", "venv", str(venv_dir), "--python", ">=3.10"],
            check=True,
        )

    click.echo("Installing dryscope into skill venv...", err=True)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--upgrade",
            "--python",
            str(venv_dir / "bin" / "python"),
            install_source,
        ],
        check=True,
    )

    template = SKILL_TEMPLATE.read_text()
    rendered = template.replace("{{DRYSCOPE_BIN}}", str(dryscope_bin))
    for dest in SKILL_DESTS:
        (dest / "SKILL.md").write_text(rendered)

    for dest in SKILL_DESTS:
        click.echo(f"Installed dryscope skill to {dest}")
    click.echo(f"Binary: {dryscope_bin}")


@main.command(context_settings=CONTEXT_SETTINGS)
def uninstall() -> None:
    """Remove the dryscope Claude Code and Codex skills."""
    removed = False
    for dest in SKILL_DESTS:
        if dest.exists():
            shutil.rmtree(dest)
            click.echo(f"Removed {dest}")
            removed = True
    if SHARED_SKILL_VENV.exists():
        shutil.rmtree(SHARED_SKILL_VENV)
        click.echo(f"Removed {SHARED_SKILL_VENV}")
        removed = True
    if not removed:
        click.echo("dryscope skill not installed.", err=True)


# ─── Config init ──────────────────────────────────────────────────────────


@main.command("init", context_settings=CONTEXT_SETTINGS)
def init_config() -> None:
    """Create a .dryscope.toml configuration file with defaults."""
    from dryscope.config import DEFAULT_CONFIG_TOML

    target = Path.cwd() / ".dryscope.toml"
    if target.exists():
        click.echo(f"{target} already exists.", err=True)
        sys.exit(1)

    target.write_text(DEFAULT_CONFIG_TOML)
    click.echo(f"Created {target}")


# ─── Report run cleanup ──────────────────────────────────────────────────


def _parse_keep_since(value: str) -> datetime:
    """Parse a date cutoff for report cleanup."""
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise click.BadParameter("expected YYYY-MM-DD or YYYY-MM")


@main.group(context_settings=CONTEXT_SETTINGS)
def reports() -> None:
    """Manage saved dryscope report runs."""
    pass


@reports.command("clean", context_settings=CONTEXT_SETTINGS)
@click.argument("path", type=click.Path(exists=True), default=".", required=False)
@click.option(
    "--keep-last", type=click.IntRange(min=0), default=None, help="Keep the newest N report runs."
)
@click.option(
    "--keep-since", default=None, help="Keep report runs on or after YYYY-MM-DD or YYYY-MM."
)
@click.option(
    "--keep-days",
    type=click.IntRange(min=0),
    default=None,
    help="Keep report runs from the last N days.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Actually delete old report runs. Without this, dry-run only.",
)
def reports_clean(
    path: str,
    keep_last: int | None,
    keep_since: str | None,
    keep_days: int | None,
    force: bool,
) -> None:
    """Clean old .dryscope/runs report directories.

    If multiple keep rules are supplied, a run is kept when it matches any rule.
    """
    from dryscope.run_store import RunStore

    if keep_last is None and keep_since is None and keep_days is None:
        raise click.UsageError("provide --keep-last, --keep-since, or --keep-days")
    if keep_since is not None and keep_days is not None:
        raise click.UsageError("use either --keep-since or --keep-days, not both")

    scan_path = Path(path).resolve()
    project_root = _find_git_root(scan_path)
    cutoff = _parse_keep_since(keep_since) if keep_since else None
    if keep_days is not None:
        cutoff = datetime.now() - timedelta(days=keep_days)

    runs = RunStore.list_runs(project_root)
    result = RunStore.cleanup_runs(
        project_root,
        keep_last=keep_last,
        keep_since=cutoff,
        dry_run=not force,
    )

    action = "Deleted" if force else "Would delete"
    removed = result.deleted if force else result.would_delete
    click.echo(f"Project: {project_root}")
    click.echo(f"Runs found: {len(runs)}")
    click.echo(f"Keeping: {len(result.kept)}")
    click.echo(f"{action}: {len(removed)}")
    for run_dir in removed:
        click.echo(f"  {run_dir.name}")
    if not force and removed:
        click.echo("Dry run only. Re-run with --force to delete.")
    if force:
        latest = RunStore.find_latest(project_root)
        if latest is not None:
            click.echo(f"Latest: {latest.run_id}")
        else:
            click.echo("Latest: none")


# ─── Cache management ─────────────────────────────────────────────────────


@main.group(context_settings=CONTEXT_SETTINGS)
def cache() -> None:
    """Cache management commands."""
    pass


@cache.command("stats", context_settings=CONTEXT_SETTINGS)
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


@cache.command("clear", context_settings=CONTEXT_SETTINGS)
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
