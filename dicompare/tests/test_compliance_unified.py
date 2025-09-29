"""Tests for the unified compliance checking function."""

import pytest
import pandas as pd
import json
import dicompare
from dicompare import check_session_compliance, ValidationError


def test_unified_compliance_field_only(tmp_path):
    """Test unified compliance with field-only schema (backward compatibility)."""
    # Create a simple field-only schema
    schema = {
        "acquisitions": {
            "T1w": {
                "fields": [
                    {"field": "RepetitionTime", "value": 2300, "tolerance": 50},
                    {"field": "EchoTime", "value": 2.98, "tolerance": 0.1},
                    {"field": "SequenceName", "contains": "MPRAGE"}
                ]
            }
        }
    }
    
    # Create input session
    session_df = pd.DataFrame({
        'Acquisition': ['T1w'] * 3,
        'RepetitionTime': [2300, 2310, 2295],
        'EchoTime': [2.98, 2.99, 2.97],
        'SequenceName': ['t1_mprage_sag', 't1_mprage_sag', 't1_mprage_sag']
    })
    
    # Check compliance
    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"T1w": "T1w"}
    )
    
    # All field checks should pass
    passed_results = [r for r in results if r['passed']]
    failed_results = [r for r in results if not r['passed']]
    
    assert len(passed_results) == 3  # All 3 fields pass
    assert len(failed_results) == 0


def test_unified_compliance_with_rules(tmp_path):
    """Test unified compliance with hybrid schema containing rules."""
    # Create hybrid schema with both fields and rules
    schema = {
        "acquisitions": {
            "QSM": {
                "fields": [
                    {"field": "FlipAngle", "value": 15, "tolerance": 1}
                ]
            }
        }
    }
    
    # Create validation rules
    validation_rules = {
        "QSM": [
            {
                "id": "echo_count",
                "name": "Echo Count Check",
                "fields": ["EchoTime"],
                "implementation": """
echo_times = value['EchoTime']
if len(echo_times) < 3:
    raise ValidationError(f'Need at least 3 echoes, found {len(echo_times)}')
"""
            }
        ]
    }
    
    # Create input session with valid field but invalid rule
    session_df = pd.DataFrame({
        'Acquisition': ['QSM'] * 2,  # Only 2 echoes (should fail rule)
        'FlipAngle': [15, 15],
        'EchoTime': [5, 10]
    })
    
    # Check compliance
    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"QSM": "QSM"},
        validation_rules=validation_rules
    )
    
    # Field check should pass, rule check should fail
    field_results = [r for r in results if 'FlipAngle' in str(r.get('field', ''))]
    rule_results = [r for r in results if 'EchoTime' in str(r.get('field', ''))]
    
    assert len(field_results) == 1
    assert field_results[0]['passed'] == True  # FlipAngle passes
    
    assert len(rule_results) == 1
    assert rule_results[0]['passed'] == False  # Echo count fails
    assert 'Need at least 3 echoes' in rule_results[0]['message']


def test_unified_compliance_series_fields(tmp_path):
    """Test unified compliance with series-level field checks."""
    schema = {
        "acquisitions": {
            "fMRI": {
                "fields": [
                    {"field": "RepetitionTime", "value": 2000}
                ],
                "series": [
                    {
                        "name": "task-rest",
                        "fields": [
                            {"field": "TaskName", "value": "rest"},
                            {"field": "NumberOfVolumes", "value": 300, "tolerance": 10}
                        ]
                    }
                ]
            }
        }
    }
    
    # Create session with matching series
    session_df = pd.DataFrame({
        'Acquisition': ['fMRI'] * 2,
        'RepetitionTime': [2000, 2000],
        'TaskName': ['rest', 'rest'],
        'NumberOfVolumes': [295, 305]  # Within tolerance
    })
    
    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"fMRI": "fMRI"}
    )
    
    # Should have 2 passes: 1 acquisition field + 1 series result (not individual fields)
    passed_results = [r for r in results if r['passed']]
    assert len(passed_results) == 2


