"""Extract code units (functions, classes, methods) from source files using tree-sitter."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node

from dryscope.treesitter import create_parser

# Node types we extract as code units
UNIT_TYPES = {"function_definition", "class_definition"}

# Directories to skip during scanning
EXCLUDED_DIRS = {
    ".venv", "venv", ".env", "env",
    "node_modules", "__pycache__",
    ".git", ".hg", ".svn",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    "site-packages", "dist", "build", "egg-info",
}


@dataclass
class CodeUnit:
    """A single extractable code unit (function, class, method)."""

    name: str
    unit_type: str  # "function", "class", "method"
    source: str
    file_path: str
    start_line: int
    end_line: int
    children: list[CodeUnit] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    def __repr__(self) -> str:
        return f"CodeUnit({self.unit_type} {self.name}, {self.file_path}:{self.start_line}-{self.end_line})"


def _get_name(node: Node) -> str:
    """Extract the name identifier from a function/class definition node."""
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8")
    return "<anonymous>"


def _extract_units(node: Node, file_path: str, parent_is_class: bool = False) -> list[CodeUnit]:
    """Recursively extract code units from a tree-sitter node."""
    units: list[CodeUnit] = []

    for child in node.children:
        if child.type in UNIT_TYPES:
            name = _get_name(child)

            if child.type == "function_definition":
                unit_type = "method" if parent_is_class else "function"
            else:
                unit_type = "class"

            unit = CodeUnit(
                name=name,
                unit_type=unit_type,
                source=child.text.decode("utf-8"),
                file_path=file_path,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
            )
            unit.children = _extract_units(
                child, file_path, parent_is_class=(child.type == "class_definition")
            )
            units.append(unit)

    return units


def parse_file(file_path: str | Path) -> list[CodeUnit]:
    """Parse a Python file and return all code units."""
    file_path = Path(file_path)
    parser = create_parser()
    tree = parser.parse(file_path.read_bytes())
    return _extract_units(tree.root_node, str(file_path))


def flatten_units(units: list[CodeUnit]) -> list[CodeUnit]:
    """Flatten nested code units into a single list (includes both parents and children)."""
    result: list[CodeUnit] = []
    for unit in units:
        result.append(unit)
        result.extend(flatten_units(unit.children))
    return result


def _is_excluded(path: Path) -> bool:
    """Check if any component of the path is in the exclusion set."""
    return bool(EXCLUDED_DIRS & set(path.parts))


def parse_directory(directory: str | Path, min_lines: int = 3) -> list[CodeUnit]:
    """Parse all Python files in a directory tree and return flattened code units."""
    directory = Path(directory)
    all_units: list[CodeUnit] = []

    for py_file in sorted(directory.rglob("*.py")):
        if _is_excluded(py_file.relative_to(directory)):
            continue
        try:
            flat = flatten_units(parse_file(py_file))
            all_units.extend(u for u in flat if u.line_count >= min_lines)
        except Exception as e:
            print(f"Warning: skipping {py_file}: {e}", file=sys.stderr)

    return all_units
