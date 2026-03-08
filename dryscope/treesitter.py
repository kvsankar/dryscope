"""Shared tree-sitter setup for multi-language parsing."""

from __future__ import annotations

from tree_sitter import Language, Parser

# Lazy-loaded language objects
_languages: dict[str, Language] = {}


def _get_language(lang: str) -> Language:
    """Get a tree-sitter Language object, loading the grammar lazily."""
    if lang not in _languages:
        if lang == "python":
            import tree_sitter_python as tspython
            _languages[lang] = Language(tspython.language())
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
    """Create a tree-sitter parser for the given language."""
    return Parser(_get_language(lang))


# File extension to language mapping
EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
}

# All supported file extensions
SUPPORTED_EXTENSIONS = set(EXT_TO_LANG.keys())
