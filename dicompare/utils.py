"""
This module provides utility functions for handling and normalizing data used in DICOM validation workflows.

"""

import sys
import os

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
        - Primitive hashable types (e.g., int, str) are returned unchanged.

    Args:
        value (Any): The value to make hashable.

    Returns:
        Any: A hashable version of the input value.
    """

    if isinstance(value, list):
        return tuple(value)
    elif isinstance(value, dict):
        return tuple((k, make_hashable(v)) for k, v in value.items())
    elif isinstance(value, set):
        return tuple(sorted(make_hashable(v) for v in value))
    return value

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

    forbidden_chars = "`~!@#$%^&*()_+=[]\{\}|;':,.<>?/\\ "
    for char in forbidden_chars:
        s = s.replace(char, "").lower()
    return s

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
    elif ext in [".dcm", ".IMA"]:
        return "dicom"
    elif ext == ".py":
        return "pydantic"
    else:
        print("Error: Could not determine the reference type. Please specify '--type'.", file=sys.stderr)
        sys.exit(1)

