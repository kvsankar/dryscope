"""Extract code units (functions, classes, methods) from source files using tree-sitter."""

from __future__ import annotations

import fnmatch
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node

from dryscope.treesitter import create_parser, EXT_TO_LANG, SUPPORTED_EXTENSIONS

# Node types we extract as code units, per language family
_FUNCTION_TYPES = {
    "function_definition",       # Python
    "function_declaration",      # TypeScript
    "generator_function_declaration",  # TypeScript
    "method_definition",         # TypeScript class methods
}

_CLASS_TYPES = {
    "class_definition",          # Python
    "class_declaration",         # TypeScript
}

# Arrow functions assigned to variables: const foo = () => {}
_ARROW_DECLARATOR = "variable_declarator"

# Directories to always skip
EXCLUDED_DIRS = {
    ".venv", "venv", ".env", "env",
    "node_modules", "__pycache__",
    ".git", ".hg", ".svn",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    "site-packages", "dist", "build", "egg-info",
}

# Regex to extract base class names from the first line of a class definition
_BASE_CLASS_RE = re.compile(r"class\s+\w+\s*\(([^)]*)\)")
# TypeScript: class Foo extends Bar implements Baz
_TS_EXTENDS_RE = re.compile(r"class\s+\w+(?:<[^>]*>)?\s+extends\s+([\w.]+)")


@dataclass
class CodeUnit:
    """A single extractable code unit (function, class, method)."""

    name: str
    unit_type: str  # "function", "class", "method"
    source: str
    file_path: str
    start_line: int
    end_line: int
    lang: str = "python"
    children: list[CodeUnit] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def base_classes(self) -> list[str]:
        """Extract base class names from a class definition's first line."""
        if self.unit_type != "class":
            return []
        first_line = self.source.split("\n", 1)[0]
        if self.lang == "python":
            m = _BASE_CLASS_RE.search(first_line)
            if not m:
                return []
            return [b.strip().rsplit(".", 1)[-1] for b in m.group(1).split(",") if b.strip()]
        else:
            m = _TS_EXTENDS_RE.search(first_line)
            if not m:
                return []
            return [m.group(1).rsplit(".", 1)[-1]]

    def __repr__(self) -> str:
        return f"CodeUnit({self.unit_type} {self.name}, {self.file_path}:{self.start_line}-{self.end_line})"


def _get_name(node: Node) -> str:
    """Extract the name identifier from a function/class definition node."""
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "property_identifier"):
            return child.text.decode("utf-8")
    return "<anonymous>"


def _is_arrow_function(node: Node) -> bool:
    """Check if a variable_declarator contains an arrow function."""
    for child in node.children:
        if child.type == "arrow_function":
            return True
    return False


def _extract_units(
    node: Node,
    file_path: str,
    lang: str,
    parent_is_class: bool = False,
) -> list[CodeUnit]:
    """Recursively extract code units from a tree-sitter node."""
    units: list[CodeUnit] = []

    for child in node.children:
        # Handle export_statement: unwrap to find the declaration inside
        if child.type == "export_statement":
            units.extend(_extract_units(child, file_path, lang, parent_is_class))
            continue

        # Functions and class methods
        if child.type in _FUNCTION_TYPES:
            name = _get_name(child)
            if child.type == "method_definition" or parent_is_class:
                unit_type = "method"
            else:
                unit_type = "function"

            unit = CodeUnit(
                name=name,
                unit_type=unit_type,
                source=child.text.decode("utf-8"),
                file_path=file_path,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                lang=lang,
            )
            unit.children = _extract_units(
                child, file_path, lang, parent_is_class=(child.type in _CLASS_TYPES),
            )
            units.append(unit)
            continue

        # Classes
        if child.type in _CLASS_TYPES:
            name = _get_name(child)
            unit = CodeUnit(
                name=name,
                unit_type="class",
                source=child.text.decode("utf-8"),
                file_path=file_path,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                lang=lang,
            )
            # Extract methods from class body (TS only — Python methods
            # are included in the class source and not split out)
            if lang != "python":
                for body_child in child.children:
                    if body_child.type == "class_body":
                        unit.children = _extract_units(body_child, file_path, lang, parent_is_class=True)
            units.append(unit)
            continue

        # Arrow functions: const foo = () => {}
        if child.type == "lexical_declaration" and lang != "python":
            for declarator in child.children:
                if declarator.type == _ARROW_DECLARATOR and _is_arrow_function(declarator):
                    name = _get_name(declarator)
                    unit = CodeUnit(
                        name=name,
                        unit_type="function",
                        source=child.text.decode("utf-8"),
                        file_path=file_path,
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        lang=lang,
                    )
                    units.append(unit)
            continue

    return units


def parse_file(file_path: str | Path) -> list[CodeUnit]:
    """Parse a source file and return all code units."""
    file_path = Path(file_path)
    ext = file_path.suffix
    lang = EXT_TO_LANG.get(ext, "python")
    parser = create_parser(lang)
    tree = parser.parse(file_path.read_bytes())
    return _extract_units(tree.root_node, str(file_path), lang)


def flatten_units(units: list[CodeUnit]) -> list[CodeUnit]:
    """Flatten nested code units into a single list (includes both parents and children)."""
    result: list[CodeUnit] = []
    for unit in units:
        result.append(unit)
        result.extend(flatten_units(unit.children))
    return result


def _is_excluded(
    path: Path,
    extra_patterns: list[str] | None = None,
    extra_dirs: set[str] | None = None,
) -> bool:
    """Check if a path should be excluded."""
    excluded = EXCLUDED_DIRS | extra_dirs if extra_dirs else EXCLUDED_DIRS
    if excluded & set(path.parts):
        return True
    if extra_patterns:
        path_str = str(path)
        for pattern in extra_patterns:
            if fnmatch.fnmatch(path_str, pattern):
                return True
    return False


def _should_exclude_unit(unit: CodeUnit, exclude_types: set[str] | None) -> bool:
    """Check if a code unit should be excluded based on its base class types."""
    if not exclude_types or unit.unit_type != "class":
        return False
    return bool(exclude_types & set(unit.base_classes))


def parse_directory(
    directory: str | Path,
    min_lines: int = 6,
    exclude_patterns: list[str] | None = None,
    exclude_types: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
) -> list[CodeUnit]:
    """Parse all supported source files in a directory tree and return flattened code units."""
    directory = Path(directory)
    all_units: list[CodeUnit] = []

    for ext in sorted(SUPPORTED_EXTENSIONS):
        for src_file in sorted(directory.rglob(f"*{ext}")):
            rel = src_file.relative_to(directory)
            if _is_excluded(rel, exclude_patterns, exclude_dirs):
                continue
            try:
                flat = flatten_units(parse_file(src_file))
                for u in flat:
                    if u.line_count >= min_lines and not _should_exclude_unit(u, exclude_types):
                        all_units.append(u)
            except Exception as e:
                print(f"Warning: skipping {src_file}: {e}", file=sys.stderr)

    return all_units
