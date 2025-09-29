"""
Web interface utilities for dicompare.

This module provides functions optimized for web interfaces, including
Pyodide integration, data preparation, and web-friendly formatting.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union, Tuple
import json
import logging
from .serialization import make_json_serializable
from .utils import filter_available_fields, detect_constant_fields
from .generate_schema import detect_acquisition_variability, create_acquisition_summary

logger = logging.getLogger(__name__)

# Global session cache for DataFrame reuse across API calls
_current_session_df = None
_current_session_metadata = None
_current_analysis_result = None

def _cache_session(session_df: pd.DataFrame, metadata: Dict[str, Any], analysis_result: Dict[str, Any]):
    """Cache session data for reuse across API calls."""
    global _current_session_df, _current_session_metadata, _current_analysis_result
    _current_session_df = session_df.copy() if session_df is not None else None
    _current_session_metadata = metadata.copy() if metadata else {}
    _current_analysis_result = analysis_result.copy() if analysis_result else {}

def _get_cached_session() -> Tuple[pd.DataFrame, Dict[str, Any], Dict[str, Any]]:
    """Get cached session data."""
    return _current_session_df, _current_session_metadata, _current_analysis_result

def clear_session_cache():
    """Clear cached session data."""
    global _current_session_df, _current_session_metadata, _current_analysis_result
    _current_session_df = None
    _current_session_metadata = None
    _current_analysis_result = None


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
                    'difference_score': result.get('difference_score', 0),
                    'status': result.get('status')  # Include the status field
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


async def analyze_dicom_files_for_web(
    dicom_files: Dict[str, bytes], 
    reference_fields: List[str] = None,
    progress_callback: Optional[callable] = None
) -> Dict[str, Any]:
    """
    Complete DICOM analysis pipeline optimized for web interface.
    
    This function replaces the 155-line analyzeDicomFiles() function in pyodideService.ts
    by providing a single, comprehensive call that handles all DICOM processing.
    
    Args:
        dicom_files: Dictionary mapping filenames to DICOM file bytes
        reference_fields: List of DICOM fields to analyze (uses DEFAULT_DICOM_FIELDS if None)
        progress_callback: Optional callback for progress updates
        
    Returns:
        Dict containing:
        {
            'acquisitions': {
                'acquisition_name': {
                    'fields': [...],
                    'series': [...],
                    'metadata': {...}
                }
            },
            'total_files': int,
            'field_summary': {...},
            'status': 'success'|'error',
            'message': str
        }
        
    Examples:
        >>> files = {'file1.dcm': b'...', 'file2.dcm': b'...'}
        >>> result = analyze_dicom_files_for_web(files)
        >>> result['total_files']
        2
        >>> result['acquisitions']['T1_MPRAGE']['fields']
        [{'field': 'RepetitionTime', 'value': 2300}, ...]
    """
    print("🚀 ANALYZE_DICOM_FILES_FOR_WEB CALLED - NEW VERSION!")
    try:
        from .io import async_load_dicom_session
        from .acquisition import assign_acquisition_and_run_numbers
        from .generate_schema import create_json_schema
        from .config import DEFAULT_DICOM_FIELDS
        import asyncio
        
        # Handle Pyodide JSProxy objects - convert to Python native types
        # This fixes the PyodideTask error when JS objects are passed from the browser
        if hasattr(dicom_files, 'to_py'):
            print(f"Converting dicom_files from JSProxy to Python dict")
            dicom_files = dicom_files.to_py()
            print(f"Converted dicom_files: type={type(dicom_files)}, keys={list(dicom_files.keys()) if isinstance(dicom_files, dict) else 'not dict'}")
        
        if hasattr(reference_fields, 'to_py'):
            print(f"Converting reference_fields from JSProxy to Python list")
            try:
                reference_fields = list(reference_fields.to_py())
                print(f"Converted reference_fields: type={type(reference_fields)}, length={len(reference_fields)}")
            except Exception as e:
                print(f"Failed to convert reference_fields, using defaults: {e}")
                reference_fields = None
        
        # Use default fields if none provided or empty list
        if reference_fields is None or len(reference_fields) == 0:
            print("Using DEFAULT_DICOM_FIELDS because reference_fields is empty")
            reference_fields = DEFAULT_DICOM_FIELDS
        
        print(f"Using reference_fields: {len(reference_fields)} fields")
        
        print(f"About to call async_load_dicom_session with dicom_files type: {type(dicom_files)}")
        print(f"dicom_files has {len(dicom_files)} files" if hasattr(dicom_files, '__len__') else f"dicom_files length unknown")
        
        # Load DICOM session
        # In Pyodide, we need to handle async functions properly to avoid PyodideTask
        if asyncio.iscoroutinefunction(async_load_dicom_session):
            # Use await directly in Pyodide environment
            print(f"Calling async_load_dicom_session with await... progress_callback={progress_callback}")
            
            # Use the passed progress_callback parameter instead of global
            js_progress_callback = progress_callback
            print(f"Parameter progress_callback = {js_progress_callback}")
            
            # Create a wrapper for the progress callback to convert from integer to object format
            wrapped_progress_callback = None
            if js_progress_callback:
                print("Testing progress callback...")
                # Test with object format that JavaScript expects
                js_progress_callback({'percentage': 5, 'currentOperation': 'Test', 'totalFiles': 100, 'totalProcessed': 5})
                print("Progress callback test successful!")
                
                # Create wrapper function with debug logging 
                def wrapped_progress_callback(percentage_int):
                    print(f"🔄 Progress callback called with percentage: {percentage_int}")
                    progress_obj = {
                        'percentage': percentage_int,
                        'currentOperation': 'Processing DICOM files...',
                        'totalFiles': len(dicom_files),
                        'totalProcessed': int((percentage_int / 100) * len(dicom_files))
                    }
                    print(f"🔄 Calling JavaScript with: {progress_obj}")
                    js_progress_callback(progress_obj)
                
                # Pass the wrapped callback directly, no globals needed
                print(f"Using wrapped_progress_callback: {wrapped_progress_callback}")
            
            session_df = await async_load_dicom_session(
                dicom_bytes=dicom_files,
                progress_function=wrapped_progress_callback
            )
        else:
            # Handle sync function
            print("Calling async_load_dicom_session synchronously...")
            # Use the passed progress_callback parameter for sync path too
            js_progress_callback_sync = progress_callback
            print(f"Sync Parameter progress_callback = {js_progress_callback_sync}")
            wrapped_progress_callback_sync = None
            if js_progress_callback_sync:
                def wrapped_progress_callback_sync(percentage_int):
                    print(f"🔄 Progress callback called with percentage: {percentage_int}")
                    progress_obj = {
                        'percentage': percentage_int,
                        'currentOperation': 'Processing DICOM files...',
                        'totalFiles': len(dicom_files),
                        'totalProcessed': int((percentage_int / 100) * len(dicom_files))
                    }
                    print(f"🔄 Calling JavaScript with: {progress_obj}")
                    js_progress_callback_sync(progress_obj)
                print(f"Using wrapped_progress_callback_sync: {wrapped_progress_callback_sync}")
            
            session_df = async_load_dicom_session(
                dicom_bytes=dicom_files,
                progress_function=wrapped_progress_callback_sync
            )
        
        print(f"async_load_dicom_session returned: type={type(session_df)}, shape={getattr(session_df, 'shape', 'no shape')}")
        
        # Assign acquisitions and run numbers
        session_df = assign_acquisition_and_run_numbers(session_df)
        
        # Filter reference fields to only include fields that exist in the session
        available_fields = [field for field in reference_fields if field in session_df.columns]
        missing_fields = [field for field in reference_fields if field not in session_df.columns]
        
        if missing_fields:
            print(f"Warning: Missing fields from DICOM data: {missing_fields}")
        
        print(f"Using {len(available_fields)} available fields out of {len(reference_fields)} requested")
        print(f"Available fields: {available_fields}")
        
        # Create schema from session with only available fields
        schema_result = create_json_schema(session_df, available_fields)
        
        # Format for web
        web_result = {
            'acquisitions': schema_result.get('acquisitions', {}),
            'total_files': len(dicom_files),
            'field_summary': {
                'total_fields': len(reference_fields),
                'acquisitions_found': len(schema_result.get('acquisitions', {})),
                'session_columns': list(session_df.columns) if session_df is not None else []
            },
            'status': 'success',
            'message': f'Successfully analyzed {len(dicom_files)} DICOM files'
        }
        
        return make_json_serializable(web_result)
        
    except Exception as e:
        import traceback
        print(f"Full traceback of error in analyze_dicom_files_for_web:")
        traceback.print_exc()
        logger.error(f"Error in analyze_dicom_files_for_web: {e}")
        return {
            'acquisitions': {},
            'total_files': len(dicom_files) if dicom_files else 0,
            'field_summary': {},
            'status': 'error',
            'message': f'Error analyzing DICOM files: {str(e)}'
        }


def load_schema_for_web(
    schema_data: Union[Dict, str], 
    instance_id: str,
    acquisition_filter: str = None
) -> Dict[str, Any]:
    """
    Load and validate schema with web-friendly response format.
    
    This function replaces the 60-line loadSchema() functions in pyodideService.ts
    by providing comprehensive schema loading with validation and error handling.
    
    Args:
        schema_data: Schema dictionary or file path to schema
        instance_id: Unique identifier for this schema instance
        acquisition_filter: Optional filter to include only specific acquisitions
        
    Returns:
        Dict containing:
        {
            'schema_id': str,
            'acquisitions': {
                'acquisition_name': {
                    'fields': [...],
                    'series': [...],
                    'rules': [...]  # For Python schemas
                }
            },
            'schema_type': 'json'|'python',
            'validation_status': 'valid'|'invalid',
            'errors': [...],
            'metadata': {...}
        }
        
    Examples:
        >>> schema = {'acquisitions': {'T1': {'fields': [...]}}}
        >>> result = load_schema_for_web(schema, 'schema_001')
        >>> result['schema_id']
        'schema_001'
        >>> result['validation_status']
        'valid'
    """
    try:
        from .io import load_json_schema, load_python_schema
        import os
        
        # Initialize result structure
        result = {
            'schema_id': instance_id,
            'acquisitions': {},
            'schema_type': 'json',
            'validation_status': 'valid',
            'errors': [],
            'metadata': {
                'total_acquisitions': 0,
                'acquisition_names': [],
                'schema_source': 'dict' if isinstance(schema_data, dict) else 'file'
            }
        }
        
        # Load schema based on type
        if isinstance(schema_data, str):
            # File path provided
            if not os.path.exists(schema_data):
                raise FileNotFoundError(f"Schema file not found: {schema_data}")
            
            if schema_data.endswith('.py'):
                # Python schema
                schema_dict = load_python_schema(schema_data)
                result['schema_type'] = 'python'
            else:
                # JSON schema
                schema_dict = load_json_schema(schema_data)
                result['schema_type'] = 'json'
        else:
            # Dictionary provided
            schema_dict = schema_data
            
            # Detect schema type
            if schema_dict.get('type') == 'python':
                result['schema_type'] = 'python'
        
        # Validate schema structure
        if not isinstance(schema_dict, dict):
            raise ValueError("Schema must be a dictionary")
        
        if 'acquisitions' not in schema_dict:
            raise ValueError("Schema must contain 'acquisitions' key")
        
        acquisitions = schema_dict['acquisitions']
        if not isinstance(acquisitions, dict):
            raise ValueError("Schema 'acquisitions' must be a dictionary")
        
        # Filter acquisitions if requested
        if acquisition_filter:
            if acquisition_filter in acquisitions:
                acquisitions = {acquisition_filter: acquisitions[acquisition_filter]}
            else:
                result['errors'].append(f"Acquisition '{acquisition_filter}' not found in schema")
                acquisitions = {}
        
        # Process acquisitions
        processed_acquisitions = {}
        for acq_name, acq_data in acquisitions.items():
            if not isinstance(acq_data, dict):
                result['errors'].append(f"Acquisition '{acq_name}' data must be a dictionary")
                continue
            
            processed_acq = {
                'name': acq_name,
                'fields': acq_data.get('fields', []),
                'series': acq_data.get('series', []),
                'rules': acq_data.get('rules', [])  # For Python schemas
            }
            
            # Add metadata
            processed_acq['metadata'] = {
                'field_count': len(processed_acq['fields']),
                'series_count': len(processed_acq['series']),
                'rule_count': len(processed_acq['rules'])
            }
            
            processed_acquisitions[acq_name] = processed_acq
        
        result['acquisitions'] = processed_acquisitions
        result['metadata'].update({
            'total_acquisitions': len(processed_acquisitions),
            'acquisition_names': list(processed_acquisitions.keys())
        })
        
        # Set validation status
        if result['errors']:
            result['validation_status'] = 'invalid'
        
        return make_json_serializable(result)
        
    except Exception as e:
        logger.error(f"Error in load_schema_for_web: {e}")
        return {
            'schema_id': instance_id,
            'acquisitions': {},
            'schema_type': 'unknown',
            'validation_status': 'invalid',
            'errors': [str(e)],
            'metadata': {
                'total_acquisitions': 0,
                'acquisition_names': [],
                'schema_source': 'unknown'
            }
        }




# New API Wrapper Functions for React Interface

def analyze_dicom_files(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze DICOM files to detect acquisitions and extract field metadata.
    Matches the exact API specification from dicompare_api.md.
    
    Args:
        files: List of file objects with structure:
               [{"name": "file1.dcm", "content": bytes}, ...]
    
    Returns:
        AnalysisResult containing acquisitions and summary statistics
    """
    try:
        # Convert files list to dict format expected by analyze_dicom_files_for_web
        dicom_files = {}
        for file_obj in files:
            if isinstance(file_obj, dict) and 'name' in file_obj and 'content' in file_obj:
                dicom_files[file_obj['name']] = file_obj['content']
            else:
                return {
                    "error": "Invalid file format. Expected dict with 'name' and 'content' keys.",
                    "error_type": "DicomError",
                    "details": {"context": "analyze_dicom_files", "file_obj": str(type(file_obj))}
                }
        
        # Use existing analyze_dicom_files_for_web logic
        import asyncio
        
        # Create event loop if needed
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Run the async function
        result = loop.run_until_complete(analyze_dicom_files_for_web(dicom_files, None))
        
        if result.get('status') == 'error':
            return {
                "error": result.get('message', 'Unknown error'),
                "error_type": "DicomError",
                "details": {"context": "analyze_dicom_files"}
            }
        
        # Get the session DataFrame that should be cached by analyze_dicom_files_for_web
        # We need to extract it from the processing
        from .io import async_load_dicom_session
        from .acquisition import assign_acquisition_and_run_numbers
        
        # Reload to get DataFrame (this is efficient since files are already processed)
        session_df = loop.run_until_complete(async_load_dicom_session(dicom_files))
        session_df = assign_acquisition_and_run_numbers(session_df)
        
        # Convert to exact AnalysisResult format
        analysis_result = _format_as_analysis_result(result, session_df)
        
        # Cache for later API calls
        _cache_session(session_df, {}, analysis_result)
        
        return analysis_result
        
    except Exception as e:
        return {
            "error": str(e),
            "error_type": "DicomError",
            "details": {"context": "analyze_dicom_files"}
        }


