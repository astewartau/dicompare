"""
Unit tests for dicompare.validation.helpers module.
Tests for validation constraint functions and edge cases.
"""

import pytest
from dicompare.validation.helpers import (
    normalize_value,
    check_equality,
    check_contains,
    check_contains_any,
    check_contains_all,
    validate_constraint,
    validate_field_values,
    format_constraint_description,
    create_compliance_record,
    ComplianceStatus,
)


class TestNormalizeValue:
    """Tests for normalize_value function."""

    def test_normalize_int(self):
        """Test that integers are returned unchanged."""
        assert normalize_value(42) == 42

    def test_normalize_float(self):
        """Test that floats are returned unchanged."""
        assert normalize_value(3.14) == 3.14

    def test_normalize_string(self):
        """Test that strings are lowercased and stripped."""
        assert normalize_value("  HELLO World  ") == "hello world"

    def test_normalize_list(self):
        """Test that lists are recursively normalized."""
        assert normalize_value(["A", "B", 1, 2.5]) == ["a", "b", 1, 2.5]

    def test_normalize_object_with_strip(self):
        """Test normalization of objects with strip method."""
        class MockString:
            def strip(self):
                return "TEST"
            def lower(self):
                return "test"
        obj = MockString()
        result = normalize_value(obj)
        assert result == "test"

    def test_normalize_object_without_strip(self):
        """Test normalization of objects converted to string."""
        class MockObj:
            def __str__(self):
                return "  OBJECT  "
        obj = MockObj()
        result = normalize_value(obj)
        assert result == "object"

    def test_normalize_value_exception_handling(self):
        """Test that exceptions in normalization return original value."""
        class BadObj:
            def __str__(self):
                raise ValueError("Cannot convert")
        obj = BadObj()
        result = normalize_value(obj)
        assert result is obj


class TestCheckEquality:
    """Tests for check_equality function."""

    def test_string_case_insensitive(self):
        """Test case-insensitive string comparison."""
        assert check_equality("HELLO", "hello")
        assert check_equality("Hello World", "hello world")

    def test_list_unwrapping_actual(self):
        """Test unwrapping single-element list in actual value."""
        assert check_equality(["hello"], "hello")
        assert not check_equality(["a", "b"], "a")

    def test_list_unwrapping_expected(self):
        """Test unwrapping single-element list in expected value."""
        assert check_equality("hello", ["hello"])
        assert not check_equality("a", ["a", "b"])

    def test_numeric_string_comparison(self):
        """Test numeric comparison between string and number."""
        assert check_equality("42", 42)
        assert check_equality(42, "42")
        assert check_equality("3.14", 3.14)
        assert check_equality(3.14, "3.14")

    def test_numeric_int_float_comparison(self):
        """Test numeric comparison between int and float."""
        assert check_equality(42, 42.0)
        assert check_equality(42.0, 42)

    def test_tuple_normalization(self):
        """Test tuple handling in normalization."""
        assert check_equality((1, 2), (1.0, 2.0))
        assert check_equality((1, 2, 3), [1, 2, 3])

    def test_string_normalization_path(self):
        """Test string comparison path."""
        assert check_equality("  test  ", "TEST")


class TestCheckContains:
    """Tests for check_contains function."""

    def test_string_contains(self):
        """Test substring matching in strings."""
        assert check_contains("hello world", "world")
        assert not check_contains("hello world", "foo")

    def test_list_contains(self):
        """Test substring matching in list elements."""
        assert check_contains(["hello", "world"], "orld")
        assert not check_contains(["hello", "world"], "foo")

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        assert check_contains("HELLO WORLD", "world")

    def test_non_string_returns_false(self):
        """Test that non-string, non-list values return False."""
        assert not check_contains(42, "4")
        assert not check_contains(None, "test")


class TestCheckContainsAny:
    """Tests for check_contains_any function."""

    def test_string_contains_any(self):
        """Test substring matching with any option."""
        assert check_contains_any("hello world", ["foo", "world"])
        assert not check_contains_any("hello", ["foo", "bar"])

    def test_list_contains_any_element(self):
        """Test element matching in lists."""
        assert check_contains_any(["a", "b", "c"], ["x", "b"])
        assert not check_contains_any(["a", "b"], ["x", "y"])

    def test_nested_list_in_constraints(self):
        """Test handling of nested lists in constraints."""
        assert check_contains_any(["a", "b"], [["a", "x"]])

    def test_non_string_non_list_returns_false(self):
        """Test that non-string, non-list actual values return False."""
        assert not check_contains_any(42, ["4", "2"])
        assert not check_contains_any(None, ["test"])

    def test_empty_constraint_list(self):
        """Test with empty constraint list."""
        assert not check_contains_any("hello", [])


