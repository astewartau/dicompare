"""
This module provides utilities and base classes for validation models and rules 
used in DICOM compliance checks.

"""

from typing import Callable, List, Dict, Any, Tuple, Type
import pandas as pd
from itertools import chain
import math
from .utils import make_hashable
from .validation_helpers import ComplianceStatus
    
def get_unique_combinations(data: pd.DataFrame, fields: List[str]) -> pd.DataFrame:
    """
    Filter a DataFrame to unique combinations of specified fields, filling varying values 
    in other fields with `None`.

    Notes:
        - Ensures all values are hashable to avoid grouping issues.
        - Useful for simplifying validation by grouping related data.

    Args:
        data (pd.DataFrame): The input DataFrame.
        fields (List[str]): The list of fields to extract unique combinations.

    Returns:
        pd.DataFrame: A DataFrame with unique combinations of the specified fields, 
                      and other fields set to `None` if they vary.
    """

    # Ensure fields are strings and drop duplicates
    fields = [str(field) for field in fields]

    # Flatten all values in the DataFrame to ensure they are hashable
    for col in data.columns:
        data[col] = data[col].apply(make_hashable)

    # Get unique combinations of specified fields
    unique_combinations = data.groupby(fields, dropna=False).first().reset_index()

    # Set all other fields to None if they vary across the combinations
    for col in data.columns:
        if col not in fields:
            # Check if the column has varying values within each group
            is_unique_per_group = data.groupby(fields)[col].nunique(dropna=False).max() == 1
            if not is_unique_per_group:
                unique_combinations[col] = None
            else:
                unique_combinations[col] = data.groupby(fields)[col].first().values

    return unique_combinations

class ValidationError(Exception):
    """
    Custom exception raised for validation errors.

    Args:
        message (str, optional): The error message describing the validation failure.

    Attributes:
        message (str): The error message.
    """

    def __init__(self, message: str=None):
        self.message = message
        super().__init__(message)


class ValidationWarning(Exception):
    """
    Custom exception raised for validation warnings.

    Unlike ValidationError, ValidationWarning indicates issues that should be flagged
    but don't prevent validation from continuing.

    Args:
        message (str, optional): The warning message describing the validation issue.

    Attributes:
        message (str): The warning message.
    """

    def __init__(self, message: str=None):
        self.message = message
        super().__init__(message)

def validator(field_names: List[str], rule_name: str, rule_message: str):
    """
    Decorator for defining field-level validation rules.

    Notes:
        - Decorated functions are automatically registered in `BaseValidationModel`.
        - The rule will be applied to unique combinations of the specified fields.

    Args:
        field_names (List[str]): The list of field names the rule applies to.
        rule_name (str): The name of the validation rule.
        rule_message (str): A description of the validation rule.

    Returns:
        Callable: The decorated function.
    """

    def decorator(func: Callable):
        func._is_field_validator = True
        func._field_names = field_names
        func._rule_name = rule_name
        func._rule_message = rule_message
        return func
    return decorator

