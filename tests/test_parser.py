"""Tests for dryscope.code.parser — source file parsing and code unit extraction."""

from pathlib import Path

import pytest

from dryscope.code.parser import (
    CodeUnit,
    _is_excluded,
    flatten_units,
    parse_directory,
    parse_file,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_A = FIXTURES / "sample_a.py"
SAMPLE_B = FIXTURES / "sample_b.py"
SAMPLE_TS = FIXTURES / "sample.ts"
SAMPLE_JS = FIXTURES / "sample.js"
SAMPLE_JAVA = FIXTURES / "sample.java"
SAMPLE_GO = FIXTURES / "sample.go"


# ── parse_file ──────────────────────────────────────────────────────────


class TestParseFile:
    def test_extracts_functions_from_sample_a(self):
        units = parse_file(SAMPLE_A)
        names = [u.name for u in units]
        assert "calculate_area" in names
        assert "process_items" in names
        assert "unique_function_a" in names

    def test_unit_count_sample_a(self):
        units = parse_file(SAMPLE_A)
        assert len(units) == 3

    def test_unit_types_are_function(self):
        units = parse_file(SAMPLE_A)
        for u in units:
            assert u.unit_type == "function"

    def test_start_and_end_lines(self):
        units = parse_file(SAMPLE_A)
        by_name = {u.name: u for u in units}
        calc = by_name["calculate_area"]
        assert calc.start_line == 4
        assert calc.end_line == 9

    def test_lang_is_python(self):
        units = parse_file(SAMPLE_A)
        for u in units:
            assert u.lang == "python"

    def test_source_contains_def(self):
        units = parse_file(SAMPLE_A)
        for u in units:
            assert u.source.startswith("def ")

    def test_line_count_property(self):
        units = parse_file(SAMPLE_A)
        by_name = {u.name: u for u in units}
        calc = by_name["calculate_area"]
        assert calc.line_count == calc.end_line - calc.start_line + 1


# ── parse_directory ─────────────────────────────────────────────────────


class TestParseDirectory:
    def test_extracts_units_from_fixtures(self):
        units = parse_directory(FIXTURES, min_lines=6)
        assert len(units) >= 4  # at least the 4 six-line functions across both files

    def test_min_lines_filter(self):
        units = parse_directory(FIXTURES, min_lines=6)
        for u in units:
            assert u.line_count >= 6

    def test_high_min_lines_filters_everything(self):
        units = parse_directory(FIXTURES, min_lines=100)
        assert len(units) == 0

    def test_names_span_both_files(self):
        units = parse_directory(FIXTURES, min_lines=1)
        names = {u.name for u in units}
        assert "calculate_area" in names
        assert "compute_surface" in names


# ── _is_excluded ────────────────────────────────────────────────────────


class TestIsExcluded:
    def test_excluded_dir(self):
        assert _is_excluded(Path("node_modules/foo.py")) is True

    def test_venv_excluded(self):
        assert _is_excluded(Path(".venv/lib/site.py")) is True

    def test_uv_cache_excluded(self):
        assert _is_excluded(Path("dev/.uv-cache/archive-v0/pkg/foo.py")) is True

    def test_next_build_dir_excluded(self):
        assert _is_excluded(Path(".next/server/app/page.ts")) is True

    def test_normal_path_not_excluded(self):
        assert _is_excluded(Path("src/main.py")) is False

    def test_extra_patterns(self):
        assert _is_excluded(Path("src/test_foo.py"), extra_patterns=["**/test_*.py"]) is True

    def test_extra_dirs(self):
        assert _is_excluded(Path("vendor/lib.py"), extra_dirs={"vendor"}) is True

    def test_no_extra_patterns_normal_file(self):
        assert _is_excluded(Path("src/app.py"), extra_patterns=None) is False


# ── flatten_units ───────────────────────────────────────────────────────


class TestFlattenUnits:
    def test_flat_list_unchanged(self):
        units = [
            CodeUnit(name="a", unit_type="function", source="def a(): pass",
                     file_path="f.py", start_line=1, end_line=1),
            CodeUnit(name="b", unit_type="function", source="def b(): pass",
                     file_path="f.py", start_line=2, end_line=2),
        ]
        flat = flatten_units(units)
        assert len(flat) == 2

    def test_nested_children_flattened(self):
        child = CodeUnit(name="method", unit_type="method", source="def method(): pass",
                         file_path="f.py", start_line=3, end_line=3)
        parent = CodeUnit(name="MyClass", unit_type="class", source="class MyClass:\n  def method(): pass",
                          file_path="f.py", start_line=1, end_line=3, children=[child])
        flat = flatten_units([parent])
        assert len(flat) == 2
        assert flat[0].name == "MyClass"
        assert flat[1].name == "method"


# ── CodeUnit.base_classes ───────────────────────────────────────────────


class TestBaseClasses:
    def test_function_has_no_base_classes(self):
        unit = CodeUnit(name="foo", unit_type="function", source="def foo(): pass",
                        file_path="f.py", start_line=1, end_line=1)
        assert unit.base_classes == []

    def test_class_with_base(self):
        unit = CodeUnit(name="MyModel", unit_type="class",
                        source="class MyModel(BaseModel):\n    pass",
                        file_path="f.py", start_line=1, end_line=2, lang="python")
        assert unit.base_classes == ["BaseModel"]

    def test_class_with_multiple_bases(self):
        unit = CodeUnit(name="MyView", unit_type="class",
                        source="class MyView(View, Mixin):\n    pass",
                        file_path="f.py", start_line=1, end_line=2, lang="python")
        assert unit.base_classes == ["View", "Mixin"]

    def test_class_no_bases(self):
        unit = CodeUnit(name="Plain", unit_type="class",
                        source="class Plain:\n    pass",
                        file_path="f.py", start_line=1, end_line=2, lang="python")
        assert unit.base_classes == []

    def test_class_dotted_base(self):
        unit = CodeUnit(name="Foo", unit_type="class",
                        source="class Foo(models.Model):\n    pass",
                        file_path="f.py", start_line=1, end_line=2, lang="python")
        assert unit.base_classes == ["Model"]


# ── TypeScript/TSX parsing ─────────────────────────────────────────────


class TestParseTypeScript:
    def test_parse_ts_file_extracts_functions(self):
        units = parse_file(SAMPLE_TS)
        names = [u.name for u in units]
        assert "greet" in names
        greet = [u for u in units if u.name == "greet"][0]
        assert greet.unit_type == "function"

    def test_parse_ts_arrow_function(self):
        units = parse_file(SAMPLE_TS)
        names = [u.name for u in units]
        assert "double" in names
        double = [u for u in units if u.name == "double"][0]
        assert double.unit_type == "function"

    def test_parse_ts_class(self):
        units = parse_file(SAMPLE_TS)
        names = [u.name for u in units]
        assert "Calculator" in names
        calc = [u for u in units if u.name == "Calculator"][0]
        assert calc.unit_type == "class"

    def test_parse_ts_class_methods(self):
        units = parse_file(SAMPLE_TS)
        all_units = flatten_units(units)
        names = [u.name for u in all_units]
        assert "add" in names
        assert "subtract" in names
        add_unit = [u for u in all_units if u.name == "add"][0]
        assert add_unit.unit_type == "method"

    def test_parse_ts_export_unwrapping(self):
        units = parse_file(SAMPLE_TS)
        names = [u.name for u in units]
        # The exported function should be found by name, not wrapped in export
        assert "greet" in names

    def test_parse_ts_lang_is_typescript(self):
        units = parse_file(SAMPLE_TS)
        for u in units:
            assert u.lang == "typescript"


class TestParseJavaScript:
    def test_parse_js_file_extracts_functions(self):
        units = parse_file(SAMPLE_JS)
        names = [u.name for u in units]
        assert "greet" in names
        greet = [u for u in units if u.name == "greet"][0]
        assert greet.unit_type == "function"

    def test_parse_js_arrow_function(self):
        units = parse_file(SAMPLE_JS)
        names = [u.name for u in units]
        assert "double" in names
        double = [u for u in units if u.name == "double"][0]
        assert double.unit_type == "function"

    def test_parse_js_class_and_methods(self):
        units = parse_file(SAMPLE_JS)
        names = [u.name for u in units]
        assert "Calculator" in names
        all_units = flatten_units(units)
        all_names = [u.name for u in all_units]
        assert "add" in all_names
        assert "subtract" in all_names
        add_unit = [u for u in all_units if u.name == "add"][0]
        assert add_unit.unit_type == "method"

    def test_parse_js_lang_is_javascript(self):
        units = parse_file(SAMPLE_JS)
        for u in units:
            assert u.lang == "javascript"


class TestParseJava:
    def test_parse_java_class_and_methods(self):
        units = parse_file(SAMPLE_JAVA)
        names = [u.name for u in units]
        assert "Calculator" in names
        all_units = flatten_units(units)
        all_names = [u.name for u in all_units]
        assert "add" in all_names
        assert "subtract" in all_names

    def test_parse_java_methods_are_methods(self):
        units = flatten_units(parse_file(SAMPLE_JAVA))
        add_unit = [u for u in units if u.name == "add"][0]
        assert add_unit.unit_type == "method"

    def test_parse_java_lang_is_java(self):
        units = parse_file(SAMPLE_JAVA)
        for u in units:
            assert u.lang == "java"

    def test_java_class_base_classes(self):
        units = parse_file(SAMPLE_JAVA)
        calc = [u for u in units if u.name == "Calculator"][0]
        assert calc.base_classes == ["BaseCalc"]


class TestParseGo:
    def test_parse_go_functions_and_types(self):
        units = parse_file(SAMPLE_GO)
        names = [u.name for u in units]
        assert "Calculator" in names
        assert "Add" in names
        assert "Subtract" in names

    def test_parse_go_method_is_method(self):
        units = parse_file(SAMPLE_GO)
        sub = [u for u in units if u.name == "Subtract"][0]
        assert sub.unit_type == "method"

    def test_parse_go_lang_is_go(self):
        units = parse_file(SAMPLE_GO)
        for u in units:
            assert u.lang == "go"
