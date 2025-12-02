"""
This module provides functions for validating DICOM acquisitions against schema definitions.
"""

from typing import List, Dict, Any, Optional
import logging
from .core import BaseValidationModel, create_validation_models_from_rules
from .helpers import (
    validate_constraint, validate_field_values, create_compliance_record,
    ComplianceStatus
)
import pandas as pd

logger = logging.getLogger(__name__)


def _find_column_match(field_name: str, columns: List[str]) -> Optional[str]:
    """
    Find a matching column name, trying various normalizations.

    Args:
        field_name: Field name from schema (e.g., "Flip Angle")
        columns: Available column names in DataFrame (e.g., ["FlipAngle"])

    Returns:
        Matching column name if found, None otherwise
    """
    # Try exact match first
    if field_name in columns:
        return field_name

    # Try without spaces
    no_space = field_name.replace(' ', '')
    if no_space in columns:
        return no_space

    # Try without underscores
    no_underscore = field_name.replace('_', '')
    if no_underscore in columns:
        return no_underscore

    # Try case-insensitive match
    field_lower = field_name.lower()
    for col in columns:
        if col.lower() == field_lower:
            return col

    # Try case-insensitive without spaces/underscores
    field_normalized = field_name.replace(' ', '').replace('_', '').lower()
    for col in columns:
        col_normalized = col.replace(' ', '').replace('_', '').lower()
        if col_normalized == field_normalized:
            return col

    return None

