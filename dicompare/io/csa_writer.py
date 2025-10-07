"""
Write Siemens CSA headers to DICOM files.

This module provides functionality to create CSA headers in the Siemens proprietary
format and embed them in DICOM private tags. This allows generation of test DICOMs
with CSA-specific fields like MultibandFactor, SliceTiming, etc.

Based on the CSA header format specification from nibabel/nicom/csareader.py
"""

import struct
from typing import Dict, List, Any, Union


def encode_csa_header(tags: Dict[str, Any], csa_type: str = 'image') -> bytes:
    """
    Encode a CSA header from a dictionary of tags.

    Creates a binary CSA header in SV10 (CSA2) format suitable for embedding
    in DICOM private tags (0029,1010) for image headers or (0029,1020) for
    series headers.

    Args:
        tags: Dictionary mapping tag names to values. Values can be:
            - Single values (int, float, str)
            - Lists of values
            Each tag will be encoded with appropriate VR
        csa_type: Either 'image' or 'series' (determines which tag to use)

    Returns:
        Binary CSA header data as bytes

    Example:
        >>> tags = {
        ...     'MultibandFactor': 3,
        ...     'SliceTiming': [0.0, 0.5, 1.0, 1.5],
        ...     'B_value': 1000
        ... }
        >>> csa_data = encode_csa_header(tags, 'image')
        >>> # Now set this to ds[0x0029, 0x1010].value

    CSA Header Format (SV10/CSA2):
        - Magic: 'SV10' (4 bytes)
        - Unused: 4 bytes
        - n_tags: 4 bytes (uint32)
        - Check value: 4 bytes (uint32), typically 77
        - Tag entries (variable):
            - Name: 64 bytes (null-padded string)
            - VM: 4 bytes (uint32) - value multiplicity
            - VR: 4 bytes (string)
            - Syngo DT: 4 bytes (uint32)
            - n_items: 4 bytes (uint32)
            - xx: 4 bytes (uint32), typically 77 or 205
            - ... (2 more uint32, typically 0)
        - Item data for each tag:
            - x0-x3: 16 bytes (4x uint32)
            - Item data: variable length
            - Padding to 4-byte boundary
    """
    buffer = bytearray()

    # CSA2 header magic
    buffer.extend(b'SV10')

    # Unused field
    buffer.extend(struct.pack('<I', 4))

    # Number of tags
    n_tags = len(tags)
    buffer.extend(struct.pack('<I', n_tags))

    # Check value (typically 77)
    buffer.extend(struct.pack('<I', 77))

    # Prepare tag entries
    tag_entries = []
    tag_items = []

    for tag_name, tag_value in tags.items():
        # Ensure tag_value is a list for consistent handling
        if not isinstance(tag_value, list):
            tag_value = [tag_value]

        # Determine VR based on value type
        if isinstance(tag_value[0], str):
            vr = 'LO'
            syngo_dt = 3  # String
        elif isinstance(tag_value[0], float):
            vr = 'FD'
            syngo_dt = 6  # Double
        elif isinstance(tag_value[0], int):
            vr = 'IS'
            syngo_dt = 4  # Integer
        else:
            vr = 'UN'
            syngo_dt = 0

        # Tag entry (without items)
        tag_entry = bytearray()

        # Name (64 bytes, null-padded)
        name_bytes = tag_name.encode('ascii')[:64]
        tag_entry.extend(name_bytes)
        tag_entry.extend(b'\x00' * (64 - len(name_bytes)))

        # VM (value multiplicity)
        vm = len(tag_value)
        tag_entry.extend(struct.pack('<I', vm))

        # VR (4 bytes, null-padded)
        vr_bytes = vr.encode('ascii')[:4]
        tag_entry.extend(vr_bytes)
        tag_entry.extend(b'\x00' * (4 - len(vr_bytes)))

        # Syngo data type
        tag_entry.extend(struct.pack('<I', syngo_dt))

        # Number of items
        n_items = len(tag_value)
        tag_entry.extend(struct.pack('<I', n_items))

        # xx (typically 77 or 205)
        tag_entry.extend(struct.pack('<I', 77))

        # Two more uint32 (typically 0)
        tag_entry.extend(struct.pack('<I', 0))
        tag_entry.extend(struct.pack('<I', 0))

        tag_entries.append(tag_entry)

        # Prepare items data for this tag
        items_data = bytearray()
        for item_value in tag_value:
            # Convert value to bytes
            if isinstance(item_value, str):
                item_bytes = item_value.encode('ascii')
            elif isinstance(item_value, float):
                item_bytes = str(item_value).encode('ascii')
            elif isinstance(item_value, int):
                item_bytes = str(item_value).encode('ascii')
            else:
                item_bytes = str(item_value).encode('ascii')

            item_len = len(item_bytes)

            # Item header: 4 uint32 values
            # For CSA2: x1 contains the item length
            items_data.extend(struct.pack('<I', 0))  # x0
            items_data.extend(struct.pack('<I', item_len))  # x1 - item length
            items_data.extend(struct.pack('<I', 0))  # x2
            items_data.extend(struct.pack('<I', 0))  # x3

            # Item data
            items_data.extend(item_bytes)

            # Pad to 4-byte boundary
            padding = (4 - (item_len % 4)) % 4
            items_data.extend(b'\x00' * padding)

        tag_items.append(items_data)

    # Write all tag entries
    for tag_entry in tag_entries:
        buffer.extend(tag_entry)

    # Write all items data
    for items_data in tag_items:
        buffer.extend(items_data)

    return bytes(buffer)


