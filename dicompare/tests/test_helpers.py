"""Shared test helper functions for dicompare tests."""

from dicompare.validation import check_acquisition_compliance
from dicompare.validation.helpers import ComplianceStatus


def check_session_compliance(in_session, schema_data, session_map, validation_rules=None, validation_models=None, raise_errors=False):
    """Helper wrapper to emulate check_session_compliance using new check_acquisition_compliance.

    This function iterates over acquisitions in the schema and checks compliance
    for each one that has a mapping in session_map.

    Args:
        in_session: DataFrame containing the session data
        schema_data: Schema dictionary with 'acquisitions' key
        session_map: Dict mapping reference acquisition names to input acquisition names
        validation_rules: Optional dict of validation rules per acquisition
        validation_models: Optional dict of validation models per acquisition
        raise_errors: Whether to raise errors on compliance failures

    Returns:
        List of compliance result dictionaries
    """
    all_results = []

    for ref_acq_name, schema_acq in schema_data["acquisitions"].items():
        if ref_acq_name not in session_map:
            all_results.append({
                "field": "Acquisition Mapping",
                "value": None,
                "expected": f"Acquisition '{ref_acq_name}' to be mapped",
                "message": f"Reference acquisition '{ref_acq_name}' is not mapped to any input acquisition.",
                "status": ComplianceStatus.ERROR.value,
                "series": None
            })
            continue

        input_acq_name = session_map[ref_acq_name]

        # Get validation rules/model for this acquisition
        acq_rules = validation_rules.get(ref_acq_name) if validation_rules else None
        acq_model = validation_models.get(ref_acq_name) if validation_models else None

        results = check_acquisition_compliance(
            in_session,
            schema_acq,
            acquisition_name=input_acq_name,
            validation_rules=acq_rules,
            validation_model=acq_model,
            raise_errors=raise_errors
        )
        all_results.extend(results)

    return all_results
