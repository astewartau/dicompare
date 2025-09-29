__version__ = "0.1.31"

# Import core functionalities
from .io import get_dicom_values, load_dicom, load_json_schema, load_dicom_session, async_load_dicom_session, load_nifti_session, load_python_schema, load_hybrid_schema, assign_acquisition_and_run_numbers, load_pro_file, load_pro_session, async_load_pro_session
try:
    from .pro_parser import load_pro_file_schema_format
except ImportError:
    def load_pro_file_schema_format(*args, **kwargs):
        raise ImportError("twixtools is required for PRO file parsing. Install with: pip install twixtools")
from .compliance import check_session_compliance_with_json_schema, check_session_compliance_with_python_module, check_session_compliance
from .mapping import map_to_json_reference, interactive_mapping_to_json_reference, interactive_mapping_to_python_reference
from .validation import BaseValidationModel, ValidationError, ValidationWarning, validator, safe_exec_rule, create_validation_model_from_rules, create_validation_models_from_rules
from .config import DEFAULT_SETTINGS_FIELDS, DEFAULT_ACQUISITION_FIELDS, DEFAULT_DICOM_FIELDS
from .tags import get_tag_info, get_all_tags_in_dataset

# Import enhanced functionality for web interfaces
from .generate_schema import create_json_schema, detect_acquisition_variability, create_acquisition_summary
from .serialization import make_json_serializable
from .utils import filter_available_fields, detect_constant_fields, clean_string, make_hashable
from .web_utils import (
    prepare_session_for_web, format_compliance_results_for_web, 
    create_field_selection_helper, prepare_schema_generation_data,
    format_validation_error_for_web, convert_pyodide_data, create_download_data
)
from .visualization import (
    extract_center_slice_data, prepare_slice_for_canvas, 
    get_acquisition_preview_data, analyze_image_characteristics
)
