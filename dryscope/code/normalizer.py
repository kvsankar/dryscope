"""Normalize code units to make structurally similar code comparable.

Normalization replaces identifiers and literals with placeholders while
preserving structural tokens (keywords, operators, control flow).
This makes Type-2 clones (renamed identifiers) appear identical.
"""

from __future__ import annotations

from tree_sitter import Node

from dryscope.code.treesitter import create_parser

# Keep these identifier names as-is (builtins, common stdlib)
PRESERVE_NAMES_PYTHON = {
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

PRESERVE_NAMES_TYPESCRIPT = {
    "this", "super", "console", "undefined", "null", "true", "false",
    "NaN", "Infinity", "Array", "Object", "Map", "Set", "WeakMap",
    "WeakSet", "Promise", "Date", "RegExp", "Error", "TypeError",
    "RangeError", "SyntaxError", "JSON", "Math", "Number", "String",
    "Boolean", "Symbol", "BigInt", "parseInt", "parseFloat", "isNaN",
    "isFinite", "encodeURI", "decodeURI", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "fetch", "Response", "Request",
    "Headers", "URL", "URLSearchParams", "Buffer", "process",
    "require", "module", "exports", "constructor",
}

PRESERVE_NAMES_JAVA = {
    "this", "super", "null", "true", "false",
    "String", "Object", "Class", "System", "Math",
    "Integer", "Long", "Double", "Float", "Boolean",
    "List", "Map", "Set", "HashMap", "ArrayList", "HashSet",
    "RuntimeException", "IllegalArgumentException", "IllegalStateException",
    "Exception", "Error",
}

# Combined set for languages
_PRESERVE: dict[str, set[str]] = {
    "python": PRESERVE_NAMES_PYTHON,
    "java": PRESERVE_NAMES_JAVA,
    "javascript": PRESERVE_NAMES_TYPESCRIPT,
    "jsx": PRESERVE_NAMES_TYPESCRIPT,
    "typescript": PRESERVE_NAMES_TYPESCRIPT,
    "tsx": PRESERVE_NAMES_TYPESCRIPT,
}

# String node types per language
_STRING_TYPES = {"string", "concatenated_string", "template_string"}

# Comment node types
_COMMENT_TYPES = {"comment"}


def _is_docstring(node: Node) -> bool:
    """Check if an expression_statement node is a docstring (Python only)."""
    return (
        node.type == "expression_statement"
        and len(node.children) == 1
        and node.children[0].type == "string"
    )


def normalize(source: str, lang: str = "python") -> str:
    """Normalize source code for structural comparison.

    - Replaces identifiers with positional placeholders (VAR_0, VAR_1, ...)
    - Replaces literals with type-based placeholders (STR, INT, FLOAT)
    - Strips comments and docstrings
    - Strips type annotations (TypeScript)
    """
    parser = create_parser(lang)
    tree = parser.parse(source.encode("utf-8"))
    preserve = _PRESERVE.get(lang, PRESERVE_NAMES_PYTHON)

    id_map: dict[str, str] = {}
    id_counter = 0
    result_parts: list[str] = []

    # TypeScript node types to skip (type annotations don't affect logic)
    skip_types = set()
    if lang in ("typescript", "tsx"):
        skip_types = {
            "type_annotation", "type_parameters", "type_arguments",
            "interface_declaration", "type_alias_declaration",
        }

    def _visit(node: Node) -> None:
        nonlocal id_counter

        if node.type in skip_types:
            return

        if _is_docstring(node) or node.type in _COMMENT_TYPES:
            return

        # Replace literal nodes wholesale
        if node.type in _STRING_TYPES:
            result_parts.append("STR")
            return
        if node.type == "integer" or node.type == "number":
            result_parts.append("INT")
            return
        if node.type == "float":
            result_parts.append("FLOAT")
            return

        if node.child_count == 0:
            text = node.text.decode("utf-8")
            if node.type in ("identifier", "type_identifier", "property_identifier") and text not in preserve:
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
