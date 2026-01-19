"""
Handle special fields that aren't standard DICOM but can be encoded in specific ways.

This module provides functionality to:
1. Categorize fields as standard DICOM, handled special fields, or unhandled
2. Encode special fields (e.g., MultibandFactor in ImageComments)
"""

from typing import Dict, List, Any, Tuple
import pydicom


# Fields we can handle through special encoding (not standard DICOM tags)
HANDLED_SPECIAL_FIELDS = {
    'MultibandFactor': {
        'encoding': 'ImageComments',
        'description': 'Multiband acceleration factor (stored in ImageComments as "Unaliased MB{n}/PE{shift}")'
    },
    'MultibandAccelerationFactor': {
        'encoding': 'ImageComments',
        'description': 'Multiband acceleration factor (alias of MultibandFactor)'
    },
    'ParallelReductionFactorOutOfPlane': {
        'encoding': 'ImageComments',
        'description': 'Out-of-plane parallel reduction factor (alias of MultibandFactor)'
    },
    'PhaseEncodingShift': {
        'encoding': 'ImageComments',
        'description': 'Phase encoding shift for multiband (PE shift in ImageComments)'
    },
}


def categorize_field(
    field_name: str,
    field_tag: str = ''
) -> Tuple[str, str]:
    """
    Categorize a field as 'standard', 'handled', or 'unhandled'.

    Args:
        field_name: Name of the field
        field_tag: DICOM tag in format "0018,0080" or empty

    Returns:
        Tuple of (category, description)
        - category: 'standard', 'handled', or 'unhandled'
        - description: Human-readable explanation

    Examples:
        >>> categorize_field('RepetitionTime', '0018,0080')
        ('standard', 'Standard DICOM field')
        >>> categorize_field('MultibandFactor', '')
        ('handled', 'Multiband acceleration factor (stored in ImageComments...)')
        >>> categorize_field('CustomField', '')
        ('unhandled', 'Non-standard field with no encoding method')
    """
    # Check if it has a valid DICOM tag
    if field_tag and ',' in field_tag:
        try:
            parts = field_tag.strip('()').split(',')
            group = int(parts[0].strip(), 16)
            element = int(parts[1].strip(), 16)
            tag = (group, element)

            # Try to get keyword from pydicom
            try:
                keyword = pydicom.datadict.keyword_for_tag(tag)
                return ('standard', 'Standard DICOM field')
            except KeyError:
                # Private tag but still has a tag number
                return ('standard', 'Private DICOM tag')
        except (ValueError, IndexError):
            pass

    # Check if it's a handled special field
    if field_name in HANDLED_SPECIAL_FIELDS:
        return ('handled', HANDLED_SPECIAL_FIELDS[field_name]['description'])

    # Unhandled
    return ('unhandled', 'Non-standard field with no encoding method')


