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
    get_dicom_values,
    load_dicom,
    load_dicom_session,
    async_load_dicom_session,
    load_nifti_session,
    assign_acquisition_and_run_numbers,
)

# JSON/Schema I/O functions
from .json import (
    load_json_schema,
    load_hybrid_schema,
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
try:
    from .pro import (
        load_pro_file,
        load_pro_file_schema_format,
        load_pro_session,
        async_load_pro_session,
        parse_protocol_parameters,
        extract_from_xprotocol,
    )
except ImportError:
    def load_pro_file(*args, **kwargs):
        raise ImportError("twixtools is required for PRO file parsing. Install with: pip install twixtools")
    def load_pro_file_schema_format(*args, **kwargs):
        raise ImportError("twixtools is required for PRO file parsing. Install with: pip install twixtools")
    def load_pro_session(*args, **kwargs):
        raise ImportError("twixtools is required for PRO file parsing. Install with: pip install twixtools")
    def async_load_pro_session(*args, **kwargs):
        raise ImportError("twixtools is required for PRO file parsing. Install with: pip install twixtools")
    parse_protocol_parameters = None
    extract_from_xprotocol = None

__all__ = [
    # DICOM I/O
    "extract_inferred_metadata",
    "extract_csa_metadata",
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
    "load_json_schema",
    "load_hybrid_schema",
    "make_json_serializable",
    # PRO file support
    "load_pro_file",
    "load_pro_file_schema_format",
    "load_pro_session",
    "async_load_pro_session",
    "parse_protocol_parameters",
    "extract_from_xprotocol",
]