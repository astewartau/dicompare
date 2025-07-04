"""
Schema generation utilities for dicompare.

This module provides functions for generating JSON schemas from DICOM sessions
that can be used for validation purposes.
"""

import pandas as pd
from typing import List, Dict, Any
from .data_utils import standardize_session_dataframe
from .utils import clean_string


def create_json_schema(session_df: pd.DataFrame, reference_fields: List[str]) -> Dict[str, Any]:
    """
    Create a JSON schema from the session DataFrame.

    Args:
        session_df (pd.DataFrame): DataFrame of the DICOM session.
        reference_fields (List[str]): Fields to include in JSON schema.

    Returns:
        Dict[str, Any]: JSON structure representing the schema.
        
    Raises:
        ValueError: If session_df is empty or reference_fields is empty.
    """
    # Input validation
    if session_df.empty:
        raise ValueError("Session DataFrame cannot be empty")
    if not reference_fields:
        raise ValueError("Reference fields list cannot be empty")
    
    # Prepare DataFrame using existing utilities (non-mutating)
    df = standardize_session_dataframe(session_df.copy(), reference_fields)

    json_schema = {"acquisitions": {}}

    # Group by acquisition
    for acquisition_name, group in df.groupby("Acquisition"):
        acquisition_entry = {"fields": [], "series": []}

        # Check reference fields for constant or varying values
        varying_fields = []
        for field in reference_fields:
            unique_values = group[field].dropna().unique()
            if len(unique_values) == 1:
                # Constant field: Add to acquisition-level fields
                acquisition_entry["fields"].append({"field": field, "value": unique_values[0]})
            else:
                # Varying field: Track for series-level fields
                varying_fields.append(field)

        # Group by series based on varying fields
        if varying_fields:
            series_groups = group.groupby(varying_fields, dropna=False)
            for i, (series_key, series_group) in enumerate(series_groups, start=1):
                series_entry = {
                    "name": f"Series {i}",
                    "fields": [{"field": field, "value": series_key[j]} for j, field in enumerate(varying_fields)]
                }
                acquisition_entry["series"].append(series_entry)

        # Add to JSON schema
        json_schema["acquisitions"][clean_string(acquisition_name)] = acquisition_entry

    return json_schema