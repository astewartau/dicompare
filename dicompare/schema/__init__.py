"""
Schema module for dicompare.

This module provides schema generation utilities and DICOM tag information
for DICOM session validation and analysis.
"""

from .generate_schema import (
    create_json_schema,
    detect_acquisition_variability,
    create_acquisition_summary
)

from .tags import (
    get_tag_info,
    get_all_tags_in_dataset,
    determine_field_type_from_values,
    FIELD_TO_KEYWORD_MAP,
    PRIVATE_TAGS,
    VR_TO_DATA_TYPE
)

__all__ = [
    # Schema generation
    'create_json_schema',
    'detect_acquisition_variability',
    'create_acquisition_summary',

    # Tag utilities
    'get_tag_info',
    'get_all_tags_in_dataset',
    'determine_field_type_from_values',
    'FIELD_TO_KEYWORD_MAP',
    'PRIVATE_TAGS',
    'VR_TO_DATA_TYPE'
]