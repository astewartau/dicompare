"""
Data processing utilities for dicompare operations.

This module provides simple utility functions for common data processing patterns,
reducing repetitive DataFrame and DICOM processing code.
"""

import pandas as pd
from typing import Dict, Any, List
from pydicom.multival import MultiValue
from .utils import make_hashable
from .config import ENHANCED_TO_REGULAR_MAPPING


def make_dataframe_hashable(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply make_hashable to all columns in a DataFrame.
    
    Args:
        df: DataFrame to process
        
    Returns:
        DataFrame with all values made hashable
    """
    for col in df.columns:
        df[col] = df[col].apply(make_hashable)
    return df


def _flatten_nested_dict(data: Dict[str, Any], parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
    """
    Recursively flatten nested dictionaries and sequences.
    
    Args:
        data: Data to flatten
        parent_key: Parent key for nested items
        sep: Separator for nested keys
        
    Returns:
        Flattened dictionary
    """
    items = {}

    if isinstance(data, dict):
        for key, value in data.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key

            if isinstance(value, dict):
                items.update(_flatten_nested_dict(value, new_key, sep=sep))

            elif isinstance(value, (list, tuple)):
                # Only descend if there's at least one dict in the list
                if any(isinstance(item, dict) for item in value):
                    for idx, item in enumerate(value):
                        item_key = f"{new_key}{sep}{idx}"
                        if isinstance(item, dict):
                            items.update(_flatten_nested_dict(item, item_key, sep=sep))
                        else:
                            items[item_key] = item
                else:
                    # Atomic list of primitives – keep it whole
                    items[new_key] = value

            else:
                items[new_key] = value

    elif isinstance(data, (list, tuple)):
        # Same logic for a top‑level list
        if any(isinstance(item, dict) for item in data):
            for idx, item in enumerate(data):
                new_key = f"{parent_key}{sep}{idx}" if parent_key else str(idx)
                if isinstance(item, dict):
                    items.update(_flatten_nested_dict(item, new_key, sep=sep))
                else:
                    items[new_key] = item
        else:
            items[parent_key] = data

    else:
        items[parent_key] = data

    return items


def _reduce_flattened_keys(flat_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Replace each key with just the last underscore-separated component.
    
    Args:
        flat_dict: Flattened dictionary
        
    Returns:
        Dictionary with reduced keys
    """
    result = {}
    for key, value in flat_dict.items():
        new_key = key.split("_")[-1]
        if new_key in result:
            # If already present, update only if existing value is None and new one isn't
            if result[new_key] is None and value is not None:
                result[new_key] = value
        else:
            result[new_key] = value
    return result


def _convert_to_plain_python_types(value: Any) -> Any:
    """
    Convert pydicom types to plain Python types.
    
    Args:
        value: Value to convert
        
    Returns:
        Converted value
    """
    if isinstance(value, (list, MultiValue, tuple)):
        return tuple(_convert_to_plain_python_types(item) for item in value)
    elif isinstance(value, dict):
        return {k: _convert_to_plain_python_types(v) for k, v in value.items()}
    elif isinstance(value, float):
        return round(value, 5)
    elif isinstance(value, int):
        return int(value)
    return value


def _process_dicom_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply the complete DICOM metadata processing pipeline.
    
    This consolidates the repetitive post-processing chain:
    - Flatten nested structures
    - Convert to plain Python types  
    - Reduce flattened keys
    - Apply enhanced to regular mapping
    
    Args:
        metadata: Raw DICOM metadata dictionary
        
    Returns:
        Processed metadata dictionary
    """
    # Step 1: Flatten nested structures
    flat_metadata = _flatten_nested_dict(metadata)
    
    # Step 2: Convert to plain Python types
    plain_metadata = {
        k: _convert_to_plain_python_types(v) 
        for k, v in flat_metadata.items()
    }
    
    # Step 3: Reduce flattened keys
    plain_metadata = _reduce_flattened_keys(plain_metadata)
    
    # Step 4: Apply enhanced to regular mapping
    for src, tgt in ENHANCED_TO_REGULAR_MAPPING.items():
        if src in plain_metadata:
            plain_metadata[tgt] = plain_metadata.pop(src)
    
    return plain_metadata


def prepare_session_dataframe(session_data: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Create and prepare a session DataFrame from raw data.
    
    Args:
        session_data: List of dictionaries containing session data
        
    Returns:
        Prepared and sorted DataFrame
    """
    if not session_data:
        raise ValueError("No session data found to process.")
    
    # Create DataFrame
    session_df = pd.DataFrame(session_data)
    
    # Make all values hashable
    session_df = make_dataframe_hashable(session_df)
    
    # Drop empty columns
    session_df.dropna(axis=1, how="all", inplace=True)
    
    # Sort by InstanceNumber or DICOM_Path
    if "InstanceNumber" in session_df.columns:
        session_df.sort_values("InstanceNumber", inplace=True)
    elif "DICOM_Path" in session_df.columns:
        session_df.sort_values("DICOM_Path", inplace=True)
    
    return session_df


def standardize_session_dataframe(df: pd.DataFrame, 
                                reference_fields: List[str] = None) -> pd.DataFrame:
    """
    Standard preparation for session DataFrames used in schema generation and validation.
    
    Args:
        df: DataFrame to standardize
        reference_fields: Optional list of fields to sort by
        
    Returns:
        Standardized DataFrame
    """
    from .acquisition import assign_acquisition_and_run_numbers
    
    # Make all values hashable
    df = make_dataframe_hashable(df)
    
    # Ensure acquisition assignment
    if "Acquisition" not in df.columns:
        df = assign_acquisition_and_run_numbers(df)
    
    # Sort by acquisition and reference fields if provided
    sort_columns = ["Acquisition"]
    if reference_fields:
        sort_columns.extend(reference_fields)
    df.sort_values(by=sort_columns, inplace=True)
    
    return df