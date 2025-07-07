"""
This module provides functions for validating a DICOM sessions.

The module supports compliance checks for JSON-based schema sessions and Python module-based validation models.

"""

from typing import List, Dict, Any
from dicompare.validation import BaseValidationModel
from dicompare.validation_helpers import (
    validate_constraint, validate_field_values, create_compliance_record, format_constraint_description
)
import pandas as pd

def check_session_compliance_with_json_schema(
    in_session: pd.DataFrame,
    schema_session: Dict[str, Any],
    session_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against a JSON schema session.
    All string comparisons occur in a case-insensitive manner with extra whitespace trimmed.
    If an input value is a list with one element and the expected value is a string,
    the element is unwrapped before comparing.

    Args:
        in_session (pd.DataFrame): Input session DataFrame containing DICOM metadata.
        schema_session (Dict[str, Any]): Schema session data loaded from a JSON file.
        session_map (Dict[str, str]): Mapping of schema acquisitions to input acquisitions.

    Returns:
        List[Dict[str, Any]]: A list of compliance issues. Acquisition-level checks yield a record with "series": None.
                              Series-level checks produce one record per schema series.
    """
    compliance_summary: List[Dict[str, Any]] = []

    def _check_acquisition_fields(
        schema_acq_name: str,
        in_acq_name: str,
        schema_fields: List[Dict[str, Any]],
        in_acq: pd.DataFrame
    ) -> None:
        for fdef in schema_fields:
            field = fdef["field"]
            expected_value = fdef.get("value")
            tolerance = fdef.get("tolerance")
            contains = fdef.get("contains")

            if field not in in_acq.columns:
                compliance_summary.append(create_compliance_record(
                    schema_acq_name, in_acq_name, None, field,
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
                schema_acq_name, in_acq_name, None, field,
                expected_value, tolerance, contains, actual_values,
                message, passed
            ))

    def _check_series_fields(
        schema_acq_name: str,
        in_acq_name: str,
        schema_series_schema: Dict[str, Any],
        in_acq: pd.DataFrame
    ) -> None:
        
        schema_series_name = schema_series_schema.get("name", "<unnamed>")
        schema_series_fields = schema_series_schema.get("fields", [])
        
        print(f"    DEBUG _check_series_fields: series '{schema_series_name}'")
        print(f"      Schema fields: {[(f['field'], f.get('value')) for f in schema_series_fields]}")
        print(f"      Input data shape: {in_acq.shape}")
        
        matching_df = in_acq

        # First pass: check for missing fields and filter matching rows
        for fdef in schema_series_fields:
            field = fdef["field"]
            e_val = fdef.get("value")
            tol = fdef.get("tolerance")
            ctn = fdef.get("contains")

            print(f"      Processing field '{field}' with expected value: {e_val}")

            if field not in matching_df.columns:
                print(f"      ERROR: Field '{field}' not found in columns")
                compliance_summary.append(create_compliance_record(
                    schema_acq_name, in_acq_name, schema_series_name, field,
                    e_val, tol, ctn, None,
                    f"Field '{field}' not found in input for series '{schema_series_name}'.", False
                ))
                return

            # Check current values before filtering
            print(f"      Current '{field}' values: {matching_df[field].unique()}")
            print(f"      Rows before filtering: {len(matching_df)}")
            
            # Filter rows that match this constraint
            matches = matching_df[field].apply(lambda x: validate_constraint(x, e_val, tol, ctn))
            print(f"      Matching constraint validation: {matches.sum()} of {len(matches)} rows match")
            
            matching_df = matching_df[matches]
            print(f"      Rows after filtering: {len(matching_df)}")
            
            if matching_df.empty:
                print(f"      No matching rows found, breaking")
                break

        # If no matching series found, report failure
        if matching_df.empty:
            print(f"      RESULT: No matching series found - creating failure record")
            field_names = [f["field"] for f in schema_series_fields]
            compliance_summary.append(create_compliance_record(
                schema_acq_name, in_acq_name, schema_series_name, ", ".join(field_names),
                schema_series_schema['fields'], None, None, None,
                f"Series '{schema_series_name}' not found with the specified constraints.", False
            ))
            return
        else:
            print(f"      RESULT: Found matching series with {len(matching_df)} rows - proceeding to validation")

        # Second pass: validate all field values in matching series
        actual_values_agg = {}
        constraints_agg = {}
        fail_messages = []
        any_fail = False

        for fdef in schema_series_fields:
            field = fdef["field"]
            e_val = fdef.get("value")
            tol = fdef.get("tolerance")
            ctn = fdef.get("contains")

            values = matching_df[field].unique().tolist()
            actual_values_agg[field] = values

            # Format constraint description
            constraints_agg[field] = format_constraint_description(e_val, tol, ctn)

            # Validate field values
            passed, invalid_values, message = validate_field_values(
                field, values, e_val, tol, ctn
            )
            
            if not passed:
                any_fail = True
                fail_messages.append(f"Field '{field}': {message}")

        # Create final compliance record
        field_names = [f["field"] for f in schema_series_fields]
        final_message = "; ".join(fail_messages) if any_fail else "Passed"
        
        print(f"      FINAL: Creating series compliance record - passed: {not any_fail}")
        print(f"      Field: {', '.join(field_names)}, Series: {schema_series_name}")
        
        compliance_summary.append({
            "schema acquisition": schema_acq_name,
            "input acquisition": in_acq_name,
            "series": schema_series_name,
            "field": ", ".join(field_names),
            "expected": constraints_agg,
            "value": actual_values_agg,
            "message": final_message,
            "passed": not any_fail
        })
        
        print(f"      ADDED to compliance_summary. Total records now: {len(compliance_summary)}")

    # 1) Check for unmapped reference acquisitions.
    for schema_acq_name in schema_session["acquisitions"]:
        if schema_acq_name not in session_map:
            compliance_summary.append(create_compliance_record(
                schema_acq_name, None, None, None,
                "(mapped acquisition required)", None, None, None,
                f"Schema acquisition '{schema_acq_name}' not mapped.", False
            ))

    # 2) Process each mapped acquisition.
    for schema_acq_name, in_acq_name in session_map.items():
        schema_acq = schema_session["acquisitions"].get(schema_acq_name, {})
        in_acq = in_session[in_session["Acquisition"] == in_acq_name]
        
        print(f"DEBUG: Processing acquisition '{schema_acq_name}' -> '{in_acq_name}'")
        print(f"  Schema has {len(schema_acq.get('fields', []))} fields, {len(schema_acq.get('series', []))} series")
        print(f"  Input has {len(in_acq)} rows, columns: {list(in_acq.columns)}")
        if 'ImageType' in in_acq.columns:
            print(f"  ImageType values in input: {in_acq['ImageType'].unique()}")
        
        schema_fields = schema_acq.get("fields", [])
        _check_acquisition_fields(schema_acq_name, in_acq_name, schema_fields, in_acq)
        
        schema_series = schema_acq.get("series", [])
        print(f"  Checking {len(schema_series)} series definitions...")
        for i, sdef in enumerate(schema_series):
            print(f"    Series {i}: name='{sdef.get('name')}', fields={[f['field'] for f in sdef.get('fields', [])]}")
            _check_series_fields(schema_acq_name, in_acq_name, sdef, in_acq)

    return compliance_summary


def check_session_compliance_with_python_module(
    in_session: pd.DataFrame,
    schema_models: Dict[str, BaseValidationModel],
    session_map: Dict[str, str],
    raise_errors: bool = False
) -> List[Dict[str, Any]]:
    """
    Validate a DICOM session against Python module-based validation models.

    Args:
        in_session (pd.DataFrame): Input session DataFrame containing DICOM metadata.
        schema_models (Dict[str, BaseValidationModel]): Dictionary mapping acquisition names to 
            validation models.
        session_map (Dict[str, str]): Mapping of reference acquisitions to input acquisitions.
        raise_errors (bool): Whether to raise exceptions for validation failures. Defaults to False.

    Returns:
        List[Dict[str, Any]]: A list of compliance issues, where each issue is represented as a dictionary.
    
    Raises:
        ValueError: If `raise_errors` is True and validation fails for any acquisition.
    """
    compliance_summary = []

    for schema_acq_name, in_acq_name in session_map.items():
        # Filter the input session for the current acquisition
        in_acq = in_session[in_session["Acquisition"] == in_acq_name]

        if in_acq.empty:
            compliance_summary.append({
                "schema acquisition": schema_acq_name,
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
        schema_model_cls = schema_models.get(schema_acq_name)
        if not schema_model_cls:
            compliance_summary.append({
                "schema acquisition": schema_acq_name,
                "input acquisition": in_acq_name,
                "field": "Model Error",
                "value": None,
                "rule_name": "Model presence",
                "expected": "Schema model must exist.",
                "message": f"No model found for reference acquisition '{schema_acq_name}'.",
                "passed": False
            })
            continue
        schema_model = schema_model_cls()

        # Prepare acquisition data as a single DataFrame
        acquisition_df = in_acq.copy()

        # Validate using the reference model
        success, errors, passes = schema_model.validate(data=acquisition_df)

        # Record errors
        for error in errors:
            compliance_summary.append({
                "schema acquisition": schema_acq_name,
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
                "schema acquisition": schema_acq_name,
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

