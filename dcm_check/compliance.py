from pydantic import ValidationError, BaseModel
from typing import List, Dict, Any, Tuple

def check_session_compliance(
        in_session: Dict[str, Dict[str, Any]],
        ref_models: Dict[Tuple[str, str], BaseModel],
        series_map: Dict[Tuple[str, str], Tuple[str, str]],  # maps (acquisition, series) to (ref_acquisition, ref_series)
        raise_errors: bool = False
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against a reference session using pre-built models.
    """
    compliance_summary = []

    for ((ref_acq_name, ref_series_name), (in_acq_name, in_series_name)) in series_map.items():
        in_acq = in_session['acquisitions'].get(in_acq_name)
        in_series = next((series for series in in_acq['series'] if series['name'] == in_series_name), None)
        ref_model = ref_models.get((ref_acq_name, ref_series_name))

        if not ref_model:
            raise ValueError(f"No model found for reference acquisition '{ref_acq_name}' and series '{ref_series_name}'.")

        in_dicom_values = in_acq.get("fields", []) + in_series.get("fields", [])
        in_dicom_values_dict = {field['field']: field['value'] for field in in_dicom_values}

        compliance_summary += check_dicom_compliance(ref_model, in_dicom_values_dict, in_acq_name, in_series_name, raise_errors)

    return compliance_summary
    
def check_session_compliance_python_module(
        in_session: Dict[str, Dict[str, Any]],
        ref_models: Dict[str, BaseModel],
        acquisition_map: Dict[str, str],  # Maps reference acquisitions to input acquisitions
        raise_errors: bool = False
) -> List[Dict[str, Any]]:
    compliance_summary = []

    for ref_acq_name, in_acq_name in acquisition_map.items():
        in_acq = in_session['acquisitions'].get(in_acq_name)
        if not in_acq:
            compliance_summary.append({
                "Reference Acquisition": ref_acq_name,
                "Input Acquisition": in_acq_name,
                "Parameter": "Acquisition-Level Error",
                "Value": "Missing",
                "Expected": "Present"
            })
            continue

        ref_model = ref_models.get(ref_acq_name)
        if not ref_model:
            raise ValueError(f"No model found for reference acquisition '{ref_acq_name}'.")

        field_behaviors = getattr(ref_model, "field_behaviors", {})

        aggregated_values = {}
        for series in in_acq.get("series", []):
            for field in series.get("fields", []):
                field_name = field['field']
                field_value = field['value']

                behavior = field_behaviors.get(field_name, "scalar")  # Default to scalar if unspecified
                if behavior == "aggregate":
                    if field_name not in aggregated_values:
                        aggregated_values[field_name] = []
                    aggregated_values[field_name].append(field_value)
                elif behavior == "scalar":
                    if field_name not in aggregated_values:
                        aggregated_values[field_name] = field_value
                    elif aggregated_values[field_name] != field_value:
                        compliance_summary.append({
                            "Acquisition": in_acq_name,
                            "Parameter": field_name,
                            "Value": aggregated_values[field_name],
                            "Expected": f"Consistent value across all series ({field_value} found)"
                        })

        flattened_values = {
            k: v[0] if isinstance(v, list) and len(v) == 1 else v
            for k, v in aggregated_values.items()
        }

        for field in in_acq.get("fields", []):
            flattened_values[field['field']] = field['value']

        try:
            ref_model(**flattened_values)
        except ValidationError as e:
            if raise_errors:
                raise e
            for error in e.errors():
                param = error['loc'][0] if error['loc'] else "Model-Level Error"
                param_i = error['loc'][1] if len(error['loc']) > 1 else ""
                expected = (error['ctx'].get('expected') if 'ctx' in error else None) or error['msg']
                if isinstance(expected, str) and expected.startswith("'") and expected.endswith("'"):
                    expected = expected[1:-1]
                actual = flattened_values.get(param, "N/A") if param != "Model-Level Error" else "N/A"
                compliance_summary.append({
                    "Acquisition": in_acq_name,
                    "Parameter": param + (f"[{param_i}]" if param_i != "" else ""),
                    "Value": actual[param_i] if param_i != "" else actual,
                    "Expected": expected
                })

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
        ref_models: Dict[Tuple[str, str], BaseModel],
        series_map: Dict[Tuple[str, str], Tuple[str, str]]
) -> bool:
    """
    Validate a DICOM session against a reference session using pre-built models.
    """
    is_compliant = True

    for ((in_acq_name, in_series_name), (ref_acq_name, ref_series_name)) in series_map.items():
        in_acq = in_session['acquisitions'].get(in_acq_name)
        in_series = next((series for series in in_acq['series'] if series['name'] == in_series_name), None)
        ref_model = ref_models.get((ref_acq_name, ref_series_name))

        if not ref_model:
            raise ValueError(f"No model found for reference acquisition '{ref_acq_name}' and series '{ref_series_name}'.")

        in_dicom_values = in_acq.get("fields", []) + in_series.get("fields", [])
        in_dicom_values_dict = {field['field']: field['value'] for field in in_dicom_values}

        is_compliant = is_compliant and is_dicom_compliant(ref_model, in_dicom_values_dict)

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