def test_unified_compliance_missing_acquisition(tmp_path):
    """Test unified compliance when input acquisition is missing."""
    schema = {
        "acquisitions": {
            "T2w": {
                "fields": [
                    {"field": "EchoTime", "value": 100}
                ]
            }
        }
    }
    
    # Create session without the expected acquisition
    session_df = pd.DataFrame({
        'Acquisition': ['T1w'] * 2,
        'EchoTime': [3, 3]
    })
    
    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"T2w": "T2w"}  # Map to non-existent acquisition
    )
    
    # Should have one error for missing acquisition
    assert len(results) == 1
    assert results[0]['passed'] == False
    assert 'not found in data' in results[0]['message']
    assert results[0]['field'] == 'Acquisition-Level Error'


def test_unified_compliance_mixed_passes_and_failures():
    """Test unified compliance with mix of passing and failing checks."""
    schema = {
        "acquisitions": {
            "MultiTest": {
                "fields": [
                    {"field": "Field1", "value": 100},  # Will pass
                    {"field": "Field2", "value": 200},  # Will fail
                    {"field": "Field3", "value": 300}   # Field missing
                ]
            }
        }
    }
    
    validation_rules = {
        "MultiTest": [
            {
                "id": "check_field4",
                "name": "Field4 Check",
                "fields": ["Field4"],
                "implementation": """
if value['Field4'].iloc[0] > 500:
    raise ValidationError('Field4 too large')
"""
            }
        ]
    }
    
    session_df = pd.DataFrame({
        'Acquisition': ['MultiTest'] * 2,
        'Field1': [100, 100],  # Matches expected
        'Field2': [250, 250],  # Doesn't match expected
        'Field4': [600, 600]   # Will fail rule check
        # Field3 is missing
    })
    
    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"MultiTest": "MultiTest"},
        validation_rules=validation_rules
    )
    
    # Count results by type
    passed = [r for r in results if r['passed']]
    failed = [r for r in results if not r['passed']]
    
    assert len(passed) == 1  # Only Field1 passes
    assert len(failed) == 3  # Field2 mismatch, Field3 missing, Field4 rule fails
    
    # Check specific failures
    field2_results = [r for r in failed if 'Field2' in str(r.get('field', ''))]
    assert len(field2_results) == 1
    
    field3_results = [r for r in failed if 'Field3' in str(r.get('field', ''))]
    assert len(field3_results) == 1
    assert 'not found' in field3_results[0]['message'].lower()
    
    field4_results = [r for r in failed if 'Field4' in str(r.get('field', ''))]
    assert len(field4_results) == 1
    assert 'too large' in field4_results[0]['message']


def test_unified_compliance_raise_errors():
    """Test that unified compliance can raise errors when requested (only for rule-based validation)."""
    schema = {
        "acquisitions": {
            "Test": {
                "fields": []  # No field validation, only rules
            }
        }
    }
    
    session_df = pd.DataFrame({
        'Acquisition': ['Test'],
        'BadField': [111]
    })
    
    # The raise_errors flag only works with rule-based validation
    validation_rules = {
        "Test": [
            {
                "id": "fail_rule",
                "name": "Always Fails",
                "fields": ["BadField"],
                "implementation": "raise ValidationError('This always fails')"
            }
        ]
    }
    
    with pytest.raises(ValueError) as exc_info:
        check_session_compliance(
            in_session=session_df,
            schema_data=schema,
            session_map={"Test": "Test"},
            validation_rules=validation_rules,
            raise_errors=True
        )
    
    assert "Validation failed" in str(exc_info.value)


def test_unified_compliance_pre_created_models():
    """Test unified compliance with pre-created validation models."""
    from dicompare import create_validation_model_from_rules
    
    # Create a model manually
    rules = [
        {
            "id": "custom_check",
            "name": "Custom Check",
            "fields": ["CustomField"],
            "implementation": """
if value['CustomField'].iloc[0] != 42:
    raise ValidationError('CustomField must be 42')
"""
        }
    ]
    
    model = create_validation_model_from_rules("Custom", rules)
    
    schema = {
        "acquisitions": {
            "Custom": {
                "fields": []  # No field checks, only rules
            }
        }
    }
    
    session_df = pd.DataFrame({
        'Acquisition': ['Custom'],
        'CustomField': [42]  # Correct value
    })
    
    # Pass pre-created model
    results = check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"Custom": "Custom"},
        validation_models={"Custom": model}
    )
    
    # Should pass the custom check
    assert len(results) == 1
    assert results[0]['passed'] == True
    assert results[0]['rule_name'] == 'Custom Check'