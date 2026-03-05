"""Normalize code units to make structurally similar code comparable.

Normalization replaces identifiers and literals with placeholders while
preserving structural tokens (keywords, operators, control flow).
This makes Type-2 clones (renamed identifiers) appear identical.
"""

from __future__ import annotations

from tree_sitter import Node

from dryscope.treesitter import create_parser

# Keep these identifier names as-is (builtins, common stdlib)
PRESERVE_NAMES = {
    "self", "cls", "super", "print", "len", "range", "enumerate",
    "zip", "map", "filter", "sorted", "reversed", "list", "dict",
    "set", "tuple", "str", "int", "float", "bool", "None", "True",
    "False", "isinstance", "issubclass", "type", "object", "property",
    "staticmethod", "classmethod", "Exception", "ValueError", "TypeError",
    "KeyError", "IndexError", "AttributeError", "RuntimeError",
    "NotImplementedError", "StopIteration", "open", "hasattr", "getattr",
    "setattr", "delattr", "callable", "iter", "next", "abs", "min", "max",
    "sum", "any", "all", "round", "divmod", "pow", "hash", "id", "repr",
    "format", "input", "vars", "dir", "globals", "locals",
    "__init__", "__str__", "__repr__", "__len__", "__getitem__",
    "__setitem__", "__delitem__", "__contains__", "__iter__", "__next__",
    "__call__", "__enter__", "__exit__", "__eq__", "__ne__", "__lt__",
    "__gt__", "__le__", "__ge__", "__hash__", "__bool__",
}


def _is_docstring(node: Node) -> bool:
    """Check if an expression_statement node is a docstring."""
    return (
        node.type == "expression_statement"
        and len(node.children) == 1
        and node.children[0].type == "string"
    )


def normalize(source: str) -> str:
    """Normalize Python source code for structural comparison.

    - Replaces identifiers with positional placeholders (VAR_0, VAR_1, ...)
    - Replaces literals with type-based placeholders (STR, INT, FLOAT)
    - Strips comments and docstrings
    """
    parser = create_parser()
    tree = parser.parse(source.encode("utf-8"))

    id_map: dict[str, str] = {}
    id_counter = 0
    result_parts: list[str] = []

    def _visit(node: Node) -> None:
        nonlocal id_counter

        if _is_docstring(node) or node.type == "comment":
            return

        # Replace literal nodes wholesale (they have children like string_start/content/end)
        if node.type in ("string", "concatenated_string"):
            result_parts.append("STR")
            return
        if node.type == "integer":
            result_parts.append("INT")
            return
        if node.type == "float":
            result_parts.append("FLOAT")
            return

        if node.child_count == 0:
            text = node.text.decode("utf-8")
            if node.type == "identifier" and text not in PRESERVE_NAMES:
                if text not in id_map:
                    id_map[text] = f"VAR_{id_counter}"
                    id_counter += 1
                result_parts.append(id_map[text])
            else:
                result_parts.append(text)
        else:
            for child in node.children:
                _visit(child)

    _visit(tree.root_node)
    return " ".join(result_parts)