class BaseValidationModel:
    """
    Base class for defining and applying validation rules to DICOM sessions.

    Notes:
        - Subclasses can define validation rules using the `validator` and `model_validator` decorators.
        - Field-level rules apply to specific columns (fields) in the DataFrame.
        - Model-level rules apply to the entire DataFrame.

    Attributes:
        _field_validators (Dict[Tuple[str, ...], List[Callable]]): Registered field-level validators.
        _model_validators (List[Callable]): Registered model-level validators.

    Methods:
        - validate(data): Runs all validation rules on the provided data.
    """

    _field_validators: Dict[Tuple[str, ...], List[Callable]]
    _model_validators: List[Callable]

    def __init_subclass__(cls, **kwargs):
        """
        Automatically registers validation rules in subclasses.

        Args:
            cls (Type[BaseValidationModel]): The subclass being initialized.
        """
        super().__init_subclass__(**kwargs)

        # collect all the field‑level and model‑level validators
        cls._field_validators = {}
        cls._model_validators = []

        for attr_name, attr_value in cls.__dict__.items():
            if hasattr(attr_value, "_is_field_validator"):
                field_names = tuple(attr_value._field_names)
                cls._field_validators.setdefault(field_names, []).append(attr_value)
            elif hasattr(attr_value, "_is_model_validator"):
                cls._model_validators.append(attr_value)

        # build a class‑level set of every field name used in any validator decorator
        cls.reference_fields = set(chain.from_iterable(cls._field_validators.keys()))

    def __init__(self):
        """
        Expose the same `reference_fields` on each instance.
        """
        # instance attribute references the class‑level set
        self.reference_fields = self.__class__.reference_fields

    def validate(
        self,
        data: pd.DataFrame
    ) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validate the input DataFrame against the registered rules.

        Notes:
            - Validations are performed for each unique acquisition in the DataFrame.
            - Field-level validations check unique combinations of specified fields.
            - Model-level validations apply to the entire dataset.

        Args:
            data (pd.DataFrame): The input DataFrame containing DICOM session data.

        Returns:
            Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
                - Overall success (True if all validations passed without errors).
                - List of failed tests with details:
                    - acquisition: The acquisition being validated.
                    - field: The field(s) involved in the validation.
                    - rule_name: The validation rule description.
                    - value: The actual value being validated.
                    - message: The error message (if validation failed).
                    - passed: False (indicating failure).
                    - status: "error" (indicating error level).
                - List of warnings with details:
                    - acquisition: The acquisition being validated.
                    - field: The field(s) involved in the validation.
                    - rule_name: The validation rule description.
                    - value: The actual value being validated.
                    - message: The warning message.
                    - passed: True (indicating validation continued).
                    - status: "warning" (indicating warning level).
                - List of passed tests with details:
                    - acquisition: The acquisition being validated.
                    - field: The field(s) involved in the validation.
                    - rule_name: The validation rule description.
                    - value: The actual value being validated.
                    - message: None (indicating success).
                    - passed: True (indicating success).
                    - status: "ok" (indicating success).
        """
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        passes: List[Dict[str, Any]] = []

        # Field‑level validation
        for acquisition in data["Acquisition"].unique():
            acq_df = data[data["Acquisition"] == acquisition]
            for field_names, validators in self._field_validators.items():
                # missing column check
                missing = [f for f in field_names if f not in acq_df.columns]
                if missing:
                    errors.append({
                        "acquisition": acquisition,
                        "field": ", ".join(field_names),
                        "rule_name": validators[0]._rule_name,
                        "expected": validators[0]._rule_message,
                        "value": None,
                        "message": f"Missing fields: {', '.join(missing)}.",
                        "passed": False,
                    })
                    continue

                # get unique combinations + counts
                grouped = (
                    acq_df[list(field_names)]
                    .groupby(list(field_names), dropna=False)
                    .size()
                    .reset_index(name="Count")
                )

                # run each validator
                for validator_func in validators:
                    try:
                        validator_func(self, grouped)
                        passes.append({
                            "acquisition": acquisition,
                            "field": ", ".join(field_names),
                            "rule_name": validator_func._rule_name,
                            "expected": validator_func._rule_message,
                            "value": str(grouped.to_dict(orient="list")),
                            "message": "OK",
                            "passed": True,
                            "status": ComplianceStatus.OK.value,
                        })
                    except ValidationWarning as w:
                        warnings.append({
                            "acquisition": acquisition,
                            "field": ", ".join(field_names),
                            "rule_name": validator_func._rule_name,
                            "expected": validator_func._rule_message,
                            "value": str(grouped.to_dict(orient="list")),
                            "message": str(w),
                            "passed": True,  # Validation continues despite warning
                            "status": ComplianceStatus.WARNING.value,
                        })
                    except ValidationError as e:
                        errors.append({
                            "acquisition": acquisition,
                            "field": ", ".join(field_names),
                            "rule_name": validator_func._rule_name,
                            "expected": validator_func._rule_message,
                            "value": str(grouped.to_dict(orient="list")),
                            "message": str(e),
                            "passed": False,
                            "status": ComplianceStatus.ERROR.value,
                        })

        overall_success = len(errors) == 0
        return overall_success, errors, warnings, passes


def safe_exec_rule(code: str, context: Dict[str, Any]) -> Any:
    """
    Safely execute rule implementation code with restricted globals.
    
    This function provides a sandboxed environment for executing validation rules
    embedded in JSON schemas, with access only to approved functions and modules.
    
    Args:
        code (str): The Python code to execute.
        context (Dict[str, Any]): Local variables available to the code.
        
    Returns:
        Any: The result of the code execution.
        
    Raises:
        ValidationError: If the code raises a validation error.
        Exception: If the code raises any other exception.
    """
    # Import builtins for safe but complete execution environment
    import builtins

    # Define allowed globals for safe execution
    # Note: We provide a reasonably complete builtins environment to avoid scoping issues
    # with generator expressions and f-strings, while still restricting dangerous functions
    safe_builtins = {
        name: getattr(builtins, name)
        for name in dir(builtins)
        if not name.startswith('_') and name not in {
            'exec', 'eval', 'compile', 'open', 'input', 'print',  # I/O and execution
            'exit', 'quit', 'help', 'license', 'copyright', 'credits',  # Interactive
            '__import__', 'globals', 'locals', 'vars', 'dir',  # Introspection that could be dangerous
            'delattr', 'setattr', 'getattr', 'hasattr',  # Attribute manipulation
        }
    }

    allowed_globals = {
        '__builtins__': safe_builtins,
        'ValidationError': ValidationError,
        'ValidationWarning': ValidationWarning,
        'pd': pd,
        'math': math,
        'abs': abs,
        'len': len,
        'all': all,
        'any': any,
        'min': min,
        'max': max,
        'sum': sum,
        'round': round,
        'isinstance': isinstance,
        'float': float,
        'int': int,
        'str': str,
        'list': list,
        'dict': dict,
        'set': set,
        'tuple': tuple,
        'range': range,
        'enumerate': enumerate,
        'zip': zip,
        'sorted': sorted,
    }

    # Merge context into globals to avoid scoping issues with generator expressions
    # This ensures all variables are accessible in nested scopes
    execution_globals = {**allowed_globals}
    execution_globals.update(context)

    # Execute the code using only the global namespace (no separate locals)
    # This avoids Python's scoping issues with generator expressions in exec()
    exec(code, execution_globals)

    # Return the 'value' from globals if it was modified
    return execution_globals.get('value')


def create_validation_model_from_rules(acquisition_name: str, rules: List[Dict[str, Any]]) -> BaseValidationModel:
    """
    Dynamically create a BaseValidationModel subclass from JSON rules.
    
    This function generates a validation model class at runtime based on rules
    defined in a JSON schema, allowing for dynamic validation without Python modules.
    
    Args:
        acquisition_name (str): Name of the acquisition for the model.
        rules (List[Dict[str, Any]]): List of rule definitions, each containing:
            - id: Unique identifier for the rule
            - name: Human-readable name
            - fields: List of field names the rule applies to
            - implementation: Python code implementing the validation logic
            - description (optional): Description of what the rule validates
            
    Returns:
        BaseValidationModel: An instance of the dynamically created validation model.
        
    Example:
        >>> rules = [{
        ...     "id": "validate_echo_count",
        ...     "name": "Multi-echo Validation",
        ...     "fields": ["EchoTime"],
        ...     "implementation": "if len(value['EchoTime']) < 3: raise ValidationError('Need 3+ echoes')"
        ... }]
        >>> model = create_validation_model_from_rules("QSM", rules)
    """
    # Create dynamic class name
    class_name = f"Dynamic{acquisition_name}Model"
    
    # Dictionary to hold class attributes (methods)
    class_attrs = {}
    
    # Create validator methods from rules
    for rule in rules:
        rule_id = rule['id']
        rule_name = rule.get('name', rule_id)
        rule_fields = rule['fields']
        rule_message = rule.get('description', '')
        rule_impl = rule['implementation']
        
        # Create the validator method
        def make_validator(impl_code, name, message):
            """Closure to capture rule-specific variables."""
            def validator_method(cls, value):
                """Dynamically generated validator method."""
                # Create a context for code execution
                context = {'value': value}
                
                # Execute the rule implementation
                try:
                    result = safe_exec_rule(impl_code, context)
                    return result if result is not None else value
                except ValidationError:
                    # Re-raise validation errors as-is
                    raise
                except ValidationWarning:
                    # Re-raise validation warnings as-is
                    raise
                except Exception as e:
                    # Wrap other exceptions as validation errors
                    raise ValidationError(f"Rule '{name}' failed: {str(e)}")
            
            # Add metadata for the validator decorator system
            validator_method._is_field_validator = True
            validator_method._field_names = rule_fields
            validator_method._rule_name = name
            validator_method._rule_message = message
            
            return validator_method
        
        # Add the validator method to the class attributes
        class_attrs[rule_id] = make_validator(rule_impl, rule_name, rule_message)
    
    # Create and return an instance of the dynamic class
    DynamicModel = type(class_name, (BaseValidationModel,), class_attrs)
    return DynamicModel()


def create_validation_models_from_rules(validation_rules: Dict[str, List[Dict[str, Any]]]) -> Dict[str, BaseValidationModel]:
    """
    Create multiple validation models from a dictionary of rules.
    
    Args:
        validation_rules (Dict[str, List[Dict[str, Any]]]): Dictionary mapping
            acquisition names to their validation rules.
            
    Returns:
        Dict[str, BaseValidationModel]: Dictionary mapping acquisition names to
            their dynamically created validation models.
            
    Example:
        >>> rules = {
        ...     "QSM": [{"id": "rule1", ...}],
        ...     "T1w": [{"id": "rule2", ...}]
        ... }
        >>> models = create_validation_models_from_rules(rules)
    """
    models = {}
    for acq_name, rules in validation_rules.items():
        if rules:  # Only create model if there are rules
            models[acq_name] = create_validation_model_from_rules(acq_name, rules)
    return models


