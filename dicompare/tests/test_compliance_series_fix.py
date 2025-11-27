"""Test for series validation fix - ensures single error per series when no match found."""

import pytest
import pandas as pd
import dicompare
from dicompare.validation.helpers import ComplianceStatus
from dicompare.tests.test_helpers import check_session_compliance


def test_series_validation_single_error():
    """Test that series validation creates single error when no matching series found."""

    schema = {
        "acquisitions": {
            "TestAcq": {
                "series": [
                    {
                        "name": "NonMatchingSeries",
                        "fields": [
                            {"field": "Field1", "value": 999},
                            {"field": "Field2", "contains": "XYZ"},
                            {"field": "Field3", "value": 100, "tolerance": 10}
                        ]
                    }
                ]
            }
        }
    }

    # Session data that doesn't match the series constraints
    session_df = pd.DataFrame({
        'Acquisition': ['TestAcq'] * 3,
        'Field1': [1, 2, 3],  # None match 999
        'Field2': ['ABC', 'DEF', 'GHI'],  # None contain 'XYZ'
        'Field3': [50, 60, 70]  # None within 100±10
    })

    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"TestAcq": "TestAcq"}
    )

    # Filter for series-related errors
    series_errors = [r for r in results if r.get('status') == 'error']

    # Should be exactly 1 error for the series, not 3 (one per field)
    assert len(series_errors) == 1, f"Expected 1 series error, got {len(series_errors)}"

    # Check the error message references the series
    error = series_errors[0]
    assert "NonMatchingSeries" in error['message'] or "not found" in error['message']
    assert error['status'] == 'error'  # Series not found is now an error, not NA


def test_series_validation_with_partial_match():
    """Test series validation when some fields match but not all."""

    schema = {
        "acquisitions": {
            "TestAcq": {
                "series": [
                    {
                        "name": "PartialMatch",
                        "fields": [
                            {"field": "FieldA", "value": 10},  # Will match
                            {"field": "FieldB", "value": 999}   # Won't match
                        ]
                    }
                ]
            }
        }
    }

    session_df = pd.DataFrame({
        'Acquisition': ['TestAcq'] * 2,
        'FieldA': [10, 10],  # Matches constraint
        'FieldB': [20, 30]   # Doesn't match constraint
    })

    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"TestAcq": "TestAcq"}
    )

    # Should get single error about series not found
    series_errors = [r for r in results if r.get('status') == 'error']
    assert len(series_errors) == 1

    error = series_errors[0]
    assert "not found" in error['message'].lower() or "PartialMatch" in error['message']


def test_series_validation_constraint_description():
    """Test that series error messages include readable constraint descriptions."""

    schema = {
        "acquisitions": {
            "TestAcq": {
                "series": [
                    {
                        "name": "ComplexSeries",
                        "fields": [
                            {"field": "F1", "value": 5.5, "tolerance": 0.5},
                            {"field": "F2", "contains": "TEST"},
                            {"field": "F3", "value": 100}
                        ]
                    }
                ]
            }
        }
    }

    session_df = pd.DataFrame({
        'Acquisition': ['TestAcq'],
        'F1': [10],  # Outside tolerance
        'F2': ['PROD'],  # Doesn't contain TEST
        'F3': [200]  # Wrong value
    })

    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"TestAcq": "TestAcq"}
    )

    series_errors = [r for r in results if r.get('status') == 'error']
    assert len(series_errors) == 1

    error = series_errors[0]
    # Check message references the series
    assert "ComplexSeries" in error['message'] or "not found" in error['message'].lower()
