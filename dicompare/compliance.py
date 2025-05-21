"""
This module provides functions for validating a DICOM sessions.

The module supports compliance checks for JSON-based reference sessions and Python module-based validation models.

"""

from typing import List, Dict, Any
from dicompare.validation import BaseValidationModel
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

    # Helper: if a value is numeric, leave it; otherwise convert to a stripped lowercase string.
    def normalize_value(val: Any) -> Any:
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, list):
            return [normalize_value(x) for x in val]
        try:
            # If the object has a strip method, assume it's string-like.
            if hasattr(val, "strip") and callable(val.strip):
                return val.strip().lower()
            # Otherwise, convert to string.
            return str(val).strip().lower()
        except Exception:
            return val

    # Compare two values in a case-insensitive manner.
    # If one is a list with one string element and the other is a string, the element is unwrapped.
    def check_equality(val: Any, expected: Any) -> bool:
        # Unwrap if actual is a list containing one string.
        if isinstance(val, list) and isinstance(expected, str):
            if len(val) == 1 and isinstance(val[0], (str,)):
                return normalize_value(val[0]) == normalize_value(expected)
            return False
        if isinstance(expected, list) and isinstance(val, str):
            if len(expected) == 1 and isinstance(expected[0], (str,)):
                return normalize_value(val) == normalize_value(expected[0])
            return False
        if isinstance(val, (str,)) or isinstance(expected, (str,)):
            return normalize_value(val) == normalize_value(expected)
        return val == expected

    # Check if actual contains the given substring, comparing in normalized form.
    def check_contains(actual: Any, substring: str) -> bool:
        sub_norm = substring.strip().lower()
        if isinstance(actual, str) or (hasattr(actual, "strip") and callable(actual.strip)):
            return normalize_value(actual).find(sub_norm) != -1
        elif isinstance(actual, (list, tuple)):
            return any(isinstance(x, str) and normalize_value(x).find(sub_norm) != -1 for x in actual)
        return False

    # Core constraint check.
    def _row_passes_constraint(
        actual_value: Any,
        expected_value: Any = None,
        tolerance: float = None,
        contains: str = None
    ) -> bool:
        if contains is not None:
            return check_contains(actual_value, contains)
        elif tolerance is not None:
            if not isinstance(actual_value, (int, float)):
                return False
            return (expected_value - tolerance <= actual_value <= expected_value + tolerance)
        elif isinstance(expected_value, list):
            if not isinstance(actual_value, list):
                return False
            return set(normalize_value(actual_value)) == set(normalize_value(expected_value))
        elif expected_value is not None:
            return check_equality(actual_value, expected_value)
        return True

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
                    "passed": False
                })
                continue

            actual_values = in_acq[field].unique().tolist()
            invalid_values = []

            if contains is not None:
                for val in actual_values:
                    if not check_contains(val, contains):
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
                        "passed": False
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
                        "passed": False
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
                        "passed": False
                    })
                    continue

            elif isinstance(expected_value, list):
                for val in actual_values:
                    if not isinstance(val, list) or set(normalize_value(val)) != set(normalize_value(expected_value)):
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
                        "passed": False
                    })
                    continue

            elif expected_value is not None:
                for val in actual_values:
                    if not check_equality(val, expected_value):
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
                        "passed": False
                    })
                    continue

            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "series": None,
                "field": field,
                "expected": f"(value={expected_value}, tolerance={tolerance}, contains={contains})",
                "value": actual_values,
                "message": "Passed.",
                "passed": True
            })

    def _check_series_fields(
        ref_acq_name: str,
        in_acq_name: str,
        ref_series_schema: Dict[str, Any],
        in_acq: pd.DataFrame
    ) -> None:
        
        ref_series_name = ref_series_schema.get("name", "<unnamed>")
        ref_series_fields = ref_series_schema.get("fields", [])
        matching_df = in_acq
        missing_field = False

        for fdef in ref_series_fields:
            field = fdef["field"]
            e_val = fdef.get("value")
            tol = fdef.get("tolerance")
            ctn = fdef.get("contains")

            if field not in matching_df.columns:
                compliance_summary.append({
                    "reference acquisition": ref_acq_name,
                    "input acquisition": in_acq_name,
                    "series": ref_series_name,
                    "field": field,
                    "expected": f"(value={e_val}, tolerance={tol}, contains={ctn})",
                    "value": None,
                    "message": f"Field '{field}' not found in input for series '{ref_series_name}'.",
                    "passed": False
                })
                missing_field = True
                break

            matching_df = matching_df[
                matching_df[field].apply(lambda x: _row_passes_constraint(x, e_val, tol, ctn))
            ]
            if matching_df.empty:
                break

        if missing_field:
            return

        if matching_df.empty:
            field_names = [f["field"] for f in ref_series_fields]
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "series": ref_series_name,
                "field": ", ".join(field_names),
                "expected": str(ref_series_schema['fields']),
                "value": None,
                "message": f"Series '{ref_series_name}' not found with the specified constraints.",
                "passed": False
            })
            return

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

            pieces = []
            if e_val is not None:
                if tol is not None:
                    pieces.append(f"value={e_val} ± {tol}")
                elif isinstance(e_val, list):
                    pieces.append(f"value(list)={e_val}")
                else:
                    pieces.append(f"value={e_val}")
            if ctn is not None:
                pieces.append(f"contains='{ctn}'")
            constraints_agg[field] = ", ".join(pieces) if pieces else "(none)"

            invalid_values = []
            if ctn is not None:
                for val in values:
                    if not check_contains(val, ctn):
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
                    if not isinstance(val, list) or set(normalize_value(val)) != set(normalize_value(e_val)):
                        invalid_values.append(val)
                if invalid_values:
                    any_fail = True
                    fail_messages.append(f"Field '{field}': expected {e_val}, got {invalid_values}")

            elif e_val is not None:
                for val in values:
                    if not check_equality(val, e_val):
                        invalid_values.append(val)
                if invalid_values:
                    any_fail = True
                    fail_messages.append(f"Field '{field}': expected {e_val}, got {invalid_values}")

        if any_fail:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "series": ref_series_name,
                "field": ", ".join([f["field"] for f in ref_series_fields]),
                "expected": constraints_agg,
                "value": actual_values_agg,
                "message": "; ".join(fail_messages),
                "passed": False
            })
        else:
            compliance_summary.append({
                "reference acquisition": ref_acq_name,
                "input acquisition": in_acq_name,
                "series": ref_series_name,
                "field": ", ".join([f["field"] for f in ref_series_fields]),
                "expected": constraints_agg,
                "value": actual_values_agg,
                "message": "Passed",
                "passed": True
            })

    # 1) Check for unmapped reference acquisitions.
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
                "passed": False
            })

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

