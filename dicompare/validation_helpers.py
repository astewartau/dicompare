"""
Validation helper functions for compliance checking.

This module provides common validation patterns used in compliance.py to reduce code repetition.
"""

from typing import Any, List, Dict, Tuple, Optional


def normalize_value(val: Any) -> Any:
    """
    Normalize a value for comparison by converting to lowercase string if text-like,
    leaving numeric values unchanged, and recursively processing lists.
    
    Args:
        val: Value to normalize
        
    Returns:
        Normalized value
    """
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, list):
        return [normalize_value(x) for x in val]
    try:
        # If the object has a strip method, assume it's string-like.
        if hasattr(val, "strip") and callable(val.strip):
            return val.strip().lower()
        # Otherwise, convert to string.
        return str(val).strip().lower()
    except Exception:
        return val


def check_equality(val: Any, expected: Any) -> bool:
    """
    Compare two values in a case-insensitive manner.
    If one is a list with one string element and the other is a string, the element is unwrapped.
    Handles numeric type mismatches between int/float values and string/numeric conversions.
    
    Args:
        val: Actual value
        expected: Expected value
        
    Returns:
        True if values are equal, False otherwise
    """
    # Helper function to try converting a value to numeric
    def try_numeric(value):
        try:
            if isinstance(value, str):
                # Try to convert string to number
                if '.' in value:
                    return float(value)
                else:
                    return int(value)
            elif isinstance(value, (int, float)):
                return float(value)
        except (ValueError, TypeError):
            pass
        return value
    
    # Helper function to normalize values for comparison
    def normalize_for_comparison(value):
        if isinstance(value, (list, tuple)):
            return tuple(normalize_for_comparison(item) for item in value)
        
        # Try to convert to numeric if possible
        numeric_val = try_numeric(value)
        if numeric_val != value:  # Conversion was successful
            return numeric_val
        
        # Fall back to string normalization
        if isinstance(value, str) or hasattr(value, 'strip'):
            return normalize_value(value)
        
        return value
    
    # Unwrap if actual is a list containing one string.
    if isinstance(val, list) and isinstance(expected, str):
        if len(val) == 1 and isinstance(val[0], (str,)):
            return normalize_value(val[0]) == normalize_value(expected)
        return False
    if isinstance(expected, list) and isinstance(val, str):
        if len(expected) == 1 and isinstance(expected[0], (str,)):
            return normalize_value(val) == normalize_value(expected[0])
        return False
    if isinstance(val, (str,)) or isinstance(expected, (str,)):
        # Check if both can be converted to numeric values
        val_numeric = try_numeric(val)
        expected_numeric = try_numeric(expected)
        
        # If both converted successfully to numeric, compare as numbers
        if (val_numeric != val or isinstance(val, (int, float))) and \
           (expected_numeric != expected or isinstance(expected, (int, float))):
            return val_numeric == expected_numeric
        
        # Fall back to string comparison
        return normalize_value(val) == normalize_value(expected)
    
    # Handle numeric or convertible values
    val_normalized = normalize_for_comparison(val)
    expected_normalized = normalize_for_comparison(expected)
    
    return val_normalized == expected_normalized


def check_contains(actual: Any, substring: str) -> bool:
    """
    Check if actual contains the given substring, comparing in normalized form.
    
    Args:
        actual: Value to search in
        substring: Substring to search for
        
    Returns:
        True if substring is found, False otherwise
    """
    sub_norm = substring.strip().lower()
    if isinstance(actual, str) or (hasattr(actual, "strip") and callable(actual.strip)):
        return normalize_value(actual).find(sub_norm) != -1
    elif isinstance(actual, (list, tuple)):
        return any(isinstance(x, str) and normalize_value(x).find(sub_norm) != -1 for x in actual)
    return False


def validate_constraint(
    actual_value: Any,
    expected_value: Any = None,
    tolerance: float = None,
    contains: str = None
) -> bool:
    """
    Core constraint validation function.
    
    Args:
        actual_value: The actual value to validate
        expected_value: Expected value (if any)
        tolerance: Numeric tolerance (if any)
        contains: Substring that must be contained (if any)
        
    Returns:
        True if constraint passes, False otherwise
    """
    if contains is not None:
        return check_contains(actual_value, contains)
    elif tolerance is not None:
        if not isinstance(actual_value, (int, float)):
            return False
        return (expected_value - tolerance <= actual_value <= expected_value + tolerance)
    elif isinstance(expected_value, list):
        if not isinstance(actual_value, (list, tuple)):
            return False
        # Handle both lists and tuples from make_hashable
        actual_normalized = list(normalize_value(list(actual_value) if isinstance(actual_value, tuple) else actual_value))
        expected_normalized = list(normalize_value(expected_value))
        return set(actual_normalized) == set(expected_normalized)
    elif expected_value is not None:
        return check_equality(actual_value, expected_value)
    return True


