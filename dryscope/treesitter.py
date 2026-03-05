"""Shared tree-sitter setup for Python parsing."""

from __future__ import annotations

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())


def create_parser() -> Parser:
    return Parser(PY_LANGUAGE)
