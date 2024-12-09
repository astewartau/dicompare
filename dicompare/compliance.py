from typing import List, Dict, Any, Tuple
from dicompare.validation import BaseValidationModel

def check_session_compliance(
        in_session: Dict[str, Dict[str, Any]],
        ref_session: Dict[str, Dict[str, Any]],
        series_map: Dict[Tuple[str, str], Tuple[str, str]]  # maps (acquisition, series) to (ref_acquisition, ref_series)
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against a reference session.

    Args:
        in_session (Dict): Input session data.
        ref_session (Dict): Reference session data.
        series_map (Dict): Mapping of input series to reference series.

    Returns:
        List[Dict[str, Any]]: List of compliance issues.
    """
    compliance_summary = []

    for ((ref_acq_name, ref_series_name), (in_acq_name, in_series_name)) in series_map.items():
        in_acq = in_session['acquisitions'].get(in_acq_name)
        if not in_acq:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "reference series": ref_series_name,
                "input acquisition": in_acq_name,
                "input series": in_series_name,
                "field": "Acquisition-Level Error",
                "value": None,
                "rule": "Input acquisition must be present.",
                "message": "Input acquisition not found.",
                "passed": "❌"
            })
            continue

        in_series = next((series for series in in_acq['series'] if series['name'] == in_series_name), None)
        if not in_series:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "reference series": ref_series_name,
                "input acquisition": in_acq_name,
                "input series": in_series_name,
                "field": "Series-Level Error",
                "value": None,
                "rule": "Input series must be present.",
                "message": "Input series not found.",
                "passed": "❌"
            })
            continue

        ref_acq = ref_session["acquisitions"].get(ref_acq_name, {})
        ref_series = next(
            (series for series in ref_acq.get("series", []) if series["name"] == ref_series_name), {}
        )

        in_dicom_values = in_acq.get("fields", []) + in_series.get("fields", [])
        in_dicom_values_dict = {field["field"]: field["value"] for field in in_dicom_values}

        compliance_summary_i = check_dicom_compliance(
            reference_fields=ref_series.get("fields", []),
            dicom_values=in_dicom_values_dict
        )

        for summary in compliance_summary_i:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "reference series": ref_series_name,
                "input acquisition": in_acq_name,
                "input series": in_series_name,
                "field": summary["field"],
                "value": summary["value"],
                "rule": summary["rule"],
                "message": summary["message"],
                "passed": summary["passed"]
            })

    return compliance_summary

def check_session_compliance_python_module(
        in_session: Dict[str, Dict[str, Any]],
        ref_models: Dict[str, BaseValidationModel],
        acquisition_map: Dict[str, str],  # Maps reference acquisitions to input acquisitions
        raise_errors: bool = False
) -> List[Dict[str, Any]]:
    
    compliance_summary = []

    for ref_acq_name, in_acq_name in acquisition_map.items():
        in_acq = in_session['acquisitions'].get(in_acq_name)
        if not in_acq:
            raise ValueError(f"Input acquisition '{in_acq_name}' not found.")

        ref_model = ref_models.get(ref_acq_name)()
        if not ref_model:
            raise ValueError(f"No model found for reference acquisition '{ref_acq_name}'.")

        # Aggregate values
        aggregated_values = {}
        for series in in_acq.get("series", []):
            for field in series.get("fields", []):
                field_name = field['field']
                field_value = field['value']

                # Determine behavior: scalar or aggregate
                behavior = ref_model.reference_fields.get(field_name, "scalar")

                if behavior == "aggregate":
                    # Aggregate field values with deduplication
                    aggregated_values.setdefault(field_name, set()).add(field_value)
                elif behavior == "scalar":
                    # Validate scalar consistency
                    if field_name not in aggregated_values:
                        aggregated_values[field_name] = field_value
                    elif aggregated_values[field_name] != field_value:
                        compliance_summary.append({
                            "reference acquisition": ref_acq_name,
                            "reference series": None,
                            "input acquisition": in_acq_name,
                            "input series": None,
                            "field": field_name,
                            "value": aggregated_values[field_name],
                            "rule": "Values should be consistent across series.",
                            "message": f"Inconsistent values detected ({field_value} found).",
                            "passed": "❌"
                        })

        # Flatten aggregated fields to deduplicated lists
        for field, values in aggregated_values.items():
            if isinstance(values, set):
                aggregated_values[field] = sorted(values)  # Deduplicated and sorted list

        # Add acquisition-level fields
        for field in in_acq.get("fields", []):
            aggregated_values[field['field']] = field['value']

        # Validate using the reference model
        success, errors, passes = ref_model.validate(data=aggregated_values)

        # Record errors and passes
        for error in errors:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "reference series": None,
                "input acquisition": in_acq_name,
                "input series": None,
                "field": error['field'],
                "value": error['value'],
                "rule": error['rule'],
                "message": error['message'],
                "passed": "❌"
            })

        for passed_test in passes:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "reference series": None,
                "input acquisition": in_acq_name,
                "input series": None,
                "field": passed_test['field'],
                "value": passed_test['value'],
                "rule": passed_test['rule'],
                "message": passed_test['message'],
                "passed": "✅"
            })

        if raise_errors and not success:
            raise ValueError(f"Validation failed for acquisition '{in_acq_name}'.")

    return compliance_summary


def check_dicom_compliance(
    reference_fields: List[Dict[str, Any]],
    dicom_values: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM file against reference fields.

    Args:
        reference_fields (List[Dict[str, Any]]): List of fields with their expected values and rules.
        dicom_values (Dict[str, Any]): Actual DICOM values.

    Returns:
        List[Dict[str, Any]]: List of compliance issues.
    """
    compliance_summary = []

    for ref_field in reference_fields:
        field_name = ref_field["field"]
        expected_value = ref_field.get("value")
        tolerance = ref_field.get("tolerance")
        contains = ref_field.get("contains")
        actual_value = dicom_values.get(field_name, "N/A")

        # Convert lists to tuples for comparison
        if expected_value is not None and isinstance(expected_value, list):
            expected_value = tuple(expected_value)
        if actual_value is not None and isinstance(actual_value, list):
            actual_value = tuple(actual_value)

        # Check for missing field
        if actual_value == "N/A":
            compliance_summary.append({
                "field": field_name,
                "value": actual_value,
                "rule": "Field must be present.",
                "message": "Field not found.",
                "passed": "❌",
            })
            continue

        # Contains check
        if contains is not None:
            if not isinstance(actual_value, list) or contains not in actual_value:
                compliance_summary.append({
                    "field": field_name,
                    "value": actual_value,
                    "rule": "Field must contain value.",
                    "message": f"Expected to contain {contains}, got {actual_value}.",
                    "passed": "❌",
                })

        # Tolerance check
        elif tolerance is not None and isinstance(actual_value, (int, float)):
            if not (expected_value - tolerance <= actual_value <= expected_value + tolerance):
                compliance_summary.append({
                    "field": field_name,
                    "value": actual_value,
                    "rule": "Field must be within tolerance.",
                    "message": f"Expected {expected_value} ± {tolerance}, got {actual_value}.",
                    "passed": "❌",
                })

        # Exact match check
        elif expected_value is not None and actual_value != expected_value:
            compliance_summary.append({
                "field": field_name,
                "value": actual_value,
                "rule": "Field must match expected value.",
                "message": f"Expected {expected_value}, got {actual_value}.",
                "passed": "❌",
            })

    return compliance_summary

def is_session_compliant(
        in_session: Dict[str, Dict[str, Any]],
        ref_session: Dict[str, Dict[str, Any]],
        series_map: Dict[Tuple[str, str], Tuple[str, str]]
) -> bool:
    """
    Validate if the DICOM session is fully compliant with the reference session.

    Args:
        in_session (Dict): Input session data.
        ref_session (Dict): Reference session data.
        series_map (Dict): Mapping of input series to reference series.

    Returns:
        bool: True if compliant, False otherwise.
    """
    compliance_issues = check_session_compliance(in_session, ref_session, series_map)
    return len(compliance_issues) == 0


def is_dicom_compliant(
        reference_model: BaseValidationModel,
        dicom_values: Dict[str, Any]
) -> bool:
    
    """Validate a DICOM file against the reference model.

    Args:
        reference_model (BaseValidationModel): The reference model for validation.
        dicom_values (Dict[str, Any]): The DICOM values to validate.

    Returns:
        is_compliant (bool): True if the DICOM values are compliant with the reference model.
    """

    compliance_issues = check_dicom_compliance(
        reference_model.fields,
        dicom_values
    )

    return len(compliance_issues) == 0