def categorize_fields(
    field_definitions: List[Dict[str, str]]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Categorize all fields in a list.

    Args:
        field_definitions: List of field metadata with 'name', 'tag', etc.

    Returns:
        Dictionary with keys 'standard', 'handled', 'unhandled', each containing
        a list of field info dictionaries with 'name', 'tag', 'category', 'description'

    Example:
        >>> fields = [
        ...     {'name': 'RepetitionTime', 'tag': '0018,0080'},
        ...     {'name': 'MultibandFactor', 'tag': ''},
        ...     {'name': 'UnknownField', 'tag': ''}
        ... ]
        >>> result = categorize_fields(fields)
        >>> len(result['standard'])
        1
        >>> len(result['handled'])
        1
        >>> len(result['unhandled'])
        1
    """
    categorized = {
        'standard': [],
        'handled': [],
        'unhandled': []
    }

    for field_def in field_definitions:
        field_name = field_def.get('name', '')
        field_tag = field_def.get('tag', '')

        category, description = categorize_field(field_name, field_tag)

        categorized[category].append({
            **field_def,
            'category': category,
            'description': description
        })

    return categorized


def encode_multiband_in_image_comments(
    multiband_factor: int,
    phase_encoding_shift: int = None,
    leak_block: bool = False
) -> str:
    """
    Encode multiband information in ImageComments field following CMRR convention.

    The CMRR multiband sequence encodes multiband info in ImageComments as:
    - "Unaliased MB{factor}/PE{shift}" for standard multiband
    - "Unaliased MB{factor}/PE{shift}/LB" for multiband with LeakBlock
    - "Single-band reference SENSE{factor}" for single-band reference images

    Args:
        multiband_factor: Multiband acceleration factor
        phase_encoding_shift: Phase encoding shift (default: factor-1 if not specified)
        leak_block: Whether LeakBlock is enabled

    Returns:
        ImageComments string in CMRR format

    Examples:
        >>> encode_multiband_in_image_comments(3)
        'Unaliased MB3/PE2'
        >>> encode_multiband_in_image_comments(3, 3)
        'Unaliased MB3/PE3'
        >>> encode_multiband_in_image_comments(4, 3, True)
        'Unaliased MB4/PE3/LB'
    """
    if multiband_factor <= 1:
        # Single-band or no multiband
        return f'Single-band reference SENSE{multiband_factor}'

    # Default PE shift is typically MB factor - 1
    if phase_encoding_shift is None:
        phase_encoding_shift = multiband_factor - 1

    comment = f'Unaliased MB{multiband_factor}/PE{phase_encoding_shift}'

    if leak_block:
        comment += '/LB'

    return comment


def apply_special_field_encoding(
    ds: pydicom.Dataset,
    field_values: Dict[str, Any]
) -> None:
    """
    Apply special field encoding to a DICOM dataset.

    Modifies the dataset in-place by encoding special fields using their
    designated encoding methods.

    Args:
        ds: pydicom Dataset to modify
        field_values: Dictionary of field names to values that need special encoding

    Example:
        >>> import pydicom
        >>> ds = pydicom.Dataset()
        >>> field_values = {'MultibandFactor': 3, 'PhaseEncodingShift': 3}
        >>> apply_special_field_encoding(ds, field_values)
        >>> ds.ImageComments
        'Unaliased MB3/PE3'
    """
    # Extract multiband-related fields
    multiband_factor = None
    phase_encoding_shift = None
    leak_block = False

    for field_name, value in field_values.items():
        if field_name in ['MultibandFactor', 'MultibandAccelerationFactor', 'ParallelReductionFactorOutOfPlane']:
            multiband_factor = int(value)
        elif field_name == 'PhaseEncodingShift':
            phase_encoding_shift = int(value)
        elif field_name == 'LeakBlock':
            leak_block = bool(value)

    # Encode multiband info in ImageComments
    if multiband_factor is not None:
        image_comments = encode_multiband_in_image_comments(
            multiband_factor,
            phase_encoding_shift,
            leak_block
        )
        ds.ImageComments = image_comments
        print(f"    Encoded MultibandFactor={multiband_factor} in ImageComments: '{image_comments}'")


def get_unhandled_field_warnings(
    field_definitions: List[Dict[str, str]],
    test_data: List[Dict[str, Any]]
) -> List[str]:
    """
    Generate warnings for unhandled fields that have data.

    Args:
        field_definitions: List of field metadata
        test_data: List of test data rows

    Returns:
        List of warning messages for fields that cannot be encoded

    Example:
        >>> field_defs = [
        ...     {'name': 'UnknownField', 'tag': ''},
        ...     {'name': 'AnotherUnknown', 'tag': ''}
        ... ]
        >>> test_data = [{'UnknownField': 123}]
        >>> warnings = get_unhandled_field_warnings(field_defs, test_data)
        >>> len(warnings)
        1
    """
    categorized = categorize_fields(field_definitions)
    unhandled_fields = categorized['unhandled']

    if not unhandled_fields or not test_data:
        return []

    # Check which unhandled fields actually have data
    fields_with_data = set()
    for row in test_data:
        for field in unhandled_fields:
            field_name = field['name']
            if field_name in row and row[field_name] is not None:
                fields_with_data.add(field_name)

    warnings = []
    for field_name in sorted(fields_with_data):
        warnings.append(
            f"'{field_name}' cannot be encoded in generated DICOMs (no standard tag or encoding method)"
        )

    return warnings