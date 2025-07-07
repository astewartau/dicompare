"""
Web interface utilities for dicompare.

This module provides functions optimized for web interfaces, including
Pyodide integration, data preparation, and web-friendly formatting.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union
import json
import logging
from .serialization import make_json_serializable
from .utils import filter_available_fields, detect_constant_fields
from .generate_schema import detect_acquisition_variability, create_acquisition_summary

logger = logging.getLogger(__name__)


def prepare_session_for_web(session_df: pd.DataFrame,
                          max_preview_rows: int = 100) -> Dict[str, Any]:
    """
    Prepare a DICOM session DataFrame for web display.
    
    Args:
        session_df: DataFrame containing DICOM session data
        max_preview_rows: Maximum number of rows to include in preview
        
    Returns:
        Dict containing web-ready session data
        
    Examples:
        >>> web_data = prepare_session_for_web(df)
        >>> web_data['total_files']
        1024
        >>> len(web_data['preview_data'])
        100
    """
    # Basic statistics
    total_files = len(session_df)
    acquisitions = session_df['Acquisition'].unique() if 'Acquisition' in session_df.columns else []
    
    # Create preview data (limited rows)
    preview_df = session_df.head(max_preview_rows).copy()
    
    # Convert to JSON-serializable format
    preview_data = make_json_serializable({
        'columns': list(preview_df.columns),
        'data': preview_df.to_dict('records'),
        'total_rows_shown': len(preview_df),
        'is_truncated': len(preview_df) < total_files
    })
    
    # Acquisition summary
    acquisition_summaries = []
    for acq in acquisitions[:10]:  # Limit to first 10 acquisitions
        try:
            summary = create_acquisition_summary(session_df, acq)
            acquisition_summaries.append(make_json_serializable(summary))
        except Exception as e:
            logger.warning(f"Could not create summary for acquisition {acq}: {e}")
    
    # Overall session characteristics
    session_characteristics = {
        'total_files': total_files,
        'total_acquisitions': len(acquisitions),
        'acquisition_names': list(acquisitions),
        'column_count': len(session_df.columns),
        'columns': list(session_df.columns),
        'has_pixel_data_paths': 'DICOM_Path' in session_df.columns,
    }
    
    return make_json_serializable({
        'session_characteristics': session_characteristics,
        'preview_data': preview_data,
        'acquisition_summaries': acquisition_summaries,
        'status': 'success'
    })


def format_compliance_results_for_web(compliance_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format compliance check results for web display.
    
    Args:
        compliance_results: Raw compliance results from dicompare
        
    Returns:
        Dict containing web-formatted compliance results
        
    Examples:
        >>> formatted = format_compliance_results_for_web(raw_results)
        >>> formatted['summary']['total_acquisitions']
        5
        >>> formatted['summary']['compliant_acquisitions']
        3
    """
    # Extract schema acquisition results
    schema_acquisition = compliance_results.get('schema acquisition', {})
    
    # Calculate summary statistics
    total_acquisitions = len(schema_acquisition)
    compliant_acquisitions = sum(1 for acq_data in schema_acquisition.values() 
                               if acq_data.get('compliant', False))
    
    # Format acquisition details as a dictionary keyed by acquisition name
    acquisition_details = {}
    for acq_name, acq_data in schema_acquisition.items():
        
        # Extract detailed results
        detailed_results = []
        if 'detailed_results' in acq_data:
            for result in acq_data['detailed_results']:
                detailed_result = {
                    'field': result.get('field', ''),
                    'expected': result.get('expected', ''),
                    'actual': result.get('actual', ''),
                    'compliant': result.get('compliant', False),
                    'message': result.get('message', ''),
                    'difference_score': result.get('difference_score', 0)
                }
                # Preserve series information if this is a series-level result
                if 'series' in result:
                    detailed_result['series'] = result['series']
                detailed_results.append(detailed_result)
        
        acquisition_details[acq_name] = {
            'acquisition': acq_name,
            'compliant': acq_data.get('compliant', False),
            'compliance_percentage': acq_data.get('compliance_percentage', 0),
            'total_fields_checked': len(detailed_results),
            'compliant_fields': sum(1 for r in detailed_results if r['compliant']),
            'detailed_results': detailed_results,
            'status_message': acq_data.get('message', 'No message')
        }
    
    return make_json_serializable({
        'summary': {
            'total_acquisitions': total_acquisitions,
            'compliant_acquisitions': compliant_acquisitions,
            'compliance_rate': (compliant_acquisitions / total_acquisitions * 100) if total_acquisitions > 0 else 0,
            'status': 'completed'
        },
        'acquisition_details': acquisition_details,
        'raw_results': compliance_results  # Include for debugging if needed
    })


