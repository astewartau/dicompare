from typing import Callable, List, Dict, Any, Tuple

class ValidationError(Exception):
    def __init__(self, message: str=None):
        self.message = message
        super().__init__(message)


def validator(field_name: str, rule_message: str = "Validation rule applied"):
    """Decorator for field-level validators."""
    def decorator(func: Callable):
        func._is_field_validator = True
        func._field_name = field_name
        func._rule_message = rule_message
        return func
    return decorator


def model_validator(rule_message: str = "Model-level validation rule applied"):
    """Decorator for model-level validators."""
    def decorator(func: Callable):
        func._is_model_validator = True
        func._rule_message = rule_message
        return func
    return decorator


class BaseValidationModel:
    _field_validators: Dict[str, List[Callable]]
    _model_validators: List[Callable]

    def __init_subclass__(cls, **kwargs):
        cls._field_validators = {}
        cls._model_validators = []

        for attr_name, attr_value in cls.__dict__.items():
            if hasattr(attr_value, "_is_field_validator"):
                field_name = attr_value._field_name
                cls._field_validators.setdefault(field_name, []).append(attr_value)
            elif hasattr(attr_value, "_is_model_validator"):
                cls._model_validators.append(attr_value)

    def validate(self, data: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validate the input data and return results.

        Returns:
            Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
                - Overall success (True if all validations passed).
                - List of failed tests with details (field, value, error message).
                - List of passed tests with details (field, value, rule message).
        """
        errors = []
        passes = []

        # Field-level validation
        for field, validators in self._field_validators.items():
            value = data.get(field)
            for validator in validators:
                try:
                    validator(self, value, data)
                    passes.append({
                        "field": field,
                        "value": value,
                        "rule": validator._rule_message,
                        "message": None,
                        "passed": True
                    })
                except ValidationError as e:
                    errors.append({
                        "field": field,
                        "value": value,
                        "rule": validator._rule_message,
                        "message": e.message if e.message else None,
                        "passed": False
                    })

        # Model-level validation
        for validator in self._model_validators:
            try:
                validator(self, data)
                passes.append({
                    "field": None,
                    "value": None,
                    "rule": validator._rule_message,
                    "message": None,
                    "passed": True
                })
            except ValidationError as e:
                errors.append({
                    "field": None,
                    "value": None,
                    "rule": validator._rule_message,
                    "message": e.message if e.message else None,
                    "passed": False
                })

        overall_success = len(errors) == 0
        return overall_success, errors, passes
