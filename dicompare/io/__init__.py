"""
I/O operations for dicompare package.

This module contains functions for loading and processing various data formats:
- DICOM files and sessions
- Siemens .pro protocol files
- JSON schema files
- NIfTI files
- Data serialization utilities
"""

# DICOM I/O functions
from .dicom import (
    extract_inferred_metadata,
    extract_csa_metadata,
    extract_ascconv,
    get_ascconv_value,
    get_dicom_values,
    load_dicom,
    load_dicom_session,
    async_load_dicom_session,
    load_nifti_session,
    assign_acquisition_and_run_numbers,
)

# JSON/Schema I/O functions
from .json import (
    load_schema,
    validate_schema,
    make_json_serializable,
)

# DICOM generation
from .dicom_generator import (
    generate_test_dicoms_from_schema,
    generate_test_dicoms_from_schema_json,
)

# Special field handling
from .special_fields import (
    categorize_field,
    categorize_fields,
    get_unhandled_field_warnings,
    get_field_categorization_summary,
)

# Siemens .pro file parsing
from .pro import (
    load_pro_file,
    load_pro_file_schema_format,
    load_pro_session,
)

# Siemens .exar1 file parsing
from .pro import (
    load_exar_file,
    load_exar_session,
    extract_protocols_from_exar,
)

__all__ = [
    # DICOM I/O
    "extract_inferred_metadata",
    "extract_csa_metadata",
    "extract_ascconv",
    "get_ascconv_value",
    "get_dicom_values",
    "load_dicom",
    "load_dicom_session",
    "async_load_dicom_session",
    "load_nifti_session",
    "assign_acquisition_and_run_numbers",
    # DICOM generation
    "generate_test_dicoms_from_schema",
    "generate_test_dicoms_from_schema_json",
    # Special field handling
    "categorize_field",
    "categorize_fields",
    "get_unhandled_field_warnings",
    "get_field_categorization_summary",
    # JSON/Schema I/O
    "load_schema",
    "validate_schema",
    "make_json_serializable",
    # PRO file support
    "load_pro_file",
    "load_pro_file_schema_format",
    "load_pro_session",
    # EXAR file support
    "load_exar_file",
    "load_exar_session",
    "extract_protocols_from_exar",
]