"""
Backwards-compatible facade for the web/UI interface.

The implementation moved into focused modules (session_analysis, protocols,
schema_tools); every name historically importable from this module is
re-exported here. New code should import from ``dicompare.interface``.
"""

from .session_analysis import (
    _analyze_dicom_session_core,
    analyze_dicom_files_for_web,
    analyze_dicom_files_for_ui,
    validate_acquisition_direct,
)
from .protocols import (
    load_protocol_for_ui,
    load_gradient_file_for_ui,
    attach_gradient_files_to_acquisitions,
    _gradient_file_kind,
    _gradient_base_name,
    _acq_field_value,
    _is_diffusion_acquisition,
    _merge_descriptor_fields,
)
# Historically re-exported through this module's namespace.
from ..io import make_json_serializable

from .schema_tools import (
    search_dicom_dictionary,
    build_schema_from_ui_acquisitions,
    run_rule_test_case,
)
