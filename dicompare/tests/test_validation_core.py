"""
Unit tests for dicompare.validation.core module.
Tests for BaseValidationModel, ValidationError, ValidationWarning, and dynamic model creation.
"""

import pytest
import pandas as pd
import numpy as np
from dicompare.validation.core import (
    ValidationError,
    ValidationWarning,
    validator,
    BaseValidationModel,
    safe_exec_rule,
    create_validation_model_from_rules,
    create_validation_models_from_rules,
)


class TestValidationExceptions:
    """Tests for ValidationError and ValidationWarning."""

    def test_validation_error_message(self):
        """Test ValidationError with message."""
        error = ValidationError("Test error message")
        assert error.message == "Test error message"
        assert str(error) == "Test error message"

    def test_validation_error_no_message(self):
        """Test ValidationError without message."""
        error = ValidationError()
        assert error.message is None

    def test_validation_warning_message(self):
        """Test ValidationWarning with message."""
        warning = ValidationWarning("Test warning message")
        assert warning.message == "Test warning message"
        assert str(warning) == "Test warning message"

    def test_validation_warning_no_message(self):
        """Test ValidationWarning without message."""
        warning = ValidationWarning()
        assert warning.message is None


class TestValidatorDecorator:
    """Tests for validator decorator."""

    def test_decorator_adds_metadata(self):
        """Test that decorator adds required metadata."""
        @validator(["EchoTime"], "test_rule", "Test validation")
        def my_validator(self, value):
            pass

        assert my_validator._is_field_validator is True
        assert my_validator._field_names == ["EchoTime"]
        assert my_validator._rule_name == "test_rule"
        assert my_validator._rule_message == "Test validation"


class TestBaseValidationModel:
    """Tests for BaseValidationModel class."""

    def test_subclass_registers_validators(self):
        """Test that subclass validators are registered."""
        class TestModel(BaseValidationModel):
            @validator(["EchoTime"], "check_echo", "Echo time validation")
            def validate_echo(self, value):
                if value["EchoTime"].iloc[0] < 0:
                    raise ValidationError("Echo time must be positive")

        model = TestModel()
        assert ("EchoTime",) in model._field_validators
        assert "EchoTime" in model.reference_fields

    def test_validate_with_passing_validator(self):
        """Test validation that passes."""
        class TestModel(BaseValidationModel):
            @validator(["EchoTime"], "check_echo", "Echo time validation")
            def validate_echo(self, value):
                pass  # Always passes

        df = pd.DataFrame({
            "Acquisition": ["T1", "T1"],
            "EchoTime": [0.01, 0.01],
        })
        model = TestModel()
        success, errors, warnings, passes = model.validate(df)
        assert success is True
        assert len(errors) == 0
        assert len(passes) == 1

    def test_validate_with_failing_validator(self):
        """Test validation that fails."""
        class TestModel(BaseValidationModel):
            @validator(["EchoTime"], "check_echo", "Echo time must be positive")
            def validate_echo(self, value):
                raise ValidationError("Echo time is invalid")

        df = pd.DataFrame({
            "Acquisition": ["T1", "T1"],
            "EchoTime": [0.01, 0.01],
        })
        model = TestModel()
        success, errors, warnings, passes = model.validate(df)
        assert success is False
        assert len(errors) == 1
        assert errors[0]["message"] == "Echo time is invalid"

    def test_validate_with_warning(self):
        """Test validation that produces warning."""
        class TestModel(BaseValidationModel):
            @validator(["EchoTime"], "check_echo", "Echo time validation")
            def validate_echo(self, value):
                raise ValidationWarning("Echo time is unusual")

        df = pd.DataFrame({
            "Acquisition": ["T1", "T1"],
            "EchoTime": [0.01, 0.01],
        })
        model = TestModel()
        success, errors, warnings, passes = model.validate(df)
        assert success is True  # Warnings don't cause failure
        assert len(warnings) == 1
        assert "unusual" in warnings[0]["message"]

    def test_validate_missing_field(self):
        """Test validation with missing field."""
        class TestModel(BaseValidationModel):
            @validator(["NonexistentField"], "check_field", "Field validation")
            def validate_field(self, value):
                pass

        df = pd.DataFrame({
            "Acquisition": ["T1"],
            "EchoTime": [0.01],
        })
        model = TestModel()
        success, errors, warnings, passes = model.validate(df)
        assert success is False
        assert "Missing fields" in errors[0]["message"]

    def test_validate_count_from_column(self):
        """Test Count calculation from pre-computed Count column."""
        class TestModel(BaseValidationModel):
            @validator(["EchoTime"], "check_count", "Count validation")
            def validate_count(self, value):
                if value["Count"].iloc[0] != 100:
                    raise ValidationError(f"Expected 100, got {value['Count'].iloc[0]}")

        df = pd.DataFrame({
            "Acquisition": ["T1", "T1"],
            "EchoTime": [0.01, 0.01],
            "Count": [100, 100],
        })
        model = TestModel()
        success, errors, warnings, passes = model.validate(df)
        assert success is True

    def test_validate_count_from_mosaic(self):
        """Test Count calculation from NumberOfImagesInMosaic."""
        class TestModel(BaseValidationModel):
            @validator(["EchoTime"], "check_count", "Count validation")
            def validate_count(self, value):
                if value["Count"].iloc[0] != 64:
                    raise ValidationError(f"Expected 64 slices, got {value['Count'].iloc[0]}")

        df = pd.DataFrame({
            "Acquisition": ["fMRI", "fMRI"],
            "EchoTime": [0.03, 0.03],
            "NumberOfImagesInMosaic": [64, 64],
        })
        model = TestModel()
        success, errors, warnings, passes = model.validate(df)
        assert success is True

    def test_validate_count_from_slice_location(self):
        """Test Count calculation from unique SliceLocation."""
        class TestModel(BaseValidationModel):
            @validator(["EchoTime"], "check_count", "Count validation")
            def validate_count(self, value):
                if value["Count"].iloc[0] != 3:
                    raise ValidationError(f"Expected 3 slices, got {value['Count'].iloc[0]}")

        df = pd.DataFrame({
            "Acquisition": ["T1", "T1", "T1"],
            "EchoTime": [0.01, 0.01, 0.01],
            "SliceLocation": [0.0, 10.0, 20.0],
        })
        model = TestModel()
        success, errors, warnings, passes = model.validate(df)
        assert success is True


