"""Configuration management for dryscope."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_INCLUDE = ["*.md", "*.rst", "*.txt", "*.adoc"]
DEFAULT_EXCLUDE = ["node_modules", "venv", ".git", ".dryscope", "*.lock"]
DEFAULT_DOCS_IA_FACET_DIMENSIONS = [
    "doc_role",
    "audience",
    "lifecycle",
    "content_type",
    "surface",
    "canonicality",
]
DEFAULT_DOCS_IA_FACET_VALUES = {
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
include = ["*.md", "*.rst", "*.txt", "*.adoc"]
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

[docs.ia]
# Generic seed dimensions shown to the LLM. These are suggestions, not a
# product-specific taxonomy; dryscope still infers the corpus topic tree.
facet_dimensions = ["doc_role", "audience", "lifecycle", "content_type", "surface", "canonicality"]

[docs.ia.facet_values]
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
    docs_ia_facet_dimensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_DOCS_IA_FACET_DIMENSIONS)
    )
    docs_ia_facet_values: dict[str, list[str]] = field(
        default_factory=lambda: {
            key: list(values)
            for key, values in DEFAULT_DOCS_IA_FACET_VALUES.items()
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
        docs_ia_cfg = docs_cfg.get("ia", {}) if isinstance(docs_cfg, dict) else {}
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
        if "escalate_refactor_min_lines" in code_cfg:
            settings.code_escalate_refactor_min_lines = code_cfg["escalate_refactor_min_lines"]
        if "escalate_refactor_min_actionability" in code_cfg:
            settings.code_escalate_refactor_min_actionability = code_cfg["escalate_refactor_min_actionability"]
        if "escalate_refactor_min_units" in code_cfg:
            settings.code_escalate_refactor_min_units = code_cfg["escalate_refactor_min_units"]
        if "keep_same_file_refactors" in code_cfg:
            settings.code_keep_same_file_refactors = code_cfg["keep_same_file_refactors"]

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
        if "intent_max_docs" in docs_cfg:
            settings.docs_intent_max_docs = docs_cfg["intent_max_docs"]
        if "llm_max_doc_pairs" in docs_cfg:
            settings.docs_llm_max_doc_pairs = docs_cfg["llm_max_doc_pairs"]
        if "intent_skip_without_similarity_min_docs" in docs_cfg:
            settings.docs_intent_skip_without_similarity_min_docs = docs_cfg["intent_skip_without_similarity_min_docs"]
        if "facet_dimensions" in docs_ia_cfg:
            settings.docs_ia_facet_dimensions = [
                str(item).strip()
                for item in docs_ia_cfg["facet_dimensions"]
                if str(item).strip()
            ]
        if "facet_values" in docs_ia_cfg:
            merged_facet_values = {
                key: list(values)
                for key, values in settings.docs_ia_facet_values.items()
            }
            merged_facet_values.update({
                str(key).strip(): [
                    str(item).strip()
                    for item in values
                    if str(item).strip()
                ]
                for key, values in docs_ia_cfg["facet_values"].items()
                if str(key).strip() and isinstance(values, list)
            })
            settings.docs_ia_facet_values = merged_facet_values

        # LLM section
        if "model" in llm_cfg:
            settings.model = llm_cfg["model"]
        if "backend" in llm_cfg:
            settings.backend = llm_cfg["backend"]
        if "max_cost" in llm_cfg:
            settings.max_cost = llm_cfg["max_cost"]
        if "concurrency" in llm_cfg:
            settings.concurrency = llm_cfg["concurrency"]
        if "ollama_host" in llm_cfg:
            settings.ollama_host = llm_cfg["ollama_host"]
        if "cli_strip_api_key" in llm_cfg:
            settings.cli_strip_api_key = llm_cfg["cli_strip_api_key"]
        if "cli_permission_mode" in llm_cfg:
            settings.cli_permission_mode = llm_cfg["cli_permission_mode"]
        if "cli_dangerously_skip_permissions" in llm_cfg:
            settings.cli_dangerously_skip_permissions = llm_cfg["cli_dangerously_skip_permissions"]

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