def validate_field_values(
    field_name: str,
    actual_values: List[Any],
    expected_value: Any = None,
    tolerance: float = None,
    contains: str = None
) -> Tuple[bool, List[Any], str]:
    """
    Validate all values for a field against constraints.
    
    Args:
        field_name: Name of the field being validated
        actual_values: List of actual values from the data
        expected_value: Expected value constraint
        tolerance: Numeric tolerance constraint
        contains: Substring constraint
        
    Returns:
        Tuple of (all_passed, invalid_values, error_message)
    """
    invalid_values = []
    
    if contains is not None:
        for val in actual_values:
            if not check_contains(val, contains):
                invalid_values.append(val)
        if invalid_values:
            return False, invalid_values, f"Expected to contain '{contains}', but got {invalid_values}"
    
    elif tolerance is not None:
        # Check for non-numeric values first
        non_numeric = [val for val in actual_values if not isinstance(val, (int, float))]
        if non_numeric:
            return False, non_numeric, f"Field must be numeric; found {non_numeric}"
        
        # Check tolerance
        for val in actual_values:
            if not (expected_value - tolerance <= val <= expected_value + tolerance):
                invalid_values.append(val)
        if invalid_values:
            return False, invalid_values, f"Expected {expected_value} ±{tolerance}, but got {invalid_values}"
    
    elif isinstance(expected_value, list):
        for val in actual_values:
            if not validate_constraint(val, expected_value):
                invalid_values.append(val)
        if invalid_values:
            return False, invalid_values, f"Expected list-based match, got {invalid_values}"
    
    elif expected_value is not None:
        for val in actual_values:
            if not check_equality(val, expected_value):
                invalid_values.append(val)
        if invalid_values:
            # Create clear error message showing expected vs actual values
            if len(invalid_values) == 1:
                return False, invalid_values, f"Expected {expected_value} but got {invalid_values[0]}"
            else:
                return False, invalid_values, f"Expected {expected_value} but got values: {invalid_values}"
    
    return True, [], "Passed."


def format_constraint_description(expected_value: Any = None, tolerance: float = None, contains: str = None) -> str:
    """
    Format a human-readable description of constraints.
    
    Args:
        expected_value: Expected value constraint
        tolerance: Numeric tolerance constraint  
        contains: Substring constraint
        
    Returns:
        Formatted constraint description
    """
    if contains is not None:
        return f"contains='{contains}'"
    elif tolerance is not None:
        return f"value={expected_value} ± {tolerance}"
    elif isinstance(expected_value, list):
        return f"value(list)={expected_value}"
    elif expected_value is not None:
        return f"value={expected_value}"
    else:
        return "(none)"


def create_compliance_record(
    schema_acq_name: str,
    in_acq_name: str,
    series_name: Optional[str],
    field_name: str,
    expected_value: Any = None,
    tolerance: float = None,
    contains: str = None,
    actual_values: List[Any] = None,
    message: str = "",
    passed: bool = True
) -> Dict[str, Any]:
    """
    Create a standardized compliance record.
    
    Args:
        schema_acq_name: Schema acquisition name
        in_acq_name: Input acquisition name
        series_name: Series name (None for acquisition-level)
        field_name: Field name being validated
        expected_value: Expected value constraint
        tolerance: Numeric tolerance constraint
        contains: Substring constraint
        actual_values: List of actual values found
        message: Validation message
        passed: Whether validation passed
        
    Returns:
        Compliance record dictionary
    """
    if expected_value is not None or tolerance is not None or contains is not None:
        expected_desc = format_constraint_description(expected_value, tolerance, contains)
    else:
        expected_desc = f"(value={expected_value}, tolerance={tolerance}, contains={contains})"
    
    return {
        "schema acquisition": schema_acq_name,
        "input acquisition": in_acq_name,
        "series": series_name,
        "field": field_name,
        "expected": expected_desc,
        "value": actual_values,
        "message": message,
        "passed": passed
    }