def _format_as_analysis_result(web_result: Dict[str, Any], session_df: pd.DataFrame) -> Dict[str, Any]:
    """Convert web_utils result to exact AnalysisResult format."""
    acquisitions = []
    
    # Extract acquisitions from web result
    web_acquisitions = web_result.get('acquisitions', {})
    
    for acq_name, acq_data in web_acquisitions.items():
        # Extract acquisition data from DataFrame
        acq_df = session_df[session_df['Acquisition'] == acq_name] if 'Acquisition' in session_df.columns else session_df
        
        acquisition = {
            "id": acq_name,
            "protocol_name": acq_data.get('protocol_name', ''),
            "series_description": acq_data.get('series_description', ''),
            "total_files": len(acq_df),
            "acquisition_fields": _extract_field_info(acq_df, level='acquisition'),
            "series_fields": _extract_field_info(acq_df, level='series'),
            "series": _extract_series_info(acq_df),
            "metadata": acq_data.get('metadata', {
                "suggested_for_validation": True,
                "confidence": "high" if len(acq_df) > 10 else "medium"
            })
        }
        acquisitions.append(acquisition)
    
    # Create summary
    summary = {
        "total_files": len(session_df),
        "total_acquisitions": len(acquisitions),
        "common_fields": _detect_common_fields(session_df),
        "suggested_validation_fields": _suggest_validation_fields(session_df)
    }
    
    return {
        "acquisitions": acquisitions,
        "summary": summary
    }


