__version__ = "0.1.26"

# Import core functionalities
from .io import get_dicom_values, load_dicom, load_json_schema, load_dicom_session, async_load_dicom_session, load_nifti_session, load_python_schema, assign_acquisition_and_run_numbers, load_pro_file, load_pro_session, async_load_pro_session
from .compliance import check_session_compliance_with_json_schema, check_session_compliance_with_python_module
from .mapping import map_to_json_reference, interactive_mapping_to_json_reference, interactive_mapping_to_python_reference
from .validation import BaseValidationModel, ValidationError, validator

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
from .compliance_session import ComplianceSession