def check_acquisition_compliance(
    in_session: pd.DataFrame,
    schema_acquisition: Dict[str, Any],
    acquisition_name: Optional[str] = None,
    validation_rules: Optional[List[Dict[str, Any]]] = None,
    validation_model: Optional[BaseValidationModel] = None,
    raise_errors: bool = False
) -> List[Dict[str, Any]]:
    """
    Validate a single DICOM acquisition against a schema acquisition definition.

    This function validates one acquisition at a time, checking both field-level constraints
    and embedded Python validation rules if provided.

    Args:
        in_session (pd.DataFrame): Input session DataFrame. If acquisition_name is provided,
            it will be filtered to that acquisition. Otherwise, assumed to already be filtered.
        schema_acquisition (Dict[str, Any]): Single acquisition definition from schema.
        acquisition_name (Optional[str]): Name of acquisition to filter from in_session.
            If None, assumes in_session is already filtered to the target acquisition.
        validation_rules (Optional[List[Dict[str, Any]]]): List of validation rules for this
            acquisition (from hybrid schemas).
        validation_model (Optional[BaseValidationModel]): Pre-created validation model.
            If not provided but validation_rules are, model will be created dynamically.
        raise_errors (bool): Whether to raise exceptions for validation failures. Defaults to False.

    Returns:
        List[Dict[str, Any]]: A list of compliance results. Each record contains:
            - field: The field(s) being validated
            - value: The actual value(s) found
            - expected: The expected value or constraint
            - message: Error message (for failures) or "OK" (for passes)
            - rule_name: The name of the validation rule (for rule-based validations)
            - passed: Boolean indicating if the check passed
            - status: The compliance status (OK, ERROR, NA, etc.)
            - series: Series name (for series-level checks, None otherwise)

    Example:
        >>> # Load schema
        >>> _, schema, validation_rules = load_schema("schema.json")
        >>> schema_acq = schema["acquisitions"]["T1_MPRAGE"]
        >>>
        >>> # Check compliance for one acquisition
        >>> results = check_acquisition_compliance(
        ...     in_session=session_df,
        ...     schema_acquisition=schema_acq,
        ...     acquisition_name="T1_structural",
        ...     validation_rules=validation_rules.get("T1_MPRAGE")
        ... )
    """
    compliance_summary = []

    # Filter to specific acquisition if name provided
    if acquisition_name is not None:
        if "Acquisition" not in in_session.columns:
            raise ValueError("in_session must have 'Acquisition' column when acquisition_name is specified")
        in_acq = in_session[in_session["Acquisition"] == acquisition_name]

        if in_acq.empty:
            compliance_summary.append(create_compliance_record(
                field="Acquisition",
                message=f"Acquisition '{acquisition_name}' not found in session data.",
                status=ComplianceStatus.ERROR,
                expected=f"Acquisition '{acquisition_name}' to exist"
            ))
            return compliance_summary
    else:
        in_acq = in_session

    # Helper for field validation
    def _check_fields(schema_fields: List[Dict[str, Any]], series_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Check field-level compliance."""
        results = []

        for fdef in schema_fields:
            field = fdef["field"]
            expected_value = fdef.get("value")
            tolerance = fdef.get("tolerance")
            contains = fdef.get("contains")
            contains_any = fdef.get("contains_any")
            contains_all = fdef.get("contains_all")

            # Find matching column name (handles "Flip Angle" vs "FlipAngle")
            matched_field = _find_column_match(field, in_acq.columns.tolist())

            if matched_field is None:
                results.append(create_compliance_record(
                    field=field,
                    message="Field not found in input session.",
                    status=ComplianceStatus.NA,
                    expected=expected_value,
                    series=series_name,
                    tolerance=tolerance,
                    contains=contains,
                    contains_any=contains_any,
                    contains_all=contains_all
                ))
                continue

            actual_values = in_acq[matched_field].unique().tolist()

            # Use validation helper
            passed, invalid_values, message = validate_field_values(
                field, actual_values, expected_value, tolerance, contains, contains_any, contains_all
            )

            results.append(create_compliance_record(
                field=field,
                message=message,
                status=ComplianceStatus.OK if passed else ComplianceStatus.ERROR,
                value=actual_values,
                expected=expected_value,
                series=series_name,
                tolerance=tolerance,
                contains=contains,
                contains_any=contains_any,
                contains_all=contains_all
            ))

        return results

    # 1. Check acquisition-level fields
    schema_fields = schema_acquisition.get("fields", [])
    if schema_fields:
        compliance_summary.extend(_check_fields(schema_fields))

    # 2. Check series-level fields
    schema_series = schema_acquisition.get("series", [])
    for series_def in schema_series:
        series_name = series_def.get("name", "<unnamed>")
        series_fields = series_def.get("fields", [])

        if not series_fields:
            continue

        # Check for missing fields (with normalization)
        missing_fields = []
        field_map = {}  # Map schema field names to actual column names
        for fdef in series_fields:
            schema_field = fdef["field"]
            matched_field = _find_column_match(schema_field, in_acq.columns.tolist())
            if matched_field is None:
                missing_fields.append(schema_field)
            else:
                field_map[schema_field] = matched_field

        if missing_fields:
            field_word = "field" if len(missing_fields) == 1 else "fields"
            compliance_summary.append(create_compliance_record(
                field=", ".join([f["field"] for f in series_fields]),
                message=f"Series not found (required {field_word} '{', '.join(missing_fields)}' not in data)",
                status=ComplianceStatus.NA,
                series=series_name
            ))
            continue

        # Find rows matching ALL constraints
        matching_df = in_acq.copy()
        for fdef in series_fields:
            schema_field = fdef["field"]
            actual_field = field_map[schema_field]
            expected = fdef.get("value")
            tolerance = fdef.get("tolerance")
            contains = fdef.get("contains")
            contains_any = fdef.get("contains_any")
            contains_all = fdef.get("contains_all")

            mask = matching_df[actual_field].apply(
                lambda x: validate_constraint(x, expected, tolerance, contains, contains_any, contains_all)
            )
            matching_df = matching_df[mask]

            if matching_df.empty:
                break

        # Create series result
        field_list = ", ".join([f["field"] for f in series_fields])

        if matching_df.empty:
            # Build constraint description
            constraint_desc = []
            for fdef in series_fields:
                field = fdef["field"]
                expected = fdef.get("value")
                tolerance = fdef.get("tolerance")
                contains = fdef.get("contains")
                contains_any = fdef.get("contains_any")
                contains_all = fdef.get("contains_all")

                if expected is not None:
                    if tolerance is not None:
                        constraint_desc.append(f"{field}={expected}±{tolerance}")
                    else:
                        constraint_desc.append(f"{field}={expected}")
                elif contains is not None:
                    constraint_desc.append(f"{field} contains '{contains}'")
                elif contains_any is not None:
                    constraint_desc.append(f"{field} contains any of {contains_any}")
                elif contains_all is not None:
                    constraint_desc.append(f"{field} contains all of {contains_all}")

            message = f"Series '{series_name}' not found with constraints: {' AND '.join(constraint_desc)}"

            compliance_summary.append(create_compliance_record(
                field=field_list,
                message=message,
                status=ComplianceStatus.ERROR,
                series=series_name
            ))
        else:
            compliance_summary.append(create_compliance_record(
                field=field_list,
                message="Passed.",
                status=ComplianceStatus.OK,
                series=series_name
            ))

    # 3. Check rule-based validation
    if validation_rules or validation_model:
        # Create model if needed
        if not validation_model and validation_rules:
            # Wrap rules in structure expected by create_validation_models_from_rules
            models_dict = create_validation_models_from_rules({"temp_acq": validation_rules})
            validation_model = models_dict.get("temp_acq")

        if validation_model:
            # Ensure model is instantiated
            if isinstance(validation_model, type):
                validation_model = validation_model()

            # Validate
            success, errors, warnings, passes = validation_model.validate(data=in_acq)

            # Record errors
            for error in errors:
                status = ComplianceStatus.NA if "not found" in error.get('message', '').lower() else ComplianceStatus.ERROR
                compliance_summary.append(create_compliance_record(
                    field=error['field'],
                    message=error['message'],
                    status=status,
                    value=error['value'],
                    expected=error.get('expected', error.get('rule_message', '')),
                    rule_name=error['rule_name']
                ))

            # Record warnings
            for warning in warnings:
                compliance_summary.append(create_compliance_record(
                    field=warning['field'],
                    message=warning['message'],
                    status=ComplianceStatus.WARNING,
                    value=warning['value'],
                    expected=warning.get('expected', warning.get('rule_message', '')),
                    rule_name=warning['rule_name']
                ))

            # Record passes
            for passed_test in passes:
                compliance_summary.append(create_compliance_record(
                    field=passed_test['field'],
                    message=passed_test['message'],
                    status=ComplianceStatus.OK,
                    value=passed_test['value'],
                    expected=passed_test.get('expected', passed_test.get('rule_message', '')),
                    rule_name=passed_test['rule_name']
                ))

            if raise_errors and not success:
                raise ValueError(f"Validation failed for acquisition.")

    return compliance_summary
