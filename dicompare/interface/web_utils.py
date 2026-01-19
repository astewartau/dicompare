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

                        # Progress during conversion phase (0-20%)
                        conversion_pct = int((batch_end / total_files) * 20)
                        print(f"Converted {batch_end}/{total_files} files... ({conversion_pct}%)")
                        if progress_callback:
                            progress_callback({
                                'percentage': conversion_pct,
                                'currentOperation': f'Converting files ({batch_end}/{total_files})...',
                                'totalFiles': total_files,
                                'totalProcessed': batch_end
                            })

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

                # Create wrapper function - scale DICOM loading to 20-80% range
                def wrapped_progress_callback(percentage_int):
                    from pyodide.ffi import to_js
                    # Scale from 0-100 to 20-80 range
                    scaled_pct = 20 + int(percentage_int * 0.6)
                    print(f"📊 Progress: {percentage_int}% -> {scaled_pct}%")
                    progress_obj = {
                        'percentage': scaled_pct,
                        'currentOperation': 'Parsing DICOM files...',
                        'totalFiles': len(dicom_files),
                        'totalProcessed': int((percentage_int / 100) * len(dicom_files))
                    }
                    # Convert to JS object so properties are accessible
                    js_progress_callback(to_js(progress_obj))

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
                    from pyodide.ffi import to_js
                    # Scale from 0-100 to 20-80 range
                    scaled_pct = 20 + int(percentage_int * 0.6)
                    progress_obj = {
                        'percentage': scaled_pct,
                        'currentOperation': 'Parsing DICOM files...',
                        'totalFiles': len(dicom_files),
                        'totalProcessed': int((percentage_int / 100) * len(dicom_files))
                    }
                    # Convert to JS object so properties are accessible
                    js_progress_callback_sync(to_js(progress_obj))
                print(f"Using wrapped_progress_callback_sync: {wrapped_progress_callback_sync}")

            session_df = async_load_dicom_session(
                dicom_bytes=dicom_files,
                progress_function=wrapped_progress_callback_sync
            )

        print(f"async_load_dicom_session returned: type={type(session_df)}, shape={getattr(session_df, 'shape', 'no shape')}")

        # Progress: DICOM loading complete (80%)
        if progress_callback:
            from pyodide.ffi import to_js
            print("📊 Sending 80% - Organizing acquisitions...")
            progress_callback(to_js({
                'percentage': 80,
                'currentOperation': 'Organizing acquisitions...',
                'totalFiles': len(dicom_files),
                'totalProcessed': len(dicom_files)
            }))

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

        # Progress: Building schema (85%)
        if progress_callback:
            from pyodide.ffi import to_js
            progress_callback(to_js({
                'percentage': 85,
                'currentOperation': 'Building schema...',
                'totalFiles': len(dicom_files),
                'totalProcessed': len(dicom_files)
            }))

        # Create schema from session with only available fields
        # build_schema will use existing Acquisition column instead of re-computing
        schema_result = build_schema(session_df, available_fields)

        # Progress: Schema complete (95%)
        if progress_callback:
            from pyodide.ffi import to_js
            progress_callback(to_js({
                'percentage': 95,
                'currentOperation': 'Finalizing...',
                'totalFiles': len(dicom_files),
                'totalProcessed': len(dicom_files)
            }))

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


