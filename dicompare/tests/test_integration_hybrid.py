"""Integration test for the complete hybrid schema workflow."""

import pytest
import pandas as pd
import json
import tempfile
import os
import dicompare


def test_end_to_end_hybrid_workflow():
    """Test the complete workflow: load hybrid schema -> validate session."""
    # Create a realistic hybrid schema
    hybrid_schema = {
        "version": "1.0",
        "name": "Multi-Modal Brain Imaging Protocol",
        "acquisitions": {
            "T1w": {
                "fields": [
                    {"field": "RepetitionTime", "value": 2300, "tolerance": 100},
                    {"field": "EchoTime", "value": 2.98, "tolerance": 0.2},
                    {"field": "FlipAngle", "value": 9, "tolerance": 1}
                ],
                "rules": [
                    {
                        "id": "check_t1_timing",
                        "name": "T1 Timing Validation",
                        "description": "Verify T1w timing parameters are within acceptable ranges",
                        "fields": ["RepetitionTime", "EchoTime"],
                        "implementation": """
# T1w timing is always good for this test
pass
"""
                    }
                ]
            },
            "QSM": {
                "fields": [
                    {"field": "RepetitionTime", "value": 28, "tolerance": 3}
                ],
                "rules": [
                    {
                        "id": "multi_echo_check",
                        "name": "Multi-Echo Validation",
                        "description": "QSM requires at least 3 echoes",
                        "fields": ["EchoTime"],
                        "implementation": """
echo_times = value['EchoTime']
if len(echo_times) < 3:
    raise ValidationError(f'QSM needs >=3 echoes, found {len(echo_times)}')
te_range = max(echo_times) - min(echo_times)
if te_range < 15:
    raise ValidationError(f'Echo time range too small: {te_range:.1f}ms')
"""
                    },
                    {
                        "id": "qsm_spacing_check", 
                        "name": "Echo Spacing Check",
                        "fields": ["EchoTime"],
                        "implementation": """
# Simple check that passes for the test
if len(value['EchoTime']) > 0:
    # All good, passes the test
    pass
"""
                    }
                ]
            },
            "fMRI": {
                "fields": [
                    {"field": "RepetitionTime", "value": 2000, "tolerance": 100}
                ],
                "series": [
                    {
                        "name": "task-rest",
                        "fields": [
                            {"field": "TaskName", "contains": "rest"},
                            {"field": "NumberOfVolumes", "value": 300, "tolerance": 50}
                        ]
                    }
                ]
            }
        }
    }
    
    # Create session data with mixed compliance scenarios
    session_data = []
    
    # T1w: Good field values, passes timing rule
    session_data.extend([
        {"Acquisition": "T1w", "RepetitionTime": 2300, "EchoTime": 2.98, "FlipAngle": 9},
        {"Acquisition": "T1w", "RepetitionTime": 2310, "EchoTime": 3.0, "FlipAngle": 9}
    ])
    
    # QSM: Good field values, 4 echoes (passes multi-echo), good spacing
    qsm_echoes = [4.9, 9.8, 14.7, 20.5]  # 4.9ms spacing, 15.6ms range
    for i, te in enumerate(qsm_echoes):
        session_data.append({
            "Acquisition": "QSM", 
            "RepetitionTime": 28, 
            "EchoTime": te,
            "SeriesNumber": 1,
            "InstanceNumber": i+1
        })
    
    # fMRI: Good field values, matches series criteria
    for vol in range(295):  # Within tolerance of 300
        session_data.append({
            "Acquisition": "fMRI",
            "RepetitionTime": 2000,
            "TaskName": "rest-state",
            "NumberOfVolumes": 295,
            "SeriesNumber": 1,
            "InstanceNumber": vol+1
        })
    
    session_df = pd.DataFrame(session_data)
    
    # Write schema to temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(hybrid_schema, f)
        schema_path = f.name
    
    try:
        # Load hybrid schema
        reference_fields, schema_data, validation_rules = dicompare.load_hybrid_schema(schema_path)
        
        # Verify schema loading worked
        assert len(reference_fields) >= 5  # TR, TE, FA, TaskName, NumberOfVolumes
        assert "RepetitionTime" in reference_fields
        assert "EchoTime" in reference_fields
        assert len(validation_rules) == 2  # T1w and QSM have rules
        assert "T1w" in validation_rules
        assert "QSM" in validation_rules
        
        # Check session compliance using unified function
        session_map = {"T1w": "T1w", "QSM": "QSM", "fMRI": "fMRI"}
        results = dicompare.check_session_compliance(
            in_session=session_df,
            schema_data=schema_data,
            session_map=session_map,
            validation_rules=validation_rules
        )
        
        # Analyze results
        passed_results = [r for r in results if r['passed']]
        failed_results = [r for r in results if not r['passed']]
        
        # All checks should pass in this scenario
        assert len(failed_results) == 0, f"Unexpected failures: {failed_results}"
        
        # Should have multiple passed checks
        assert len(passed_results) >= 6  # Multiple field + rule checks
        
        # Verify specific rule results
        t1_rule_results = [r for r in passed_results if r.get('rule_name') == 'T1 Timing Validation']
        assert len(t1_rule_results) == 1
        
        qsm_rule_results = [r for r in passed_results if 'Multi-Echo' in r.get('rule_name', '')]
        assert len(qsm_rule_results) == 1
        
        echo_spacing_results = [r for r in passed_results if 'Echo Spacing' in r.get('rule_name', '')]
        assert len(echo_spacing_results) == 1
        
    finally:
        # Clean up temporary file
        os.unlink(schema_path)


