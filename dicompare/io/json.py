"""
JSON and schema loading/serialization utilities for dicompare.

This module contains functions for:
- Loading and parsing JSON schema files
- Loading Python validation modules
- Hybrid schema support (JSON + Python rules)
- JSON serialization utilities for numpy/pandas types
"""

import json
import importlib.util
import numpy as np
import pandas as pd
from typing import Any, List, Dict, Tuple

from ..utils import normalize_numeric_values
from ..validation import BaseValidationModel


def load_json_schema(json_schema_path: str) -> Tuple[List[str], Dict[str, Any]]:
    """
    Load a JSON schema file and extract fields for acquisitions and series.

    Expects the modern dict-based acquisitions format used by React applications.

    Args:
        json_schema_path (str): Path to the JSON schema file.

    Returns:
        Tuple[List[str], Dict[str, Any]]:
            - Sorted list of all reference fields encountered.
            - Schema data as loaded from the file.

    Raises:
        FileNotFoundError: If the specified JSON file path does not exist.
        JSONDecodeError: If the file is not a valid JSON file.
    """
    with open(json_schema_path, "r") as f:
        schema_data = json.load(f)

    schema_data = normalize_numeric_values(schema_data)

    # Extract field names from the schema
    reference_fields = set()
    acquisitions_data = schema_data.get("acquisitions", {})

    for acq_name, acq_data in acquisitions_data.items():
        # Extract field names from acquisition fields
        for field in acq_data.get("fields", []):
            if "field" in field:
                reference_fields.add(field["field"])

        # Extract field names from series fields
        for series in acq_data.get("series", []):
            for field in series.get("fields", []):
                if "field" in field:
                    reference_fields.add(field["field"])

    return sorted(reference_fields), schema_data


def load_hybrid_schema(json_schema_path: str) -> Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
    """
    Load a hybrid JSON schema file that supports both field validation and embedded Python rules.

    This function extends load_json_schema to also extract and prepare validation rules
    for dynamic model generation.

    Args:
        json_schema_path (str): Path to the JSON schema file.

    Returns:
        Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
            - Sorted list of all reference fields encountered.
            - Schema data as loaded from the file.
            - Dictionary mapping acquisition names to their validation rules.

    Raises:
        FileNotFoundError: If the specified JSON file path does not exist.
        JSONDecodeError: If the file is not a valid JSON file.
    """
    with open(json_schema_path, "r") as f:
        schema_data = json.load(f)

    schema_data = normalize_numeric_values(schema_data)

    # Extract field names and rules from the schema
    reference_fields = set()
    validation_rules = {}
    acquisitions_data = schema_data.get("acquisitions", {})

    for acq_name, acq_data in acquisitions_data.items():
        # Extract field names from acquisition fields
        for field in acq_data.get("fields", []):
            if "field" in field:
                reference_fields.add(field["field"])

        # Extract field names from series fields
        for series in acq_data.get("series", []):
            for field in series.get("fields", []):
                if "field" in field:
                    reference_fields.add(field["field"])

        # Extract validation rules if present
        if "rules" in acq_data:
            validation_rules[acq_name] = acq_data["rules"]
            # Also add fields referenced in rules to the reference fields
            for rule in acq_data["rules"]:
                if "fields" in rule:
                    for field in rule["fields"]:
                        reference_fields.add(field)

    return sorted(reference_fields), schema_data, validation_rules


def load_python_schema(module_path: str) -> Dict[str, BaseValidationModel]:
    """
    Load validation models from a Python schema module for DICOM compliance checks.

    Notes:
        - The module must define `ACQUISITION_MODELS` as a dictionary mapping acquisition names to validation models.
        - Validation models must inherit from `BaseValidationModel`.

    Args:
        module_path (str): Path to the Python module containing validation models.

    Returns:
        Dict[str, BaseValidationModel]: The acquisition validation models from the module.

    Raises:
        FileNotFoundError: If the specified Python module path does not exist.
        ValueError: If the module does not define `ACQUISITION_MODELS` or its format is incorrect.
    """
    spec = importlib.util.spec_from_file_location("validation_module", module_path)
    validation_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validation_module)

    if not hasattr(validation_module, "ACQUISITION_MODELS"):
        raise ValueError(f"The module {module_path} does not define 'ACQUISITION_MODELS'.")

    acquisition_models = getattr(validation_module, "ACQUISITION_MODELS")
    if not isinstance(acquisition_models, dict):
        raise ValueError("'ACQUISITION_MODELS' must be a dictionary.")

    return acquisition_models


def make_json_serializable(data: Any) -> Any:
    """
    Convert numpy/pandas types to standard Python types for JSON serialization.

    This function recursively processes data structures to convert:
    - numpy arrays to lists
    - numpy scalars to Python scalars
    - pandas NaN/NA to None
    - pandas Series to lists
    - pandas DataFrames to list of dicts

    Args:
        data: Any data structure potentially containing numpy/pandas types

    Returns:
        Data structure with all numpy/pandas types converted to JSON-serializable types

    Examples:
        >>> import numpy as np
        >>> data = {'array': np.array([1, 2, 3]), 'value': np.int64(42)}
        >>> make_json_serializable(data)
        {'array': [1, 2, 3], 'value': 42}
    """
    if isinstance(data, dict):
        return {k: make_json_serializable(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return [make_json_serializable(item) for item in data]
    elif isinstance(data, np.ndarray):
        return data.tolist()
    elif isinstance(data, pd.Series):
        return data.tolist()
    elif isinstance(data, pd.DataFrame):
        return data.to_dict('records')
    elif pd.isna(data) or data is None:
        return None
    elif isinstance(data, (np.integer, np.floating)):
        if np.isnan(data) or np.isinf(data):
            return None
        return data.item()
    elif isinstance(data, float):
        if np.isnan(data) or np.isinf(data):
            return None
        return data
    else:
        # For any other type, try to convert to standard Python type
        # Handle numpy bool_
        if hasattr(data, 'item'):
            return data.item()
        return data