async def analyze_dicom_files_for_ui(
    dicom_files: Dict[str, bytes],
    progress_callback: Optional[callable] = None
) -> List[Dict[str, Any]]:
    """
    Analyze DICOM files and return UI-ready acquisition format.

    This extends analyze_dicom_files_for_web() to return data in a format
    directly usable by the web UI, including:
    - acquisitionFields (with tag, name, keyword, value, vr, dataType, fieldType, level)
    - seriesFields (with values array)
    - series (with fields as array, not object)

    Args:
        dicom_files: Dictionary mapping filenames to DICOM file bytes
        progress_callback: Optional callback for progress updates

    Returns:
        List of UI-ready acquisition dictionaries
    """
    from ..schema import get_tag_info, determine_field_type_from_values
    from pydicom.datadict import dictionary_VR
    import json

    # Call the base analysis function
    result = await analyze_dicom_files_for_web(dicom_files, None, progress_callback)

    if result.get('status') == 'error':
        raise RuntimeError(result.get('message', 'DICOM analysis failed'))

    # Get cached session for additional data
    session_df, metadata, _ = _get_cached_session()

    # Helper to get VR for a field
    def _get_vr_for_field(field_name: str) -> str:
        try:
            tag_info = get_tag_info(field_name)
            if tag_info["tag"]:
                tag_str = tag_info["tag"].strip("()")
                tag_parts = tag_str.split(",")
                tag_tuple = (int(tag_parts[0], 16), int(tag_parts[1], 16))
                return dictionary_VR(tag_tuple) or 'LO'
        except:
            pass
        return 'LO'

    # Convert web result to UI format
    ui_acquisitions = []
    web_acquisitions = result.get('acquisitions', {})

    for acq_name, acq_data in web_acquisitions.items():
        # Get acquisition DataFrame for metadata
        acq_df = session_df[session_df['Acquisition'] == acq_name] if session_df is not None and 'Acquisition' in session_df.columns else None

        # Process acquisition-level fields
        acquisition_fields = []
        for field_data in acq_data.get('fields', []):
            field_name = field_data.get('field')
            field_value = field_data.get('value')
            field_tag = field_data.get('tag')
            field_type = field_data.get('fieldType')

            # Get tag info if not provided
            if field_type is None or field_tag is None:
                tag_info = get_tag_info(field_name)
                if field_type is None:
                    field_type = tag_info.get('fieldType', 'standard')
                if field_tag is None:
                    tag = tag_info.get('tag')
                    field_tag = tag.strip("()") if tag else None

            # Determine data type
            data_type = determine_field_type_from_values(field_name, [field_value] if field_value is not None else [])

            acquisition_fields.append({
                'tag': field_tag,
                'name': field_name,
                'keyword': field_name,
                'value': field_value,
                'vr': _get_vr_for_field(field_name),
                'level': 'acquisition',
                'dataType': data_type,
                'fieldType': field_type,
                'consistency': 'constant',
                'validationRule': {'type': 'exact'}
            })

        # Process series and series fields
        series_fields = []
        series_list = []
        dicompare_series = acq_data.get('series', [])

        if dicompare_series:
            # Collect all series field names and their values
            series_field_values = {}

            for series_data in dicompare_series:
                for field_data in series_data.get('fields', []):
                    field_name = field_data.get('field')
                    field_value = field_data.get('value')
                    field_tag = field_data.get('tag')
                    field_type = field_data.get('fieldType')

                    if field_name not in series_field_values:
                        series_field_values[field_name] = {
                            'values': [],
                            'tag': field_tag,
                            'fieldType': field_type
                        }
                    series_field_values[field_name]['values'].append(field_value)

            # Create series fields
            for field_name, field_info in series_field_values.items():
                field_type = field_info.get('fieldType')
                field_tag = field_info.get('tag')

                if field_type is None or field_tag is None:
                    tag_info = get_tag_info(field_name)
                    if field_type is None:
                        field_type = tag_info.get('fieldType', 'standard')
                    if field_tag is None:
                        tag = tag_info.get('tag')
                        field_tag = tag.strip("()") if tag else None

                data_type = determine_field_type_from_values(field_name, field_info['values'])

                series_fields.append({
                    'tag': field_tag,
                    'name': field_name,
                    'keyword': field_name,
                    'values': field_info['values'],
                    'vr': _get_vr_for_field(field_name),
                    'level': 'series',
                    'dataType': data_type,
                    'fieldType': field_type,
                    'consistency': 'varying',
                    'validationRule': {'type': 'exact'}
                })

            # Create series with fields as array
            for series_data in dicompare_series:
                series_name = series_data.get('name', f'Series {len(series_list) + 1}')
                series_fields_array = []

                for field_data in series_data.get('fields', []):
                    field_name = field_data.get('field')
                    field_value = field_data.get('value')
                    field_tag = field_data.get('tag')
                    field_type = field_data.get('fieldType')

                    if field_type is None:
                        tag_info = get_tag_info(field_name)
                        field_type = tag_info.get('fieldType', 'standard')
                        if field_tag is None:
                            tag = tag_info.get('tag')
                            field_tag = tag.strip("()") if tag else None

                    series_fields_array.append({
                        'name': field_name,
                        'tag': field_tag,
                        'value': field_value,
                        'fieldType': field_type
                    })

                series_list.append({
                    'name': series_name,
                    'fields': series_fields_array
                })

        # Get series description
        series_desc = acq_name
        if acq_df is not None and 'SeriesDescription' in acq_df.columns:
            series_desc_vals = acq_df['SeriesDescription'].dropna()
            if len(series_desc_vals) > 0:
                series_desc = str(series_desc_vals.iloc[0])

        # Generate unique ID
        base_id = str(acq_name).replace(' ', '_').replace('-', '_').replace('/', '_')
        base_id = ''.join(c for c in base_id if c.isalnum() or c == '_')

        existing_ids = [a['id'] for a in ui_acquisitions]
        if base_id in existing_ids:
            counter = 2
            while f"{base_id}_{counter}" in existing_ids:
                counter += 1
            unique_id = f"{base_id}_{counter}"
        else:
            unique_id = base_id

        # Compute sliceCount - number of unique slice locations (actual slices, not files)
        # Priority: NumberOfImagesInMosaic (Siemens mosaic) > unique SliceLocation > file count
        slice_count = 0
        if acq_df is not None:
            if 'NumberOfImagesInMosaic' in acq_df.columns and acq_df['NumberOfImagesInMosaic'].notna().any():
                # Siemens mosaic: slices packed into single 2D image
                slice_count = int(acq_df['NumberOfImagesInMosaic'].iloc[0])
            elif 'SliceLocation' in acq_df.columns and acq_df['SliceLocation'].nunique() > 1:
                # Regular multi-slice: count unique slice locations
                slice_count = acq_df['SliceLocation'].nunique()
            else:
                # Fallback to file count
                slice_count = len(acq_df)

        ui_acquisitions.append({
            'id': unique_id,
            'protocolName': str(acq_name),
            'seriesDescription': series_desc,
            'totalFiles': len(acq_df) if acq_df is not None else 0,
            'sliceCount': slice_count,
            'acquisitionFields': acquisition_fields,
            'seriesFields': series_fields,
            'series': series_list,
            'metadata': {
                'analysis_timestamp': pd.Timestamp.now().isoformat(),
                'source': 'dicom_analysis'
            }
        })

    return make_json_serializable(ui_acquisitions)


