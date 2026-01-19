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
        tag_raw = field.get('tag')
        tag_str = (tag_raw or '').strip('()')
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

    # Pre-generate SeriesInstanceUIDs for each unique series
    # This ensures DICOMs in the same series share the same SeriesInstanceUID
    series_uid_map = {}  # {seriesIndex: SeriesInstanceUID}

    for row_data in test_data:
        series_idx = row_data.get('_seriesIndex')
        if series_idx is not None and series_idx not in series_uid_map:
            series_uid_map[series_idx] = generate_uid()

    print(f"📊 Generated {len(series_uid_map)} unique SeriesInstanceUIDs for series")

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

            # Extract series metadata if available
            series_idx = row_data.get('_seriesIndex')
            series_name = row_data.get('_seriesName', '')

            # Core DICOM elements
            ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.4'
            ds.SOPInstanceUID = generate_uid()
            ds.StudyInstanceUID = generate_uid()

            # Use shared SeriesInstanceUID for same series, or generate new if no series info
            if series_idx is not None and series_idx in series_uid_map:
                ds.SeriesInstanceUID = series_uid_map[series_idx]
            else:
                ds.SeriesInstanceUID = generate_uid()

            ds.FrameOfReferenceUID = generate_uid()

            # Basic patient/study info - use same PatientID for all files in the session
            ds.PatientName = 'TEST^PATIENT'
            ds.PatientID = 'TEST_PATIENT_001'
            ds.StudyDate = datetime.now().strftime('%Y%m%d')
            ds.StudyTime = datetime.now().strftime('%H%M%S')
            ds.AccessionNumber = f'TEST_ACC_{idx:03d}'
            ds.StudyDescription = 'Test Study from Schema'
            ds.Modality = 'MR'  # Required field for DICOM image validation
            ds.SeriesDate = ds.StudyDate
            ds.SeriesTime = ds.StudyTime

            # Use series name as SeriesDescription
            if series_name:
                ds.SeriesDescription = series_name
            else:
                ds.SeriesDescription = acquisition_info.get('seriesDescription', 'Test Series')
            ds.SeriesNumber = str(series_idx + 1 if series_idx is not None else idx + 1)
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
                # Skip internal metadata fields (used for series grouping)
                if field_name.startswith('_'):
                    continue

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
