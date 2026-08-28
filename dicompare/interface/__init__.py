"""
Interface module for dicompare.

This module provides user interface utilities including web interfaces,
visualization, and data preparation for external consumption.
"""

from .session_analysis import (
    analyze_dicom_files_for_ui,
    validate_acquisition_direct,
)
from .protocols import (
    load_protocol_for_ui,
    load_gradient_file_for_ui,
    attach_gradient_files_to_acquisitions,
)
from .schema_tools import (
    search_dicom_dictionary,
    build_schema_from_ui_acquisitions,
    run_rule_test_case,
)

__all__ = [
    # Web utilities
    'analyze_dicom_files_for_ui',
    'validate_acquisition_direct',
    'load_protocol_for_ui',
    'load_gradient_file_for_ui',
    'attach_gradient_files_to_acquisitions',
    'search_dicom_dictionary',
    'build_schema_from_ui_acquisitions',
    'run_rule_test_case',
]