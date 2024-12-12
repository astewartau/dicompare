"""
This module provides utilities and base classes for validation models and rules 
used in DICOM compliance checks.

"""

from typing import Callable, List, Dict, Any, Tuple
import pandas as pd

def make_hashable(value):
    """
    Convert a value into a hashable format for use in dictionaries or sets.

    Notes:
        - Lists are converted to tuples.
        - Dictionaries are converted to sorted tuples of key-value pairs.
        - Sets are converted to sorted tuples of elements.
        - Nested structures are processed recursively.
        - Primitive hashable types (e.g., int, str) are returned unchanged.

    Args:
        value (Any): The value to make hashable.

    Returns:
        Any: A hashable version of the input value.
    """

    if isinstance(value, dict):
        return tuple((k, make_hashable(v)) for k, v in value.items())
    elif isinstance(value, list):
        return tuple(make_hashable(v) for v in value)
    elif isinstance(value, set):
        return tuple(sorted(make_hashable(v) for v in value))  # Sort sets for consistent hash
    elif isinstance(value, tuple):
        return tuple(make_hashable(v) for v in value)
    else:
        return value  # Assume the value is already hashable
    
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

def validator(field_names: List[str], rule_message: str = "Validation rule applied"):
    """
    Decorator for defining field-level validation rules.

    Notes:
        - Decorated functions are automatically registered in `BaseValidationModel`.
        - The rule will be applied to unique combinations of the specified fields.

    Args:
        field_names (List[str]): The list of field names the rule applies to.
        rule_message (str): A description of the validation rule.

    Returns:
        Callable: The decorated function.
    """

    def decorator(func: Callable):
        func._is_field_validator = True
        func._field_names = field_names
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
        cls._field_validators = {}
        cls._model_validators = []

        for attr_name, attr_value in cls.__dict__.items():
            if hasattr(attr_value, "_is_field_validator"):
                # Convert field_names to a tuple to make it hashable
                field_names = tuple(attr_value._field_names)
                cls._field_validators.setdefault(field_names, []).append(attr_value)
            elif hasattr(attr_value, "_is_model_validator"):
                cls._model_validators.append(attr_value)

    def validate(self, data: pd.DataFrame) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
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
                    - rule: The validation rule description.
                    - value: The actual value being validated.
                    - message: The error message (if validation failed).
                    - passed: False (indicating failure).
                - List of passed tests with details:
                    - acquisition: The acquisition being validated.
                    - field: The field(s) involved in the validation.
                    - rule: The validation rule description.
                    - value: The actual value being validated.
                    - message: None (indicating success).
                    - passed: True (indicating success).
        """
        errors = []
        passes = []

        # Field-level validation
        for acquisition in data["Acquisition"].unique():
            acquisition_data = data[data["Acquisition"] == acquisition]
            for field_names, validator_list in self._field_validators.items():
                # Check for missing fields
                missing_fields = [field for field in field_names if field not in acquisition_data.columns]
                if missing_fields:
                    errors.append({
                        "acquisition": acquisition,
                        "field": ", ".join(field_names),
                        "rule": validator_list[0]._rule_message,
                        "value": None,
                        "message": f"Missing fields: {', '.join(missing_fields)}.",
                        "passed": False,
                    })
                    continue

                # Filter the data to include only the requested fields
                filtered_data = acquisition_data[list(field_names)].copy()

                # Get unique combinations of requested fields with counts
                unique_combinations = (
                    filtered_data.groupby(list(field_names), dropna=False)
                    .size()
                    .reset_index(name="Count")
                )

                # Iterate over all validators for the field group
                for validator_func in validator_list:
                    try:
                        # Pass the unique combinations with counts to the validator
                        validator_func(self, unique_combinations)
                        passes.append({
                            "acquisition": acquisition,
                            "field": ", ".join(field_names),
                            "rule": validator_func._rule_message,
                            "value": unique_combinations.to_dict(orient="list"),
                            "message": None,
                            "passed": True,
                        })
                    except ValidationError as e:
                        errors.append({
                            "acquisition": acquisition,
                            "field": ", ".join(field_names),
                            "rule": validator_func._rule_message,
                            "value": unique_combinations.to_dict(orient="list"),
                            "message": e.message,
                            "passed": False,
                        })

        overall_success = len(errors) == 0
        return overall_success, errors, passes