class TestCheckContainsAll:
    """Tests for check_contains_all function."""

    def test_list_contains_all(self):
        """Test all elements present in list."""
        assert check_contains_all(["a", "b", "c"], ["a", "b"])
        assert not check_contains_all(["a", "b"], ["a", "c"])

    def test_non_list_returns_false(self):
        """Test that non-list values return False."""
        assert not check_contains_all("abc", ["a", "b"])


class TestValidateConstraint:
    """Tests for validate_constraint function."""

    def test_contains_any(self):
        """Test contains_any constraint."""
        assert validate_constraint("hello world", contains_any=["foo", "world"])
        assert not validate_constraint("hello", contains_any=["foo", "bar"])

    def test_contains_all(self):
        """Test contains_all constraint."""
        assert validate_constraint(["a", "b", "c"], contains_all=["a", "b"])
        assert not validate_constraint(["a", "b"], contains_all=["a", "c"])

    def test_contains(self):
        """Test contains constraint."""
        assert validate_constraint("hello world", contains="world")
        assert not validate_constraint("hello", contains="world")

    def test_min_max_range(self):
        """Test min/max range validation."""
        assert validate_constraint(50, min_value=0, max_value=100)
        assert validate_constraint(0, min_value=0, max_value=100)
        assert validate_constraint(100, min_value=0, max_value=100)
        assert not validate_constraint(-1, min_value=0, max_value=100)
        assert not validate_constraint(101, min_value=0, max_value=100)

    def test_min_only(self):
        """Test min value only."""
        assert validate_constraint(10, min_value=5)
        assert not validate_constraint(3, min_value=5)

    def test_max_only(self):
        """Test max value only."""
        assert validate_constraint(5, max_value=10)
        assert not validate_constraint(15, max_value=10)

    def test_min_max_non_numeric_fails(self):
        """Test that non-numeric values fail min/max validation."""
        assert not validate_constraint("string", min_value=0, max_value=100)

    def test_tolerance(self):
        """Test tolerance constraint."""
        assert validate_constraint(10.5, expected_value=10, tolerance=1)
        assert validate_constraint(9.5, expected_value=10, tolerance=1)
        assert not validate_constraint(12, expected_value=10, tolerance=1)

    def test_tolerance_non_numeric_fails(self):
        """Test that non-numeric values fail tolerance validation."""
        assert not validate_constraint("string", expected_value=10, tolerance=1)

    def test_list_expected_value(self):
        """Test list expected value comparison."""
        assert validate_constraint(["a", "b"], expected_value=["a", "b"])
        assert validate_constraint(["a", "b"], expected_value=["b", "a"])  # Set comparison
        assert not validate_constraint(["a"], expected_value=["a", "b"])

    def test_tuple_as_list(self):
        """Test tuple treated as list."""
        assert validate_constraint(("a", "b"), expected_value=["a", "b"])

    def test_simple_expected_value(self):
        """Test simple expected value comparison."""
        assert validate_constraint("hello", expected_value="hello")
        assert validate_constraint(42, expected_value=42)

    def test_no_constraints_passes(self):
        """Test that no constraints always passes."""
        assert validate_constraint("anything")
        assert validate_constraint(None)


