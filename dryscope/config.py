"""Configuration management for dryscope."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_INCLUDE = ["*.md", "*.mdx", "*.rst", "*.txt", "*.adoc"]
DEFAULT_EXCLUDE = ["node_modules", "venv", ".git", ".dryscope", "*.lock"]
DEFAULT_DOCS_MAP_FACET_DIMENSIONS = [
    "doc_role",
    "audience",
    "lifecycle",
    "content_type",
    "surface",
    "canonicality",
]
DEFAULT_DOCS_MAP_FACET_VALUES = {
    "doc_role": [
        "guide",
        "reference",
        "tutorial",
        "spec",
        "plan",
        "status",
        "research",
        "changelog",
        "architecture",
        "decision",
        "overview",
        "troubleshooting",
    ],
    "audience": ["user", "contributor", "maintainer", "operator", "internal", "agent"],
    "lifecycle": ["current", "proposed", "historical", "deprecated", "draft", "unknown"],
    "content_type": [
        "concept",
        "workflow",
        "api",
        "troubleshooting",
        "decision",
        "benchmark",
        "example",
        "architecture",
        "requirements",
    ],
    "surface": ["public", "internal", "generated", "extension", "package", "integration"],
    "canonicality": ["primary", "supporting", "archive", "duplicate", "index", "unknown"],
}

DEFAULT_CONFIG_TOML = """\
[code]
min_lines = 6
min_tokens = 0
max_cluster_size = 15
threshold = 0.90
embedding_model = "text-embedding-3-small"
escalate_refactor_min_lines = 40
escalate_refactor_min_actionability = 2.0
escalate_refactor_min_units = 3
keep_same_file_refactors = false
# exclude = ["**/test_*.py"]
# exclude_type = ["BaseModel"]

[docs]
include = ["*.md", "*.mdx", "*.rst", "*.txt", "*.adoc"]
exclude = ["node_modules", "venv", ".git", ".dryscope", "*.lock"]
threshold_similarity = 0.9
threshold_intent = 0.8
min_content_words = 15
include_intra = false
token_weight = 0.3
# Same embedding backend choices as [code].
embedding_model = "text-embedding-3-small"
intent_max_docs = 0
llm_max_doc_pairs = 250
intent_skip_without_similarity_min_docs = 0

[docs.map]
# Generic seed dimensions shown to the LLM. These are suggestions, not a
# product-specific taxonomy; dryscope still infers the corpus topic tree.
facet_dimensions = ["doc_role", "audience", "lifecycle", "content_type", "surface", "canonicality"]

[docs.map.facet_values]
doc_role = ["guide", "reference", "tutorial", "spec", "plan", "status", "research", "changelog", "architecture", "decision", "overview", "troubleshooting"]
audience = ["user", "contributor", "maintainer", "operator", "internal", "agent"]
lifecycle = ["current", "proposed", "historical", "deprecated", "draft", "unknown"]
content_type = ["concept", "workflow", "api", "troubleshooting", "decision", "benchmark", "example", "architecture", "requirements"]
surface = ["public", "internal", "generated", "extension", "package", "integration"]
canonicality = ["primary", "supporting", "archive", "duplicate", "index", "unknown"]

[llm]
model = "claude-haiku-4-5-20251001"
backend = "cli"
max_cost = 5.00
concurrency = 8
# For backend = "ollama", optionally set:
# ollama_host = "http://localhost:11434"
# For backend = "codex-cli", the configured model is passed to `codex exec -m`
# if your Codex auth supports it. With ChatGPT-account auth, the default Codex
# model may be the only supported option.
# For backend = "cli", optionally set:
# cli_strip_api_key = true
# cli_permission_mode = "bypassPermissions"
# cli_dangerously_skip_permissions = false