def test_hybrid_workflow_with_failures():
    """Test hybrid workflow with various failure scenarios."""
    # Schema with strict requirements
    schema = {
        "acquisitions": {
            "Strict": {
                "fields": [
                    {"field": "RequiredField", "value": 100}  # Exact match required
                ],
                "rules": [
                    {
                        "id": "strict_rule",
                        "name": "Strict Validation",
                        "fields": ["TestField"],
                        "implementation": """
val = value['TestField'].iloc[0]
if val != 42:
    raise ValidationError(f'TestField must be exactly 42, got {val}')
"""
                    }
                ]
            }
        }
    }
    
    # Session with failing data
    session_df = pd.DataFrame({
        'Acquisition': ['Strict'] * 2,
        'RequiredField': [99, 101],  # Wrong values (not 100)
        'TestField': [41, 43]        # Wrong values (not 42)
    })
    
    rules = {"Strict": schema["acquisitions"]["Strict"]["rules"]}
    
    results = dicompare.check_session_compliance(
        in_session=session_df,
        schema_data=schema,
        session_map={"Strict": "Strict"},
        validation_rules=rules
    )
    
    # Should have failures
    failed_results = [r for r in results if not r['passed']]
    passed_results = [r for r in results if r['passed']]
    
    # Expect 2 failures: 1 field mismatch + 1 rule failure
    assert len(failed_results) == 2
    assert len(passed_results) == 0
    
    # Check specific failure types
    field_failures = [r for r in failed_results if 'RequiredField' in str(r.get('field', ''))]
    rule_failures = [r for r in failed_results if 'TestField' in str(r.get('field', ''))]
    
    assert len(field_failures) == 1
    assert len(rule_failures) == 1
    assert 'must be exactly 42' in rule_failures[0]['message']


def test_backward_compatibility_with_existing_schemas():
    """Test that the unified function works with existing field-only schemas."""
    # Traditional field-only schema (no rules)
    old_schema = {
        "acquisitions": {
            "Traditional": {
                "fields": [
                    {"field": "ProtocolName", "contains": "MPRAGE"},
                    {"field": "SliceThickness", "value": 1.0, "tolerance": 0.1}
                ],
                "series": [
                    {
                        "name": "sagittal",
                        "fields": [
                            {"field": "ImageOrientationPatient", "contains": "1\\0\\0"},
                            {"field": "NumberOfSlices", "value": 176, "tolerance": 10}
                        ]
                    }
                ]
            }
        }
    }
    
    # Compatible session data
    session_df = pd.DataFrame({
        'Acquisition': ['Traditional'] * 4,
        'ProtocolName': ['t1_mprage_sag'] * 4,
        'SliceThickness': [1.0] * 4,
        'ImageOrientationPatient': ['1\\0\\0\\0\\1\\0'] * 4,
        'NumberOfSlices': [176] * 4
    })
    
    # Test with no validation rules (traditional usage)
    results = dicompare.check_session_compliance(
        in_session=session_df,
        schema_data=old_schema,
        session_map={"Traditional": "Traditional"}
        # No validation_rules parameter
    )
    
    # Should only have field-based compliance checks
    passed_results = [r for r in results if r['passed']]
    failed_results = [r for r in results if not r['passed']]
    
    # All field checks should pass
    assert len(failed_results) == 0
    assert len(passed_results) >= 3  # Acquisition fields + series result (not individual fields)
    
    # None should be rule-based
    rule_results = [r for r in results if 'rule_name' in r and r['rule_name'] not in ['Field validation', None]]
    assert len(rule_results) == 0  # No custom rules