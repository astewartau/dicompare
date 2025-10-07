"""Test for series validation fix - ensures single error per series when no match found."""

import pytest
import pandas as pd
import dicompare
from dicompare.validation import check_acquisition_compliance
from dicompare.validation.helpers import ComplianceStatus

def check_session_compliance(in_session, schema_data, session_map, validation_rules=None, validation_models=None, raise_errors=False):
    """Helper for legacy test format - uses new API internally."""
    for ref_acq_name, input_acq_name in session_map.items():
        if ref_acq_name in schema_data["acquisitions"]:
            acq_rules = validation_rules.get(ref_acq_name) if validation_rules else None
            acq_model = validation_models.get(ref_acq_name) if validation_models else None
            return check_acquisition_compliance(
                in_session,
                schema_data["acquisitions"][ref_acq_name],
                acquisition_name=input_acq_name,
                validation_rules=acq_rules,
                validation_model=acq_model,
                raise_errors=raise_errors
            )
    return []


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
    series_errors = [r for r in results if r.get('series') == 'NonMatchingSeries' and not r['passed']]
    
    # Should be exactly 1 error for the series, not 3 (one per field)
    assert len(series_errors) == 1, f"Expected 1 series error, got {len(series_errors)}"
    
    # Check the error has all fields listed
    error = series_errors[0]
    assert "Field1, Field2, Field3" in error['field']
    assert "NonMatchingSeries" in error['message']
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
    series_errors = [r for r in results if r.get('series') == 'PartialMatch' and not r['passed']]
    assert len(series_errors) == 1
    
    error = series_errors[0]
    assert "FieldA, FieldB" in error['field']
    assert "FieldA=10" in error['message']
    assert "FieldB=999" in error['message']


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
    
    series_errors = [r for r in results if r.get('series') == 'ComplexSeries' and not r['passed']]
    assert len(series_errors) == 1
    
    error = series_errors[0]
    # Check constraint description includes all constraints
    assert "F1=5.5±0.5" in error['message']
    assert "F2 contains 'TEST'" in error['message']
    assert "F3=100" in error['message']
    assert " AND " in error['message']  # Constraints are joined with AND