[cache]
enabled = true
path = "~/.cache/dryscope/cache.db"
"""


@dataclass
class Settings:
    """Merged configuration from defaults, TOML file, and CLI flags."""

    # Code settings
    code_min_lines: int = 6
    code_min_tokens: int = 0
    code_max_cluster_size: int = 15
    code_threshold: float = 0.90
    code_embedding_model: str = "text-embedding-3-small"
    code_escalate_refactor_min_lines: int = 40
    code_escalate_refactor_min_actionability: float = 2.0
    code_escalate_refactor_min_units: int = 3
    code_keep_same_file_refactors: bool = False

    # Docs settings
    include: list[str] = field(default_factory=lambda: list(DEFAULT_INCLUDE))
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    threshold_similarity: float = 0.9
    threshold_intent: float = 0.8
    min_content_words: int = 15
    include_intra: bool = False
    token_weight: float = 0.3
    docs_embedding_model: str = "text-embedding-3-small"
    docs_intent_max_docs: int = 0
    docs_llm_max_doc_pairs: int = 250
    docs_intent_skip_without_similarity_min_docs: int = 0
    docs_map_facet_dimensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_DOCS_MAP_FACET_DIMENSIONS)
    )
    docs_map_facet_values: dict[str, list[str]] = field(
        default_factory=lambda: {
            key: list(values) for key, values in DEFAULT_DOCS_MAP_FACET_VALUES.items()
        }
    )

    # LLM settings
    model: str = "claude-haiku-4-5-20251001"
    backend: str = "cli"
    max_cost: float = 5.00
    concurrency: int = 8
    ollama_host: str | None = None
    cli_strip_api_key: bool = True
    cli_permission_mode: str | None = None
    cli_dangerously_skip_permissions: bool = False

    # Cache settings
    cache_enabled: bool = True
    cache_path: str = "~/.cache/dryscope/cache.db"

    @property
    def resolved_cache_path(self) -> Path:
        return Path(self.cache_path).expanduser()


def load_toml(path: Path) -> dict:
    """Load a .dryscope.toml file and return its contents as a dict."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def find_config_file(scan_path: Path | None = None) -> Path | None:
    """Find .dryscope.toml in the scan target dir or cwd."""
    candidates = []
    if scan_path is not None:
        target = scan_path if scan_path.is_dir() else scan_path.parent
        candidates.append(target / ".dryscope.toml")
    candidates.append(Path.cwd() / ".dryscope.toml")

    for c in candidates:
        if c.exists():
            return c
    return None


def _pattern_list(value: str | Sequence[str]) -> list[str]:
    """Normalize comma-separated or repeated CLI pattern values."""
    if isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = []
        for item in value:
            raw_items.extend(str(item).split(","))
    return [item.strip() for item in raw_items if item.strip()]


def _dict_section(data: dict, key: str) -> dict:
    """Return a TOML section if present and object-shaped."""
    section = data.get(key, {})
    return section if isinstance(section, dict) else {}


def _apply_scalar_options(settings: Settings, cfg: dict, mapping: dict[str, str]) -> None:
    """Apply direct TOML key -> Settings attribute assignments."""
    for key, attr in mapping.items():
        if key in cfg:
            setattr(settings, attr, cfg[key])


def _apply_code_config(settings: Settings, code_cfg: dict) -> None:
    _apply_scalar_options(
        settings,
        code_cfg,
        {
            "min_lines": "code_min_lines",
            "min_tokens": "code_min_tokens",
            "max_cluster_size": "code_max_cluster_size",
            "threshold": "code_threshold",
            "embedding_model": "code_embedding_model",
            "escalate_refactor_min_lines": "code_escalate_refactor_min_lines",
            "escalate_refactor_min_actionability": "code_escalate_refactor_min_actionability",
            "escalate_refactor_min_units": "code_escalate_refactor_min_units",
            "keep_same_file_refactors": "code_keep_same_file_refactors",
        },
    )


def _apply_docs_map_config(settings: Settings, docs_map_cfg: dict) -> None:
    if "facet_dimensions" in docs_map_cfg:
        settings.docs_map_facet_dimensions = [
            str(item).strip() for item in docs_map_cfg["facet_dimensions"] if str(item).strip()
        ]
    if "facet_values" not in docs_map_cfg:
        return
    merged_facet_values = {
        key: list(values) for key, values in settings.docs_map_facet_values.items()
    }
    merged_facet_values.update(
        {
            str(key).strip(): [str(item).strip() for item in values if str(item).strip()]
            for key, values in docs_map_cfg["facet_values"].items()
            if str(key).strip() and isinstance(values, list)
        }
    )
    settings.docs_map_facet_values = merged_facet_values


def _apply_docs_config(settings: Settings, docs_cfg: dict) -> None:
    _apply_scalar_options(
        settings,
        docs_cfg,
        {
            "include": "include",
            "exclude": "exclude",
            "threshold_similarity": "threshold_similarity",
            "threshold_intent": "threshold_intent",
            "min_content_words": "min_content_words",
            "include_intra": "include_intra",
            "token_weight": "token_weight",
            "embedding_model": "docs_embedding_model",
            "intent_max_docs": "docs_intent_max_docs",
            "llm_max_doc_pairs": "docs_llm_max_doc_pairs",
            "intent_skip_without_similarity_min_docs": "docs_intent_skip_without_similarity_min_docs",
        },
    )
    _apply_docs_map_config(settings, _dict_section(docs_cfg, "map"))


