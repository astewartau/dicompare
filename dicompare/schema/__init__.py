"""
Schema module for dicompare.

This module provides schema generation utilities and DICOM tag information
for DICOM session validation and analysis.
"""

from .build_schema import (
    build_schema
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
    'build_schema',

    # Tag utilities
    'get_tag_info',
    'get_all_tags_in_dataset',
    'determine_field_type_from_values',
    'FIELD_TO_KEYWORD_MAP',
    'PRIVATE_TAGS',
    'VR_TO_DATA_TYPE'
]