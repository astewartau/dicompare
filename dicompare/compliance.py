"""
This module provides functions for validating a DICOM sessions.

The module supports compliance checks for JSON-based reference sessions and Python module-based validation models.

"""

from typing import List, Dict, Any
from dicompare.validation import BaseValidationModel
from dicompare.validation_helpers import (
    normalize_value, check_equality, check_contains, validate_constraint,
    validate_field_values, create_compliance_record
)
import pandas as pd

def check_session_compliance_with_json_reference(
    in_session: pd.DataFrame,
    ref_session: Dict[str, Any],
    session_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against a JSON reference session.
    All string comparisons occur in a case-insensitive manner with extra whitespace trimmed.
    If an input value is a list with one element and the expected value is a string,
    the element is unwrapped before comparing.

    Args:
        in_session (pd.DataFrame): Input session DataFrame containing DICOM metadata.
        ref_session (Dict[str, Any]): Reference session data loaded from a JSON file.
        session_map (Dict[str, str]): Mapping of reference acquisitions to input acquisitions.

    Returns:
        List[Dict[str, Any]]: A list of compliance issues. Acquisition-level checks yield a record with "series": None.
                              Series-level checks produce one record per reference series.
    """
    compliance_summary: List[Dict[str, Any]] = []

    def _check_acquisition_fields(
        ref_acq_name: str,
        in_acq_name: str,
        ref_fields: List[Dict[str, Any]],
        in_acq: pd.DataFrame
    ) -> None:
        for fdef in ref_fields:
            field = fdef["field"]
            expected_value = fdef.get("value")
            tolerance = fdef.get("tolerance")
            contains = fdef.get("contains")

            if field not in in_acq.columns:
                compliance_summary.append(create_compliance_record(
                    ref_acq_name, in_acq_name, None, field,
                    expected_value, tolerance, contains, None,
                    "Field not found in input session.", False
                ))
                continue

            actual_values = in_acq[field].unique().tolist()
            
            # Use validation helper to check field values
            passed, invalid_values, message = validate_field_values(
                field, actual_values, expected_value, tolerance, contains
            )
            
            compliance_summary.append(create_compliance_record(
                ref_acq_name, in_acq_name, None, field,
                expected_value, tolerance, contains, actual_values,
                message, passed
            ))

    def _check_series_fields(
        ref_acq_name: str,
        in_acq_name: str,
        ref_series_schema: Dict[str, Any],
        in_acq: pd.DataFrame
    ) -> None:
        
        ref_series_name = ref_series_schema.get("name", "<unnamed>")
        ref_series_fields = ref_series_schema.get("fields", [])
        matching_df = in_acq

        # First pass: check for missing fields and filter matching rows
        for fdef in ref_series_fields:
            field = fdef["field"]
            e_val = fdef.get("value")
            tol = fdef.get("tolerance")
            ctn = fdef.get("contains")

            if field not in matching_df.columns:
                compliance_summary.append(create_compliance_record(
                    ref_acq_name, in_acq_name, ref_series_name, field,
                    e_val, tol, ctn, None,
                    f"Field '{field}' not found in input for series '{ref_series_name}'.", False
                ))
                return

            # Filter rows that match this constraint
            matching_df = matching_df[
                matching_df[field].apply(lambda x: validate_constraint(x, e_val, tol, ctn))
            ]
            if matching_df.empty:
                break

        # If no matching series found, report failure
        if matching_df.empty:
            field_names = [f["field"] for f in ref_series_fields]
            compliance_summary.append(create_compliance_record(
                ref_acq_name, in_acq_name, ref_series_name, ", ".join(field_names),
                ref_series_schema['fields'], None, None, None,
                f"Series '{ref_series_name}' not found with the specified constraints.", False
            ))
            return

        # Second pass: validate all field values in matching series
        actual_values_agg = {}
        constraints_agg = {}
        fail_messages = []
        any_fail = False

        for fdef in ref_series_fields:
            field = fdef["field"]
            e_val = fdef.get("value")
            tol = fdef.get("tolerance")
            ctn = fdef.get("contains")

            values = matching_df[field].unique().tolist()
            actual_values_agg[field] = values

            # Format constraint description
            from dicompare.validation_helpers import format_constraint_description
            constraints_agg[field] = format_constraint_description(e_val, tol, ctn)

            # Validate field values
            passed, invalid_values, message = validate_field_values(
                field, values, e_val, tol, ctn
            )
            
            if not passed:
                any_fail = True
                fail_messages.append(f"Field '{field}': {message}")

        # Create final compliance record
        field_names = [f["field"] for f in ref_series_fields]
        final_message = "; ".join(fail_messages) if any_fail else "Passed"
        
        compliance_summary.append({
            "reference acquisition": ref_acq_name,
            "input acquisition": in_acq_name,
            "series": ref_series_name,
            "field": ", ".join(field_names),
            "expected": constraints_agg,
            "value": actual_values_agg,
            "message": final_message,
            "passed": not any_fail
        })

    # 1) Check for unmapped reference acquisitions.
    for ref_acq_name in ref_session["acquisitions"]:
        if ref_acq_name not in session_map:
            compliance_summary.append(create_compliance_record(
                ref_acq_name, None, None, None,
                "(mapped acquisition required)", None, None, None,
                f"Reference acquisition '{ref_acq_name}' not mapped.", False
            ))

    # 2) Process each mapped acquisition.
    for ref_acq_name, in_acq_name in session_map.items():
        ref_acq = ref_session["acquisitions"].get(ref_acq_name, {})
        in_acq = in_session[in_session["Acquisition"] == in_acq_name]
        ref_fields = ref_acq.get("fields", [])
        _check_acquisition_fields(ref_acq_name, in_acq_name, ref_fields, in_acq)
        ref_series = ref_acq.get("series", [])
        for sdef in ref_series:
            _check_series_fields(ref_acq_name, in_acq_name, sdef, in_acq)

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
                "rule_name": "Acquisition presence",
                "expected": "Specified input acquisition must be present.",
                "message": f"Input acquisition '{in_acq_name}' not found in data.",
                "passed": False
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
                "rule_name": "Model presence",
                "expected": "Reference model must exist.",
                "message": f"No model found for reference acquisition '{ref_acq_name}'.",
                "passed": False
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
                "input acquisition": in_acq_name,
                "field": error['field'],
                "value": error['value'],
                "expected": error['expected'],
                "message": error['message'],
                "rule_name": error['rule_name'],
                "passed": False
            })

        # Record passes
        for passed_test in passes:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "field": passed_test['field'],
                "value": passed_test['value'],
                "expected": passed_test['expected'],
                "message": passed_test['message'],
                "rule_name": passed_test['rule_name'],
                "passed": True
            })

        # Raise an error if validation fails and `raise_errors` is True
        if raise_errors and not success:
            raise ValueError(f"Validation failed for acquisition '{in_acq_name}'.")

    return compliance_summary

