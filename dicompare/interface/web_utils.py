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
from ..io import make_json_serializable

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
        from ..io import async_load_dicom_session
        from ..session import assign_acquisition_and_run_numbers
        from ..schema import build_schema
        from ..config import DEFAULT_DICOM_FIELDS
        import asyncio

        # Handle Pyodide JSProxy objects - convert to Python native types
        # This fixes the PyodideTask error when JS objects are passed from the browser
        if hasattr(dicom_files, 'to_py'):
            print(f"Converting dicom_files from JSProxy to Python dict")
            try:
                dicom_files = dicom_files.to_py()
                print(f"Converted dicom_files: type={type(dicom_files)}, keys={list(dicom_files.keys()) if isinstance(dicom_files, dict) else 'not dict'}")
            except Exception as e:
                print(f"Failed to convert dicom_files with to_py(): {e}")
                # Try batched conversion as fallback - convert in chunks to avoid buffer overflow
                # while still being faster than one-by-one conversion
                print("Attempting batched conversion...")
                try:
                    # Get keys by iterating directly - JSProxy supports iter()
                    js_keys = list(dicom_files)
                    total_files = len(js_keys)
                    print(f"Found {total_files} files to convert in batches")

                    converted_files = {}
                    BATCH_SIZE = 200  # Convert 200 files at a time

                    for batch_start in range(0, total_files, BATCH_SIZE):
                        batch_end = min(batch_start + BATCH_SIZE, total_files)
                        batch_keys = js_keys[batch_start:batch_end]

                        # Convert this batch
                        for key in batch_keys:
                            try:
                                js_content = dicom_files.get(key)
                                if js_content is None:
                                    js_content = getattr(dicom_files, key, None)

                                if js_content is not None:
                                    if hasattr(js_content, 'to_py'):
                                        converted_files[key] = bytes(js_content.to_py())
                                    else:
                                        converted_files[key] = bytes(js_content)
                            except Exception as file_error:
                                print(f"Warning: Failed to convert file {key}: {file_error}")
                                continue

                        # Progress logging per batch
                        print(f"Converted {batch_end}/{total_files} files...")

                    dicom_files = converted_files
                    print(f"Batched conversion complete: {len(dicom_files)} files converted")
                except Exception as incremental_error:
                    print(f"Batched conversion also failed: {incremental_error}")
                    raise RuntimeError(f"Cannot convert DICOM files from JavaScript: {e}")

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

        # Filter reference fields to only include fields that exist in the session
        available_fields = [field for field in reference_fields if field in session_df.columns]
        missing_fields = [field for field in reference_fields if field not in session_df.columns]

        if missing_fields:
            print(f"Warning: Missing fields from DICOM data: {missing_fields}")

        print(f"Using {len(available_fields)} available fields out of {len(reference_fields)} requested")
        print(f"Available fields: {available_fields}")

        # Assign acquisition and run numbers ONCE here, so the same names are used
        # for both the schema result AND the cached DataFrame for validation
        session_df = assign_acquisition_and_run_numbers(session_df)
        print(f"Assigned acquisitions: {session_df['Acquisition'].unique().tolist()}")

        # Cache DataFrame with Acquisition column for reuse across API calls
        metadata = {
            'total_files': len(dicom_files),
            'reference_fields': reference_fields,
            'available_fields': available_fields
        }
        _cache_session(session_df, metadata, None)

        # Create schema from session with only available fields
        # build_schema will use existing Acquisition column instead of re-computing
        schema_result = build_schema(session_df, available_fields)

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