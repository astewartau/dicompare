"""
This module provides functions for validating a DICOM sessions.

The module supports compliance checks for JSON-based reference sessions and Python module-based validation models.

"""

from typing import List, Dict, Any, Tuple
from dicompare.validation import BaseValidationModel
import pandas as pd

def check_session_compliance_with_json_reference(
    in_session: pd.DataFrame,
    ref_session: Dict[str, Any],
    session_map: Dict[Tuple[str, str], Tuple[str, str]]
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against a JSON reference session.

    Args:
        in_session (pd.DataFrame): Input session DataFrame containing DICOM metadata.
        ref_session (Dict[str, Any]): Reference session data loaded from a JSON file.
        session_map (Dict[Tuple[str, str], Tuple[str, str]]): Mapping of input acquisitions/series 
            to reference acquisitions/series.

    Returns:
        List[Dict[str, Any]]: A list of compliance issues, where each issue is represented as a dictionary.
    """

    def check_fields(in_data, in_name, ref_series, ref_name):
        summary = []
        ref_fields = ref_series.get("fields", [])
        for ref_field in ref_fields:
            field_name = ref_field["field"]
            expected_value = ref_field.get("value")
            tolerance = ref_field.get("tolerance")
            contains = ref_field.get("contains")

            # Check the corresponding field in the input session DataFrame
            if field_name not in in_data.columns:
                summary.append({
                    "reference acquisition": ref_name,
                    "input acquisition": in_name,
                    "field": field_name,
                    "value": None,
                    "rule": "Field must be present.",
                    "message": "Field not found in input session.",
                    "passed": "❌"
                })
                continue

            actual_value = in_data[field_name].iloc[0]

            # Contains check
            if contains is not None:
                if contains not in actual_value:
                    summary.append({
                        "reference acquisition": ref_name,
                        "input acquisition": in_name,
                        "field": field_name,
                        "value": actual_value,
                        "rule": "Field must contain value.",
                        "message": f"Expected to contain {contains}, got {actual_value}.",
                        "passed": "❌"
                    })

            # Tolerance check
            elif tolerance is not None and isinstance(actual_value, (int, float)):
                if not (expected_value - tolerance <= actual_value <= expected_value + tolerance):
                    summary.append({
                        "reference acquisition": ref_name,
                        "input acquisition": in_name,
                        "field": field_name,
                        "value": actual_value,
                        "rule": "Field must be within tolerance.",
                        "message": f"Expected {expected_value} ± {tolerance}, got {actual_value}.",
                        "passed": "❌"
                    })

            # Exact match check
            elif expected_value is not None and actual_value != expected_value:
                summary.append({
                    "reference acquisition": ref_name,
                    "input acquisition": in_name,
                    "field": field_name,
                    "value": actual_value,
                    "rule": "Field must match expected value.",
                    "message": f"Expected {expected_value}, got {actual_value}.",
                    "passed": "❌"
                })
        return summary
    
    compliance_summary = []

    for ref_acq_name, in_acq_name in list(set([(ref[0], in_[0]) for ref, in_ in session_map.items()])):
        in_acq = in_session[in_session["Acquisition"] == in_acq_name]
        ref_acq = ref_session['acquisitions'].get(ref_acq_name)

        if in_acq.empty:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "field": "Acquisition-Level Error",
                "value": None,
                "rule": "Input acquisition must be present.",
                "message": "Input acquisition not found.",
                "passed": "❌"
            })
            continue

        compliance_summary.extend(check_fields(in_acq, in_acq_name, ref_acq, ref_acq_name))

    # Iterate over the session mapping
    for (ref_acq_name, ref_series_name), (in_acq_name, in_series_name) in session_map.items():
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

        compliance_summary.extend(check_fields(in_acq_series, f"{in_acq_name}::{in_series_name}", ref_series, f"{ref_acq_name}::{ref_series_name}"))

    return compliance_summary

def check_session_compliance_with_python_module(
    in_session: pd.DataFrame,
    ref_models: Dict[str, BaseValidationModel],
    session_map: Dict[str, str],
    raise_errors: bool = False
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against Python module-based validation models.

    Args:
        in_session (pd.DataFrame): Input session DataFrame containing DICOM metadata.
        ref_models (Dict[str, BaseValidationModel]): Dictionary mapping acquisition names to 
            validation models.
        session_map (Dict[str, str]): Mapping of reference acquisitions to input acquisitions.
        raise_errors (bool): Whether to raise exceptions for validation failures. Defaults to False.

    Returns:
        List[Dict[str, Any]]: A list of compliance issues, where each issue is represented as a dictionary.
    
    Raises:
        ValueError: If `raise_errors` is True and validation fails for any acquisition.
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
        ref_model = ref_model_cls()

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
    Validate individual DICOM values against reference fields.

    Args:
        reference_fields (List[Dict[str, Any]]): A list of dictionaries defining the expected values 
            and rules for validation (e.g., tolerance, contains).
        dicom_values (Dict[str, Any]): Dictionary of DICOM metadata values to be validated.

    Returns:
        List[Dict[str, Any]]: A list of compliance issues, where each issue is represented as a dictionary.
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
    Check if the entire DICOM session complies with the reference session.

    Args:
        in_session (Dict): Input session data containing DICOM metadata.
        ref_session (Dict): Reference session data containing expected metadata and rules.
        session_map (Dict): Mapping of input acquisitions/series to reference acquisitions/series.

    Returns:
        bool: True if the session is fully compliant, False otherwise.
    """

    compliance_issues = check_session_compliance_with_json_reference(in_session, ref_session, session_map)
    return len(compliance_issues) == 0

def is_dicom_compliant(
        reference_model: BaseValidationModel,
        dicom_values: Dict[str, Any]
) -> bool:
    """
    Check if a DICOM file's metadata complies with a validation model.

    Args:
        reference_model (BaseValidationModel): The validation model defining expected metadata.
        dicom_values (Dict[str, Any]): Dictionary of DICOM metadata values to be validated.

    Returns:
        bool: True if the DICOM metadata is compliant, False otherwise.
    """

    compliance_issues = check_dicom_compliance(
        reference_model.fields,
        dicom_values
    )

    return len(compliance_issues) == 0

