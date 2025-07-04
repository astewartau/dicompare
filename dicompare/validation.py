"""
This module provides utilities and base classes for validation models and rules 
used in DICOM compliance checks.

"""

from typing import Callable, List, Dict, Any, Tuple
import pandas as pd
from itertools import chain
from .utils import make_hashable
    
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
    ) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validate the input DataFrame against the registered rules.

        Notes:
            - Validations are performed for each unique acquisition in the DataFrame.
            - Field-level validations check unique combinations of specified fields.
            - Model-level validations apply to the entire dataset.

        Args:
            data (pd.DataFrame): The input DataFrame containing DICOM session data.

        Returns:
            Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
                - Overall success (True if all validations passed).
                - List of failed tests with details:
                    - acquisition: The acquisition being validated.
                    - field: The field(s) involved in the validation.
                    - rule_name: The validation rule description.
                    - value: The actual value being validated.
                    - message: The error message (if validation failed).
                    - passed: False (indicating failure).
                - List of passed tests with details:
                    - acquisition: The acquisition being validated.
                    - field: The field(s) involved in the validation.
                    - rule_name: The validation rule description.
                    - value: The actual value being validated.
                    - message: None (indicating success).
                    - passed: True (indicating success).
        """
        errors: List[Dict[str, Any]] = []
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
                            "value": grouped.to_dict(orient="list"),
                            "message": "OK",
                            "passed": True,
                        })
                    except ValidationError as e:
                        errors.append({
                            "acquisition": acquisition,
                            "field": ", ".join(field_names),
                            "rule_name": validator_func._rule_name,
                            "expected": validator_func._rule_message,
                            "value": grouped.to_dict(orient="list"),
                            "message": str(e),
                            "passed": False,
                        })

        overall_success = len(errors) == 0
        return overall_success, errors, passes


