"""
This module provides functions for validating a DICOM sessions.

The module supports compliance checks for JSON-based reference sessions and Python module-based validation models.

"""

from typing import List, Dict, Any
from dicompare.validation import BaseValidationModel
import pandas as pd

import pandas as pd
from typing import Dict, Any, List


def check_session_compliance_with_json_reference(
    in_session: pd.DataFrame,
    ref_session: Dict[str, Any],
    session_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against a JSON reference session.

    Args:
        in_session (pd.DataFrame): Input session DataFrame containing DICOM metadata.
        ref_session (Dict[str, Any]): Reference session data loaded from a JSON file.
        session_map (Dict[str, str]): Mapping of reference acquisitions to input acquisitions.

    Returns:
        List[Dict[str, Any]]: A list of compliance issues, where each issue is represented
                              as a dictionary. Acquisition-level fields yield a record with
                              "series": None. Series-level checks produce one pass/fail record
                              per reference series, with a "series" key indicating the
                              reference series name.
    """

    compliance_summary: List[Dict[str, Any]] = []

    # -------------------------------------------------------
    # Helper: Checks if a single row's value meets the constraint (contains, tolerance, etc.)
    def _row_passes_constraint(
        actual_value: Any,
        expected_value: Any = None,
        tolerance: float = None,
        contains: str = None
    ) -> bool:
        if contains is not None:
            if not isinstance(actual_value, (str, list, tuple)):
                return False
            return (contains in actual_value)

        elif tolerance is not None:
            if not isinstance(actual_value, (int, float)):
                return False
            return (expected_value - tolerance <= actual_value <= expected_value + tolerance)

        elif isinstance(expected_value, list):
            if not isinstance(actual_value, list):
                return False
            return set(actual_value) == set(expected_value)

        elif expected_value is not None:
            return (actual_value == expected_value)

        return True  # no constraints specified => pass

    # -------------------------------------------------------
    # Acquisition-level fields → one record per field ("series": None).
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
                compliance_summary.append({
                    "reference acquisition": ref_acq_name,
                    "input acquisition": in_acq_name,
                    "series": None,
                    "field": field,
                    "expected": f"(value={expected_value}, tolerance={tolerance}, contains={contains})",
                    "value": None,
                    "message": "Field not found in input session.",
                    "passed": "❌"
                })
                continue

            actual_values = in_acq[field].unique().tolist()
            invalid_values = []

            # Evaluate constraints
            if contains is not None:
                for val in actual_values:
                    if not isinstance(val, (str, list, tuple)) or (contains not in val):
                        invalid_values.append(val)

                if invalid_values:
                    compliance_summary.append({
                        "reference acquisition": ref_acq_name,
                        "input acquisition": in_acq_name,
                        "series": None,
                        "field": field,
                        "expected": f"contains='{contains}'",
                        "value": actual_values,
                        "message": f"Expected to contain '{contains}', got {invalid_values}",
                        "passed": "❌"
                    })
                    continue

            elif tolerance is not None:
                non_numeric = [val for val in actual_values if not isinstance(val, (int, float))]
                if non_numeric:
                    compliance_summary.append({
                        "reference acquisition": ref_acq_name,
                        "input acquisition": in_acq_name,
                        "series": None,
                        "field": field,
                        "expected": f"value={expected_value} ± {tolerance}",
                        "value": actual_values,
                        "message": f"Field must be numeric; found {non_numeric}",
                        "passed": "❌"
                    })
                    continue

                for val in actual_values:
                    if not (expected_value - tolerance <= val <= expected_value + tolerance):
                        invalid_values.append(val)

                if invalid_values:
                    compliance_summary.append({
                        "reference acquisition": ref_acq_name,
                        "input acquisition": in_acq_name,
                        "series": None,
                        "field": field,
                        "expected": f"value={expected_value} ± {tolerance}",
                        "value": actual_values,
                        "message": f"Invalid values found: {invalid_values} (all values: {actual_values})",
                        "passed": "❌"
                    })
                    continue

            elif isinstance(expected_value, list):
                for val in actual_values:
                    if not isinstance(val, list) or set(val) != set(expected_value):
                        invalid_values.append(val)
                if invalid_values:
                    compliance_summary.append({
                        "reference acquisition": ref_acq_name,
                        "input acquisition": in_acq_name,
                        "series": None,
                        "field": field,
                        "expected": f"value={expected_value}",
                        "value": actual_values,
                        "message": f"Expected list-based match, got {invalid_values}",
                        "passed": "❌"
                    })
                    continue

            elif expected_value is not None:
                for val in actual_values:
                    if val != expected_value:
                        invalid_values.append(val)
                if invalid_values:
                    compliance_summary.append({
                        "reference acquisition": ref_acq_name,
                        "input acquisition": in_acq_name,
                        "series": None,
                        "field": field,
                        "expected": f"value={expected_value}",
                        "value": actual_values,
                        "message": f"Mismatched values: {invalid_values}",
                        "passed": "❌"
                    })
                    continue

            # If we reach here, no fails → pass
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "series": None,
                "field": field,
                "expected": f"(value={expected_value}, tolerance={tolerance}, contains={contains})",
                "value": actual_values,
                "message": "Passed.",
                "passed": "✅"
            })

    # -------------------------------------------------------
    # Series-level fields → one record per reference series ("series": s_name).
    def _check_series_fields(
        ref_acq_name: str,
        in_acq_name: str,
        sdef: Dict[str, Any],
        in_acq: pd.DataFrame
    ) -> None:
        s_name = sdef.get("name", "<unnamed>")
        s_fields = sdef.get("fields", [])

        matching_df = in_acq
        missing_field = False

        # Step 1) Filter by row constraints
        for fdef in s_fields:
            field = fdef["field"]
            e_val = fdef.get("value")
            tol = fdef.get("tolerance")
            ctn = fdef.get("contains")

            if field not in matching_df.columns:
                compliance_summary.append({
                    "reference acquisition": ref_acq_name,
                    "input acquisition": in_acq_name,
                    "series": s_name,
                    "field": field,
                    "expected": f"(value={e_val}, tolerance={tol}, contains={ctn})",
                    "value": None,
                    "message": f"Field '{field}' not found in input for series '{s_name}'.",
                    "passed": "❌"
                })
                missing_field = True
                break

            matching_df = matching_df[
                matching_df[field].apply(lambda x: _row_passes_constraint(x, e_val, tol, ctn))
            ]
            if matching_df.empty:
                break

        if missing_field:
            # Already logged an error
            return

        if matching_df.empty:
            # No rows matched all constraints
            field_names = [f["field"] for f in s_fields]
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "series": s_name,
                "field": ", ".join(field_names),
                "expected": str(sdef['fields']),
                "value": None,
                "message": f"Series '{s_name}' not found with the specified constraints.",
                "passed": "❌"
            })
            return

        # Step 2) We have at least one row that meets all constraints
        # Summarize into one pass/fail record for all fields in this series.
        actual_values_agg = {}
        constraints_agg = {}
        fail_messages = []
        any_fail = False

        for fdef in s_fields:
            field = fdef["field"]
            e_val = fdef.get("value")
            tol = fdef.get("tolerance")
            ctn = fdef.get("contains")

            # Rows that survived the filter
            values = matching_df[field].unique().tolist()
            actual_values_agg[field] = values

            # Build a short descriptor of constraints
            constraint_pieces = []
            if e_val is not None:
                if tol is not None:
                    constraint_pieces.append(f"value={e_val} ± {tol}")
                elif isinstance(e_val, list):
                    constraint_pieces.append(f"value(list)={e_val}")
                else:
                    constraint_pieces.append(f"value={e_val}")
            if ctn is not None:
                constraint_pieces.append(f"contains='{ctn}'")

            constraints_agg[field] = ", ".join(constraint_pieces) if constraint_pieces else "(none)"

            # Double-check for fails just to collect a final message
            invalid_values = []
            if ctn is not None:
                for val in values:
                    if not isinstance(val, (str, list, tuple)) or (ctn not in val):
                        invalid_values.append(val)
                if invalid_values:
                    any_fail = True
                    fail_messages.append(f"Field '{field}': must contain '{ctn}', got {invalid_values}")

            elif tol is not None:
                non_numeric = [val for val in values if not isinstance(val, (int, float))]
                if non_numeric:
                    any_fail = True
                    fail_messages.append(f"Field '{field}': found non-numeric {non_numeric}, tolerance used")
                else:
                    for val in values:
                        if not (e_val - tol <= val <= e_val + tol):
                            invalid_values.append(val)
                    if invalid_values:
                        any_fail = True
                        fail_messages.append(f"Field '{field}': value={e_val} ± {tol}, got {invalid_values}")

            elif isinstance(e_val, list):
                for val in values:
                    if not isinstance(val, list) or set(val) != set(e_val):
                        invalid_values.append(val)
                if invalid_values:
                    any_fail = True
                    fail_messages.append(f"Field '{field}': expected {e_val}, got {invalid_values}")

            elif e_val is not None:
                for val in values:
                    if val != e_val:
                        invalid_values.append(val)
                if invalid_values:
                    any_fail = True
                    fail_messages.append(f"Field '{field}': expected {e_val}, got {invalid_values}")

        # Summarize pass/fail
        if any_fail:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "series": s_name,
                "field": ", ".join([f["field"] for f in s_fields]),
                "expected": constraints_agg,
                "value": actual_values_agg,
                "message": "; ".join(fail_messages),
                "passed": "❌"
            })
        else:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "series": s_name,
                "field": ", ".join([f["field"] for f in s_fields]),
                "expected": constraints_agg,
                "value": actual_values_agg,
                "message": "Passed",
                "passed": "✅"
            })

    # -------------------------------------------------------
    # 1) Check for unmapped reference acquisitions
    for ref_acq_name in ref_session["acquisitions"]:
        if ref_acq_name not in session_map:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": None,
                "series": None,
                "field": None,
                "expected": "(mapped acquisition required)",
                "value": None,
                "message": f"Reference acquisition '{ref_acq_name}' not mapped.",
                "passed": "❌"
            })

    # -------------------------------------------------------
    # 2) Process each mapped acquisition
    for ref_acq_name, in_acq_name in session_map.items():
        ref_acq = ref_session["acquisitions"].get(ref_acq_name, {})
        in_acq = in_session[in_session["Acquisition"] == in_acq_name]

        # Acquisition-level checks
        ref_fields = ref_acq.get("fields", [])
        _check_acquisition_fields(ref_acq_name, in_acq_name, ref_fields, in_acq)

        # Series-level checks
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
                "expected": "Specified input acquisition must be present.",
                "message": f"Input acquisition '{in_acq_name}' not found in data.",
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
                "expected": "Reference model must exist.",
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
                "expected": error['expected'],
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
                "expected": passed_test['expected'],
                "message": passed_test['message'],
                "passed": "✅"
            })

        # Raise an error if validation fails and `raise_errors` is True
        if raise_errors and not success:
            raise ValueError(f"Validation failed for acquisition '{in_acq_name}'.")

    return compliance_summary