def _extract_field_info(acq_df: pd.DataFrame, level: str = 'acquisition') -> List[Dict[str, Any]]:
    """Extract FieldInfo objects from acquisition DataFrame."""
    from dicompare.tags import get_tag_info, determine_field_type_from_values
    
    fields = []
    
    for col in acq_df.columns:
        if col in ['DicomPath', 'DICOM_Path', 'Acquisition', 'RunNumber']:  # Skip metadata columns
            continue
            
        unique_values = acq_df[col].dropna().unique()
        
        # Get tag info which includes the type
        tag_info = get_tag_info(col)
        
        # Determine type based on actual values
        data_type = determine_field_type_from_values(col, acq_df[col])
        
        field_info = {
            "tag": tag_info["tag"].strip("()") if tag_info["tag"] else None,
            "name": col,
            "vr": _get_vr_for_field(col),
            "level": level,
            "consistency": "constant" if len(unique_values) <= 1 else "varying",
            "data_type": data_type  # Use enhanced type detection
        }
        
        if len(unique_values) == 1:
            field_info["value"] = unique_values[0]
        else:
            field_info["values"] = list(unique_values)
        
        fields.append(field_info)
    
    return fields


def _transform_fields_to_dict(fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Transform array of field objects to dictionary keyed by tag.
    
    Args:
        fields: List of field dictionaries with 'tag' and 'value' keys
        
    Returns:
        Dictionary mapping tag to value
    """
    field_dict = {}
    for field in fields:
        if field.get('tag') and 'value' in field:
            field_dict[field['tag']] = field['value']
        elif field.get('tag') and 'values' in field:
            # Handle multi-valued fields
            field_dict[field['tag']] = field['values']
    return field_dict


def _extract_series_info(acq_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Extract series information from acquisition DataFrame."""
    series_list = []
    
    # Group by series-level identifiers if available
    if 'SeriesInstanceUID' in acq_df.columns:
        for series_uid, series_df in acq_df.groupby('SeriesInstanceUID'):
            # Get field info as array first
            field_array = _extract_field_info(series_df, level='series')
            
            # Transform to dictionary for UI compatibility
            field_dict = _transform_fields_to_dict(field_array)
            
            series_info = {
                "series_instance_uid": series_uid,
                "series_number": series_df['SeriesNumber'].iloc[0] if 'SeriesNumber' in series_df.columns else None,
                "file_count": len(series_df),
                "fields": field_dict,  # Now a dictionary keyed by tag
                "field_metadata": field_array  # Keep original array for metadata if needed
            }
            series_list.append(series_info)
    else:
        # Similar transformation for single series case
        field_array = _extract_field_info(acq_df, level='series')
        field_dict = _transform_fields_to_dict(field_array)
        
        series_info = {
            "series_instance_uid": "unknown",
            "series_number": 1,
            "file_count": len(acq_df),
            "fields": field_dict,
            "field_metadata": field_array
        }
        series_list.append(series_info)
    
    return series_list


def _detect_common_fields(session_df: pd.DataFrame) -> List[str]:
    """Detect fields present across all acquisitions."""
    common_fields = []
    
    if 'Acquisition' not in session_df.columns:
        return list(session_df.columns)[:10]  # Return first 10 columns if no acquisitions
    
    for col in session_df.columns:
        if col not in ['DicomPath', 'DICOM_Path', 'Acquisition', 'RunNumber']:
            # Check if field has values in all acquisitions
            non_null_by_acq = session_df.groupby('Acquisition')[col].apply(lambda x: x.notna().any())
            if non_null_by_acq.all():
                common_fields.append(col)
    
    return common_fields


def _suggest_validation_fields(session_df: pd.DataFrame) -> List[str]:
    """Suggest fields suitable for validation."""
    try:
        from .utils import filter_available_fields
        from .config import DEFAULT_DICOM_FIELDS
        
        available_fields = filter_available_fields(session_df, DEFAULT_DICOM_FIELDS)
        return available_fields[:10]  # Limit suggestions
    except ImportError:
        # Fallback to common fields if config is not available
        return _detect_common_fields(session_df)[:10]


def _get_dicom_tag_for_field(field_name: str) -> str:
    """Get DICOM tag for field name using the tags module."""
    from dicompare.tags import get_tag_info
    
    info = get_tag_info(field_name)
    if info["tag"]:
        # Convert from (XXXX,XXXX) to XXXX,XXXX format
        return info["tag"].strip("()")
    
    # Return None for fields without tags
    return None


def _get_vr_for_field(field_name: str) -> str:
    """Get VR (Value Representation) for field name."""
    from dicompare.tags import get_tag_info
    from pydicom.datadict import dictionary_VR, tag_for_keyword
    
    info = get_tag_info(field_name)
    if info["tag"]:
        try:
            # Convert tag string to tuple
            tag_str = info["tag"].strip("()")
            tag_parts = tag_str.split(",")
            tag_tuple = (int(tag_parts[0], 16), int(tag_parts[1], 16))
            
            if tag_tuple in dictionary_VR:
                return dictionary_VR[tag_tuple]
        except:
            pass
    
    # Default to LO (Long String) as safe fallback
    return 'LO'


def _infer_data_type(value: Any) -> str:
    """Infer data type from a single value."""
    if pd.isna(value):
        return "string"
    elif isinstance(value, (int, float, np.number)):
        return "number"
    elif isinstance(value, bool):
        return "boolean"
    else:
        return "string"


def _infer_data_type_from_list(values: List[Any]) -> str:
    """Infer data type from a list of values."""
    if not values:
        return "string"
    
    # Check if all values are numeric
    numeric_count = sum(1 for v in values if isinstance(v, (int, float, np.number)) and not pd.isna(v))
    
    if numeric_count == len(values):
        return "number"
    elif numeric_count > 0:
        return "mixed"
    else:
        return "string"


def validate_compliance(
    dicom_data: Optional[Dict[str, Any]] = None,
    schema_content: str = "",
    format: str = "json"
) -> Dict[str, Any]:
    """
    Validate DICOM data compliance against schema rules.
    Uses cached DataFrame for efficiency.
    
    Args:
        dicom_data: AnalysisResult from analyze_dicom_files (optional if using cache)
        schema_content: Schema content as string
        format: Schema format ("json" or "python")
    
    Returns:
        Dict with compliance_report or error message
    """
    try:
        # Get cached session data
        session_df, metadata, analysis_result = _get_cached_session()
        
        if session_df is None and dicom_data is None:
            return {
                "error": "No DICOM data available. Call analyze_dicom_files first or provide dicom_data.",
                "error_type": "ValidationError"
            }
        
        # Use cached DataFrame or extract from dicom_data
        if session_df is not None:
            df_to_use = session_df
        else:
            # TODO: Extract DataFrame from dicom_data if needed
            df_to_use = _extract_dataframe_from_analysis_result(dicom_data)
        
        # Parse schema
        if format == "json":
            try:
                from .io import load_json_schema
                if isinstance(schema_content, str):
                    import json
                    schema = json.loads(schema_content)
                else:
                    schema = schema_content
            except Exception as e:
                return {
                    "error": f"Failed to parse JSON schema: {str(e)}",
                    "error_type": "SchemaParseError"
                }
        else:
            return {
                "error": f"Unsupported schema format: {format}",
                "error_type": "SchemaParseError"
            }
        
        # Create session mapping (acquisition names mapping)
        session_map = _create_session_mapping(df_to_use, schema)
        
        # Run compliance check
        try:
            from .compliance import check_session_compliance_with_json_schema
            raw_results = check_session_compliance_with_json_schema(df_to_use, schema, session_map)
            
            # Format for web
            formatted_results = format_compliance_results_for_web(raw_results)
            
            return {"compliance_report": formatted_results}
        except ImportError:
            return {
                "error": "Compliance module not available",
                "error_type": "ValidationError"
            }
        
    except Exception as e:
        return {
            "error": str(e),
            "error_type": "ValidationError",
            "details": {"schema_format": format}
        }


def _create_session_mapping(session_df: pd.DataFrame, schema: Dict[str, Any]) -> Dict[str, str]:
    """Create mapping between schema acquisitions and session acquisitions."""
    # Simple mapping - match by name similarity or use acquisition names as-is
    acquisitions_in_session = session_df['Acquisition'].unique() if 'Acquisition' in session_df.columns else []
    schema_acquisitions = list(schema.get('acquisitions', {}).keys())
    
    # For now, use exact matching or create 1:1 mapping
    mapping = {}
    for schema_acq in schema_acquisitions:
        if schema_acq in acquisitions_in_session:
            mapping[schema_acq] = schema_acq
        elif len(acquisitions_in_session) > 0:
            # Default to first available acquisition
            mapping[schema_acq] = acquisitions_in_session[0]
    
    return mapping


def _extract_dataframe_from_analysis_result(dicom_data: Dict[str, Any]) -> pd.DataFrame:
    """Extract DataFrame from AnalysisResult (placeholder implementation)."""
    # This would need to reconstruct the DataFrame from the analysis result
    # For now, return empty DataFrame
    return pd.DataFrame()


def generate_validation_template(
    acquisitions: List[Dict[str, Any]],
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate a validation template from acquisition configurations.
    
    Args:
        acquisitions: List of acquisition configurations with validation rules
        metadata: Template metadata (name, version, authors, etc.)
    
    Returns:
        ValidationTemplate with generated rules and statistics
    """
    try:
        # Get cached session data
        session_df, _, _ = _get_cached_session()
        
        if session_df is None:
            return {
                "error": "No session data available. Call analyze_dicom_files first.",
                "error_type": "ValidationError"
            }
        
        # Extract reference fields from acquisition configurations
        reference_fields = []
        for acq in acquisitions:
            acq_fields = acq.get('acquisition_fields', [])
            for field in acq_fields:
                if field.get('tag') and field['tag'] not in [f.get('tag') for f in reference_fields]:
                    reference_fields.append(field)
        
        # Convert to field names for schema generation
        field_names = []
        for field in reference_fields:
            if field.get('name'):
                field_names.append(field['name'])
        
        # Generate schema using existing function
        try:
            from .generate_schema import create_json_schema
            template_data = create_json_schema(session_df, field_names)
        except ImportError:
            # Fallback if generate_schema is not available
            template_data = {
                "acquisitions": {
                    acq['id']: {
                        "fields": acq.get('acquisition_fields', [])
                    } for acq in acquisitions
                }
            }
        
        # Add metadata
        template = {
            "version": metadata.get("version", "1.0"),
            "name": metadata.get("name", "Generated Template"),
            "description": metadata.get("description", "Auto-generated validation template"),
            "created": pd.Timestamp.now().isoformat(),
            "acquisitions": template_data.get("acquisitions", {}),
            "global_constraints": {}
        }
        
        # Calculate statistics
        total_acquisitions = len(template["acquisitions"])
        total_fields = sum(len(acq.get("fields", [])) for acq in template["acquisitions"].values())
        
        statistics = {
            "total_acquisitions": total_acquisitions,
            "total_validation_fields": total_fields,
            "estimated_validation_time": f"{total_fields * 0.1:.1f} seconds"
        }
        
        return {
            "template": template,
            "statistics": statistics
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "error_type": "ValidationError"
        }


def parse_schema(schema_content: str, format: str = "json") -> Dict[str, Any]:
    """
    Parse schema content and extract detailed validation rules.
    
    Args:
        schema_content: Raw schema content as string
        format: Schema format ("json" or "python")
    
    Returns:
        Dict with parsed_schema or error message
    """
    try:
        if format == "json":
            try:
                import json
                parsed = json.loads(schema_content)
                
                # Validate basic schema structure
                if not isinstance(parsed, dict):
                    return {
                        "error": "Schema must be a JSON object",
                        "error_type": "SchemaParseError"
                    }
                
                if 'acquisitions' not in parsed:
                    return {
                        "error": "Schema must contain 'acquisitions' key",
                        "error_type": "SchemaParseError"
                    }
                
                return {"parsed_schema": parsed}
                
            except json.JSONDecodeError as e:
                return {
                    "error": f"Invalid JSON: {str(e)}",
                    "error_type": "SchemaParseError"
                }
            
        elif format == "python":
            return {
                "error": "Python schema format not yet implemented",
                "error_type": "SchemaParseError"
            }
        else:
            return {
                "error": f"Unsupported schema format: {format}",
                "error_type": "SchemaParseError"
            }
            
    except Exception as e:
        return {
            "error": f"Schema parsing failed: {str(e)}",
            "error_type": "SchemaParseError",
            "details": {"format": format}
        }


def get_field_info(tag: str) -> Dict[str, Any]:
    """
    Get comprehensive field information from DICOM dictionary.
    
    Args:
        tag: DICOM tag in format "0008,0060" or "00080060"
    
    Returns:
        FieldDictionary with complete field information
    """
    try:
        import pydicom
        from pydicom.datadict import dictionary_VR, keyword_dict, dictionary_description
        
        # Normalize tag format
        clean_tag = tag.replace(",", "").replace("(", "").replace(")", "").replace(" ", "")
        if len(clean_tag) == 8:
            try:
                tag_int = int(clean_tag, 16)
            except ValueError:
                return {
                    "error": f"Invalid hexadecimal tag format: {tag}",
                    "error_type": "TagNotFoundError"
                }
        else:
            return {
                "error": f"Invalid tag format: {tag}. Expected 8 hex digits.",
                "error_type": "TagNotFoundError"
            }
        
        # Get field information from pydicom
        vr = dictionary_VR.get(tag_int, "UN")
        keyword = None
        description = dictionary_description.get(tag_int, "Unknown field")
        
        # Find keyword by reverse lookup
        for kw, t in keyword_dict.items():
            if t == tag_int:
                keyword = kw
                break
        
        if keyword is None:
            return {
                "error": f"DICOM tag not found: {tag}",
                "error_type": "TagNotFoundError"
            }
        
        # Format response
        tag_formatted = f"{tag_int:08X}"
        tag_display = f"{tag_formatted[:4]},{tag_formatted[4:]}"
        
        field_info = {
            "tag": tag_display,
            "name": keyword.replace("_", " ").title(),
            "keyword": keyword,
            "vr": vr,
            "vm": "1",  # Default, could be enhanced
            "description": description,
            "suggested_data_type": _map_vr_to_data_type(vr),
            "suggested_validation": _suggest_validation_for_vr(vr),
            "common_values": [],  # Could be populated from analysis
            "validation_hints": _get_validation_hints_for_vr(vr)
        }
        
        return field_info
        
    except ImportError:
        return {
            "error": "pydicom not available for field lookup",
            "error_type": "TagNotFoundError"
        }
    except Exception as e:
        return {
            "error": f"Field lookup failed: {str(e)}",
            "error_type": "TagNotFoundError"
        }


def search_fields(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search DICOM fields by name, tag, or keyword.
    
    Args:
        query: Search term (partial names, tags, or keywords)
        limit: Maximum number of results to return
    
    Returns:
        List of matching FieldDictionary entries, ranked by relevance
    """
    try:
        import pydicom
        from pydicom.datadict import keyword_dict, dictionary_description
        
        results = []
        query_lower = query.lower()
        
        # Search through keyword dictionary
        for keyword, tag_int in keyword_dict.items():
            # Check if query matches keyword or description
            keyword_lower = keyword.lower()
            description = dictionary_description.get(tag_int, "").lower()
            tag_str = f"{tag_int:08X}"
            tag_display = f"{tag_str[:4]},{tag_str[4:]}"
            
            if (query_lower in keyword_lower or 
                query_lower in description or
                query.replace(",", "").replace("(", "").replace(")", "").upper() in tag_str):
                
                field_info = get_field_info(tag_display)
                if "error" not in field_info:
                    # Add relevance score
                    relevance = 0
                    if query_lower == keyword_lower:
                        relevance = 100  # Exact match
                    elif keyword_lower.startswith(query_lower):
                        relevance = 90   # Starts with query
                    elif query_lower in keyword_lower:
                        relevance = 70   # Contains query in keyword
                    elif query_lower in description:
                        relevance = 60   # Contains query in description
                    else:
                        relevance = 50   # Tag match
                    
                    field_info["relevance"] = relevance
                    results.append(field_info)
        
        # Sort by relevance and limit
        results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        return results[:limit]
        
    except ImportError:
        return [{
            "error": "pydicom not available for field search",
            "error_type": "SearchError"
        }]
    except Exception as e:
        return [{
            "error": f"Field search failed: {str(e)}",
            "error_type": "SearchError"
        }]


def _map_vr_to_data_type(vr: str) -> str:
    """Map DICOM VR to suggested data type."""
    from dicompare.tags import VR_TO_DATA_TYPE
    return VR_TO_DATA_TYPE.get(vr, "string")


def _suggest_validation_for_vr(vr: str) -> str:
    """Suggest validation approach for VR type."""
    if vr in ["DS", "IS", "FD", "FL", "SS", "US", "SL", "UL"]:
        return "tolerance"
    elif vr in ["CS", "LO", "SH"]:
        return "exact"
    else:
        return "contains"


def _get_validation_hints_for_vr(vr: str) -> Optional[Dict[str, Any]]:
    """Get validation hints for VR type."""
    hints = {}
    if vr in ["DS", "IS", "FD", "FL"]:
        hints["tolerance_typical"] = 0.001
    elif vr in ["SS", "US", "SL", "UL"]:
        hints["tolerance_typical"] = 1
    return hints if hints else None


def get_example_dicom_data() -> Dict[str, Any]:
    """
    Get example DICOM data (same structure as analyze_dicom_files).
    
    Returns:
        AnalysisResult with realistic example data
    """
    # Create example AnalysisResult structure
    example_data = {
        "acquisitions": [
            {
                "id": "T1_MPRAGE",
                "protocol_name": "T1 MPRAGE",
                "series_description": "T1 weighted MPRAGE", 
                "total_files": 176,
                "acquisition_fields": [
                    {
                        "tag": "0008,0060",
                        "name": "Modality",
                        "value": "MR",
                        "vr": "CS",
                        "level": "acquisition",
                        "data_type": "string",
                        "consistency": "constant"
                    },
                    {
                        "tag": "0018,0080",
                        "name": "Repetition Time",
                        "value": 2300.0,
                        "vr": "DS", 
                        "level": "acquisition",
                        "data_type": "number",
                        "consistency": "constant"
                    },
                    {
                        "tag": "0018,0081",
                        "name": "Echo Time",
                        "value": 2.98,
                        "vr": "DS",
                        "level": "acquisition", 
                        "data_type": "number",
                        "consistency": "constant"
                    },
                    {
                        "tag": "0018,1314",
                        "name": "Flip Angle",
                        "value": 9.0,
                        "vr": "DS",
                        "level": "acquisition",
                        "data_type": "number", 
                        "consistency": "constant"
                    }
                ],
                "series_fields": [
                    {
                        "tag": "0020,0011",
                        "name": "Series Number",
                        "value": 3,
                        "vr": "IS",
                        "level": "series",
                        "data_type": "number",
                        "consistency": "constant"
                    }
                ],
                "series": [
                    {
                        "series_instance_uid": "1.2.3.4.5.6.7.8.9.10",
                        "series_number": 3,
                        "file_count": 176,
                        "fields": [
                            {
                                "tag": "0020,0013",
                                "name": "Instance Number", 
                                "values": list(range(1, 177)),
                                "vr": "IS",
                                "level": "series",
                                "data_type": "number",
                                "consistency": "varying"
                            }
                        ]
                    }
                ],
                "metadata": {
                    "suggested_for_validation": True,
                    "confidence": "high"
                }
            },
            {
                "id": "T2_FLAIR", 
                "protocol_name": "T2 FLAIR",
                "series_description": "T2 FLAIR axial",
                "total_files": 25,
                "acquisition_fields": [
                    {
                        "tag": "0008,0060",
                        "name": "Modality",
                        "value": "MR",
                        "vr": "CS",
                        "level": "acquisition",
                        "data_type": "string",
                        "consistency": "constant"
                    },
                    {
                        "tag": "0018,0080", 
                        "name": "Repetition Time",
                        "value": 11000.0,
                        "vr": "DS",
                        "level": "acquisition",
                        "data_type": "number",
                        "consistency": "constant"
                    },
                    {
                        "tag": "0018,0081",
                        "name": "Echo Time", 
                        "value": 125.0,
                        "vr": "DS",
                        "level": "acquisition",
                        "data_type": "number",
                        "consistency": "constant"
                    }
                ],
                "series_fields": [
                    {
                        "tag": "0020,0011",
                        "name": "Series Number",
                        "value": 5,
                        "vr": "IS",
                        "level": "series", 
                        "data_type": "number",
                        "consistency": "constant"
                    }
                ],
                "series": [
                    {
                        "series_instance_uid": "1.2.3.4.5.6.7.8.9.11",
                        "series_number": 5,
                        "file_count": 25,
                        "fields": []
                    }
                ],
                "metadata": {
                    "suggested_for_validation": True,
                    "confidence": "high"
                }
            }
        ],
        "summary": {
            "total_files": 201,
            "total_acquisitions": 2,
            "common_fields": ["Modality", "RepetitionTime", "EchoTime"],
            "suggested_validation_fields": ["Modality", "RepetitionTime", "EchoTime", "FlipAngle"]
        }
    }
    
    return example_data


def get_example_dicom_data_for_ui() -> List[Dict[str, Any]]:
    """
    Get example DICOM data in UI format.
    
    Returns:
        List of UI-formatted acquisition objects
    """
    example_data = get_example_dicom_data()
    return example_data["acquisitions"]


def get_example_validation_schema() -> Dict[str, Any]:
    """
    Get example validation schema for testing.
    
    Returns:
        Example JSON schema with realistic validation rules
    """
    example_schema = {
        "version": "1.0",
        "name": "Example MR Protocol Validation",
        "description": "Example validation schema for MR imaging protocols",
        "acquisitions": {
            "T1_MPRAGE": {
                "fields": [
                    {
                        "field": "Modality",
                        "expected": "MR",
                        "validation": "exact"
                    },
                    {
                        "field": "RepetitionTime", 
                        "expected": 2300.0,
                        "validation": "tolerance",
                        "tolerance": 50.0
                    },
                    {
                        "field": "EchoTime",
                        "expected": 2.98,
                        "validation": "tolerance", 
                        "tolerance": 0.5
                    },
                    {
                        "field": "FlipAngle",
                        "expected": 9.0,
                        "validation": "tolerance",
                        "tolerance": 1.0
                    }
                ]
            },
            "T2_FLAIR": {
                "fields": [
                    {
                        "field": "Modality",
                        "expected": "MR", 
                        "validation": "exact"
                    },
                    {
                        "field": "RepetitionTime",
                        "expected": 11000.0,
                        "validation": "tolerance",
                        "tolerance": 500.0
                    },
                    {
                        "field": "EchoTime",
                        "expected": 125.0,
                        "validation": "tolerance",
                        "tolerance": 5.0
                    }
                ]
            }
        }
    }
    
    return example_schema