class TestValidateFieldValues:
    """Tests for validate_field_values function."""

    def test_contains_any_pass(self):
        """Test contains_any validation passing."""
        # For lists, contains_any checks if any element in the constraint list is in the actual list
        passed, invalid, msg = validate_field_values(
            "ScanningSequence", [["GR", "IR"]], contains_any=["GR", "SE"]
        )
        assert passed
        assert invalid == []

    def test_contains_any_fail(self):
        """Test contains_any validation failing."""
        passed, invalid, msg = validate_field_values(
            "ScanningSequence", [["GR"]], contains_any=["SE", "EP"]
        )
        assert not passed
        assert "contain any of" in msg

    def test_contains_all_pass(self):
        """Test contains_all validation passing."""
        passed, invalid, msg = validate_field_values(
            "ImageType", [["ORIGINAL", "PRIMARY"]], contains_all=["ORIGINAL", "PRIMARY"]
        )
        assert passed

    def test_contains_all_fail(self):
        """Test contains_all validation failing."""
        passed, invalid, msg = validate_field_values(
            "ImageType", [["ORIGINAL"]], contains_all=["ORIGINAL", "PRIMARY"]
        )
        assert not passed
        assert "contain all of" in msg

    def test_contains_pass(self):
        """Test contains validation passing."""
        passed, invalid, msg = validate_field_values(
            "SeriesDescription", ["T1_MPRAGE_sequence"], contains="MPRAGE"
        )
        assert passed

    def test_contains_fail(self):
        """Test contains validation failing."""
        passed, invalid, msg = validate_field_values(
            "SeriesDescription", ["T2_sequence"], contains="MPRAGE"
        )
        assert not passed
        assert "Expected to contain" in msg

    def test_min_max_pass(self):
        """Test min/max range validation passing."""
        passed, invalid, msg = validate_field_values(
            "EchoTime", [0.01, 0.02, 0.03], min_value=0.0, max_value=0.1
        )
        assert passed

    def test_min_max_fail(self):
        """Test min/max range validation failing."""
        passed, invalid, msg = validate_field_values(
            "EchoTime", [0.01, 0.5], min_value=0.0, max_value=0.1
        )
        assert not passed
        assert 0.5 in invalid

    def test_min_max_nested_lists(self):
        """Test min/max with nested list values."""
        passed, invalid, msg = validate_field_values(
            "PixelSpacing", [(1.0, 1.0)], min_value=0.5, max_value=2.0
        )
        assert passed

    def test_min_max_non_numeric_fails(self):
        """Test min/max with non-numeric values."""
        passed, invalid, msg = validate_field_values(
            "Field", ["string"], min_value=0, max_value=100
        )
        assert not passed
        assert "must be numeric" in msg

    def test_min_max_range_message(self):
        """Test range error message formatting."""
        passed, invalid, msg = validate_field_values(
            "Field", [150], min_value=0, max_value=100
        )
        assert "0-100" in msg

    def test_min_only_message(self):
        """Test min-only error message formatting."""
        passed, invalid, msg = validate_field_values(
            "Field", [-5], min_value=0
        )
        assert ">= 0" in msg

    def test_max_only_message(self):
        """Test max-only error message formatting."""
        passed, invalid, msg = validate_field_values(
            "Field", [150], max_value=100
        )
        assert "<= 100" in msg

    def test_tolerance_pass(self):
        """Test tolerance validation passing."""
        passed, invalid, msg = validate_field_values(
            "FlipAngle", [29, 30, 31], expected_value=30, tolerance=2
        )
        assert passed

    def test_tolerance_fail(self):
        """Test tolerance validation failing."""
        passed, invalid, msg = validate_field_values(
            "FlipAngle", [25, 30], expected_value=30, tolerance=2
        )
        assert not passed
        assert 25 in invalid

    def test_tolerance_nested_values(self):
        """Test tolerance with nested tuple values."""
        passed, invalid, msg = validate_field_values(
            "PixelSpacing", [(1.0, 1.0)], expected_value=1.0, tolerance=0.1
        )
        assert passed

    def test_tolerance_non_numeric_fails(self):
        """Test tolerance with non-numeric values."""
        passed, invalid, msg = validate_field_values(
            "Field", ["string"], expected_value=10, tolerance=1
        )
        assert not passed
        assert "must be numeric" in msg

    def test_tolerance_multi_value_expected(self):
        """Test tolerance with multi-value expected."""
        passed, invalid, msg = validate_field_values(
            "PixelSpacing", [(1.0, 1.0)], expected_value=[1.0, 1.0], tolerance=0.1
        )
        assert passed

    def test_tolerance_multi_value_length_mismatch(self):
        """Test tolerance with length mismatch."""
        passed, invalid, msg = validate_field_values(
            "PixelSpacing", [(1.0,)], expected_value=[1.0, 1.0], tolerance=0.1
        )
        assert not passed
        assert "Expected 2 values" in msg

    def test_list_expected_single_tuple(self):
        """Test list expected value with single tuple actual."""
        passed, invalid, msg = validate_field_values(
            "ImageType", [("ORIGINAL", "PRIMARY")], expected_value=["ORIGINAL", "PRIMARY"]
        )
        assert passed

    def test_list_expected_list_comparison(self):
        """Test list expected value with list comparison."""
        passed, invalid, msg = validate_field_values(
            "Values", ["a", "b"], expected_value=["a", "b"]
        )
        assert passed

    def test_simple_expected_pass(self):
        """Test simple expected value passing."""
        passed, invalid, msg = validate_field_values(
            "Manufacturer", ["SIEMENS", "SIEMENS"], expected_value="SIEMENS"
        )
        assert passed

    def test_simple_expected_fail(self):
        """Test simple expected value failing."""
        passed, invalid, msg = validate_field_values(
            "Manufacturer", ["GE"], expected_value="SIEMENS"
        )
        assert not passed
        assert "Expected SIEMENS but got" in msg

    def test_no_constraints_passes(self):
        """Test that no constraints always passes."""
        passed, invalid, msg = validate_field_values("Field", ["anything"])
        assert passed
        assert msg == "Passed."


