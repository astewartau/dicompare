"""
This module provides utility functions for handling and normalizing data used in DICOM validation workflows.
"""

import sys
import os
import logging
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

def normalize_numeric_values(data):
    """
    Recursively convert all numeric values in a data structure to floats.

    Notes:
        - Useful for ensuring consistent numeric comparisons, especially for JSON data.
        - Non-numeric values are returned unchanged.

    Args:
        data (Any): The data structure (dict, list, or primitive types) to process.

    Returns:
        Any: The data structure with all numeric values converted to floats.
    """

    if isinstance(data, dict):
        return {k: normalize_numeric_values(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_numeric_values(v) for v in data]
    elif isinstance(data, (int, float)):
        return float(data)
    return data

def convert_jsproxy(obj):
    """
    Convert a JSProxy object (or similar) to a Python dictionary.

    Notes:
        - Handles nested structures recursively.
        - Supports JSProxy objects with a `to_py` method for conversion.
        - If the input is already a Python data type, it is returned as-is.

    Args:
        obj (Any): The object to convert.

    Returns:
        Any: The equivalent Python data structure (dict, list, or primitive types).
    """

    if hasattr(obj, "to_py"):
        return convert_jsproxy(obj.to_py())
    elif isinstance(obj, dict):
        return {k: convert_jsproxy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_jsproxy(v) for v in obj]
    else:
        return obj
    
def make_hashable(value):
    """
    Convert a value into a hashable format for use in dictionaries or sets.

    Notes:
        - Lists are converted to tuples.
        - Dictionaries are converted to sorted tuples of key-value pairs.
        - Sets are converted to sorted tuples of elements.
        - Nested structures are processed recursively.
        - Primitive hashable types (e.g., int, str) are returned unchanged.

    Args:
        value (Any): The value to make hashable.

    Returns:
        Any: A hashable version of the input value.
    """

    if isinstance(value, dict):
        return tuple((k, make_hashable(v)) for k, v in value.items())
    elif isinstance(value, list):
        return tuple(make_hashable(v) for v in value)
    elif isinstance(value, set):
        return tuple(sorted(make_hashable(v) for v in value))  # Sort sets for consistent hash
    elif isinstance(value, tuple):
        return tuple(make_hashable(v) for v in value)
    else:
        return value  # Assume the value is already hashable

def clean_string(s: str):
    """
    Clean a string by removing forbidden characters and converting it to lowercase.

    Notes:
        - Removes special characters such as punctuation, whitespace, and symbols.
        - Converts the string to lowercase for standardization.
        - Commonly used for normalizing acquisition names or other identifiers.

    Args:
        s (str): The string to clean.

    Returns:
        str: The cleaned string.
    """
    # Removed unnecessary escapes from the curly braces and properly escape the backslash.
    forbidden_chars = "`~!@#$%^&*()_+=[]{}|;':,.<>?/\\ "
    for char in forbidden_chars:
        s = s.replace(char, "").lower()
    return s

def safe_convert_value(value, target_type, default_val=None, replace_zero_with_none=False, nonzero_keys=None, element_keyword=None):
    """
    Safely convert a value to a target type with optional zero replacement.

    Args:
        value: The value to convert
        target_type: The target type (int, float, str)
        default_val: Default value if conversion fails
        replace_zero_with_none: Whether to replace zero values with None
        nonzero_keys: Set of field names that should not be zero
        element_keyword: The DICOM element keyword being processed

    Returns:
        Converted value or default
    """
    try:
        converted = target_type(value)
        
        # Handle zero replacement logic
        if replace_zero_with_none and converted == 0:
            if nonzero_keys and element_keyword and element_keyword in nonzero_keys:
                return None
        
        return converted
    except (ValueError, TypeError):
        return default_val

def infer_type_from_extension(ref_path):
    """
    Infer the type of reference based on the file extension.

    Notes:
        - Recognizes '.json' as JSON references.
        - Recognizes '.dcm' and '.IMA' as DICOM references.
        - Recognizes '.py' as Python module references for Pydantic models.
        - Exits the program with an error message if the extension is unrecognized.

    Args:
        ref_path (str): The file path to infer the type from.

    Returns:
        str: The inferred reference type ('json', 'dicom', or 'pydantic').
    """

    _, ext = os.path.splitext(ref_path.lower())
    if ext == ".json":
        return "json"
    elif ext in [".dcm", ".ima"]:
        return "dicom"
    elif ext == ".py":
        return "pydantic"
    else:
        logger.error("Could not determine the reference type. Please specify '--type'.")
        sys.exit(1)


def filter_available_fields(df: pd.DataFrame, 
                           requested_fields: List[str], 
                           fallback_fields: Optional[List[str]] = None) -> List[str]:
    """
    Get fields that exist in the dataframe from requested fields.
    
    Args:
        df: DataFrame to check for field availability
        requested_fields: List of field names to check
        fallback_fields: Optional fallback fields if none of requested_fields exist
        
    Returns:
        List of available field names
        
    Raises:
        ValueError: If no suitable fields are found
        
    Examples:
        >>> df = pd.DataFrame({'A': [1, 2], 'B': [3, 4]})
        >>> filter_available_fields(df, ['A', 'C', 'D'], ['B'])
        ['A']
        >>> filter_available_fields(df, ['X', 'Y'], ['B'])
        ['B']
    """
    # Check which requested fields exist in the dataframe
    available = [field for field in requested_fields if field in df.columns]
    
    # If no requested fields are available, try fallback fields
    if not available and fallback_fields:
        available = [field for field in fallback_fields if field in df.columns]
    
    # If still no fields found, raise an error
    if not available:
        available_cols = list(df.columns)
        raise ValueError(
            f"No suitable fields found in dataframe. "
            f"Requested: {requested_fields}, "
            f"Fallback: {fallback_fields}, "
            f"Available: {available_cols}"
        )
    
    return available


def detect_constant_fields(df: pd.DataFrame, 
                         fields: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Detect which fields are constant vs variable within a dataframe.
    
    Args:
        df: DataFrame to analyze
        fields: List of field names to check
        
    Returns:
        Tuple of (constant_fields_dict, variable_fields_list)
        - constant_fields_dict: Dict mapping field names to their constant values
        - variable_fields_list: List of field names that have multiple values
        
    Examples:
        >>> df = pd.DataFrame({
        ...     'A': [1, 1, 1], 
        ...     'B': [2, 3, 4], 
        ...     'C': ['x', 'x', 'x']
        ... })
        >>> constant, variable = detect_constant_fields(df, ['A', 'B', 'C'])
        >>> constant
        {'A': 1, 'C': 'x'}
        >>> variable
        ['B']
    """
    constant_fields = {}
    variable_fields = []
    
    for field in fields:
        if field not in df.columns:
            logger.warning(f"Field '{field}' not found in dataframe columns")
            continue
            
        # Get unique non-null values
        unique_values = df[field].dropna().unique()
        
        if len(unique_values) == 0:
            # All values are null
            constant_fields[field] = None
        elif len(unique_values) == 1:
            # Single unique value - it's constant
            constant_fields[field] = unique_values[0]
        else:
            # Multiple unique values - it's variable
            variable_fields.append(field)
    
    return constant_fields, variable_fields

