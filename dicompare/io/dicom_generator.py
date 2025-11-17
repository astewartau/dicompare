"""
Generate test DICOM files from schema-based test data.

This module provides functionality to create valid DICOM files from schema constraints,
useful for testing compliance and generating reference datasets.
"""

import io
import zipfile
import warnings
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

from .special_fields import (
    categorize_fields,
    apply_special_field_encoding,
    get_unhandled_field_warnings
)


def generate_test_dicoms_from_schema(
    test_data: List[Dict[str, Any]],
    field_definitions: List[Dict[str, str]],
    acquisition_info: Optional[Dict[str, str]] = None
) -> bytes:
    """
    Generate test DICOM files from schema-based test data.

    Creates valid DICOM files with minimal pixel data and schema-defined field values.
    Each row in test_data generates one DICOM file. All files are packaged into a ZIP.

    Args:
        test_data: List of dicts, each representing one DICOM's field values.
                   Example: [{'RepetitionTime': 2000, 'EchoTime': 2.46, ...}, ...]
        field_definitions: List of field metadata with 'name', 'tag', and optionally 'vr'.
                          Example: [{'name': 'RepetitionTime', 'tag': '0018,0080', 'vr': 'DS'}, ...]
        acquisition_info: Optional metadata dict with 'protocolName' and 'seriesDescription'.

    Returns:
        ZIP file as bytes containing all generated DICOM files.

    Example:
        >>> test_data = [
        ...     {'RepetitionTime': 2000, 'EchoTime': 2.46, 'FlipAngle': 9.0},
        ...     {'RepetitionTime': 2000, 'EchoTime': 3.5, 'FlipAngle': 9.0}
        ... ]
        >>> field_defs = [
        ...     {'name': 'RepetitionTime', 'tag': '0018,0080', 'vr': 'DS'},
        ...     {'name': 'EchoTime', 'tag': '0018,0081', 'vr': 'DS'},
        ...     {'name': 'FlipAngle', 'tag': '0018,1314', 'vr': 'DS'}
        ... ]
        >>> zip_bytes = generate_test_dicoms_from_schema(test_data, field_defs)
        >>> # zip_bytes can be saved to file or returned via API
    """
    if acquisition_info is None:
        acquisition_info = {}

    print(f"📊 Generating DICOMs from {len(test_data)} test data rows")
    print(f"📊 Field info received: {len(field_definitions)} fields")
    for i, field in enumerate(field_definitions[:3]):  # Show first 3 fields
        print(f"  Field {i}: {field}")

    # Categorize fields and show warnings for unhandled fields
    categorized = categorize_fields(field_definitions)
    print(f"\n📋 Field categorization:")
    print(f"  Standard DICOM fields: {len(categorized['standard'])}")
    print(f"  Handled special fields: {len(categorized['handled'])}")
    print(f"  Unhandled fields: {len(categorized['unhandled'])}")

    # Get warnings for unhandled fields with data
    unhandled_warnings = get_unhandled_field_warnings(field_definitions, test_data)
    if unhandled_warnings:
        print(f"\n⚠️  WARNING: Some fields cannot be encoded in DICOMs:")
        for warning in unhandled_warnings:
            print(f"  - {warning}")
        print(f"\n  Generated DICOMs may not pass validation if these fields are required.")

    # Create mappings of field names to DICOM tags and VRs
    field_tag_map = {}
    field_vr_map = {}

    for field in field_definitions:
        field_name = field.get('name', '')
        tag_str = field.get('tag', '').strip('()')
        vr = field.get('vr', 'UN')

        if tag_str and ',' in tag_str:
            try:
                parts = tag_str.split(',')
                group = int(parts[0].strip(), 16)
                element = int(parts[1].strip(), 16)
                field_tag_map[field_name] = (group, element)
                field_vr_map[field_name] = vr
                print(f"  Field: {field_name} -> {tag_str} (VR: {vr})")
            except Exception as e:
                print(f"  Skipping invalid tag: {field_name} -> {tag_str}, error: {e}")

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:

        for idx, row_data in enumerate(test_data):
            print(f"🔧 Creating DICOM file {idx + 1}/{len(test_data)}")

            # Create a minimal DICOM dataset
            ds = Dataset()

            # Required DICOM header elements
            ds.file_meta = Dataset()
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds.file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.4'  # MR Image Storage
            ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
            ds.file_meta.ImplementationClassUID = generate_uid()
            ds.file_meta.ImplementationVersionName = 'DICOMPARE_TEST_GEN_1.0'

            # Core DICOM elements
            ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.4'
            ds.SOPInstanceUID = generate_uid()
            ds.StudyInstanceUID = generate_uid()
            ds.SeriesInstanceUID = generate_uid()
            ds.FrameOfReferenceUID = generate_uid()

            # Basic patient/study info
            ds.PatientName = 'TEST^PATIENT'
            ds.PatientID = f'TEST_ID_{idx:03d}'
            ds.StudyDate = datetime.now().strftime('%Y%m%d')
            ds.StudyTime = datetime.now().strftime('%H%M%S')
            ds.AccessionNumber = f'TEST_ACC_{idx:03d}'
            ds.StudyDescription = 'Test Study from Schema'
            ds.Modality = 'MR'  # Required field for DICOM image validation
            ds.SeriesDate = ds.StudyDate
            ds.SeriesTime = ds.StudyTime
            ds.SeriesDescription = acquisition_info.get('seriesDescription', 'Test Series')
            ds.SeriesNumber = str(idx + 1)
            ds.InstanceNumber = str(idx + 1)

            # Image-specific elements (minimal)
            ds.ImageType = ['ORIGINAL', 'PRIMARY', 'OTHER']
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = 'MONOCHROME2'
            ds.Rows = 64  # Small test image
            ds.Columns = 64
            ds.BitsAllocated = 16
            ds.BitsStored = 16
            ds.HighBit = 15
            ds.PixelRepresentation = 0

            # Create minimal pixel data (64x64 test pattern)
            pixel_array = np.zeros((64, 64), dtype=np.uint16)
            # Add a simple test pattern
            pixel_array[20:44, 20:44] = 1000  # Square in center
            ds.PixelData = pixel_array.tobytes()

            # Separate standard DICOM fields from special fields
            standard_fields = {}
            special_fields = {}

            for field_name, value in row_data.items():
                if field_name in field_tag_map:
                    standard_fields[field_name] = value
                else:
                    # Check if it's a handled special field
                    field_def = next((f for f in field_definitions if f.get('name') == field_name), None)
                    if field_def:
                        category, _ = categorized.get(field_name, ('unhandled', ''))
                        # For categorized dict, we need to search through the lists
                        is_handled = any(f['name'] == field_name for f in categorized['handled'])
                        if is_handled:
                            special_fields[field_name] = value

            # Add standard DICOM fields
            for field_name, value in standard_fields.items():
                if field_name in field_tag_map:
                    tag = field_tag_map[field_name]
                    try:
                        # Get VR from PyDicom's dictionary (more reliable than frontend VR)
                        try:
                            actual_vr = pydicom.datadict.dictionary_VR(tag)
                        except KeyError:
                            actual_vr = field_vr_map.get(field_name, 'UN')

                        print(f"    Processing {field_name}: value={value}, Frontend_VR={field_vr_map.get(field_name, 'UN')}, PyDicom_VR={actual_vr}")

                        if isinstance(value, list):
                            # Handle multi-value fields based on actual VR
                            if actual_vr in ['DS']:
                                # Decimal String - convert to list of strings
                                dicom_value = [str(float(v)) for v in value]
                            elif actual_vr in ['IS']:
                                # Integer String - convert to list of strings
                                dicom_value = [str(int(v)) for v in value]
                            elif actual_vr in ['FL', 'FD']:
                                # Float types - keep as numeric list
                                dicom_value = [float(v) for v in value]
                            elif actual_vr in ['SL', 'SS', 'UL', 'US', 'SV', 'UV']:
                                # Integer types - keep as numeric list
                                dicom_value = [int(v) for v in value]
                            else:
                                # String types - convert to string list
                                dicom_value = [str(v) for v in value]
                        elif isinstance(value, (int, float)):
                            # Single numeric values
                            if actual_vr in ['DS']:
                                dicom_value = str(float(value))
                            elif actual_vr in ['IS']:
                                dicom_value = str(int(value))
                            elif actual_vr in ['FL', 'FD']:
                                dicom_value = float(value)
                            elif actual_vr in ['SL', 'SS', 'UL', 'US', 'SV', 'UV']:
                                dicom_value = int(value)
                            else:
                                dicom_value = value
                        else:
                            # String values
                            dicom_value = str(value) if value is not None else ""

                        # Set the field in the dataset
                        try:
                            keyword = pydicom.datadict.keyword_for_tag(tag)
                        except KeyError:
                            # If tag is not recognized, use a fallback name
                            keyword = f"Tag{tag[0]:04X}{tag[1]:04X}"

                        setattr(ds, keyword, dicom_value)
                        print(f"    Set {field_name} ({keyword}): {dicom_value}")

                    except Exception as e:
                        print(f"    Warning: Could not set {field_name}: {e}")

            # Apply special field encoding (e.g., MultibandFactor in ImageComments)
            if special_fields:
                print(f"    Applying special encoding for {len(special_fields)} fields")
                apply_special_field_encoding(ds, special_fields)

                # Set Manufacturer to SIEMENS if multiband fields were encoded
                if any(f in special_fields for f in ['MultibandFactor', 'MultibandAccelerationFactor']):
                    if not hasattr(ds, 'Manufacturer'):
                        ds.Manufacturer = 'SIEMENS'

            # Save DICOM to zip
            dicom_buffer = io.BytesIO()
            ds.save_as(dicom_buffer, write_like_original=False)
            dicom_bytes = dicom_buffer.getvalue()

            filename = f"test_dicom_{idx:03d}.dcm"
            zip_file.writestr(filename, dicom_bytes)
            print(f"    ✅ Saved {filename} ({len(dicom_bytes)} bytes)")

    zip_buffer.seek(0)
    zip_bytes = zip_buffer.getvalue()
    print(f"🎯 Generated ZIP file with {len(test_data)} DICOM files ({len(zip_bytes)} bytes)")

    return zip_bytes


