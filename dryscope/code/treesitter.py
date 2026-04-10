"""Shared tree-sitter setup for multi-language parsing."""

from __future__ import annotations

from tree_sitter import Language, Parser

# Lazy-loaded language objects
_languages: dict[str, Language] = {}

# Cached parser objects (one per language)
_parser_cache: dict[str, Parser] = {}


def _get_language(lang: str) -> Language:
    """Get a tree-sitter Language object, loading the grammar lazily."""
    if lang not in _languages:
        if lang == "python":
            import tree_sitter_python as tspython
            _languages[lang] = Language(tspython.language())
        elif lang == "java":
            import tree_sitter_java as tsjava
            _languages[lang] = Language(tsjava.language())
        elif lang == "go":
            import tree_sitter_go as tsgo
            _languages[lang] = Language(tsgo.language())
        elif lang == "javascript":
            import tree_sitter_javascript as tsjavascript
            _languages[lang] = Language(tsjavascript.language())
        elif lang == "jsx":
            import tree_sitter_javascript as tsjavascript
            _languages[lang] = Language(tsjavascript.language())
        elif lang == "typescript":
            import tree_sitter_typescript as tstype
            _languages[lang] = Language(tstype.language_typescript())
        elif lang == "tsx":
            import tree_sitter_typescript as tstype
            _languages[lang] = Language(tstype.language_tsx())
        else:
            raise ValueError(f"Unsupported language: {lang}")
    return _languages[lang]


def create_parser(lang: str = "python") -> Parser:
    """Create (or return cached) tree-sitter parser for the given language."""
    if lang in _parser_cache:
        return _parser_cache[lang]
    parser = Parser(_get_language(lang))
    _parser_cache[lang] = parser
    return parser


# File extension to language mapping
EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
}

# All supported file extensions
SUPPORTED_EXTENSIONS = set(EXT_TO_LANG.keys())
