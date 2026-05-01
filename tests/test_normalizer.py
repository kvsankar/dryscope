"""Tests for dryscope.code.normalizer — code normalization for structural comparison."""

from dryscope.code.normalizer import normalize


class TestNormalizePython:
    def test_identifiers_replaced_with_vars(self):
        code = "def foo(x, y):\n    return x + y"
        result = normalize(code, lang="python")
        assert "VAR_0" in result
        assert "foo" not in result

    def test_strings_replaced_with_str(self):
        code = 'x = "hello world"'
        result = normalize(code, lang="python")
        assert "STR" in result
        assert "hello" not in result

    def test_integers_replaced_with_int(self):
        code = "x = 42"
        result = normalize(code, lang="python")
        assert "INT" in result
        assert "42" not in result

    def test_preserved_names_kept(self):
        code = "self.x = len(items)"
        result = normalize(code, lang="python")
        assert "self" in result
        assert "len" in result

    def test_comments_stripped(self):
        code = "x = 1  # this is a comment\ny = 2"
        result = normalize(code, lang="python")
        assert "comment" not in result.lower()
        # The comment text should not appear
        assert "this is" not in result

    def test_docstrings_stripped(self):
        code = 'def foo():\n    """UNIQUE_MARKER docstring content."""\n    return 1'
        result = normalize(code, lang="python")
        assert "UNIQUE_MARKER" not in result

    def test_structurally_identical_functions_normalize_same(self):
        code_a = (
            "def calculate_area(width, height):\n    result = width * height\n    return result"
        )
        code_b = "def compute_surface(w, h):\n    area = w * h\n    return area"
        norm_a = normalize(code_a, lang="python")
        norm_b = normalize(code_b, lang="python")
        assert norm_a == norm_b

    def test_return_type_is_string(self):
        result = normalize("x = 1", lang="python")
        assert isinstance(result, str)

    def test_empty_source(self):
        result = normalize("", lang="python")
        assert isinstance(result, str)
        assert result.strip() == ""

    def test_builtin_exceptions_preserved(self):
        code = "raise ValueError('bad')"
        result = normalize(code, lang="python")
        assert "ValueError" in result

    def test_dunder_methods_preserved(self):
        code = "def __init__(self):\n    pass"
        result = normalize(code, lang="python")
        assert "__init__" in result
        assert "self" in result


class TestNormalizeTypeScript:
    def test_ts_type_annotations_stripped(self):
        code = "function greet(name: string): string { return name; }"
        result = normalize(code, lang="typescript")
        assert "string" not in result
        # The structural tokens should remain
        assert "function" in result
        assert "return" in result

    def test_ts_preserved_names(self):
        code = "this.x = console.log(undefined)"
        result = normalize(code, lang="typescript")
        assert "this" in result
        assert "console" in result
        assert "undefined" in result

    def test_ts_template_string_replaced(self):
        code = "const msg = `Hello, ${name}!`;"
        result = normalize(code, lang="typescript")
        assert "STR" in result
        assert "Hello" not in result


class TestNormalizeJavaScript:
    def test_js_preserved_names(self):
        code = "this.x = console.log(undefined)"
        result = normalize(code, lang="javascript")
        assert "this" in result
        assert "console" in result
        assert "undefined" in result

    def test_js_template_string_replaced(self):
        code = "const msg = `Hello, ${name}!`;"
        result = normalize(code, lang="javascript")
        assert "STR" in result
        assert "Hello" not in result

    def test_js_structurally_identical_functions_normalize_same(self):
        code_a = "function greet(name) { const msg = name; return msg; }"
        code_b = "function hello(person) { const text = person; return text; }"
        norm_a = normalize(code_a, lang="javascript")
        norm_b = normalize(code_b, lang="javascript")
        assert norm_a == norm_b


class TestNormalizeJava:
    def test_java_preserved_names(self):
        code = "this.value = System.out.println(null);"
        result = normalize(code, lang="java")
        assert "this" in result
        assert "System" in result
        assert "null" in result

    def test_java_structurally_identical_methods_normalize_same(self):
        code_a = "public int add(int a, int b) { int sum = a + b; return sum; }"
        code_b = "public int plus(int x, int y) { int total = x + y; return total; }"
        norm_a = normalize(code_a, lang="java")
        norm_b = normalize(code_b, lang="java")
        assert norm_a == norm_b


class TestNormalizeGo:
    def test_go_preserved_names(self):
        code = "return len(items)"
        result = normalize(code, lang="go")
        assert "len" in result

    def test_go_structurally_identical_functions_normalize_same(self):
        code_a = "func Add(a int, b int) int { sum := a + b; return sum }"
        code_b = "func Plus(x int, y int) int { total := x + y; return total }"
        norm_a = normalize(code_a, lang="go")
        norm_b = normalize(code_b, lang="go")
        assert norm_a == norm_b
