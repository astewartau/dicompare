__version__ = "0.1.37"

# Import core functionalities
from .io import get_dicom_values, load_dicom, load_json_schema, load_dicom_session, async_load_dicom_session, load_nifti_session, load_hybrid_schema, load_pro_file, load_pro_session, generate_test_dicoms_from_schema, generate_test_dicoms_from_schema_json, load_pro_file_schema_format
from .validation import check_acquisition_compliance
from .session import assign_acquisition_and_run_numbers
from .session import map_to_json_reference, interactive_mapping_to_json_reference
from .validation import BaseValidationModel, ValidationError, ValidationWarning, validator, safe_exec_rule, create_validation_model_from_rules, create_validation_models_from_rules
from .config import DEFAULT_SETTINGS_FIELDS, DEFAULT_ACQUISITION_FIELDS, DEFAULT_DICOM_FIELDS
from .schema import get_tag_info, get_all_tags_in_dataset

# Import enhanced functionality for web interfaces
from .schema import create_json_schema, detect_acquisition_variability, create_acquisition_summary
from .io import make_json_serializable
from .utils import filter_available_fields, detect_constant_fields, clean_string, make_hashable
from .interface import (
    analyze_dicom_files_for_web,
)