class TestSafeExecRule:
    """Tests for safe_exec_rule function."""

    def test_basic_execution(self):
        """Test basic code execution."""
        code = "value = x + y"
        context = {"x": 1, "y": 2}
        result = safe_exec_rule(code, context)
        assert result == 3

    def test_validation_error_raised(self):
        """Test that ValidationError is raised."""
        code = "raise ValidationError('Test error')"
        with pytest.raises(ValidationError) as exc_info:
            safe_exec_rule(code, {})
        assert "Test error" in str(exc_info.value)

    def test_validation_warning_raised(self):
        """Test that ValidationWarning is raised."""
        code = "raise ValidationWarning('Test warning')"
        with pytest.raises(ValidationWarning) as exc_info:
            safe_exec_rule(code, {})
        assert "Test warning" in str(exc_info.value)

    def test_math_module_available(self):
        """Test that math module is available."""
        code = "value = math.sqrt(16)"
        result = safe_exec_rule(code, {})
        assert result == 4.0

    def test_pandas_available(self):
        """Test that pandas is available."""
        code = "value = pd.DataFrame({'a': [1, 2, 3]}).sum()['a']"
        result = safe_exec_rule(code, {})
        assert result == 6

    def test_builtins_available(self):
        """Test that safe builtins are available."""
        code = "value = len([1, 2, 3]) + sum([1, 2, 3])"
        result = safe_exec_rule(code, {})
        assert result == 9


class TestCreateValidationModelFromRules:
    """Tests for create_validation_model_from_rules function."""

    def test_basic_model_creation(self):
        """Test basic dynamic model creation."""
        rules = [{
            "id": "test_rule",
            "name": "Test Rule",
            "fields": ["EchoTime"],
            "description": "Test validation",
            "implementation": "pass"
        }]
        model = create_validation_model_from_rules("Test", rules)
        assert isinstance(model, BaseValidationModel)
        assert ("EchoTime",) in model._field_validators

    def test_model_with_validation_error(self):
        """Test model that raises ValidationError."""
        rules = [{
            "id": "check_echo",
            "name": "Check Echo",
            "fields": ["EchoTime"],
            "description": "Echo must be positive",
            "implementation": "if value['EchoTime'].iloc[0] < 0: raise ValidationError('Negative echo')"
        }]
        model = create_validation_model_from_rules("Test", rules)
        df = pd.DataFrame({
            "Acquisition": ["T1"],
            "EchoTime": [-0.01],
        })
        success, errors, warnings, passes = model.validate(df)
        assert success is False
        assert "Negative echo" in errors[0]["message"]

    def test_model_with_exception_wrapped(self):
        """Test that general exceptions are wrapped."""
        rules = [{
            "id": "bad_rule",
            "name": "Bad Rule",
            "fields": ["EchoTime"],
            "description": "Bad validation",
            "implementation": "1/0"  # ZeroDivisionError
        }]
        model = create_validation_model_from_rules("Test", rules)
        df = pd.DataFrame({
            "Acquisition": ["T1"],
            "EchoTime": [0.01],
        })
        success, errors, warnings, passes = model.validate(df)
        assert success is False
        assert "failed" in errors[0]["message"]


class TestCreateValidationModelsFromRules:
    """Tests for create_validation_models_from_rules function."""

    def test_multiple_models(self):
        """Test creating multiple models."""
        rules = {
            "T1": [{
                "id": "t1_rule",
                "name": "T1 Rule",
                "fields": ["EchoTime"],
                "implementation": "pass"
            }],
            "T2": [{
                "id": "t2_rule",
                "name": "T2 Rule",
                "fields": ["EchoTime"],
                "implementation": "pass"
            }],
        }
        models = create_validation_models_from_rules(rules)
        assert "T1" in models
        assert "T2" in models
        assert isinstance(models["T1"], BaseValidationModel)
        assert isinstance(models["T2"], BaseValidationModel)

    def test_empty_rules_skipped(self):
        """Test that acquisitions with empty rules are skipped."""
        rules = {
            "T1": [{
                "id": "t1_rule",
                "name": "T1 Rule",
                "fields": ["EchoTime"],
                "implementation": "pass"
            }],
            "T2": [],  # Empty rules
        }
        models = create_validation_models_from_rules(rules)
        assert "T1" in models
        assert "T2" not in models
