"""Configuration management for dryscope."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_INCLUDE = ["*.md", "*.rst", "*.txt", "*.adoc"]
DEFAULT_EXCLUDE = ["node_modules", "venv", ".git", "*.lock"]

DEFAULT_CONFIG_TOML = """\
[code]
min_lines = 6
min_tokens = 0
max_cluster_size = 15
threshold = 0.90
embedding_model = "all-MiniLM-L6-v2"
# exclude = ["**/test_*.py"]
# exclude_type = ["BaseModel"]

[docs]
include = ["*.md", "*.rst", "*.txt", "*.adoc"]
exclude = ["node_modules", "venv", ".git", "*.lock"]
threshold_similarity = 0.9
threshold_intent = 0.8
min_content_words = 15
include_intra = false
token_weight = 0.3
embedding_model = "all-MiniLM-L6-v2"

[llm]
model = "claude-haiku-4-5-20251001"
backend = "cli"
max_cost = 5.00
concurrency = 8

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
    code_embedding_model: str = "all-MiniLM-L6-v2"

    # Docs settings
    include: list[str] = field(default_factory=lambda: list(DEFAULT_INCLUDE))
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    threshold_similarity: float = 0.9
    threshold_intent: float = 0.8
    min_content_words: int = 15
    include_intra: bool = False
    token_weight: float = 0.3
    docs_embedding_model: str = "all-MiniLM-L6-v2"

    # LLM settings
    model: str = "claude-haiku-4-5-20251001"
    backend: str = "cli"
    max_cost: float = 5.00
    concurrency: int = 8

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
    include: str | None = None,
    exclude: str | None = None,
    max_cost: float | None = None,
    min_words: int | None = None,
    concurrency: int | None = None,
    intra: bool | None = None,
    token_weight: float | None = None,
) -> Settings:
    """Load settings with merge order: defaults -> .dryscope.toml -> CLI flags."""
    settings = Settings()

    # Layer 2: TOML file
    config_path = find_config_file(scan_path)
    if config_path is not None:
        data = load_toml(config_path)
        code_cfg = data.get("code", {})
        # Backward compat: read [scan] if [docs] is absent
        docs_cfg = data.get("docs", {}) or data.get("scan", {})
        llm_cfg = data.get("llm", {})
        cache_cfg = data.get("cache", {})

        # Code section
        if "min_lines" in code_cfg:
            settings.code_min_lines = code_cfg["min_lines"]
        if "min_tokens" in code_cfg:
            settings.code_min_tokens = code_cfg["min_tokens"]
        if "max_cluster_size" in code_cfg:
            settings.code_max_cluster_size = code_cfg["max_cluster_size"]
        if "threshold" in code_cfg:
            settings.code_threshold = code_cfg["threshold"]
        if "embedding_model" in code_cfg:
            settings.code_embedding_model = code_cfg["embedding_model"]

        # Docs section
        if "include" in docs_cfg:
            settings.include = docs_cfg["include"]
        if "exclude" in docs_cfg:
            settings.exclude = docs_cfg["exclude"]
        if "threshold_similarity" in docs_cfg:
            settings.threshold_similarity = docs_cfg["threshold_similarity"]
        # Backward compat: threshold_embedding treated as alias
        elif "threshold_embedding" in docs_cfg:
            settings.threshold_similarity = docs_cfg["threshold_embedding"]
        if "threshold_intent" in docs_cfg:
            settings.threshold_intent = docs_cfg["threshold_intent"]
        if "min_content_words" in docs_cfg:
            settings.min_content_words = docs_cfg["min_content_words"]
        if "include_intra" in docs_cfg:
            settings.include_intra = docs_cfg["include_intra"]
        if "token_weight" in docs_cfg:
            settings.token_weight = docs_cfg["token_weight"]
        if "embedding_model" in docs_cfg:
            settings.docs_embedding_model = docs_cfg["embedding_model"]

        # LLM section
        if "model" in llm_cfg:
            settings.model = llm_cfg["model"]
        if "backend" in llm_cfg:
            settings.backend = llm_cfg["backend"]
        if "max_cost" in llm_cfg:
            settings.max_cost = llm_cfg["max_cost"]
        if "concurrency" in llm_cfg:
            settings.concurrency = llm_cfg["concurrency"]

        # Cache section
        if "enabled" in cache_cfg:
            settings.cache_enabled = cache_cfg["enabled"]
        if "path" in cache_cfg:
            settings.cache_path = cache_cfg["path"]

    # Layer 3: CLI flags — code
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

    # Layer 3: CLI flags — docs
    if model is not None:
        settings.model = model
    if docs_embedding_model is not None:
        settings.docs_embedding_model = docs_embedding_model
    if threshold is not None:
        settings.threshold_similarity = threshold
    if threshold_intent is not None:
        settings.threshold_intent = threshold_intent
    if include is not None:
        settings.include = [s.strip() for s in include.split(",")]
    if exclude is not None:
        settings.exclude = [s.strip() for s in exclude.split(",")]
    if backend is not None:
        settings.backend = backend
    if max_cost is not None:
        settings.max_cost = max_cost
    if min_words is not None:
        settings.min_content_words = min_words
    if concurrency is not None:
        settings.concurrency = concurrency
    if intra is not None:
        settings.include_intra = intra
    if token_weight is not None:
        settings.token_weight = token_weight

    return settings
