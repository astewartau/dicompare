from pydantic import ValidationError, BaseModel
from typing import List, Dict, Any, Tuple

def check_session_compliance(
        in_session: Dict[str, Dict[str, Any]],
        ref_session: Dict[str, Dict[str, Any]],
        series_map: Dict[Tuple[str, str], Tuple[str, str]], # maps (acquisition, series) to (ref_acquisition, ref_series)
        raise_errors: bool = False
) -> List[Dict[str, Any]]:
    
    """Validate a DICOM session against a reference session."""
    compliance_summary = []

    for ((in_acq_name, in_series_name), (ref_acq_name, ref_series_name)) in series_map.items():
        in_acq = in_session['acquisitions'].get(in_acq_name)
        in_series = next((series for series in in_acq['series'] if series['name'] == in_series_name), None)
        ref_acq = ref_session['acquisitions'].get(ref_acq_name)
        ref_series = next((series for series in ref_acq['series'] if series['name'] == ref_series_name), None)

        in_dicom_values = in_acq.get("fields") + in_series.get("fields")
        in_dicom_values_dict = {field['field']: field['value'] for field in in_dicom_values}

        compliance_summary += check_dicom_compliance(ref_series.get("model"), in_dicom_values_dict, in_acq_name, in_series_name, raise_errors)

    return compliance_summary
    
def check_dicom_compliance(
        reference_model: BaseModel,
        dicom_values: Dict[str, Any],
        acquisition: str = None,
        series: str = None,
        raise_errors: bool = False
) -> List[Dict[str, Any]]:
    
    """Validate a DICOM file against the reference model."""
    compliance_summary = []

    try:
        model_instance = reference_model(**dicom_values)
    except ValidationError as e:
        if raise_errors:
            raise e
        for error in e.errors():
            param = error['loc'][0] if error['loc'] else "Model-Level Error"
            expected = (error['ctx'].get('expected') if 'ctx' in error else None) or error['msg']
            if isinstance(expected, str) and expected.startswith("'") and expected.endswith("'"):
                expected = expected[1:-1]
            actual = dicom_values.get(param, "N/A") if param != "Model-Level Error" else "N/A"
            compliance_summary.append({
                "Acquisition": acquisition,
                "Series": series,
                "Parameter": param,
                "Value": actual,
                "Expected": expected
            })

    return compliance_summary

def is_session_compliant(
        in_session: Dict[str, Dict[str, Any]],
        ref_session: Dict[str, Dict[str, Any]],
        series_map: Dict[Tuple[str, str], Tuple[str, str]]
) -> bool:
    
    """Validate a DICOM session against a reference session."""
    is_compliant = True

    for ((in_acq_name, in_series_name), (ref_acq_name, ref_series_name)) in series_map.items():
        in_acq = in_session['acquisitions'].get(in_acq_name)
        in_series = next((series for series in in_acq['series'] if series['name'] == in_series_name), None)
        ref_acq = ref_session['acquisitions'].get(ref_acq_name)
        ref_series = next((series for series in ref_acq['series'] if series['name'] == ref_series_name), None)

        in_dicom_values = in_acq.get("fields") + in_series.get("fields")
        in_dicom_values_dict = {field['field']: field['value'] for field in in_dicom_values}

        is_compliant = is_compliant and is_dicom_compliant(ref_series.get("model"), in_dicom_values_dict)

    return is_compliant

def is_dicom_compliant(
        reference_model: BaseModel,
        dicom_values: Dict[str, Any]
) -> bool:
    
    """Validate a DICOM file against the reference model.

    Args:
        reference_model (BaseModel): The reference model for validation.
        dicom_values (Dict[str, Any]): The DICOM values to validate.

    Returns:
        is_compliant (bool): True if the DICOM values are compliant with the reference model.
    """
    is_compliant = True

    try:
        model_instance = reference_model(**dicom_values)
    except ValidationError as e:
        is_compliant = False

    return is_compliant

