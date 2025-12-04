"""
JSON and schema loading/serialization utilities for dicompare.

This module contains functions for:
- Loading and parsing JSON schema files
- Hybrid schema support (JSON + Python rules)
- JSON serialization utilities for numpy/pandas types
- Schema validation against the DiCompare metaschema
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any, List, Dict, Tuple

from jsonschema import validate

from ..utils import normalize_numeric_values


# Cache the metaschema to avoid reloading it on every validation
_metaschema_cache = None


def _get_metaschema() -> Dict[str, Any]:
    """Load and cache the DiCompare metaschema."""
    global _metaschema_cache
    if _metaschema_cache is None:
        metaschema_path = Path(__file__).parent.parent / "metaschema.json"
        with open(metaschema_path, "r") as f:
            _metaschema_cache = json.load(f)
    return _metaschema_cache


def validate_schema(schema_data: Dict[str, Any]) -> None:
    """
    Validate a schema dictionary against the DiCompare metaschema.

    Args:
        schema_data: The schema data to validate.

    Raises:
        jsonschema.ValidationError: If the schema is invalid.
    """
    validate(instance=schema_data, schema=_get_metaschema())


def load_schema(json_schema_path: str, validate_schema: bool = True) -> Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
    """
    Load a JSON schema file with support for both field validation and embedded Python rules.

    This function loads schema files and extracts field definitions and validation rules
    for dynamic model generation.

    Args:
        json_schema_path (str): Path to the JSON schema file.
        validate_schema (bool): Whether to validate the schema against the DiCompare
            metaschema. Defaults to True.

    Returns:
        Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
            - Sorted list of all reference fields encountered.
            - Schema data as loaded from the file.
            - Dictionary mapping acquisition names to their validation rules.

    Raises:
        FileNotFoundError: If the specified JSON file path does not exist.
        JSONDecodeError: If the file is not a valid JSON file.
        jsonschema.ValidationError: If validate_schema is True and the schema is invalid.
    """
    with open(json_schema_path, "r") as f:
        schema_data = json.load(f)

    if validate_schema:
        validate(instance=schema_data, schema=_get_metaschema())

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