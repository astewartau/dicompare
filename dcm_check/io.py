import os
import pydicom
import json
import importlib.util
import pandas as pd

from pydantic import create_model, BaseModel, Field, confloat, field_validator
from typing import Literal, List, Optional, Dict, Any, Union
from pydicom.multival import MultiValue
from pydicom.uid import UID
from pydicom.valuerep import PersonName, DSfloat, IS
from pydantic_core import PydanticUndefined
from io import BytesIO

from .utils import clean_string

def get_dicom_values(ds: pydicom.dataset.FileDataset) -> Dict[str, Any]:
    """Convert a DICOM dataset to a dictionary, handling sequences and DICOM-specific data types.

    Args:
        ds (pydicom.dataset.FileDataset): The DICOM dataset to process.

    Returns:
        dicom_dict (Dict[str, Any]): A dictionary of DICOM values.
    """
    dicom_dict = {}

    def process_element(element):
        if element.VR == 'SQ':
            return [get_dicom_values(item) for item in element]
        elif isinstance(element.value, MultiValue):
            return list(element.value)
        elif isinstance(element.value, (UID, PersonName)):
            return str(element.value)
        elif isinstance(element.value, (DSfloat, float)):
            return float(element.value)
        elif isinstance(element.value, (IS, int)):
            return int(element.value)
        else:
            return str(element.value)[:50]

    for element in ds:
        if element.tag == 0x7fe00010:  # skip pixel data
            continue
        dicom_dict[element.keyword] = process_element(element)

    return dicom_dict

def load_dicom(dicom_file: Union[str, bytes]) -> Dict[str, Any]:
    """Load a DICOM file from a path or bytes and extract values as a dictionary.

    Args:
        dicom_file (Union[str, bytes]): Path to the DICOM file or file content as bytes.

    Returns:
        dicom_values (Dict[str, Any]): A dictionary of DICOM values.
    """
    if isinstance(dicom_file, (bytes, memoryview)):
        # Convert dicom_file to BytesIO if it's in bytes or memoryview format
        ds = pydicom.dcmread(BytesIO(dicom_file), stop_before_pixels=True)
    else:
        ds = pydicom.dcmread(dicom_file, stop_before_pixels=True)
    
    return get_dicom_values(ds)

def read_dicom_session(
    reference_fields: List[str],
    session_dir: Optional[str] = None,
    dicom_bytes: Optional[Dict[str, bytes]] = None,
    acquisition_fields: List[str] = ["ProtocolName"]
) -> dict:
    """
    Read all files in a DICOM session directory or a dictionary of DICOM files and produce a dictionary resembling the JSON structure.

    Args:
        reference_fields (List[str]): Fields to include in the output.
        session_dir (Optional[str]): Path to the directory containing DICOM files.
        dicom_bytes (Optional[Dict[str, bytes]]): Dictionary of DICOM files as byte content.
        acquisition_fields (List[str]): Fields to uniquely identify each acquisition.

    Returns:
        dict: A dictionary resembling the JSON structure with acquisitions and series information.
    """
    session_data = []

    # Collect session data from either dicom_bytes or session_dir
    if dicom_bytes is not None:
        for dicom_path, dicom_content in dicom_bytes.items():
            dicom_values = load_dicom(dicom_content)
            dicom_entry = {
                k: v for k, v in dicom_values.items() if k in acquisition_fields + reference_fields
            }
            dicom_entry["DICOM_Path"] = dicom_path
            session_data.append(dicom_entry)
    elif session_dir is not None:
        for root, _, files in os.walk(session_dir):
            for file in files:
                if file.endswith((".dcm", ".IMA")):
                    dicom_path = os.path.join(root, file)
                    dicom_values = load_dicom(dicom_path)
                    dicom_entry = {
                        k: v for k, v in dicom_values.items() if k in acquisition_fields + reference_fields
                    }
                    dicom_entry["DICOM_Path"] = dicom_path
                    session_data.append(dicom_entry)
    else:
        raise ValueError("Either session_dir or dicom_bytes must be provided.")

    acquisitions = {}

    # Create a DataFrame from the session data for easier processing
    session_df = pd.DataFrame(session_data)

    # Ensure all fields used for grouping are hashable
    for field in acquisition_fields + reference_fields:
        if field in session_df.columns:
            session_df[field] = session_df[field].apply(
                lambda x: tuple(x) if isinstance(x, list) else x
            )

    # Group data by acquisition fields
    grouped = session_df.groupby(acquisition_fields)

    for acq_key, group in grouped:
        # Create acq_name using only acquisition fields
        acq_name = "acq-" + clean_string("-".join(
            f"{group[field].iloc[0]}" for field in acquisition_fields if field in group
        ))
        acq_entry = {"fields": [], "series": []}

        # Add acquisition-level fields
        for field in acquisition_fields:
            unique_values = group[field].unique()
            if len(unique_values) == 1:
                acq_entry["fields"].append({"field": field, "value": unique_values[0]})

        # Add series-level fields if reference_fields vary within the acquisition
        series_grouped = group.groupby(reference_fields)
        for i, (_, series_group) in enumerate(series_grouped, start=1):
            series_entry = {
                "name": f"Series {i}",
                "fields": []
            }
            for field in reference_fields:
                unique_values = series_group[field].unique()
                if len(unique_values) == 1:
                    series_entry["fields"].append({"field": field, "value": unique_values[0]})
            acq_entry["series"].append(series_entry)

        acquisitions[acq_name] = acq_entry

    return {"acquisitions": acquisitions}

def read_json_session(json_ref: str) -> tuple:
    """
    Read a JSON reference and produce a tuple containing:
    1. A list of field names described at the acquisition level.
    2. A list of field names described at the series level.
    3. A dictionary resembling the JSON structure.

    Args:
        json_ref (str): Path to the JSON file.

    Returns:
        tuple: (acquisition_fields, series_fields, acquisitions_dict)
    """
    def process_fields(fields):
        """
        Helper function to process fields into a structured list.
        """
        processed_fields = []
        for field in fields:
            field_entry = {"field": field["field"]}
            if "value" in field:
                field_entry["value"] = field["value"]
            if "tolerance" in field:
                field_entry["tolerance"] = field["tolerance"]
            if "contains" in field:
                field_entry["contains"] = field["contains"]
            processed_fields.append(field_entry)
        return processed_fields

    with open(json_ref, 'r') as f:
        reference_data = json.load(f)

    acquisitions = {}
    acquisition_fields = set()  # Store unique field names at the acquisition level
    series_fields = set()  # Store unique field names at the series level

    for acq_name, acquisition in reference_data.get("acquisitions", {}).items():
        # Process acquisition-level fields
        acq_entry = {
            "fields": process_fields(acquisition.get("fields", [])),
            "series": []
        }
        acquisition_fields.update(field["field"] for field in acquisition.get("fields", []))

        # Process series-level fields
        for series in acquisition.get("series", []):
            series_entry = {
                "name": series["name"],
                "fields": process_fields(series.get("fields", []))
            }
            acq_entry["series"].append(series_entry)
            series_fields.update(field["field"] for field in series.get("fields", []))

        acquisitions[acq_name] = acq_entry

    # Convert sets to sorted lists for consistency
    return sorted(acquisition_fields), sorted(series_fields), {"acquisitions": acquisitions}

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
