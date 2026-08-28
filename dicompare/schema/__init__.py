"""
Schema module for dicompare.

This module provides schema generation, linting, and DICOM tag information
for DICOM session validation and analysis.
"""

from .build_schema import (
    build_schema
)

from .lint import (
    lint_schema,
    format_findings,
    LintFinding,
)

from .tags import (
    get_tag_info,
    get_all_tags_in_dataset,
    determine_field_type_from_values,
    # Internal tables, kept importable for backwards compatibility but no
    # longer part of the curated API.
    FIELD_TO_KEYWORD_MAP,
    PRIVATE_TAGS,
    VR_TO_DATA_TYPE
)

__all__ = [
    # Schema generation
    'build_schema',

    # Schema linting
    'lint_schema',
    'format_findings',
    'LintFinding',

    # Tag utilities
    'get_tag_info',
    'get_all_tags_in_dataset',
    'determine_field_type_from_values',
]
