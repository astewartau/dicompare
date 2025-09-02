"""
Validation helper functions for compliance checking.

This module provides common validation patterns used in compliance.py to reduce code repetition.
"""

from typing import Any, List, Dict, Tuple, Optional
from enum import Enum


class ComplianceStatus(Enum):
    """Enum for compliance check status."""
    OK = "ok"
    ERROR = "error"
    WARNING = "warning"
    NA = "na"  # Not Applicable - e.g., field not found in input


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


def check_contains_any(actual: Any, constraint_list: List[str]) -> bool:
    """
    Check if actual contains any of the specified substrings (for strings) or elements (for lists).
    
    For string fields: Case-insensitive substring matching
    For list fields: Exact element matching
    
    Args:
        actual: Value to search in (string or list)
        constraint_list: List of substrings/elements to search for
        
    Returns:
        True if any constraint is satisfied, False otherwise
    """
    if isinstance(actual, (list, tuple)):
        # For lists: check if any constraint element is present in the actual list
        actual_normalized = [normalize_value(x) for x in actual]
        constraint_normalized = [normalize_value(x) for x in constraint_list]
        return any(constraint_item in actual_normalized for constraint_item in constraint_normalized)
    elif isinstance(actual, str) or (hasattr(actual, "strip") and callable(actual.strip)):
        # For strings: check if any constraint substring is contained in the actual string
        actual_norm = normalize_value(actual)
        return any(normalize_value(substring) in actual_norm for substring in constraint_list)
    return False


def check_contains_all(actual: Any, constraint_list: List[str]) -> bool:
    """
    Check if actual contains all of the specified elements (for lists only).
    
    Args:
        actual: List value to search in
        constraint_list: List of elements that must all be present
        
    Returns:
        True if all constraints are satisfied, False otherwise
    """
    if isinstance(actual, (list, tuple)):
        # For lists: check if all constraint elements are present in the actual list
        actual_normalized = [normalize_value(x) for x in actual]
        constraint_normalized = [normalize_value(x) for x in constraint_list]
        return all(constraint_item in actual_normalized for constraint_item in constraint_normalized)
    # contains_all is only valid for list data
    return False


def validate_constraint(
    actual_value: Any,
    expected_value: Any = None,
    tolerance: float = None,
    contains: str = None,
    contains_any: List[str] = None,
    contains_all: List[str] = None
) -> bool:
    """
    Core constraint validation function.
    
    Args:
        actual_value: The actual value to validate
        expected_value: Expected value (if any)
        tolerance: Numeric tolerance (if any)
        contains: Substring that must be contained (if any)
        contains_any: List of substrings/elements where at least one must match (if any)
        contains_all: List of elements that must all be present in lists (if any)
        
    Returns:
        True if constraint passes, False otherwise
    """
    # Priority order: contains_any, contains_all, contains, tolerance, value
    if contains_any is not None:
        return check_contains_any(actual_value, contains_any)
    elif contains_all is not None:
        return check_contains_all(actual_value, contains_all)
    elif contains is not None:
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
    contains: str = None,
    contains_any: List[str] = None,
    contains_all: List[str] = None
) -> Tuple[bool, List[Any], str]:
    """
    Validate all values for a field against constraints.
    
    Args:
        field_name: Name of the field being validated
        actual_values: List of actual values from the data
        expected_value: Expected value constraint
        tolerance: Numeric tolerance constraint
        contains: Substring constraint
        contains_any: List of substrings/elements where at least one must match
        contains_all: List of elements that must all be present in lists
        
    Returns:
        Tuple of (all_passed, invalid_values, error_message)
    """
    invalid_values = []
    
    # Priority order: contains_any, contains_all, contains, tolerance, value
    if contains_any is not None:
        for val in actual_values:
            if not check_contains_any(val, contains_any):
                invalid_values.append(val)
        if invalid_values:
            return False, invalid_values, f"Expected to contain any of {contains_any}, but got {invalid_values}"
    
    elif contains_all is not None:
        for val in actual_values:
            if not check_contains_all(val, contains_all):
                invalid_values.append(val)
        if invalid_values:
            return False, invalid_values, f"Expected to contain all of {contains_all}, but got {invalid_values}"
    
    elif contains is not None:
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
        # Handle special case where actual_values contains a single list/tuple (from make_hashable)
        # that should be compared directly against expected_value
        if len(actual_values) == 1 and isinstance(actual_values[0], (list, tuple)):
            if not validate_constraint(actual_values[0], expected_value):
                return False, actual_values, f"Expected {expected_value}, got {actual_values}"
        else:
            # Compare the entire actual_values list against expected_value list
            if not validate_constraint(actual_values, expected_value):
                return False, actual_values, f"Expected {expected_value}, got {actual_values}"
    
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


def format_constraint_description(
    expected_value: Any = None, 
    tolerance: float = None, 
    contains: str = None,
    contains_any: List[str] = None,
    contains_all: List[str] = None
) -> str:
    """
    Format a human-readable description of constraints.
    
    Args:
        expected_value: Expected value constraint
        tolerance: Numeric tolerance constraint  
        contains: Substring constraint
        contains_any: List of substrings/elements where at least one must match
        contains_all: List of elements that must all be present in lists
        
    Returns:
        Formatted constraint description
    """
    # Priority order: contains_any, contains_all, contains, tolerance, value
    if contains_any is not None:
        return f"contains_any={contains_any}"
    elif contains_all is not None:
        return f"contains_all={contains_all}"
    elif contains is not None:
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
    contains_any: List[str] = None,
    contains_all: List[str] = None,
    actual_values: List[Any] = None,
    message: str = "",
    passed: bool = True,
    status: Optional[ComplianceStatus] = None
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
        contains_any: List of substrings/elements where at least one must match
        contains_all: List of elements that must all be present in lists
        actual_values: List of actual values found
        message: Validation message
        passed: Whether validation passed
        status: Compliance status (if None, will be derived from passed/message)
        
    Returns:
        Compliance record dictionary
    """
    if (expected_value is not None or tolerance is not None or contains is not None or 
        contains_any is not None or contains_all is not None):
        expected_desc = format_constraint_description(expected_value, tolerance, contains, contains_any, contains_all)
    else:
        expected_desc = f"(value={expected_value}, tolerance={tolerance}, contains={contains}, contains_any={contains_any}, contains_all={contains_all})"
    
    # Determine status if not explicitly provided
    if status is None:
        if "Field not found in input" in message:
            print(f"DEBUG: Setting status to NA for message: '{message}'")
            status = ComplianceStatus.NA
        elif passed:
            status = ComplianceStatus.OK
        else:
            print(f"DEBUG: Setting status to ERROR for message: '{message}', passed: {passed}")
            status = ComplianceStatus.ERROR
    
    result = {
        "schema acquisition": schema_acq_name,
        "input acquisition": in_acq_name,
        "series": series_name,
        "field": field_name,
        "expected": expected_desc,
        "value": actual_values,
        "message": message,
        "passed": passed,
        "status": status.value  # Store as string for JSON serialization
    }
    
    # Debug: print records with "not found" message
    if "not found" in message.lower():
        print(f"DEBUG create_compliance_record: Created record with status '{status.value}' for message: '{message}'")
    
    return result