def generate_test_dicoms_from_schema_json(
    schema_json: Dict[str, Any],
    acquisition_name: str,
    as_zip: bool = True
) -> Union[bytes, List[Dataset]]:
    """
    Generate test DICOM files directly from a schema JSON.

    This function parses a schema JSON, extracts field values from acquisition/series
    definitions and validation test cases, then generates valid DICOM files.

    Priority order for field values:
    1. Acquisition-level field values (base values)
    2. Series-level field values (override acquisition values)
    3. Validation test case values (only if no conflict with above)

    Args:
        schema_json: Complete schema dictionary with acquisitions, fields, series, and rules
        acquisition_name: Name of the acquisition to generate DICOMs for
        as_zip: If True, return ZIP bytes. If False, return list of pydicom Dataset objects

    Returns:
        ZIP file bytes (if as_zip=True) or list of Dataset objects (if as_zip=False)

    Raises:
        KeyError: If acquisition_name not found in schema
        ValueError: If schema structure is invalid or missing required data

    Example:
        >>> schema = {
        ...     "acquisitions": {
        ...         "T1_MPRAGE": {
        ...             "fields": [{"field": "RepetitionTime", "tag": "0018,0080", "value": 2000}],
        ...             "series": [{"name": "Series1", "fields": [...]}],
        ...             "rules": []
        ...         }
        ...     }
        ... }
        >>> zip_bytes = generate_test_dicoms_from_schema_json(schema, "T1_MPRAGE")
    """
    print(f"\n📋 Generating test DICOMs from schema for acquisition: {acquisition_name}")

    # Step 1: Extract schema data for acquisition
    if 'acquisitions' not in schema_json:
        raise ValueError("Schema JSON missing 'acquisitions' key")

    if acquisition_name not in schema_json['acquisitions']:
        available = list(schema_json['acquisitions'].keys())
        raise KeyError(f"Acquisition '{acquisition_name}' not found. Available: {available}")

    acq_data = schema_json['acquisitions'][acquisition_name]

    # Step 2: Build base test data from acquisition fields
    base_values = {}
    acquisition_fields = acq_data.get('fields', [])

    print(f"📊 Found {len(acquisition_fields)} acquisition-level fields")
    for field in acquisition_fields:
        field_name = field.get('field') or field.get('name')
        if field_name and 'value' in field:
            base_values[field_name] = field['value']
            print(f"  - {field_name}: {field['value']}")

    # Step 3: Extract series data
    series_list = acq_data.get('series', [])
    test_data_rows = []

    if series_list:
        print(f"📊 Found {len(series_list)} series")
        for series in series_list:
            series_name = series.get('name', 'Unknown')
            series_values = base_values.copy()

            series_fields = series.get('fields', [])
            for field in series_fields:
                field_name = field.get('field') or field.get('name')
                if field_name and 'value' in field:
                    series_values[field_name] = field['value']
                    print(f"  Series '{series_name}': {field_name} = {field['value']}")

            test_data_rows.append(series_values)
    else:
        # No series - use base acquisition values
        if base_values:
            print(f"📊 No series found, using acquisition values")
            test_data_rows.append(base_values)
        else:
            print(f"⚠️  No acquisition fields and no series - will rely on validation test data")

    # Step 4: Extract validation test data
    rules = acq_data.get('rules', [])
    validation_fields = {}
    field_conflicts = []

    print(f"\n📊 Processing {len(rules)} validation rules")
    for rule in rules:
        rule_name = rule.get('name', rule.get('id', 'Unknown'))
        test_cases = rule.get('testCases', [])

        if not test_cases:
            warnings.warn(f"⚠️  Validation rule '{rule_name}' has no test cases - skipping for DICOM generation")
            print(f"  ⚠️  Rule '{rule_name}': No test cases")
            continue

        # Find passing test cases
        passing_tests = [
            tc for tc in test_cases
            if tc.get('expectedResult') == 'pass'
        ]

        if not passing_tests:
            warnings.warn(f"⚠️  Validation rule '{rule_name}' has no passing test cases")
            print(f"  ⚠️  Rule '{rule_name}': No passing tests")
            continue

        # Use first passing test
        passing_test = passing_tests[0]
        test_data = passing_test.get('data', {})

        print(f"  ✅ Rule '{rule_name}': Found passing test with {len(test_data)} fields")

        for field_name, value in test_data.items():
            # Check for conflicts with base/series values
            if field_name in base_values:
                if base_values[field_name] != value:
                    conflict_msg = (
                        f"Field '{field_name}' has schema value {base_values[field_name]} "
                        f"but validation test expects {value} - using schema value (acquisition field takes precedence)"
                    )
                    field_conflicts.append(conflict_msg)
                    warnings.warn(f"⚠️  {conflict_msg}")
                    print(f"    ⚠️  Conflict: {field_name}")
                continue

            # Check if any series defines this field
            series_defines_field = any(
                field_name in row for row in test_data_rows
            )

            if series_defines_field:
                # Check for conflicts with series values
                series_values = [row.get(field_name) for row in test_data_rows if field_name in row]
                if any(sv != value for sv in series_values):
                    conflict_msg = (
                        f"Field '{field_name}' has series values {series_values} "
                        f"but validation test expects {value} - using series values (series definition takes precedence)"
                    )
                    field_conflicts.append(conflict_msg)
                    warnings.warn(f"⚠️  {conflict_msg}")
                    print(f"    ⚠️  Conflict: {field_name}")
                continue

            # No conflict - add to validation fields
            validation_fields[field_name] = value
            print(f"    ✅ Adding validation field: {field_name} = {value}")

    # Step 5: Merge validation data into test rows (only non-conflicting fields)
    if validation_fields:
        print(f"\n📊 Merging {len(validation_fields)} validation fields into test data")
        for row in test_data_rows:
            row.update(validation_fields)

    # Handle case where we have no base data but have validation data
    if not test_data_rows and validation_fields:
        print(f"📊 Creating test data from validation fields only")
        test_data_rows.append(validation_fields)

    if not test_data_rows:
        raise ValueError(
            f"No test data generated for acquisition '{acquisition_name}'. "
            "Schema must have either field values, series definitions, or validation test cases."
        )

    print(f"\n📊 Final test data: {len(test_data_rows)} DICOM(s) to generate")
    for i, row in enumerate(test_data_rows):
        print(f"  DICOM {i+1}: {len(row)} fields")

    # Step 6: Build field definitions with DICOM tags
    all_field_names = set()
    for row in test_data_rows:
        all_field_names.update(row.keys())

    field_definitions = []

    # First, get tags from schema field definitions
    schema_field_tags = {}
    for field in acquisition_fields:
        field_name = field.get('field') or field.get('name')
        tag = field.get('tag', '')
        vr = field.get('vr', '')
        if field_name and tag:
            schema_field_tags[field_name] = (tag.strip('()'), vr)

    # Also check series fields
    for series in series_list:
        for field in series.get('fields', []):
            field_name = field.get('field') or field.get('name')
            tag = field.get('tag', '')
            vr = field.get('vr', '')
            if field_name and tag:
                schema_field_tags[field_name] = (tag.strip('()'), vr)

    print(f"\n📊 Building field definitions for {len(all_field_names)} unique fields")
    for field_name in all_field_names:
        if field_name in schema_field_tags:
            tag, vr = schema_field_tags[field_name]
            field_definitions.append({
                'name': field_name,
                'tag': tag,
                'vr': vr or 'UN'
            })
            print(f"  ✅ {field_name}: {tag} (VR: {vr or 'UN'})")
        else:
            # Try to look up in DICOM dictionary by keyword
            try:
                # Convert field name to DICOM keyword (assume it's already correct)
                tag_int = pydicom.datadict.tag_for_keyword(field_name)
                if tag_int is None:
                    raise KeyError(f"Unknown keyword: {field_name}")
                # tag_for_keyword returns an int, convert to tuple (group, element)
                group = (tag_int >> 16) & 0xFFFF
                element = tag_int & 0xFFFF
                tag_str = f"{group:04X},{element:04X}"
                vr = pydicom.datadict.dictionary_VR(tag_int)

                field_definitions.append({
                    'name': field_name,
                    'tag': tag_str,
                    'vr': vr
                })
                print(f"  ✅ {field_name}: {tag_str} (VR: {vr}) [from DICOM dict]")
            except (KeyError, AttributeError):
                warnings.warn(
                    f"⚠️  Unknown field '{field_name}' from validation test - "
                    "cannot map to DICOM tag (field will be skipped)"
                )
                print(f"  ⚠️  {field_name}: Unknown DICOM tag (skipping)")
                # Remove from test data
                for row in test_data_rows:
                    row.pop(field_name, None)

    # Step 7: Generate DICOMs using existing function
    acquisition_info = {
        'protocolName': acquisition_name,
        'seriesDescription': acq_data.get('description', '')
    }

    print(f"\n🔧 Calling DICOM generator...")
    zip_bytes = generate_test_dicoms_from_schema(
        test_data=test_data_rows,
        field_definitions=field_definitions,
        acquisition_info=acquisition_info
    )

    if field_conflicts:
        print(f"\n⚠️  Generated DICOMs with {len(field_conflicts)} field conflict(s)")

    # Step 8: Return based on format
    if as_zip:
        return zip_bytes
    else:
        # Extract datasets from ZIP
        datasets = []
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            for filename in zf.namelist():
                dicom_bytes = zf.read(filename)
                ds = pydicom.dcmread(io.BytesIO(dicom_bytes))
                datasets.append(ds)
        return datasets
