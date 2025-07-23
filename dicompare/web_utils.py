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
            reference_fields = reference_fields.to_py()
            print(f"Converted reference_fields: type={type(reference_fields)}, length={len(reference_fields) if hasattr(reference_fields, '__len__') else 'no length'}")
        
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
            print("Calling async_load_dicom_session with await...")
            session_df = await async_load_dicom_session(
                dicom_bytes=dicom_files,
                progress_function=progress_callback
            )
        else:
            # Handle sync function
            print("Calling async_load_dicom_session synchronously...")
            session_df = async_load_dicom_session(
                dicom_bytes=dicom_files,
                progress_function=progress_callback
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


def check_all_compliance_for_web(
    compliance_session,
    schema_mappings: Dict[str, Dict[str, str]]
) -> List[Dict[str, Any]]:
    """
    Run compliance checks for multiple schemas with web formatting.
    
    This function replaces the 270-line analyzeCompliance() function in pyodideService.ts
    by providing a single call that handles all compliance checking logic.
    
    Args:
        compliance_session: ComplianceSession instance with loaded session and schemas
        schema_mappings: Dict mapping schema_id to user_mapping dict
        
    Returns:
        List of compliance results formatted for web:
        [
            {
                'schema_id': str,
                'schema_acquisition': str,
                'input_acquisition': str,
                'field': str,
                'expected': Any,
                'actual': Any,
                'passed': bool,
                'message': str,
                'series': str|None
            }, ...
        ]
        
    Examples:
        >>> mappings = {'schema1': {'T1_MPRAGE': 't1_mprage_sag'}}
        >>> results = check_all_compliance_for_web(session, mappings)
        >>> len(results) > 0
        True
    """
    try:
        # Handle Pyodide JSProxy objects - convert to Python native types
        if hasattr(schema_mappings, 'to_py'):
            schema_mappings = schema_mappings.to_py()
        
        all_results = []
        
        if not hasattr(compliance_session, 'has_session') or not compliance_session.has_session():
            logger.error("No session loaded in ComplianceSession")
            return [{
                'schema_id': 'error',
                'schema_acquisition': 'error',
                'input_acquisition': 'error',
                'field': 'session_check',
                'expected': 'loaded session',
                'actual': 'no session',
                'passed': False,
                'message': 'No session loaded in ComplianceSession',
                'series': None
            }]
        
        # Process each schema mapping
        for schema_id, user_mapping in schema_mappings.items():
            try:
                # Check if schema exists
                if not compliance_session.has_schema(schema_id):
                    all_results.append({
                        'schema_id': schema_id,
                        'schema_acquisition': 'unknown',
                        'input_acquisition': 'unknown',
                        'field': 'schema_validation',
                        'expected': 'valid schema',
                        'actual': 'schema not found',
                        'passed': False,
                        'message': f'Schema "{schema_id}" not found in ComplianceSession',
                        'series': None
                    })
                    continue
                
                # Validate mapping
                validation_result = compliance_session.validate_user_mapping(schema_id, user_mapping)
                if not validation_result.get('valid', False):
                    for error in validation_result.get('errors', []):
                        all_results.append({
                            'schema_id': schema_id,
                            'schema_acquisition': 'unknown',
                            'input_acquisition': 'unknown',
                            'field': 'mapping_validation',
                            'expected': 'valid mapping',
                            'actual': 'invalid mapping',
                            'passed': False,
                            'message': error,
                            'series': None
                        })
                    continue
                
                # Get schema data to determine type
                schema_data = compliance_session.schemas.get(schema_id, {})
                is_python_schema = schema_data.get('type') == 'python'
                
                if is_python_schema:
                    # Use Python schema compliance
                    from .compliance import check_session_compliance_with_python_module
                    
                    python_models = schema_data.get('python_models', {})
                    if not python_models:
                        all_results.append({
                            'schema_id': schema_id,
                            'schema_acquisition': 'error',
                            'input_acquisition': 'error',
                            'field': 'python_schema',
                            'expected': 'python models',
                            'actual': 'no models found',
                            'passed': False,
                            'message': 'Python schema missing python_models',
                            'series': None
                        })
                        continue
                    
                    # Run Python compliance
                    session_df = compliance_session.session_df
                    compliance_summary = check_session_compliance_with_python_module(
                        in_session=session_df,
                        schema_models=python_models,
                        session_map=user_mapping,
                        raise_errors=False
                    )
                    
                    # Convert Python results to standard format
                    for result in compliance_summary:
                        all_results.append({
                            'schema_id': schema_id,
                            'schema_acquisition': result.get('schema acquisition', 'unknown'),
                            'input_acquisition': result.get('input acquisition', 'unknown'),
                            'field': result.get('rule_name', result.get('field', 'unknown')),
                            'expected': result.get('expected', ''),
                            'actual': result.get('value', ''),
                            'passed': result.get('passed', False),
                            'message': result.get('message', ''),
                            'series': result.get('series', None)
                        })
                else:
                    # Use JSON schema compliance
                    compliance_results = compliance_session.check_compliance(schema_id, user_mapping)
                    
                    # Extract results from ComplianceSession format
                    acquisition_details = compliance_results.get('acquisition_details', {})
                    
                    for schema_acq_name, acq_details in acquisition_details.items():
                        input_acq_name = acq_details.get('input_acquisition', schema_acq_name)
                        
                        for field_result in acq_details.get('detailed_results', []):
                            result_item = {
                                'schema_id': schema_id,
                                'schema_acquisition': schema_acq_name,
                                'input_acquisition': input_acq_name,
                                'field': field_result.get('field', ''),
                                'expected': field_result.get('expected', ''),
                                'actual': field_result.get('actual', ''),
                                'passed': field_result.get('compliant', False),
                                'message': field_result.get('message', ''),
                                'series': field_result.get('series', None)
                            }
                            all_results.append(result_item)
                
            except Exception as e:
                logger.error(f"Error checking compliance for schema '{schema_id}': {e}")
                all_results.append({
                    'schema_id': schema_id,
                    'schema_acquisition': 'error',
                    'input_acquisition': 'error',
                    'field': 'compliance_check',
                    'expected': 'successful check',
                    'actual': 'error occurred',
                    'passed': False,
                    'message': f'Error: {str(e)}',
                    'series': None
                })
        
        return make_json_serializable(all_results)
        
    except Exception as e:
        logger.error(f"Error in check_all_compliance_for_web: {e}")
        return [{
            'schema_id': 'error',
            'schema_acquisition': 'error', 
            'input_acquisition': 'error',
            'field': 'function_error',
            'expected': 'successful execution',
            'actual': 'function error',
            'passed': False,
            'message': f'Error in check_all_compliance_for_web: {str(e)}',
            'series': None
        }]