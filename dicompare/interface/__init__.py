"""
Interface module for dicompare.

This module provides user interface utilities including web interfaces,
visualization, and data preparation for external consumption.
"""

from .web_utils import (
    analyze_dicom_files_for_web,
    analyze_dicom_files_for_ui,
    validate_acquisition_for_ui,
    validate_acquisition_direct,
    load_protocol_for_ui,
    search_dicom_dictionary,
    build_schema_from_ui_acquisitions,
    format_compliance_results_for_web,
)

__all__ = [
    # Web utilities
    'analyze_dicom_files_for_web',
    'analyze_dicom_files_for_ui',
    'validate_acquisition_for_ui',
    'validate_acquisition_direct',
    'load_protocol_for_ui',
    'search_dicom_dictionary',
    'build_schema_from_ui_acquisitions',
    'format_compliance_results_for_web',
]