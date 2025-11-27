"""
Schema generation utilities for dicompare.

This module provides functions for generating JSON schemas from DICOM sessions
that can be used for validation purposes.
"""

import pandas as pd
from typing import List, Dict, Any
from ..config import DEFAULT_SETTINGS_FIELDS
from ..utils import clean_string
from ..session import assign_acquisition_and_run_numbers
from .tags import get_tag_info


def build_schema(session_df: pd.DataFrame, reference_fields: List[str] = None) -> Dict[str, Any]:
    """
    Create a JSON schema from the session DataFrame.

    Args:
        session_df (pd.DataFrame): DataFrame of the DICOM session.
        reference_fields (List[str], optional): Fields to include in JSON schema.

    Returns:
        Dict[str, Any]: JSON structure representing the schema.

    Raises:
        ValueError: If session_df is empty or reference_fields is empty.
    """
    # Input validation
    if session_df.empty:
        raise ValueError("Session DataFrame cannot be empty")
    if not reference_fields:
        reference_fields = [f for f in DEFAULT_SETTINGS_FIELDS if f in session_df.columns]

    # Use assign_acquisition_and_run_numbers to get proper series identification
    df = assign_acquisition_and_run_numbers(session_df.copy())

    # Filter reference fields to only those present in the DataFrame
    available_fields = [f for f in reference_fields if f in df.columns]

    json_schema = {"acquisitions": {}}

    # Group by acquisition
    for acquisition_name, acq_group in df.groupby("Acquisition"):
        acquisition_entry = {"fields": [], "series": []}

        # Determine which reference fields are constant at acquisition level vs varying
        varying_fields = []

        for field in available_fields:
            unique_values = acq_group[field].dropna().unique()
            if len(unique_values) == 1:
                # Constant across entire acquisition - add to acquisition-level fields
                tag_info = get_tag_info(field)
                acquisition_entry["fields"].append({
                    "field": field,
                    "tag": tag_info["tag"].strip("()") if tag_info["tag"] else None,
                    "value": unique_values[0]
                })
            elif len(unique_values) > 1:
                # Varying field - will be added to series
                varying_fields.append(field)

        # Group by varying fields to create series
        # Each unique combination of varying field values becomes a series
        if varying_fields:
            series_groups = acq_group.groupby(varying_fields, dropna=False)

            for i, (series_key, series_group) in enumerate(series_groups, start=1):
                # Handle single field vs multiple fields
                if len(varying_fields) == 1:
                    values = [series_key]
                else:
                    values = list(series_key)

                fields_with_tags = []
                for j, field in enumerate(varying_fields):
                    tag_info = get_tag_info(field)
                    value = values[j]
                    # Unwrap if value is a single-element tuple containing another tuple
                    if isinstance(value, tuple) and len(value) == 1 and isinstance(value[0], tuple):
                        value = value[0]
                    fields_with_tags.append({
                        "field": field,
                        "tag": tag_info["tag"].strip("()") if tag_info["tag"] else None,
                        "value": value
                    })

                series_entry = {
                    "name": f"Series {i:02d}",
                    "fields": fields_with_tags
                }
                acquisition_entry["series"].append(series_entry)

        # Add to JSON schema
        json_schema["acquisitions"][clean_string(acquisition_name)] = acquisition_entry

    return json_schema

