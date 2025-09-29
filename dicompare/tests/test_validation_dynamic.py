"""Tests for dynamic validation model generation and safe code execution."""

import pytest
import pandas as pd
import dicompare
from dicompare import ValidationError, ValidationWarning, create_validation_model_from_rules, safe_exec_rule, create_validation_models_from_rules


def test_safe_exec_rule_basic():
    """Test basic safe execution of rule code."""
    code = """
result = value['x'] * 2
value = result
"""
    context = {'value': {'x': 5}}
    result = safe_exec_rule(code, context)
    assert result == 10


def test_safe_exec_rule_with_validation_error():
    """Test that ValidationError is properly raised."""
    code = """
if value['count'] < 3:
    raise ValidationError('Count too low')
"""
    context = {'value': {'count': 2}}
    
    with pytest.raises(ValidationError) as exc_info:
        safe_exec_rule(code, context)
    assert 'Count too low' in str(exc_info.value)


def test_safe_exec_rule_restricted_globals():
    """Test that dangerous operations are blocked."""
    # Test that file operations are blocked
    code = "open('/etc/passwd', 'r')"
    context = {'value': {}}
    
    with pytest.raises(NameError):
        safe_exec_rule(code, context)
    
    # Test that import is blocked
    code = "import os"
    with pytest.raises((NameError, ImportError)):
        safe_exec_rule(code, context)


def test_safe_exec_rule_allowed_functions():
    """Test that allowed functions work correctly."""
    code = """
nums = [1, 2, 3, 4, 5]
value = {
    'sum': sum(nums),
    'max': max(nums),
    'min': min(nums),
    'len': len(nums),
    'abs': abs(-10),
    'round': round(3.7)
}
"""
    context = {'value': {}}
    result = safe_exec_rule(code, context)
    
    assert result['sum'] == 15
    assert result['max'] == 5
    assert result['min'] == 1
    assert result['len'] == 5
    assert result['abs'] == 10
    assert result['round'] == 4


def test_create_validation_model_from_rules():
    """Test creating a dynamic validation model from rules."""
    rules = [
        {
            "id": "check_echo_count",
            "name": "Echo Count Check",
            "description": "Verify at least 3 echoes",
            "fields": ["EchoTime"],
            "implementation": """
if 'EchoTime' not in value.columns:
    raise ValidationError('EchoTime field missing')
echo_count = len(value)
if echo_count < 3:
    raise ValidationError(f'Only {echo_count} echoes found, need at least 3')
"""
        }
    ]
    
    model = create_validation_model_from_rules("TestAcq", rules)
    
    # Test with valid data (3 echoes)
    valid_data = pd.DataFrame({
        'Acquisition': ['TestAcq'] * 3,
        'EchoTime': [5, 10, 15]
    })

    success, errors, warnings, passes = model.validate(valid_data)
    assert success == True
    assert len(errors) == 0
    assert len(passes) == 1
    
    # Test with invalid data (2 echoes)
    invalid_data = pd.DataFrame({
        'Acquisition': ['TestAcq'] * 2,
        'EchoTime': [5, 10]
    })

    success, errors, warnings, passes = model.validate(invalid_data)
    assert success == False
    assert len(errors) == 1
    assert 'Only 2 echoes found' in errors[0]['message']


def test_create_validation_model_multiple_rules():
    """Test model with multiple validation rules."""
    rules = [
        {
            "id": "check_tr_range",
            "name": "TR Range",
            "fields": ["RepetitionTime"],
            "implementation": """
tr_values = value['RepetitionTime']
if tr_values.min() < 20 or tr_values.max() > 30:
    raise ValidationError('TR must be between 20-30ms')
"""
        },
        {
            "id": "check_te_range",
            "name": "TE Range",
            "fields": ["EchoTime"],
            "implementation": """
te_values = value['EchoTime']
if te_values.min() < 2 or te_values.max() > 100:
    raise ValidationError('TE must be between 2-100ms')
"""
        }
    ]
    
    model = create_validation_model_from_rules("MultiRule", rules)
    
    # Test with all valid data
    valid_data = pd.DataFrame({
        'Acquisition': ['MultiRule'] * 3,
        'RepetitionTime': [25, 25, 25],
        'EchoTime': [5, 10, 15]
    })

    success, errors, warnings, passes = model.validate(valid_data)
    assert success == True
    assert len(passes) == 2  # Both rules pass
    
    # Test with invalid TR
    invalid_tr_data = pd.DataFrame({
        'Acquisition': ['MultiRule'] * 3,
        'RepetitionTime': [35, 35, 35],  # Too high
        'EchoTime': [5, 10, 15]
    })

    success, errors, warnings, passes = model.validate(invalid_tr_data)
    assert success == False
    assert len(errors) == 1
    assert 'TR must be between 20-30ms' in errors[0]['message']


