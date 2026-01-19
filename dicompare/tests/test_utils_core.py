"""
Unit tests for core utility functions in dicompare.utils module.
Tests for make_hashable, safe_convert_value, normalize_numeric_values, and clean_string.
"""

import pytest
from dicompare.utils import (
    make_hashable,
    safe_convert_value,
    normalize_numeric_values,
    clean_string,
)


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
