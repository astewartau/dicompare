__version__ = "0.1.7"

# Import core functionalities
from .io import get_dicom_values, load_dicom, read_json_session, read_dicom_session, load_python_module
from .compliance import check_dicom_compliance, is_dicom_compliant, check_session_compliance, is_session_compliant, check_session_compliance_python_module
from .mapping import calculate_field_score, calculate_match_score, map_session, interactive_mapping
from .utils import clean_string, infer_type_from_extension

