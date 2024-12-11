from typing import List, Dict, Any, Tuple
from dicompare.validation import BaseValidationModel
import pandas as pd

def check_session_compliance(
    in_session: pd.DataFrame,
    ref_session: Dict[str, Any],
    session_map: Dict[Tuple[str, str], Tuple[str, str]]  # Maps (input_acquisition, input_series) to (ref_acquisition, ref_series)
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against a reference session.

    Args:
        in_session (pd.DataFrame): Input session DataFrame as returned by `load_dicom_session`.
        ref_session (Dict[str, Any]): Reference session dictionary as returned by `load_json_session`.
        session_map (Dict[Tuple[str, str], Tuple[str, str]]): Mapping of input acquisitions and series to reference acquisitions and series.

    Returns:
        List[Dict[str, Any]]: List of compliance issues.
    """
    compliance_summary = []

    # Iterate over the session mapping
    for (in_acq_name, in_series_name), (ref_acq_name, ref_series_name) in session_map.items():
        # Filter the input session for the current acquisition and series
        in_acq_series = in_session[
            (in_session["Acquisition"] == in_acq_name) & 
            (in_session["Series"] == in_series_name)
        ]

        if in_acq_series.empty:
            compliance_summary.append({
                "reference acquisition": (ref_acq_name, ref_series_name),
                "input acquisition": (in_acq_name, in_series_name),
                "field": "Acquisition-Level Error",
                "value": None,
                "rule": "Input acquisition and series must be present.",
                "message": "Input acquisition or series not found.",
                "passed": "❌"
            })
            continue

        # Filter the reference session for the current acquisition and series
        ref_acq = ref_session["acquisitions"].get(ref_acq_name, {})
        ref_series = next(
            (series for series in ref_acq.get("series", []) if series["name"] == ref_series_name),
            None
        )

        if not ref_series:
            compliance_summary.append({
                "reference acquisition": (ref_acq_name, ref_series_name),
                "input acquisition": (in_acq_name, in_series_name),
                "field": "Reference-Level Error",
                "value": None,
                "rule": "Reference acquisition and series must be present.",
                "message": "Reference acquisition or series not found.",
                "passed": "❌"
            })
            continue

        # Iterate through the reference fields and check compliance
        for ref_field in ref_series.get("fields", []):
            field_name = ref_field["field"]
            expected_value = ref_field.get("value")
            tolerance = ref_field.get("tolerance")
            contains = ref_field.get("contains")

            # Check the corresponding field in the input session DataFrame
            if field_name not in in_acq_series.columns:
                compliance_summary.append({
                    "reference acquisition": (ref_acq_name, ref_series_name),
                    "input acquisition": (in_acq_name, in_series_name),
                    "field": field_name,
                    "value": None,
                    "rule": "Field must be present.",
                    "message": "Field not found in input session.",
                    "passed": "❌"
                })
                continue

            actual_value = in_acq_series[field_name].iloc[0]

            # Contains check
            if contains is not None:
                if not isinstance(actual_value, list) or contains not in actual_value:
                    compliance_summary.append({
                        "reference acquisition": (ref_acq_name, ref_series_name),
                        "input acquisition": (in_acq_name, in_series_name),
                        "field": field_name,
                        "value": actual_value,
                        "rule": "Field must contain value.",
                        "message": f"Expected to contain {contains}, got {actual_value}.",
                        "passed": "❌"
                    })

            # Tolerance check
            elif tolerance is not None and isinstance(actual_value, (int, float)):
                if not (expected_value - tolerance <= actual_value <= expected_value + tolerance):
                    compliance_summary.append({
                        "reference acquisition": (ref_acq_name, ref_series_name),
                        "input acquisition": (in_acq_name, in_series_name),
                        "field": field_name,
                        "value": actual_value,
                        "rule": "Field must be within tolerance.",
                        "message": f"Expected {expected_value} ± {tolerance}, got {actual_value}.",
                        "passed": "❌"
                    })

            # Exact match check
            elif expected_value is not None and actual_value != expected_value:
                compliance_summary.append({
                    "reference acquisition": (ref_acq_name, ref_series_name),
                    "input acquisition": (in_acq_name, in_series_name),
                    "field": field_name,
                    "value": actual_value,
                    "rule": "Field must match expected value.",
                    "message": f"Expected {expected_value}, got {actual_value}.",
                    "passed": "❌"
                })

    return compliance_summary
def check_session_compliance_python_module(
    in_session: pd.DataFrame,
    ref_models: Dict[str, BaseValidationModel],
    session_map: Dict[str, str],  # Maps reference acquisitions to input acquisitions
    raise_errors: bool = False
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against reference models defined in a Python module.

    Args:
        in_session (pd.DataFrame): Input session DataFrame as returned by `load_dicom_session`.
        ref_models (Dict[str, BaseValidationModel]): Reference models loaded from a Python module.
        session_map (Dict[str, str]): Mapping of reference acquisitions to input acquisitions.
        raise_errors (bool): If True, raise an exception when validation fails.

    Returns:
        List[Dict[str, Any]]: Compliance summary with validation results.
    """
    compliance_summary = []

    for ref_acq_name, in_acq_name in session_map.items():
        # Filter the input session for the current acquisition
        in_acq = in_session[in_session["Acquisition"] == in_acq_name]

        if in_acq.empty:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "field": "Acquisition-Level Error",
                "value": None,
                "rule": "Input acquisition must be present.",
                "message": f"Input acquisition '{in_acq_name}' not found.",
                "passed": "❌"
            })
            continue

        # Retrieve reference model
        ref_model_cls = ref_models.get(ref_acq_name)
        if not ref_model_cls:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "field": "Model Error",
                "value": None,
                "rule": "Reference model must exist.",
                "message": f"No model found for reference acquisition '{ref_acq_name}'.",
                "passed": "❌"
            })
            continue
        ref_model = ref_model_cls()  # Instantiate the validation model

        # Prepare acquisition data as a single DataFrame
        acquisition_df = in_acq.copy()

        # Validate using the reference model
        success, errors, passes = ref_model.validate(data=acquisition_df)

        # Record errors
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

        # Record passes
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

        # Raise an error if validation fails and `raise_errors` is True
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
        session_map: Dict[Tuple[str, str], Tuple[str, str]]
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
    compliance_issues = check_session_compliance(in_session, ref_session, session_map)
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