def validate_acquisition_direct(
    acquisition_data: Dict[str, Any],
    schema_content: str,
    schema_acquisition_index: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Validate an acquisition using data passed directly (not from cache).

    This function is used when the cached session may not contain the acquisition
    data (e.g., when multiple datasets were uploaded at different times).

    Args:
        acquisition_data: The acquisition data dict with:
            - protocolName: Name of the acquisition
            - acquisitionFields: List of field dicts with tag, keyword, name, value
            - series: List of series dicts with name and fields
        schema_content: JSON string of the schema
        schema_acquisition_index: Index of the schema acquisition to validate against

    Returns:
        List of validation result dictionaries (same format as validate_acquisition_for_ui)
    """
    from ..validation import check_acquisition_compliance
    from ..io import load_schema
    import json
    import tempfile
    import os

    # Build a session DataFrame from the passed acquisition data
    acquisition_name = acquisition_data.get('protocolName', 'Unknown')
    slice_count = acquisition_data.get('sliceCount', 0)

    # Helper to make values hashable for pandas (lists -> tuples)
    def make_hashable(value):
        if isinstance(value, list):
            # Convert list to tuple so pandas can hash it for unique()
            return tuple(make_hashable(v) for v in value)
        return value

    # Collect acquisition-level fields (constant for all rows)
    # Include Count as a field so validation rules can access it (actual slice count)
    base_row = {'Acquisition': acquisition_name, 'Count': slice_count}
    for field in acquisition_data.get('acquisitionFields', []):
        field_name = field.get('keyword') or field.get('name') or field.get('tag')
        if field_name:
            base_row[field_name] = make_hashable(field.get('value'))

    # Build rows - one per series (for proper series-level validation)
    series_list = acquisition_data.get('series', [])
    if series_list:
        rows = []
        for series in series_list:
            row = base_row.copy()
            # Add series-level fields
            for field in series.get('fields', []):
                field_name = field.get('keyword') or field.get('name') or field.get('tag')
                if field_name:
                    row[field_name] = make_hashable(field.get('value'))
            rows.append(row)
        session_df = pd.DataFrame(rows)
    else:
        # No series - just use base row
        session_df = pd.DataFrame([base_row])

    # Write schema to temp file for load_schema
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(schema_content)
        temp_schema_path = f.name

    try:
        # Load schema
        fields, schema_data, validation_rules = load_schema(temp_schema_path)

        # Get schema acquisition names
        all_schema_acquisitions = list(schema_data.get('acquisitions', {}).keys())

        if not all_schema_acquisitions:
            raise ValueError("Schema contains no acquisitions")

        # Determine which schema acquisition to use
        if schema_acquisition_index is not None:
            if schema_acquisition_index < 0 or schema_acquisition_index >= len(all_schema_acquisitions):
                raise ValueError(f"Invalid acquisition index {schema_acquisition_index}. Schema has {len(all_schema_acquisitions)} acquisitions.")
            schema_acquisition_name = all_schema_acquisitions[schema_acquisition_index]
        elif len(all_schema_acquisitions) == 1:
            schema_acquisition_name = all_schema_acquisitions[0]
        else:
            raise ValueError(f"Multiple acquisitions in schema {all_schema_acquisitions} but no index specified.")

        # Get schema acquisition data
        schema_acquisition = schema_data['acquisitions'][schema_acquisition_name]

        # Get validation rules for this acquisition
        acq_validation_rules = validation_rules.get(schema_acquisition_name, []) if validation_rules else []

        # Run compliance check
        compliance_results = check_acquisition_compliance(
            in_session=session_df,
            schema_acquisition=schema_acquisition,
            acquisition_name=acquisition_name,
            validation_rules=acq_validation_rules
        )

        # Convert to UI format (same as validate_acquisition_for_ui)
        def _extract_single_value(value):
            """Extract single value from compliance result (may be list)."""
            if isinstance(value, list):
                return value[0] if value else None
            return value

        ui_results = []
        for result in compliance_results:
            # Determine status
            status_value = result.get('status', '').lower() if 'status' in result else None
            if status_value == 'na':
                status = 'na'
            elif status_value == 'warning':
                status = 'warning'
            elif status_value in ['pass', 'ok']:
                status = 'pass'
            elif status_value in ['fail', 'error']:
                status = 'fail'
            else:
                status = 'pass' if result.get('passed', False) else 'fail'

            # Determine validation type
            is_series = result.get('series') is not None
            rule_name = result.get('rule_name')
            is_rule = rule_name is not None

            ui_result = {
                'fieldPath': result.get('field', ''),
                'fieldName': result.get('field', ''),
                'status': status,
                'message': result.get('message', ''),
                'actualValue': _extract_single_value(result.get('value')),
                'expectedValue': result.get('expected') if not is_rule else None,
                'validationType': 'rule' if is_rule else ('series' if is_series else 'field')
            }

            if is_rule:
                ui_result['rule_name'] = rule_name
                ui_result['expectedValue'] = result.get('expected', '')

            if is_series:
                ui_result['seriesName'] = result.get('series', '')

            ui_results.append(ui_result)

        return make_json_serializable(ui_results)

    finally:
        os.unlink(temp_schema_path)


def load_protocol_for_ui(
    file_content: bytes,
    file_name: str,
    file_type: str
) -> List[Dict[str, Any]]:
    """
    Load a protocol file and return UI-ready acquisition(s).

    Args:
        file_content: Binary content of the protocol file
        file_name: Name of the file
        file_type: Type of protocol file ('pro', 'exar1', 'examcard', 'lxprotocol')

    Returns:
        List of UI-ready acquisition dictionaries with:
        - id, protocolName, seriesDescription
        - acquisitionFields (with tag, name, keyword, value, vr, dataType, fieldType)
        - seriesFields
        - series (with fields array)
        - metadata
    """
    from ..io import (
        load_pro_file_schema_format, load_exar_file,
        load_examcard_file_schema_format, load_lxprotocol_file_schema_format
    )
    from ..schema import get_tag_info
    from pydicom.datadict import dictionary_VR
    import tempfile
    import os
    import time

    # Helper to get VR
    def _get_vr(field_name: str) -> str:
        try:
            tag_info = get_tag_info(field_name)
            if tag_info["tag"]:
                tag_str = tag_info["tag"].strip("()")
                tag_parts = tag_str.split(",")
                tag_tuple = (int(tag_parts[0], 16), int(tag_parts[1], 16))
                return dictionary_VR(tag_tuple) or 'LO'
        except:
            pass
        return 'LO'

    # Helper to determine data type from value
    def _get_data_type(value: Any) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return 'number'
        elif isinstance(value, list):
            if len(value) == 0:
                return 'list_string'
            elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
                return 'list_number'
            else:
                return 'list_string'
        else:
            return 'string'

    # Helper to convert schema format to UI format
    def _convert_to_ui_acquisition(schema_data: Dict[str, Any], source_type: str, idx: int) -> Dict[str, Any]:
        acq_info = schema_data.get('acquisition_info', {})
        protocol_name = acq_info.get('protocol_name', file_name)

        # Process acquisition-level fields
        acquisition_fields = []
        for field_data in schema_data.get('fields', []):
            field_name = field_data.get('field', '')
            field_value = field_data.get('value')

            # Get tag info
            tag_info = get_tag_info(field_name)
            tag = tag_info.get('tag')
            field_tag = tag.strip("()") if tag else None
            field_type = tag_info.get('fieldType', 'standard')

            # Handle single-element arrays
            processed_value = field_value
            data_type = _get_data_type(field_value)
            if isinstance(field_value, list) and len(field_value) == 1:
                if isinstance(field_value[0], (int, float)) and not isinstance(field_value[0], bool):
                    data_type = 'number'
                    processed_value = field_value[0]
                elif isinstance(field_value[0], str):
                    data_type = 'string'
                    processed_value = field_value[0]

            acquisition_fields.append({
                'tag': field_tag,
                'name': field_name,
                'keyword': field_name,
                'value': processed_value,
                'vr': _get_vr(field_name),
                'level': 'acquisition',
                'dataType': data_type,
                'fieldType': field_type,
                'validationRule': {'type': 'exact'}
            })

        # Process series
        series_fields = []
        series_list = []
        schema_series = schema_data.get('series', [])

        if schema_series:
            # Collect series field definitions from first series
            first_series = schema_series[0] if schema_series else {}
            series_field_values = {}

            for series_data in schema_series:
                for field_data in series_data.get('fields', []):
                    field_name = field_data.get('field', '')
                    field_value = field_data.get('value')

                    if field_name not in series_field_values:
                        series_field_values[field_name] = []
                    series_field_values[field_name].append(field_value)

            # Create series fields
            for field_name, values in series_field_values.items():
                tag_info = get_tag_info(field_name)
                tag = tag_info.get('tag')
                field_tag = tag.strip("()") if tag else None
                field_type = tag_info.get('fieldType', 'standard')

                series_fields.append({
                    'tag': field_tag,
                    'name': field_name,
                    'keyword': field_name,
                    'values': values,
                    'vr': _get_vr(field_name),
                    'level': 'series',
                    'dataType': _get_data_type(values[0]) if values else 'string',
                    'fieldType': field_type,
                    'validationRule': {'type': 'exact'}
                })

            # Create series with fields as array
            for series_data in schema_series:
                series_name = series_data.get('name', f'Series {len(series_list) + 1}')
                series_fields_array = []

                for field_data in series_data.get('fields', []):
                    field_name = field_data.get('field', '')
                    field_value = field_data.get('value')

                    tag_info = get_tag_info(field_name)
                    tag = tag_info.get('tag')
                    field_tag = tag.strip("()") if tag else None
                    field_type = tag_info.get('fieldType', 'standard')

                    series_fields_array.append({
                        'name': field_name,
                        'tag': field_tag,
                        'value': field_value,
                        'fieldType': field_type,
                        'validationRule': {'type': 'exact'}
                    })

                series_list.append({
                    'name': series_name,
                    'fields': series_fields_array
                })

        timestamp = int(time.time() * 1000)
        return {
            'id': f'{source_type}_{timestamp}_{idx}',
            'protocolName': protocol_name,
            'seriesDescription': f'Protocol from {file_name}',
            'totalFiles': 1,
            'acquisitionFields': acquisition_fields,
            'seriesFields': series_fields,
            'series': series_list,
            'metadata': {
                'source': source_type,
                'originalFileName': file_name,
                'acquisitionInfo': acq_info
            }
        }

    # Write to temp file
    suffix_map = {
        'pro': '.pro',
        'exar1': '.exar1',
        'examcard': '.ExamCard',
        'lxprotocol': ''
    }
    suffix = suffix_map.get(file_type, '')
    mode = 'wb' if file_type in ['exar1', 'examcard'] else 'w'

    with tempfile.NamedTemporaryFile(mode=mode, suffix=suffix, delete=False) as f:
        if mode == 'wb':
            f.write(file_content)
        else:
            f.write(file_content.decode('utf-8'))
        temp_path = f.name

    try:
        # Load based on file type
        if file_type == 'pro':
            schema_data = load_pro_file_schema_format(temp_path)
            return make_json_serializable([_convert_to_ui_acquisition(schema_data, 'siemens_protocol', 0)])

        elif file_type == 'exar1':
            protocols = load_exar_file(temp_path)
            # load_exar_file returns flat format, need to convert
            result = []
            for idx, proto in enumerate(protocols):
                # Convert flat format to schema format structure
                schema_format = {
                    'acquisition_info': {
                        'protocol_name': proto.get('ProtocolName', proto.get('tProtocolName', f'Protocol_{idx}')),
                        'source_type': 'exar1'
                    },
                    'fields': [{'field': k, 'value': v} for k, v in proto.items()],
                    'series': []
                }
                result.append(_convert_to_ui_acquisition(schema_format, 'siemens_exar', idx))
            return make_json_serializable(result)

        elif file_type == 'examcard':
            scans = load_examcard_file_schema_format(temp_path)
            result = []
            for idx, scan_data in enumerate(scans):
                result.append(_convert_to_ui_acquisition(scan_data, 'philips_examcard', idx))
            return make_json_serializable(result)

        elif file_type == 'lxprotocol':
            scans = load_lxprotocol_file_schema_format(temp_path)
            result = []
            for idx, scan_data in enumerate(scans):
                result.append(_convert_to_ui_acquisition(scan_data, 'ge_lxprotocol', idx))
            return make_json_serializable(result)

        else:
            raise ValueError(f"Unknown file type: {file_type}")

    finally:
        os.unlink(temp_path)


def search_dicom_dictionary(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search DICOM dictionary for fields matching the query.

    Args:
        query: Search query (matches against keyword, name, or tag)
        limit: Maximum number of results to return

    Returns:
        List of matching field dictionaries with:
        - tag, name, keyword, vr, vm, description, suggested_data_type
    """
    from pydicom.datadict import keyword_for_tag, dictionary_VR, dictionary_VM, dictionary_description
    from ..schema.tags import VR_TO_DATA_TYPE

    query_lower = query.lower()
    results = []
    count = 0

    # Search through pydicom's keyword dictionary
    for tag_int, keyword in keyword_for_tag.items():
        if count >= limit:
            break

        # Convert tag to string format
        tag_str = f"{tag_int:08X}"
        tag_formatted = f"{tag_str[:4]},{tag_str[4:]}"

        # Get additional info
        try:
            vr = dictionary_VR(tag_int) or "UN"
            vm = dictionary_VM(tag_int) or "1"
            description = dictionary_description(tag_int) or keyword
        except:
            vr = "UN"
            vm = "1"
            description = keyword

        # Check if query matches
        if (query_lower in keyword.lower() or
            query_lower in description.lower() or
            query_lower in tag_formatted.lower() or
            query_lower in tag_str.lower()):

            # Determine suggested data type from VR
            suggested_type = VR_TO_DATA_TYPE.get(vr, 'string')
            if vm not in ['1', '1-1'] and suggested_type in ['string', 'number']:
                suggested_type = f"list_{suggested_type}"

            results.append({
                'tag': tag_formatted,
                'name': description,
                'keyword': keyword,
                'vr': vr,
                'vm': vm,
                'description': description,
                'suggested_data_type': suggested_type,
                'suggested_validation': 'exact',
                'common_values': []
            })
            count += 1

    return make_json_serializable(results)


def build_schema_from_ui_acquisitions(
    acquisitions: List[Dict[str, Any]],
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build a dicompare schema from UI acquisition format.

    This is the inverse of analyze_dicom_files_for_ui() - it takes UI
    acquisition data and creates a dicompare-compatible schema.

    Args:
        acquisitions: List of UI acquisition dictionaries
        metadata: Schema metadata (name, description, version, authors, tags)

    Returns:
        Dicompare-compatible schema dictionary
    """
    from ..schema import get_tag_info

    dicompare_acquisitions = {}

    for acquisition in acquisitions:
        acq_name = acquisition.get('protocolName', acquisition.get('id', 'Unknown'))

        # Process acquisition fields
        acq_fields = []
        for field in acquisition.get('acquisitionFields', []):
            field_entry = {
                'field': field.get('keyword', field.get('name', '')),
                'tag': field.get('tag') or field.get('fieldType', 'derived')
            }

            # Get actual value and validation rule
            actual_value = field.get('value')
            validation_rule = field.get('validationRule', {})

            # Handle complex value objects
            if isinstance(actual_value, dict) and ('validationRule' in actual_value or 'dataType' in actual_value):
                actual_value = actual_value.get('value')
                validation_rule = actual_value.get('validationRule', validation_rule)

            # Apply validation rules to create flat structure
            rule_type = validation_rule.get('type', 'exact') if validation_rule else 'exact'

            if rule_type == 'tolerance':
                if validation_rule.get('value') is not None and validation_rule.get('tolerance') is not None:
                    field_entry['value'] = validation_rule['value']
                    field_entry['tolerance'] = validation_rule['tolerance']
                else:
                    field_entry['value'] = actual_value
            elif rule_type == 'range':
                min_val = validation_rule.get('min')
                max_val = validation_rule.get('max')
                if min_val is not None:
                    field_entry['min'] = min_val
                if max_val is not None:
                    field_entry['max'] = max_val
                # Don't set 'value' for range constraints - min/max are the constraints
            elif rule_type == 'contains':
                if validation_rule.get('contains') is not None:
                    field_entry['contains'] = validation_rule['contains']
                else:
                    field_entry['value'] = actual_value
            elif rule_type == 'contains_any':
                if validation_rule.get('contains_any') is not None:
                    field_entry['contains_any'] = validation_rule['contains_any']
                else:
                    field_entry['value'] = actual_value
            elif rule_type == 'contains_all':
                if validation_rule.get('contains_all') is not None:
                    field_entry['contains_all'] = validation_rule['contains_all']
                else:
                    field_entry['value'] = actual_value
            else:
                field_entry['value'] = actual_value

            acq_fields.append(field_entry)

        # Process series
        series_data = []
        for series in acquisition.get('series', []):
            series_fields = []
            fields_array = series.get('fields', [])

            # Handle both array and object formats
            if isinstance(fields_array, dict):
                fields_array = [
                    {'name': k, 'tag': k, 'value': v.get('value') if isinstance(v, dict) else v,
                     'validationRule': v.get('validationRule', {'type': 'exact'}) if isinstance(v, dict) else {'type': 'exact'}}
                    for k, v in fields_array.items()
                ]

            for field in fields_array:
                field_entry = {
                    'field': field.get('keyword', field.get('name', '')),
                    'tag': field.get('tag') or field.get('fieldType', 'derived')
                }

                actual_value = field.get('value')
                validation_rule = field.get('validationRule', {})
                rule_type = validation_rule.get('type', 'exact') if validation_rule else 'exact'

                if rule_type == 'tolerance':
                    if validation_rule.get('value') is not None and validation_rule.get('tolerance') is not None:
                        field_entry['value'] = validation_rule['value']
                        field_entry['tolerance'] = validation_rule['tolerance']
                    else:
                        field_entry['value'] = actual_value
                elif rule_type == 'range':
                    min_val = validation_rule.get('min')
                    max_val = validation_rule.get('max')
                    if min_val is not None:
                        field_entry['min'] = min_val
                    if max_val is not None:
                        field_entry['max'] = max_val
                    # Don't set 'value' for range constraints - min/max are the constraints
                elif rule_type == 'contains':
                    if validation_rule.get('contains') is not None:
                        field_entry['contains'] = validation_rule['contains']
                    else:
                        field_entry['value'] = actual_value
                elif rule_type == 'contains_any':
                    if validation_rule.get('contains_any') is not None:
                        field_entry['contains_any'] = validation_rule['contains_any']
                    else:
                        field_entry['value'] = actual_value
                elif rule_type == 'contains_all':
                    if validation_rule.get('contains_all') is not None:
                        field_entry['contains_all'] = validation_rule['contains_all']
                    else:
                        field_entry['value'] = actual_value
                else:
                    field_entry['value'] = actual_value

                # Only include fields with actual constraints
                if 'value' in field_entry or 'contains' in field_entry or 'tolerance' in field_entry or 'min' in field_entry or 'max' in field_entry:
                    series_fields.append(field_entry)

            if series_fields:
                series_data.append({
                    'name': series.get('name', f'Series {len(series_data) + 1}'),
                    'fields': series_fields
                })

        # Build acquisition entry
        acq_entry = {
            'description': acquisition.get('seriesDescription', ''),
            'detailed_description': acquisition.get('detailedDescription', ''),
            'fields': acq_fields,
            'series': series_data
        }

        # Add tags if present
        acq_tags = acquisition.get('tags', [])
        if acq_tags:
            acq_entry['tags'] = acq_tags

        # Add validation rules if present
        validation_functions = acquisition.get('validationFunctions', [])
        if validation_functions:
            acq_entry['rules'] = [
                {
                    'id': func.get('id', f"rule_{acq_name.lower().replace(' ', '_')}_{idx}"),
                    'name': func.get('customName', func.get('name', '')),
                    'description': func.get('customDescription', func.get('description', '')),
                    'implementation': func.get('customImplementation', func.get('implementation', '')),
                    'parameters': func.get('configuredParams', func.get('parameters', {})),
                    'fields': func.get('customFields', func.get('fields', [])),
                    'testCases': func.get('customTestCases', func.get('testCases', []))
                }
                for idx, func in enumerate(validation_functions)
            ]

        dicompare_acquisitions[acq_name] = acq_entry

    # Build schema (only include fields defined in metaschema)
    schema = {
        'name': metadata.get('name', 'Generated Schema'),
        'description': metadata.get('description', ''),
        'version': metadata.get('version', '1.0'),
        'authors': metadata.get('authors', []),
        'acquisitions': dicompare_acquisitions
    }

    return make_json_serializable(schema)