class TestFormatConstraintDescription:
    """Tests for format_constraint_description function."""

    def test_contains_any(self):
        """Test contains_any formatting."""
        result = format_constraint_description(contains_any=["a", "b"])
        assert result == "contains_any=['a', 'b']"

    def test_contains_all(self):
        """Test contains_all formatting."""
        result = format_constraint_description(contains_all=["a", "b"])
        assert result == "contains_all=['a', 'b']"

    def test_contains(self):
        """Test contains formatting."""
        result = format_constraint_description(contains="test")
        assert result == "contains='test'"

    def test_range_both(self):
        """Test range formatting with both min and max."""
        result = format_constraint_description(min_value=0, max_value=100)
        assert result == "range=0-100"

    def test_min_only(self):
        """Test min-only formatting."""
        result = format_constraint_description(min_value=10)
        assert result == "min=10"

    def test_max_only(self):
        """Test max-only formatting."""
        result = format_constraint_description(max_value=100)
        assert result == "max=100"

    def test_tolerance(self):
        """Test tolerance formatting."""
        result = format_constraint_description(expected_value=30, tolerance=5)
        assert result == "value=30 ± 5"

    def test_list_value(self):
        """Test list value formatting."""
        result = format_constraint_description(expected_value=["a", "b"])
        assert result == "value(list)=['a', 'b']"

    def test_simple_value(self):
        """Test simple value formatting."""
        result = format_constraint_description(expected_value="test")
        assert result == "value=test"

    def test_none_constraints(self):
        """Test no constraints formatting."""
        result = format_constraint_description()
        assert result == "(none)"


class TestCreateComplianceRecord:
    """Tests for create_compliance_record function."""

    def test_basic_record(self):
        """Test basic compliance record creation."""
        record = create_compliance_record(
            field="EchoTime",
            message="OK",
            status=ComplianceStatus.OK,
            value=0.03,
            expected=0.03
        )
        assert record["field"] == "EchoTime"
        assert record["message"] == "OK"
        assert record["status"] == "ok"
        assert record["value"] == 0.03
        assert record["expected"] == 0.03

    def test_record_with_series(self):
        """Test record with series information."""
        record = create_compliance_record(
            field="EchoTime",
            message="OK",
            status=ComplianceStatus.OK,
            series="Series 001"
        )
        assert record["series"] == "Series 001"

    def test_record_with_rule_name(self):
        """Test record with rule name."""
        record = create_compliance_record(
            field="Count",
            message="Validation passed",
            status=ComplianceStatus.OK,
            rule_name="validate_slice_count"
        )
        assert record["rule_name"] == "validate_slice_count"

    def test_record_auto_format_tolerance(self):
        """Test auto-formatting expected from tolerance."""
        record = create_compliance_record(
            field="FlipAngle",
            message="OK",
            status=ComplianceStatus.OK,
            tolerance=5
        )
        assert "±" in record.get("expected", "")

    def test_record_auto_format_contains(self):
        """Test auto-formatting expected from contains."""
        record = create_compliance_record(
            field="SeriesDescription",
            message="OK",
            status=ComplianceStatus.OK,
            contains="MPRAGE"
        )
        assert "contains" in record.get("expected", "")

    def test_record_auto_format_min_max(self):
        """Test auto-formatting expected from min/max."""
        record = create_compliance_record(
            field="EchoTime",
            message="OK",
            status=ComplianceStatus.OK,
            min_value=0,
            max_value=100
        )
        assert "range" in record.get("expected", "")


class TestComplianceStatus:
    """Tests for ComplianceStatus enum."""

    def test_status_values(self):
        """Test status enum values."""
        assert ComplianceStatus.OK.value == "ok"
        assert ComplianceStatus.ERROR.value == "error"
        assert ComplianceStatus.WARNING.value == "warning"
        assert ComplianceStatus.NA.value == "na"