def create_field_selection_helper(session_df: pd.DataFrame, 
                                acquisition: str,
                                priority_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Create a helper for field selection in web interfaces.
    
    Args:
        session_df: DataFrame containing DICOM session data
        acquisition: Acquisition to analyze for field selection
        priority_fields: Optional list of high-priority fields to highlight
        
    Returns:
        Dict containing field selection recommendations
        
    Examples:
        >>> helper = create_field_selection_helper(df, 'T1_MPRAGE')
        >>> helper['recommended']['constant_fields'][:3]
        ['RepetitionTime', 'FlipAngle', 'SliceThickness']
    """
    if priority_fields is None:
        priority_fields = [
            'RepetitionTime', 'EchoTime', 'FlipAngle', 'SliceThickness',
            'AcquisitionMatrix', 'MagneticFieldStrength', 'PixelBandwidth'
        ]
    
    # Get variability analysis
    try:
        variability = detect_acquisition_variability(session_df, acquisition)
    except ValueError as e:
        return {'error': str(e), 'status': 'failed'}
    
    # Categorize fields
    constant_priority = [f for f in priority_fields if f in variability['constant_fields']]
    variable_priority = [f for f in priority_fields if f in variability['variable_fields']]
    
    # Additional constant fields (not in priority list)
    other_constant = [f for f in variability['constant_fields'] 
                     if f not in priority_fields]
    
    # Additional variable fields
    other_variable = [f for f in variability['variable_fields'] 
                     if f not in priority_fields]
    
    # Create recommendations
    recommended = {
        'constant_fields': constant_priority + other_constant[:5],  # Limit to prevent overwhelming
        'series_grouping_fields': variable_priority + other_variable[:3],
        'priority_constant': constant_priority,
        'priority_variable': variable_priority
    }
    
    # Field metadata for display
    field_metadata = {}
    for field in (constant_priority + variable_priority + other_constant[:5] + other_variable[:3]):
        if field in variability['field_analysis']:
            analysis = variability['field_analysis'][field]
            field_metadata[field] = {
                'is_constant': analysis['is_constant'],
                'unique_count': analysis['unique_count'],
                'null_count': analysis['null_count'],
                'sample_values': analysis['sample_values'],
                'is_priority': field in priority_fields,
                'category': 'constant' if analysis['is_constant'] else 'variable'
            }
    
    return make_json_serializable({
        'acquisition': acquisition,
        'total_files': variability['total_files'],
        'recommended': recommended,
        'field_metadata': field_metadata,
        'status': 'success'
    })


def prepare_schema_generation_data(session_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Prepare data for schema generation in web interfaces.
    
    Args:
        session_df: DataFrame containing DICOM session data
        
    Returns:
        Dict containing data needed for interactive schema generation
        
    Examples:
        >>> schema_data = prepare_schema_generation_data(df)
        >>> len(schema_data['acquisitions'])
        5
        >>> schema_data['suggested_fields'][:3]
        ['RepetitionTime', 'EchoTime', 'FlipAngle']
    """
    acquisitions = session_df['Acquisition'].unique() if 'Acquisition' in session_df.columns else []
    
    # Get field suggestions for each acquisition
    acquisition_analysis = {}
    for acq in acquisitions:
        try:
            helper = create_field_selection_helper(session_df, acq)
            if helper.get('status') == 'success':
                acquisition_analysis[acq] = helper
        except Exception as e:
            logger.warning(f"Could not analyze acquisition {acq}: {e}")
    
    # Find commonly constant fields across acquisitions
    all_constant_fields = set()
    all_variable_fields = set()
    
    for acq_data in acquisition_analysis.values():
        if 'recommended' in acq_data:
            all_constant_fields.update(acq_data['recommended']['constant_fields'])
            all_variable_fields.update(acq_data['recommended']['series_grouping_fields'])
    
    # Global suggestions
    suggested_fields = list(all_constant_fields)[:10]  # Most commonly constant fields
    
    return make_json_serializable({
        'acquisitions': list(acquisitions),
        'acquisition_count': len(acquisitions),
        'total_files': len(session_df),
        'suggested_fields': suggested_fields,
        'acquisition_analysis': acquisition_analysis,
        'available_columns': list(session_df.columns),
        'status': 'ready'
    })


def format_validation_error_for_web(error: Exception) -> Dict[str, Any]:
    """
    Format validation errors for web display.
    
    Args:
        error: Exception that occurred during validation
        
    Returns:
        Dict containing formatted error information
        
    Examples:
        >>> formatted = format_validation_error_for_web(ValueError("Field not found"))
        >>> formatted['error_type']
        'ValueError'
    """
    return make_json_serializable({
        'error_type': type(error).__name__,
        'error_message': str(error),
        'status': 'error',
        'user_message': f"Validation failed: {str(error)}",
        'suggestions': [
            "Check that your DICOM files are properly formatted",
            "Verify that the required fields exist in your data",
            "Try uploading a different set of DICOM files"
        ]
    })


def convert_pyodide_data(data: Any) -> Any:
    """
    Convert Pyodide JSProxy objects to Python data structures.
    
    Args:
        data: Data potentially containing JSProxy objects
        
    Returns:
        Data with JSProxy objects converted to Python equivalents
        
    Examples:
        >>> # In Pyodide context
        >>> js_data = some_javascript_object
        >>> py_data = convert_pyodide_data(js_data)
    """
    if hasattr(data, 'to_py'):
        # It's a JSProxy object
        return convert_pyodide_data(data.to_py())
    elif isinstance(data, dict):
        return {k: convert_pyodide_data(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return [convert_pyodide_data(item) for item in data]
    else:
        return data


def create_download_data(data: Dict[str, Any], 
                        filename: str,
                        file_type: str = 'json') -> Dict[str, Any]:
    """
    Prepare data for download in web interfaces.
    
    Args:
        data: Data to prepare for download
        filename: Suggested filename (without extension)
        file_type: File type ('json', 'csv', etc.)
        
    Returns:
        Dict containing download-ready data
        
    Examples:
        >>> download = create_download_data({'schema': {...}}, 'my_schema')
        >>> download['filename']
        'my_schema.json'
    """
    # Ensure data is JSON serializable
    serializable_data = make_json_serializable(data)
    
    if file_type == 'json':
        content = json.dumps(serializable_data, indent=2)
        mime_type = 'application/json'
        extension = '.json'
    elif file_type == 'csv':
        # For CSV, data should be tabular
        if isinstance(serializable_data, list) and serializable_data:
            df = pd.DataFrame(serializable_data)
            content = df.to_csv(index=False)
        else:
            content = "No tabular data available"
        mime_type = 'text/csv'
        extension = '.csv'
    else:
        # Default to JSON
        content = json.dumps(serializable_data, indent=2)
        mime_type = 'application/json'
        extension = '.json'
    
    return {
        'content': content,
        'filename': f"{filename}{extension}",
        'mime_type': mime_type,
        'size_bytes': len(content.encode('utf-8')),
        'status': 'ready'
    }