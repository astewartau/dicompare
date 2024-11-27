from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, create_model, confloat, Literal, List, field_validator
from pydantic_core import PydanticUndefined
import importlib.util

def load_ref_dict(session: dict) -> dict:
    """
    Update the session dictionary with Pydantic models for each acquisition and series.

    Args:
        session (dict): The session dictionary containing acquisitions and series.

    Returns:
        dict: The updated session dictionary with models added.
    """

    def build_model(acquisition: dict, series: Optional[dict] = None) -> BaseModel:
        """
        Build a reference model for the given acquisition or series, incorporating patterns, tolerances, and 'contains'.

        Args:
            acquisition (dict): The acquisition dictionary containing fields and series.
            series (Optional[dict]): The series dictionary containing fields, if applicable.

        Returns:
            BaseModel: A dynamically generated Pydantic model.
        """
        reference_values = {}
        fields_config = []

        # Collect acquisition-level fields
        if "fields" in acquisition:
            for field in acquisition["fields"]:
                field_entry = {"field": field["field"]}
                if "value" in field:
                    field_entry["value"] = field["value"]
                    reference_values[field["field"]] = field["value"]
                if "tolerance" in field:
                    field_entry["tolerance"] = field["tolerance"]
                if "contains" in field:
                    field_entry["contains"] = field["contains"]
                fields_config.append(field_entry)

        # Collect series-level fields if provided
        if series and "fields" in series:
            for field in series["fields"]:
                field_entry = {"field": field["field"]}
                if "value" in field:
                    field_entry["value"] = field["value"]
                    reference_values[field["field"]] = field["value"]
                if "tolerance" in field:
                    field_entry["tolerance"] = field["tolerance"]
                if "contains" in field:
                    field_entry["contains"] = field["contains"]
                fields_config.append(field_entry)

        # Create and return the Pydantic model
        return create_reference_model(reference_values, fields_config)

    # Iterate through each acquisition and series in the session
    for acquisition_name, acquisition_data in session.get("acquisitions", {}).items():
        # If there are series within the acquisition, build series-level models
        for series in acquisition_data.get("series", []):
            series["model"] = build_model(acquisition_data, series)

    return session

def create_reference_model(reference_values: Dict[str, Any], fields_config: List[Union[str, Dict[str, Any]]]) -> BaseModel:
    model_fields = {}
    validators = {}

    # Define validation functions dynamically
    def contains_check_factory(field_name, contains_value):
        @field_validator(field_name)
        def contains_check(cls, v):
            if not isinstance(v, list) or contains_value not in v:
                raise ValueError(f"{field_name} must contain '{contains_value}'")
            return v
        return contains_check

    def normalize_value(value):
        """Normalize lists and tuples to lists."""
        if isinstance(value, tuple):
            return list(value)
        return value

    for field in fields_config:
        field_name = field["field"]
        tolerance = field.get("tolerance")
        pattern = field.get("value") if isinstance(field.get("value"), str) and "*" in field["value"] else None
        contains = field.get("contains")
        ref_value = normalize_value(reference_values.get(field_name, field.get("value")))

        if pattern:
            # Pattern matching
            model_fields[field_name] = (
                str,
                Field(default=PydanticUndefined, pattern=pattern.replace("*", ".*"))
            )
        elif tolerance is not None:
            # Numeric tolerance
            model_fields[field_name] = (
                confloat(ge=ref_value - tolerance, le=ref_value + tolerance),
                Field(default=ref_value)
            )
        elif contains:
            # Add a field expecting a list and register a custom validator for "contains"
            model_fields[field_name] = (List[str], Field(default=PydanticUndefined))
            validators[f"{field_name}_contains"] = contains_check_factory(field_name, contains)
        elif isinstance(ref_value, list):
            # Exact match for lists
            model_fields[field_name] = (
                List[type(ref_value[0])] if ref_value else List[Any],
                Field(default=ref_value)
            )
        else:
            # Exact match for scalar values
            model_fields[field_name] = (
                Literal[ref_value],
                Field(default=PydanticUndefined)
            )

    # Create model with dynamically added validators
    return create_model("ReferenceModel", **model_fields, __validators__=validators)

def load_ref_pydantic(module_path: str, acquisition: str) -> BaseModel:
    """Load a Pydantic model from a specified Python file for the given acquisition.

    Args:
        module_path (str): Path to the Python file containing the acquisition models.
        acquisition (str): The acquisition to retrieve (e.g., "T1_MPR").

    Returns:
        reference_model (BaseModel): The Pydantic model for the specified acquisition type.
    """
    # Load the module from the specified file path
    spec = importlib.util.spec_from_file_location("ref_module", module_path)
    ref_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref_module)

    # Retrieve ACQUISITION_MODELS from the loaded module
    acquisition_models: Dict[str, Any] = getattr(ref_module, "ACQUISITION_MODELS", None)
    if not acquisition_models:
        raise ValueError(f"No ACQUISITION_MODELS found in the module '{module_path}'.")

    # Retrieve the specific model for the given acquisition
    reference_model = acquisition_models.get(acquisition)
    if not reference_model:
        raise ValueError(f"Acquisition '{acquisition}' is not defined in ACQUISITION_MODELS.")

    return reference_model

