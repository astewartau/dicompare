__version__ = "0.1.43"

# Import core functionalities
from .io import get_dicom_values, load_dicom, load_schema, validate_schema, load_dicom_session, async_load_dicom_session, load_nifti_session, load_pro_file, load_pro_session, generate_test_dicoms_from_schema, generate_test_dicoms_from_schema_json, load_pro_file_schema_format, load_exar_file, load_exar_session, load_examcard_file, load_examcard_file_all_scans, load_examcard_file_schema_format, load_examcard_session, load_lxprotocol_file, load_lxprotocol_file_schema_format, load_lxprotocol_session
from .validation import check_acquisition_compliance
from .session import assign_acquisition_and_run_numbers
from .session import map_to_json_reference, interactive_mapping_to_json_reference
from .validation import BaseValidationModel, ValidationError, ValidationWarning, validator, safe_exec_rule, create_validation_model_from_rules, create_validation_models_from_rules
from .config import DEFAULT_SETTINGS_FIELDS, DEFAULT_ACQUISITION_FIELDS, DEFAULT_DICOM_FIELDS
from .schema import get_tag_info, get_all_tags_in_dataset

# Import enhanced functionality for web interfaces
from .schema import build_schema, determine_field_type_from_values
from .io import make_json_serializable
from .utils import detect_constant_fields, clean_string, make_hashable
from .interface import (
    analyze_dicom_files_for_web,
    analyze_dicom_files_for_ui,
    validate_acquisition_for_ui,
    load_protocol_for_ui,
    search_dicom_dictionary,
    build_schema_from_ui_acquisitions,
    format_compliance_results_for_web,
)
