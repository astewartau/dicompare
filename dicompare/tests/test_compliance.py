import pytest
import pandas as pd
from dicompare.compliance import (
    check_session_compliance_with_json_reference,
    check_session_compliance_with_python_module
)
from dicompare.validation import BaseValidationModel

# Dummy validation model for python module-based compliance checks.
class DummyValidationModel(BaseValidationModel):
    def validate(self, data: pd.DataFrame):
        # If the input DataFrame has a column 'fail' with a True value in its first row, simulate failure.
        if "fail" in data.columns and data["fail"].iloc[0]:
            return (
                False,
                [{'field': 'fail', 'value': data["fail"].iloc[0], 'expected': False, 'message': 'should be False'}],
                []
            )
        # Otherwise, simulate a passing check.
        return (
            True,
            [],
            [{'field': 'dummy', 'value': 'ok', 'expected': 'ok', 'message': 'passed'}]
        )

# -------------------- Fixtures --------------------

@pytest.fixture
def dummy_in_session():
    """
    Create a dummy input session DataFrame with an "Acquisition" column and other fields.
    """
    data = {
        "Acquisition": ["acq1", "acq1", "acq2"],
        "Age": [30, 30, 25],
        "Name": ["John Doe", "John Doe", "Jane Smith"],
        "SeriesDescription": ["SeriesA", "SeriesA", "SeriesB"],
        "SeriesNumber": [1, 1, 2],
    }
    return pd.DataFrame(data)

@pytest.fixture
def dummy_ref_session_pass():
    """
    A dummy JSON reference session that should pass all compliance checks.
    """
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "Age", "value": 30, "tolerance": 5},
                    {"field": "Name", "value": "John Doe"}
                ],
                "series": [
                    {"name": "SeriesA", "fields": [{"field": "Name", "value": "John Doe"}]}
                ]
            }
        }
    }
    return ref_session

@pytest.fixture
def dummy_ref_session_fail():
    """
    A dummy JSON reference session that triggers compliance failures.
      - 'Weight' field is missing.
      - 'Age' constraint for ref2 is set to a value that does not match.
    """
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "Weight", "value": 70}  # Field not present in in_session.
                ],
                "series": [
                    {"name": "SeriesA", "fields": [{"field": "Name", "value": "John Doe"}]}
                ]
            },
            "ref2": {
                "fields": [
                    {"field": "Age", "value": 40, "tolerance": 2}  # In in_session, ages are 30 and 25.
                ],
                "series": [
                    {"name": "SeriesB", "fields": [{"field": "Name", "value": "Jane Smith"}]}
                ]
            }
        }
    }
    return ref_session

@pytest.fixture
def dummy_session_map_pass():
    """
    Map a reference acquisition to an input acquisition.
    """
    return {"ref1": "acq1"}

@pytest.fixture
def dummy_session_map_fail():
    # Map only "ref1", leaving "ref2" unmapped to trigger the expected error.
    return {"ref1": "acq1"}

@pytest.fixture
def dummy_ref_models():
    """
    A dummy reference models dictionary for python module-based compliance.
    """
    return {"ref1": DummyValidationModel, "ref2": DummyValidationModel}

# -------------------- Tests for JSON Reference Compliance --------------------

def test_check_session_compliance_with_json_reference_pass(dummy_in_session, dummy_ref_session_pass, dummy_session_map_pass):
    """Test a scenario where all acquisition- and series-level constraints pass."""
    compliance = check_session_compliance_with_json_reference(dummy_in_session, dummy_ref_session_pass, dummy_session_map_pass)
    # Expect all records to indicate a passing status.
    for record in compliance:
        assert record["passed"] == True, f"Expected pass but got {record}"

def test_check_session_compliance_with_json_reference_missing_field(dummy_in_session, dummy_ref_session_fail, dummy_session_map_fail):
    """Test when a required field is missing from the input session."""
    compliance = check_session_compliance_with_json_reference(dummy_in_session, dummy_ref_session_fail, dummy_session_map_fail)
    missing_field_record = any(
        "Field not found in input session" in rec.get("message", "")
        for rec in compliance
    )
    unmapped_record = any(
        "not mapped" in rec.get("message", "")
        for rec in compliance
    )
    assert missing_field_record, "Expected missing field error not found."
    assert unmapped_record, "Expected unmapped acquisition error not found."

def test_check_session_compliance_with_json_reference_series_fail(dummy_in_session):
    """
    Test series-level failure where the series constraints do not match.
    For example, require a Name value that is not present.
    """
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [],
                "series": [
                    {"name": "SeriesA", "fields": [{"field": "Name", "value": "Nonexistent Name"}]}
                ]
            }
        }
    }
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_reference(dummy_in_session, ref_session, session_map)
    series_fail = any(
        rec.get("series") is not None and "not found" in rec.get("message", "")
        for rec in compliance
    )
    assert series_fail, "Expected series-level failure record."

# -------------------- Tests for Python Module Compliance --------------------

def test_check_session_compliance_with_python_module_pass(dummy_in_session, dummy_ref_models):
    """
    Test python module compliance when the dummy model passes.
    The dummy model returns a passing record when no failure condition is present.
    """
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_python_module(dummy_in_session, dummy_ref_models, session_map, raise_errors=False)
    passed_records = [r for r in compliance if r["passed"] == True]
    assert passed_records, "Expected at least one passing record."

def test_check_session_compliance_with_python_module_fail(dummy_in_session, dummy_ref_models):
    """
    Test python module compliance when the dummy model returns errors.
    In this case, we add a 'fail' column with a True value to simulate a failure.
    """
    df = dummy_in_session.copy()
    df.loc[df["Acquisition"] == "acq1", "fail"] = True
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_python_module(df, dummy_ref_models, session_map, raise_errors=False)
    failed_records = [r for r in compliance if r["passed"] == False]
    assert failed_records, "Expected at least one failing record."

def test_check_session_compliance_with_python_module_empty_acquisition(dummy_in_session, dummy_ref_models):
    """
    Test when the input session does not contain the acquisition specified in the session map.
    Expect an acquisition-level error record.
    """
    session_map = {"ref1": "nonexistent"}
    compliance = check_session_compliance_with_python_module(dummy_in_session, dummy_ref_models, session_map, raise_errors=False)
    error_record = next((r for r in compliance if "Acquisition-Level Error" in r.get("field", "")), None)
    assert error_record is not None, "Expected an acquisition-level error record."

def test_check_session_compliance_with_python_module_raise_error(dummy_in_session, dummy_ref_models):
    """
    Test that when raise_errors is True and validation fails, a ValueError is raised.
    """
    df = dummy_in_session.copy()
    df.loc[df["Acquisition"] == "acq1", "fail"] = True
    session_map = {"ref1": "acq1"}
    with pytest.raises(ValueError, match="Validation failed for acquisition 'acq1'"):
        check_session_compliance_with_python_module(df, dummy_ref_models, session_map, raise_errors=True)
