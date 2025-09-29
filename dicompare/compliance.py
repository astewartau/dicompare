"""
This module provides functions for validating a DICOM sessions.

The module supports compliance checks for JSON-based schema sessions and Python module-based validation models.

"""

from typing import List, Dict, Any, Optional
from dicompare.validation import BaseValidationModel, create_validation_models_from_rules
from dicompare.validation_helpers import (
    validate_constraint, validate_field_values, create_compliance_record, format_constraint_description,
    ComplianceStatus
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
            contains_any = fdef.get("contains_any")
            contains_all = fdef.get("contains_all")

            if field not in in_acq.columns:
                print(f"DEBUG compliance.py: Field '{field}' not found, creating NA record")
                compliance_summary.append(create_compliance_record(
                    schema_acq_name, in_acq_name, None, field,
                    expected_value, tolerance, contains, contains_any, contains_all, None,
                    "Field not found in input session.", False,
                    status=ComplianceStatus.NA
                ))
                continue

            actual_values = in_acq[field].unique().tolist()
            
            # Use validation helper to check field values
            passed, invalid_values, message = validate_field_values(
                field, actual_values, expected_value, tolerance, contains, contains_any, contains_all
            )
            
            compliance_summary.append(create_compliance_record(
                schema_acq_name, in_acq_name, None, field,
                expected_value, tolerance, contains, contains_any, contains_all, actual_values,
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

        field_names = [f["field"] for f in schema_series_fields]

        # Check for missing fields first
        missing_fields = []
        for fdef in schema_series_fields:
            field = fdef["field"]
            if field not in in_acq.columns:
                missing_fields.append(field)

        if missing_fields:
            print(f"      RESULT: Missing fields {missing_fields} - creating NA record for series")
            compliance_summary.append(create_compliance_record(
                schema_acq_name, in_acq_name, schema_series_name, schema_series_name,
                None, None, None, None, None, None,
                f"Series '{schema_series_name}' missing required fields: {', '.join(missing_fields)}", False,
                status=ComplianceStatus.NA
            ))
            return

        # Find rows that match ALL constraints simultaneously
        matching_df = in_acq.copy()
        for fdef in schema_series_fields:
            field = fdef["field"]
            e_val = fdef.get("value")
            tol = fdef.get("tolerance")
            ctn = fdef.get("contains")
            ctn_any = fdef.get("contains_any")
            ctn_all = fdef.get("contains_all")

            # Apply constraint to this field
            matches = matching_df[field].apply(lambda x: validate_constraint(x, e_val, tol, ctn, ctn_any, ctn_all))
            matching_df = matching_df[matches]

            if matching_df.empty:
                break

        # Create single series result
        if matching_df.empty:
            print(f"      RESULT: No rows match all constraints - creating ERROR record for series")
            field_names = [f["field"] for f in schema_series_fields]
            field_list = ", ".join(field_names)
            compliance_summary.append(create_compliance_record(
                schema_acq_name, in_acq_name, schema_series_name, field_list,
                None, None, None, None, None, None,
                f"Series '{schema_series_name}' not found with the specified constraints.", False,
                status=ComplianceStatus.ERROR
            ))
        else:
            print(f"      RESULT: Found {len(matching_df)} matching rows - series PASSED")
            compliance_summary.append(create_compliance_record(
                schema_acq_name, in_acq_name, schema_series_name, schema_series_name,
                None, None, None, None, None, None,
                "Passed.", True,
                status=ComplianceStatus.OK
            ))

    # 1) Check for unmapped reference acquisitions.
    for schema_acq_name in schema_session["acquisitions"]:
        if schema_acq_name not in session_map:
            compliance_summary.append(create_compliance_record(
                schema_acq_name, None, None, None,
                None, None, None, None, None, None,
                f"Schema acquisition '{schema_acq_name}' not mapped.", False,
                ComplianceStatus.ERROR
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
                "passed": False,
                "status": ComplianceStatus.NA.value
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
                "passed": False,
                "status": ComplianceStatus.ERROR.value
            })
            continue
        schema_model = schema_model_cls()

        # Prepare acquisition data as a single DataFrame
        acquisition_df = in_acq.copy()

        # Validate using the reference model
        success, errors, warnings, passes = schema_model.validate(data=acquisition_df)

        # Record errors
        for error in errors:
            # Check if this is a "field not found" error
            status = ComplianceStatus.NA if "not found" in error.get('message', '').lower() else ComplianceStatus.ERROR
            compliance_summary.append({
                "schema acquisition": schema_acq_name,
                "input acquisition": in_acq_name,
                "field": error['field'],
                "value": error['value'],
                "expected": error['expected'],
                "message": error['message'],
                "rule_name": error['rule_name'],
                "passed": False,
                "status": status.value
            })

        # Record warnings
        for warning in warnings:
            compliance_summary.append({
                "schema acquisition": schema_acq_name,
                "input acquisition": in_acq_name,
                "field": warning['field'],
                "value": warning['value'],
                "expected": warning['expected'],
                "message": warning['message'],
                "rule_name": warning['rule_name'],
                "passed": True,  # Warnings don't fail validation
                "status": ComplianceStatus.WARNING.value
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
                "passed": True,
                "status": ComplianceStatus.OK.value
            })

        # Raise an error if validation fails and `raise_errors` is True
        if raise_errors and not success:
            raise ValueError(f"Validation failed for acquisition '{in_acq_name}'.")

    return compliance_summary


def check_session_compliance(
    in_session: pd.DataFrame,
    schema_data: Dict[str, Any],
    session_map: Dict[str, str],
    validation_rules: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    validation_models: Optional[Dict[str, BaseValidationModel]] = None,
    raise_errors: bool = False
) -> List[Dict[str, Any]]:
    """
    Unified compliance checking function that handles both field validation and rule validation.
    
    This function combines the functionality of check_session_compliance_with_json_schema and
    check_session_compliance_with_python_module, supporting hybrid schemas with both field
    constraints and embedded Python validation rules.
    
    Args:
        in_session (pd.DataFrame): Input session DataFrame containing DICOM metadata.
        schema_data (Dict[str, Any]): Schema data loaded from a JSON file.
        session_map (Dict[str, str]): Mapping of schema acquisitions to input acquisitions.
        validation_rules (Optional[Dict[str, List[Dict[str, Any]]]]): Dictionary mapping
            acquisition names to their validation rules (from hybrid schemas).
        validation_models (Optional[Dict[str, BaseValidationModel]]): Pre-created validation
            models. If not provided but validation_rules are, models will be created dynamically.
        raise_errors (bool): Whether to raise exceptions for validation failures. Defaults to False.
        
    Returns:
        List[Dict[str, Any]]: A list of compliance issues and passes. Each record contains:
            - schema acquisition: The reference acquisition name
            - input acquisition: The actual acquisition name in the input
            - field: The field(s) being validated
            - value: The actual value(s) found
            - expected: The expected value or constraint
            - message: Error message (for failures) or "OK" (for passes)
            - rule_name: The name of the validation rule (for rule-based validations)
            - passed: Boolean indicating if the check passed
            - status: The compliance status (OK, ERROR, NA, etc.)
            
    Raises:
        ValueError: If `raise_errors` is True and validation fails for any acquisition.
        
    Example:
        >>> # Load a hybrid schema
        >>> fields, schema_data, rules = load_hybrid_schema("schema.json")
        >>> 
        >>> # Check compliance
        >>> results = check_session_compliance(
        ...     in_session=session_df,
        ...     schema_data=schema_data,
        ...     session_map={"QSM": "qsm_acq"},
        ...     validation_rules=rules
        ... )
    """
    compliance_summary = []
    
    # Create validation models from rules if needed
    if validation_rules and not validation_models:
        validation_models = create_validation_models_from_rules(validation_rules)
    
    # Helper function for field validation (adapted from check_session_compliance_with_json_schema)
    def _check_field_compliance(
        schema_acq_name: str,
        in_acq_name: str,
        schema_fields: List[Dict[str, Any]],
        in_acq: pd.DataFrame,
        series_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Check field-level compliance for an acquisition or series."""
        field_results = []
        
        for fdef in schema_fields:
            field = fdef["field"]
            expected_value = fdef.get("value")
            tolerance = fdef.get("tolerance")
            contains = fdef.get("contains")
            contains_any = fdef.get("contains_any")
            contains_all = fdef.get("contains_all")
            
            if field not in in_acq.columns:
                field_results.append(create_compliance_record(
                    schema_acq_name, in_acq_name, series_name, field,
                    expected_value, tolerance, contains, contains_any, contains_all, None,
                    "Field not found in input session.", False,
                    status=ComplianceStatus.NA
                ))
                continue
            
            actual_values = in_acq[field].unique().tolist()
            
            # Use validation helper to check field values
            passed, invalid_values, message = validate_field_values(
                field, actual_values, expected_value, tolerance, contains, contains_any, contains_all
            )
            
            field_results.append(create_compliance_record(
                schema_acq_name, in_acq_name, series_name, field,
                expected_value, tolerance, contains, contains_any, contains_all, actual_values,
                message, passed
            ))
        
        return field_results
    
    # Process each mapped acquisition
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
                "passed": False,
                "status": ComplianceStatus.NA.value
            })
            continue
        
        # Get acquisition schema
        acquisitions_data = schema_data.get("acquisitions", {})
        schema_acq = acquisitions_data.get(schema_acq_name, {})
        
        # 1. Check field-level compliance
        schema_fields = schema_acq.get("fields", [])
        if schema_fields:
            field_results = _check_field_compliance(
                schema_acq_name, in_acq_name, schema_fields, in_acq
            )
            compliance_summary.extend(field_results)
        
        # 2. Check series-level field compliance
        schema_series = schema_acq.get("series", [])
        for series_def in schema_series:
            series_name = series_def.get("name", "<unnamed>")
            series_fields = series_def.get("fields", [])

            if series_fields:
                # Check for missing fields first
                missing_fields = []
                for fdef in series_fields:
                    field = fdef["field"]
                    if field not in in_acq.columns:
                        missing_fields.append(field)

                if missing_fields:
                    # Missing fields = NA for whole series
                    field_list = ", ".join([f["field"] for f in series_fields])
                    record = create_compliance_record(
                        schema_acq_name, in_acq_name, series_name, field_list,
                        None, None, None, None, None, None,
                        f"Series '{series_name}' missing required fields: {', '.join(missing_fields)}", False,
                        status=ComplianceStatus.NA
                    )
                    record["series"] = series_name
                    compliance_summary.append(record)
                    continue

                # Find rows that match ALL constraints simultaneously
                matching_df = in_acq.copy()
                for fdef in series_fields:
                    field = fdef["field"]
                    expected = fdef.get("value")
                    tolerance = fdef.get("tolerance")
                    contains = fdef.get("contains")
                    contains_any = fdef.get("contains_any")
                    contains_all = fdef.get("contains_all")

                    # Apply constraint to this field
                    mask = matching_df[field].apply(
                        lambda x: validate_constraint(x, expected, tolerance, contains, contains_any, contains_all)
                    )
                    matching_df = matching_df[mask]

                    if matching_df.empty:
                        break

                # Create single series result
                if matching_df.empty:
                    # Concatenate field names for the field attribute
                    field_list = ", ".join([f["field"] for f in series_fields])

                    # Create detailed constraint description
                    constraint_descriptions = []
                    for fdef in series_fields:
                        field = fdef["field"]
                        expected = fdef.get("value")
                        tolerance = fdef.get("tolerance")
                        contains = fdef.get("contains")
                        contains_any = fdef.get("contains_any")
                        contains_all = fdef.get("contains_all")

                        if expected is not None:
                            if tolerance is not None:
                                constraint_descriptions.append(f"{field}={expected}±{tolerance}")
                            else:
                                constraint_descriptions.append(f"{field}={expected}")
                        elif contains is not None:
                            constraint_descriptions.append(f"{field} contains '{contains}'")
                        elif contains_any is not None:
                            constraint_descriptions.append(f"{field} contains any of {contains_any}")
                        elif contains_all is not None:
                            constraint_descriptions.append(f"{field} contains all of {contains_all}")
                        else:
                            constraint_descriptions.append(f"{field}")

                    message = f"Series '{series_name}' not found with constraints: {' AND '.join(constraint_descriptions)}"

                    record = create_compliance_record(
                        schema_acq_name, in_acq_name, series_name, field_list,
                        None, None, None, None, None, None,
                        message, False,
                        status=ComplianceStatus.NA
                    )
                    # Add series information to the record
                    record["series"] = series_name
                    compliance_summary.append(record)
                else:
                    field_list = ", ".join([f["field"] for f in series_fields])
                    record = create_compliance_record(
                        schema_acq_name, in_acq_name, series_name, field_list,
                        None, None, None, None, None, None,
                        "Passed.", True,
                        status=ComplianceStatus.OK
                    )
                    record["series"] = series_name
                    compliance_summary.append(record)
        
        # 3. Check rule-based compliance if models are available
        if validation_models and schema_acq_name in validation_models:
            model = validation_models[schema_acq_name]
            
            # Ensure the model is instantiated if it's a class
            if isinstance(model, type):
                model = model()
            
            # Validate using the model
            success, errors, warnings, passes = model.validate(data=in_acq)
            
            # Record errors
            for error in errors:
                status = ComplianceStatus.NA if "not found" in error.get('message', '').lower() else ComplianceStatus.ERROR
                compliance_summary.append({
                    "schema acquisition": schema_acq_name,
                    "input acquisition": in_acq_name,
                    "field": error['field'],
                    "value": error['value'],
                    "expected": error.get('expected', error.get('rule_message', '')),
                    "message": error['message'],
                    "rule_name": error['rule_name'],
                    "passed": False,
                    "status": status.value
                })

            # Record warnings
            for warning in warnings:
                compliance_summary.append({
                    "schema acquisition": schema_acq_name,
                    "input acquisition": in_acq_name,
                    "field": warning['field'],
                    "value": warning['value'],
                    "expected": warning.get('expected', warning.get('rule_message', '')),
                    "message": warning['message'],
                    "rule_name": warning['rule_name'],
                    "passed": True,  # Warnings don't fail validation
                    "status": ComplianceStatus.WARNING.value
                })

            # Record passes
            for passed_test in passes:
                compliance_summary.append({
                    "schema acquisition": schema_acq_name,
                    "input acquisition": in_acq_name,
                    "field": passed_test['field'],
                    "value": passed_test['value'],
                    "expected": passed_test.get('expected', passed_test.get('rule_message', '')),
                    "message": passed_test['message'],
                    "rule_name": passed_test['rule_name'],
                    "passed": True,
                    "status": ComplianceStatus.OK.value
                })
            
            # Raise an error if validation fails and `raise_errors` is True
            if raise_errors and not success:
                raise ValueError(f"Validation failed for acquisition '{in_acq_name}'.")
    
    return compliance_summary