def add_csa_tags_to_dicom(ds, csa_tags: Dict[str, Any], csa_type: str = 'image'):
    """
    Add CSA header tags to a pydicom Dataset.

    This is a convenience function that encodes CSA tags and adds them to the
    appropriate DICOM private tag.

    Args:
        ds: pydicom Dataset to modify
        csa_tags: Dictionary of CSA tag names and values
        csa_type: Either 'image' or 'series'

    Example:
        >>> import pydicom
        >>> ds = pydicom.Dataset()
        >>> csa_tags = {'MultibandFactor': 3, 'B_value': 1000}
        >>> add_csa_tags_to_dicom(ds, csa_tags, 'image')
        >>> # ds now has CSA header in tag (0029,1010)
    """
    csa_data = encode_csa_header(csa_tags, csa_type)

    if csa_type == 'image':
        # CSA Image Header Info
        ds.add_new((0x0029, 0x1010), 'OB', csa_data)
    else:
        # CSA Series Header Info
        ds.add_new((0x0029, 0x1020), 'OB', csa_data)


def extract_csa_fields_from_test_data(
    field_definitions: List[Dict[str, str]],
    row_data: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """
    Extract fields that should go into CSA headers from test data.

    Separates standard DICOM fields from CSA-specific fields based on
    known CSA field names.

    Args:
        field_definitions: List of field metadata with 'name', 'tag', etc.
        row_data: Dictionary of field values for one DICOM

    Returns:
        Dictionary with keys 'image_csa', 'series_csa', and 'standard'
        containing the appropriate field mappings

    Example:
        >>> field_defs = [
        ...     {'name': 'RepetitionTime', 'tag': '0018,0080'},
        ...     {'name': 'MultibandFactor', 'tag': ''},  # CSA field
        ... ]
        >>> row_data = {'RepetitionTime': 2000, 'MultibandFactor': 3}
        >>> result = extract_csa_fields_from_test_data(field_defs, row_data)
        >>> result['image_csa']
        {'MultibandFactor': 3}
        >>> result['standard']
        {'RepetitionTime': 2000}
    """
    # Known CSA image header fields (from nibabel/dicompare)
    CSA_IMAGE_FIELDS = {
        'MultibandFactor', 'MultibandAccelerationFactor',
        'B_value', 'DiffusionGradientDirection',
        'SliceMeasurementDuration', 'BandwidthPerPixelPhaseEncode',
        'TotalReadoutTime', 'MosaicRefAcqTimes', 'SliceTiming',
        'NumberOfImagesInMosaic', 'DiffusionDirectionality',
        'GradientMode', 'B_matrix', 'SliceNormalVector',
        'ImaAbsTablePosition', 'ImaRelTablePosition',
        'PhaseEncodingDirectionPositive', 'ProtocolSliceNumber',
        'RealDwellTime', 'DwellTime', 'UsedChannelString',
        'ICE_Dims', 'AcquisitionMatrixText', 'MeasuredFourierLines',
    }

    # Known CSA series header fields
    CSA_SERIES_FIELDS = {
        'MrPhoenixProtocol', 'ImagedNucleus',
    }

    image_csa = {}
    series_csa = {}
    standard = {}

    for field_name, value in row_data.items():
        if field_name in CSA_IMAGE_FIELDS:
            image_csa[field_name] = value
        elif field_name in CSA_SERIES_FIELDS:
            series_csa[field_name] = value
        else:
            standard[field_name] = value

    return {
        'image_csa': image_csa,
        'series_csa': series_csa,
        'standard': standard
    }
