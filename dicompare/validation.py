from typing import Callable, List, Dict, Any, Tuple
import pandas as pd

def make_hashable(value):
    """
    Convert a value into a hashable format.
    Handles lists, dictionaries, and other non-hashable types.
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
    Filter a dataframe to unique combinations of specified fields.
    Fields not in the list are filled with `None` if they vary.
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
    def __init__(self, message: str=None):
        self.message = message
        super().__init__(message)


def validator(field_names: List[str], rule_message: str = "Validation rule applied"):
    """Decorator for field-level validators with specified field filtering."""
    def decorator(func: Callable):
        func._is_field_validator = True
        func._field_names = field_names
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
    _field_validators: Dict[Tuple[str, ...], List[Callable]]
    _model_validators: List[Callable]

    def __init_subclass__(cls, **kwargs):
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
        Validate the input dataframe and return results.

        Args:
            data (pd.DataFrame): The input dataframe.

        Returns:
            Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
                - Overall success (True if all validations passed).
                - List of failed tests with details (field, value, error message).
                - List of passed tests with details (field, value, rule message).
        """
        errors = []
        passes = []

        # Field-level validation
        for acquisition in data["Acquisition"].unique():
            acquisition_data = data[data["Acquisition"] == acquisition]
            for field_names, validator_list in self._field_validators.items():
                # Iterate over all validators for the field group
                for validator_func in validator_list:
                    filtered_data = get_unique_combinations(acquisition_data, list(field_names))
                    try:
                        validator_func(self, filtered_data)
                        passes.append({
                            "acquisition": acquisition,
                            "field": ", ".join(field_names),
                            "rule": validator_func._rule_message,
                            "value": filtered_data[list(field_names)].to_dict(orient='list'),  # Corrected column access
                            "message": None,
                            "passed": True
                        })
                    except ValidationError as e:
                        errors.append({
                            "acquisition": acquisition,
                            "field": ", ".join(field_names),
                            "rule": validator_func._rule_message,
                            "value": filtered_data[list(field_names)].to_dict(orient='list'),  # Corrected column access
                            "message": e.message,
                            "passed": False
                        })

        overall_success = len(errors) == 0
        return overall_success, errors, passes



