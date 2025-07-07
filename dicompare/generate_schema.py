"""
Schema generation utilities for dicompare.

This module provides functions for generating JSON schemas from DICOM sessions
that can be used for validation purposes.
"""

import pandas as pd
from typing import List, Dict, Any, Tuple
from .data_utils import standardize_session_dataframe
from .utils import clean_string, filter_available_fields, detect_constant_fields


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


def detect_acquisition_variability(session_df: pd.DataFrame, 
                                  acquisition: str, 
                                  fields: List[str] = None) -> Dict[str, Any]:
    """
    Analyze field variability within an acquisition.
    
    Args:
        session_df: DataFrame containing DICOM session data
        acquisition: Acquisition name to analyze
        fields: List of fields to analyze (if None, uses all available fields)
        
    Returns:
        Dict containing analysis of constant vs variable fields
        
    Examples:
        >>> df = pd.DataFrame({
        ...     'Acquisition': ['T1', 'T1', 'T1'],
        ...     'EchoTime': [0.01, 0.01, 0.01],
        ...     'SliceThickness': [1.0, 2.0, 1.5]
        ... })
        >>> detect_acquisition_variability(df, 'T1', ['EchoTime', 'SliceThickness'])
        {
            'acquisition': 'T1',
            'total_files': 3,
            'constant_fields': {'EchoTime': 0.01},
            'variable_fields': ['SliceThickness'],
            'field_analysis': {...}
        }
    """
    # Filter to the specified acquisition
    acq_data = session_df[session_df['Acquisition'] == acquisition]
    
    if acq_data.empty:
        raise ValueError(f"No data found for acquisition: {acquisition}")
    
    # Use all numeric/string columns if fields not specified
    if fields is None:
        # Exclude certain system fields
        exclude_fields = {'Acquisition', 'DICOM_Path', 'index'}
        fields = [col for col in acq_data.columns 
                 if col not in exclude_fields and 
                 acq_data[col].dtype in ['object', 'int64', 'float64']]
    
    # Filter to available fields
    try:
        available_fields = filter_available_fields(acq_data, fields)
    except ValueError:
        available_fields = []
    
    # Analyze constant vs variable fields
    constant_fields, variable_fields = detect_constant_fields(acq_data, available_fields)
    
    # Detailed field analysis
    field_analysis = {}
    for field in available_fields:
        unique_values = acq_data[field].dropna().unique()
        field_analysis[field] = {
            'unique_count': len(unique_values),
            'null_count': acq_data[field].isnull().sum(),
            'is_constant': field in constant_fields,
            'sample_values': unique_values[:5].tolist() if len(unique_values) <= 5 else unique_values[:5].tolist()
        }
    
    return {
        'acquisition': acquisition,
        'total_files': len(acq_data),
        'constant_fields': constant_fields,
        'variable_fields': variable_fields,
        'field_analysis': field_analysis,
        'suggested_series_fields': variable_fields[:3] if variable_fields else []
    }


def create_acquisition_summary(session_df: pd.DataFrame, 
                             acquisition: str, 
                             fields: List[str] = None) -> Dict[str, Any]:
    """
    Create a detailed summary of an acquisition for web interfaces.
    
    Args:
        session_df: DataFrame containing DICOM session data
        acquisition: Acquisition name to summarize
        fields: List of fields to include in summary (if None, uses all available)
        
    Returns:
        Dict containing acquisition summary optimized for web display
        
    Examples:
        >>> summary = create_acquisition_summary(df, 'T1_MPRAGE')
        >>> summary['display_name']
        'T1 MPRAGE'
        >>> summary['file_count']
        176
    """
    # Get variability analysis
    variability = detect_acquisition_variability(session_df, acquisition, fields)
    
    # Filter acquisition data
    acq_data = session_df[session_df['Acquisition'] == acquisition]
    
    # Create display-friendly name
    display_name = acquisition.replace('_', ' ').title()
    
    # Get sample DICOM paths for potential visualization
    sample_paths = acq_data['DICOM_Path'].dropna().head(3).tolist() if 'DICOM_Path' in acq_data.columns else []
    
    # Key acquisition parameters for quick display
    key_params = {}
    priority_fields = ['EchoTime', 'RepetitionTime', 'FlipAngle', 'SliceThickness']
    
    for field in priority_fields:
        if field in variability['constant_fields']:
            key_params[field] = variability['constant_fields'][field]
        elif field in variability['variable_fields']:
            # Show range for variable fields
            values = acq_data[field].dropna()
            if not values.empty:
                key_params[field] = f"{values.min():.3f} - {values.max():.3f}"
    
    # Series grouping suggestion
    series_suggestion = None
    if variability['variable_fields']:
        primary_field = variability['variable_fields'][0]
        unique_values = acq_data[primary_field].dropna().unique()
        series_suggestion = {
            'field': primary_field,
            'series_count': len(unique_values),
            'values': unique_values.tolist()[:10]  # Limit to first 10
        }
    
    return {
        'acquisition': acquisition,
        'display_name': display_name,
        'file_count': len(acq_data),
        'key_parameters': key_params,
        'constant_field_count': len(variability['constant_fields']),
        'variable_field_count': len(variability['variable_fields']),
        'series_suggestion': series_suggestion,
        'sample_dicom_paths': sample_paths,
        'variability_analysis': variability
    }