def test_create_validation_models_from_rules():
    """Test creating multiple models from a rules dictionary."""
    validation_rules = {
        "QSM": [
            {
                "id": "multi_echo",
                "name": "Multi-echo",
                "fields": ["EchoTime"],
                "implementation": "if len(value) < 3: raise ValidationError('Need 3+ echoes')"
            }
        ],
        "T1w": [
            {
                "id": "check_sequence",
                "name": "Sequence Check",
                "fields": ["SequenceName"],
                "implementation": "if 'MPRAGE' not in str(value['SequenceName'].iloc[0]): raise ValidationError('Must be MPRAGE')"
            }
        ],
        "T2w": []  # No rules for T2w
    }
    
    models = create_validation_models_from_rules(validation_rules)
    
    # Check that models were created for acquisitions with rules
    assert "QSM" in models
    assert "T1w" in models
    assert "T2w" not in models  # No model for empty rules
    
    # Test QSM model
    qsm_data = pd.DataFrame({
        'Acquisition': ['QSM'] * 4,
        'EchoTime': [5, 10, 15, 20]
    })
    success, _, _, _ = models["QSM"].validate(qsm_data)
    assert success == True
    
    # Test T1w model
    t1w_data = pd.DataFrame({
        'Acquisition': ['T1w'],
        'SequenceName': ['MPRAGE']
    })
    success, _, _, _ = models["T1w"].validate(t1w_data)
    assert success == True


def test_dynamic_model_with_pandas_operations():
    """Test that pandas operations work in dynamic models."""
    rules = [
        {
            "id": "check_statistics",
            "name": "Statistical Check",
            "fields": ["FlipAngle"],
            "implementation": """
fa_values = value['FlipAngle']
mean_fa = fa_values.mean()
std_fa = fa_values.std()
if std_fa > 5:
    raise ValidationError(f'Flip angle too variable: std={std_fa:.2f}')
if mean_fa < 5 or mean_fa > 90:
    raise ValidationError(f'Mean flip angle out of range: {mean_fa:.2f}')
"""
        }
    ]
    
    model = create_validation_model_from_rules("Stats", rules)
    
    # Test with low variability (good)
    good_data = pd.DataFrame({
        'Acquisition': ['Stats'] * 5,
        'FlipAngle': [30, 31, 29, 30, 30]  # Low std
    })

    success, errors, warnings, passes = model.validate(good_data)
    assert success == True
    
    # Test with high variability (bad)
    bad_data = pd.DataFrame({
        'Acquisition': ['Stats'] * 5,
        'FlipAngle': [20, 40, 25, 45, 30]  # High std
    })

    success, errors, warnings, passes = model.validate(bad_data)
    assert success == False
    assert 'too variable' in errors[0]['message']


def test_dynamic_model_reference_fields():
    """Test that reference fields are properly extracted from dynamic models."""
    rules = [
        {
            "id": "rule1",
            "name": "Rule 1",
            "fields": ["Field1", "Field2"],
            "implementation": "pass"
        },
        {
            "id": "rule2",
            "name": "Rule 2",
            "fields": ["Field3"],
            "implementation": "pass"
        }
    ]
    
    model = create_validation_model_from_rules("Test", rules)
    
    # Check that all referenced fields are captured
    assert "Field1" in model.reference_fields
    assert "Field2" in model.reference_fields
    assert "Field3" in model.reference_fields
    assert len(model.reference_fields) == 3