def _apply_llm_config(settings: Settings, llm_cfg: dict) -> None:
    _apply_scalar_options(
        settings,
        llm_cfg,
        {
            "model": "model",
            "backend": "backend",
            "max_cost": "max_cost",
            "concurrency": "concurrency",
            "ollama_host": "ollama_host",
            "cli_strip_api_key": "cli_strip_api_key",
            "cli_permission_mode": "cli_permission_mode",
            "cli_dangerously_skip_permissions": "cli_dangerously_skip_permissions",
        },
    )


def _apply_cache_config(settings: Settings, cache_cfg: dict) -> None:
    _apply_scalar_options(settings, cache_cfg, {"enabled": "cache_enabled", "path": "cache_path"})


def _apply_file_config(settings: Settings, config_path: Path) -> None:
    data = load_toml(config_path)
    _apply_code_config(settings, _dict_section(data, "code"))
    _apply_docs_config(settings, _dict_section(data, "docs"))
    _apply_llm_config(settings, _dict_section(data, "llm"))
    _apply_cache_config(settings, _dict_section(data, "cache"))


def _apply_cli_overrides(
    settings: Settings,
    *,
    code_threshold: float | None,
    code_min_lines: int | None,
    code_min_tokens: int | None,
    code_max_cluster_size: int | None,
    code_embedding_model: str | None,
    model: str | None,
    docs_embedding_model: str | None,
    backend: str | None,
    threshold: float | None,
    threshold_intent: float | None,
    include: str | Sequence[str] | None,
    exclude: str | Sequence[str] | None,
    max_cost: float | None,
    min_words: int | None,
    llm_max_doc_pairs: int | None,
    concurrency: int | None,
    intra: bool | None,
    token_weight: float | None,
) -> None:
    """Apply CLI overrides to settings."""
    if code_threshold is not None:
        settings.code_threshold = code_threshold
    if code_min_lines is not None:
        settings.code_min_lines = code_min_lines
    if code_min_tokens is not None:
        settings.code_min_tokens = code_min_tokens
    if code_max_cluster_size is not None:
        settings.code_max_cluster_size = code_max_cluster_size
    if code_embedding_model is not None:
        settings.code_embedding_model = code_embedding_model
    if model is not None:
        settings.model = model
    if docs_embedding_model is not None:
        settings.docs_embedding_model = docs_embedding_model
    if threshold is not None:
        settings.threshold_similarity = threshold
    if threshold_intent is not None:
        settings.threshold_intent = threshold_intent
    if include is not None:
        settings.include = _pattern_list(include)
    if exclude is not None:
        settings.exclude = [*settings.exclude, *_pattern_list(exclude)]
    if backend is not None:
        settings.backend = backend
    if max_cost is not None:
        settings.max_cost = max_cost
    if min_words is not None:
        settings.min_content_words = min_words
    if llm_max_doc_pairs is not None:
        settings.docs_llm_max_doc_pairs = llm_max_doc_pairs
    if concurrency is not None:
        settings.concurrency = concurrency
    if intra is not None:
        settings.include_intra = intra
    if token_weight is not None:
        settings.token_weight = token_weight


def load_settings(
    scan_path: Path | None = None,
    *,
    # Code-specific overrides
    code_threshold: float | None = None,
    code_min_lines: int | None = None,
    code_min_tokens: int | None = None,
    code_max_cluster_size: int | None = None,
    code_embedding_model: str | None = None,
    # Docs-specific overrides
    model: str | None = None,
    docs_embedding_model: str | None = None,
    backend: str | None = None,
    threshold: float | None = None,
    threshold_intent: float | None = None,
    include: str | Sequence[str] | None = None,
    exclude: str | Sequence[str] | None = None,
    max_cost: float | None = None,
    min_words: int | None = None,
    llm_max_doc_pairs: int | None = None,
    concurrency: int | None = None,
    intra: bool | None = None,
    token_weight: float | None = None,
) -> Settings:
    """Load settings with merge order: defaults -> .dryscope.toml -> CLI flags."""
    settings = Settings()

    # Layer 2: TOML file
    config_path = find_config_file(scan_path)
    if config_path is not None:
        _apply_file_config(settings, config_path)

    # Layer 3: CLI flags
    _apply_cli_overrides(
        settings,
        code_threshold=code_threshold,
        code_min_lines=code_min_lines,
        code_min_tokens=code_min_tokens,
        code_max_cluster_size=code_max_cluster_size,
        code_embedding_model=code_embedding_model,
        model=model,
        docs_embedding_model=docs_embedding_model,
        backend=backend,
        threshold=threshold,
        threshold_intent=threshold_intent,
        include=include,
        exclude=exclude,
        max_cost=max_cost,
        min_words=min_words,
        llm_max_doc_pairs=llm_max_doc_pairs,
        concurrency=concurrency,
        intra=intra,
        token_weight=token_weight,
    )

    return settings
