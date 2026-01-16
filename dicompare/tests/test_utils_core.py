"""
Unit tests for core utility functions in dicompare.utils module.
Tests for convert_jsproxy, make_hashable, safe_convert_value, and infer_type_from_extension.
"""

import pytest
import sys
from dicompare.utils import (
    convert_jsproxy,
    make_hashable,
    safe_convert_value,
    infer_type_from_extension,
    normalize_numeric_values,
    clean_string,
)


class TestConvertJsProxy:
    """Tests for convert_jsproxy function."""

    def test_dict_passthrough(self):
        """Test that dicts are returned with converted values."""
        data = {"a": 1, "b": {"c": 2}}
        result = convert_jsproxy(data)
        assert result == {"a": 1, "b": {"c": 2}}

    def test_list_passthrough(self):
        """Test that lists are returned with converted values."""
        data = [1, 2, [3, 4]]
        result = convert_jsproxy(data)
        assert result == [1, 2, [3, 4]]

    def test_primitive_passthrough(self):
        """Test that primitives are returned unchanged."""
        assert convert_jsproxy(42) == 42
        assert convert_jsproxy("hello") == "hello"
        assert convert_jsproxy(3.14) == 3.14
        assert convert_jsproxy(None) is None

    def test_object_with_to_py(self):
        """Test conversion of objects with to_py method."""
        class MockJsProxy:
            def to_py(self):
                return {"converted": True}

        proxy = MockJsProxy()
        result = convert_jsproxy(proxy)
        assert result == {"converted": True}

    def test_nested_to_py(self):
        """Test nested conversion with to_py objects."""
        class InnerProxy:
            def to_py(self):
                return [1, 2, 3]

        class OuterProxy:
            def to_py(self):
                return {"inner": InnerProxy()}

        proxy = OuterProxy()
        result = convert_jsproxy(proxy)
        assert result == {"inner": [1, 2, 3]}


class TestMakeHashable:
    """Tests for make_hashable function."""

    def test_dict_to_tuple(self):
        """Test dict conversion to tuple."""
        result = make_hashable({"a": 1, "b": 2})
        assert isinstance(result, tuple)
        assert ("a", 1) in result
        assert ("b", 2) in result

    def test_list_to_tuple(self):
        """Test list conversion to tuple."""
        result = make_hashable([1, 2, 3])
        assert result == (1, 2, 3)

    def test_set_to_sorted_tuple(self):
        """Test set conversion to sorted tuple."""
        result = make_hashable({3, 1, 2})
        assert result == (1, 2, 3)

    def test_tuple_recursive(self):
        """Test tuple with nested structures."""
        result = make_hashable((1, [2, 3], {4, 5}))
        assert result == (1, (2, 3), (4, 5))

    def test_nested_dict(self):
        """Test nested dict conversion."""
        result = make_hashable({"a": {"b": [1, 2]}})
        assert isinstance(result, tuple)

    def test_primitive_unchanged(self):
        """Test that primitives are unchanged."""
        assert make_hashable(42) == 42
        assert make_hashable("hello") == "hello"
        assert make_hashable(3.14) == 3.14


class TestSafeConvertValue:
    """Tests for safe_convert_value function."""

    def test_int_conversion(self):
        """Test conversion to int."""
        assert safe_convert_value("42", int) == 42
        assert safe_convert_value(42.9, int) == 42

    def test_float_conversion(self):
        """Test conversion to float."""
        assert safe_convert_value("3.14", float) == 3.14
        assert safe_convert_value(42, float) == 42.0

    def test_str_conversion(self):
        """Test conversion to str."""
        assert safe_convert_value(42, str) == "42"
        assert safe_convert_value(3.14, str) == "3.14"

    def test_default_on_failure(self):
        """Test default value returned on conversion failure."""
        assert safe_convert_value("not a number", int) is None
        assert safe_convert_value("not a number", int, default_val=-1) == -1

    def test_zero_replacement_disabled(self):
        """Test zero replacement when disabled."""
        result = safe_convert_value(0, int, replace_zero_with_none=False)
        assert result == 0

    def test_zero_replacement_enabled_no_match(self):
        """Test zero replacement when key not in nonzero_keys."""
        result = safe_convert_value(
            0, int,
            replace_zero_with_none=True,
            nonzero_keys={"OtherField"},
            element_keyword="TestField"
        )
        assert result == 0

    def test_zero_replacement_enabled_match(self):
        """Test zero replacement when key matches nonzero_keys."""
        result = safe_convert_value(
            0, int,
            replace_zero_with_none=True,
            nonzero_keys={"TestField"},
            element_keyword="TestField"
        )
        assert result is None

    def test_type_error_handling(self):
        """Test handling of TypeError during conversion."""
        assert safe_convert_value(None, int) is None


class TestInferTypeFromExtension:
    """Tests for infer_type_from_extension function."""

    def test_json_extension(self):
        """Test .json extension inference."""
        assert infer_type_from_extension("schema.json") == "json"
        assert infer_type_from_extension("/path/to/file.JSON") == "json"

    def test_dicom_extensions(self):
        """Test .dcm and .IMA extension inference."""
        assert infer_type_from_extension("image.dcm") == "dicom"
        assert infer_type_from_extension("image.DCM") == "dicom"
        assert infer_type_from_extension("image.ima") == "dicom"
        assert infer_type_from_extension("image.IMA") == "dicom"

    def test_python_extension(self):
        """Test .py extension inference."""
        assert infer_type_from_extension("model.py") == "pydantic"

    def test_unknown_extension_exits(self):
        """Test that unknown extension causes system exit."""
        with pytest.raises(SystemExit) as exc_info:
            infer_type_from_extension("file.unknown")
        assert exc_info.value.code == 1


class TestNormalizeNumericValues:
    """Tests for normalize_numeric_values function."""

    def test_dict_normalization(self):
        """Test dict value normalization."""
        data = {"a": 1, "b": 2.5, "c": "text"}
        result = normalize_numeric_values(data)
        assert result == {"a": 1.0, "b": 2.5, "c": "text"}

    def test_list_normalization(self):
        """Test list value normalization."""
        data = [1, 2, 3.5]
        result = normalize_numeric_values(data)
        assert result == [1.0, 2.0, 3.5]

    def test_nested_normalization(self):
        """Test nested structure normalization."""
        data = {"outer": [{"inner": 42}]}
        result = normalize_numeric_values(data)
        assert result == {"outer": [{"inner": 42.0}]}

    def test_non_numeric_unchanged(self):
        """Test that non-numeric values are unchanged."""
        assert normalize_numeric_values("text") == "text"
        assert normalize_numeric_values(None) is None


class TestCleanString:
    """Tests for clean_string function."""

    def test_removes_special_chars(self):
        """Test removal of special characters."""
        assert clean_string("Hello World!") == "helloworld"
        assert clean_string("Test@123#") == "test123"

    def test_lowercase_conversion(self):
        """Test lowercase conversion."""
        assert clean_string("UPPERCASE") == "uppercase"
        assert clean_string("MixedCase") == "mixedcase"

    def test_removes_spaces(self):
        """Test removal of spaces."""
        assert clean_string("hello world") == "helloworld"

    def test_removes_punctuation(self):
        """Test removal of various punctuation."""
        assert clean_string("a,b.c;d:e") == "abcde"

    def test_empty_string(self):
        """Test empty string input."""
        assert clean_string("") == ""
