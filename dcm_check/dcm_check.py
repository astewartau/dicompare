#!/usr/bin/env python

import pydicom
import json
import importlib.util
from pydantic import ValidationError, create_model, BaseModel, Field, confloat
from typing import Literal, List, Optional, Dict, Any, Union, Pattern
from pydicom.multival import MultiValue
from pydicom.uid import UID
from pydicom.valuerep import PersonName, DSfloat, IS
from pydantic_core import PydanticUndefined

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
            return [get_dicom_values(item) for item in element] # TODO TEST THIS
        elif isinstance(element.value, MultiValue):
            return list(element.value)
        elif isinstance(element.value, (UID, PersonName)):
            return str(element.value)
        elif isinstance(element.value, DSfloat):
            return float(element.value)
        elif isinstance(element.value, IS):
            return int(element.value)
        elif isinstance(element.value, (int, float)):
            return element.value
        else:
            return str(element.value[:50])

    for element in ds:
        # skip pixel data
        if element.tag == 0x7fe00010:
            continue
        dicom_dict[element.keyword] = process_element(element)
        
    return dicom_dict

def load_dicom(dicom_file: str) -> Dict[str, Any]:
    """Load a DICOM file and extract the values as a dictionary.

    Args:
        dicom_file (str): Path to the DICOM file to load.

    Returns:
        dicom_values (Dict[str, Any]): A dictionary of DICOM values.
    """
    ds = pydicom.dcmread(dicom_file)
    return get_dicom_values(ds)

def create_reference_model(reference_values: Dict[str, Any], fields_config: List[Union[str, Dict[str, Any]]]) -> BaseModel:
    model_fields = {}

    for field in fields_config:
        field_name = field["field"]
        tolerance = field.get("tolerance")
        pattern = field.get("value") if isinstance(field.get("value"), str) and "*" in field["value"] else None
        ref_value = reference_values.get(field_name, field.get("value"))

        if pattern:
            # Use the `pattern` parameter in Field to directly enforce the regex pattern
            model_fields[field_name] = (
                str,
                Field(
                    default=PydanticUndefined,
                    pattern=pattern.replace("*", ".*")  # Pydantic will apply this regex pattern directly
                ),
            )
        elif tolerance is not None:
            model_fields[field_name] = (
                confloat(ge=ref_value - tolerance, le=ref_value + tolerance),
                Field(default=ref_value),
            )
        else:
            model_fields[field_name] = (
                Literal[ref_value],
                Field(default=PydanticUndefined),
            )

    return create_model("ReferenceModel", **model_fields)


def load_ref_json(json_path: str, scan_type: str) -> BaseModel:
    """Load a JSON configuration file and create a reference model for a specified scan type.

    Args:
        json_path (str): Path to the JSON configuration file.
        scan_type (str): Scan type to load (e.g., "T1").

    Returns:
        reference_model (BaseModel): A Pydantic model based on the JSON configuration.
    """
    with open(json_path, 'r') as f:
        config = json.load(f)

    scan_config = config.get("acquisitions", {}).get(scan_type)
    if not scan_config:
        raise ValueError(f"Scan type '{scan_type}' not found in JSON configuration.")

    ref_file = scan_config.get("ref", None)
    fields_config = scan_config["fields"]

    if ref_file:
        reference_values = load_dicom(ref_file)
    else:
        reference_values = {field["field"]: field["value"] for field in fields_config if "value" in field}

    return create_reference_model(reference_values, fields_config)

def load_ref_dicom(dicom_values: Dict[str, Any], fields: Optional[List[str]] = None) -> BaseModel:
    """Create a reference model based on DICOM values.

    Args:
        dicom_values (Dict[str, Any]): DICOM values to use for the reference model.
        fields (Optional[List[str]]): Specific fields to include in validation (default is all fields).

    Returns:
        reference_model (BaseModel): A Pydantic model based on DICOM values.
    """
    if fields:
        dicom_values = {field: dicom_values[field] for field in fields if field in dicom_values}

    fields_config = [{"field": field} for field in fields] if fields else [{"field": key} for key in dicom_values]
    return create_reference_model(dicom_values, fields_config)

def load_ref_pydantic(module_path: str, scan_type: str) -> BaseModel:
    """Load a Pydantic model from a specified Python file for the given scan type.

    Args:
        module_path (str): Path to the Python file containing the scan models.
        scan_type (str): The scan type to retrieve (e.g., "T1_MPR").

    Returns:
        reference_model (BaseModel): The Pydantic model for the specified scan type.
    """
    # Load the module from the specified file path
    spec = importlib.util.spec_from_file_location("ref_module", module_path)
    ref_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref_module)

    # Retrieve SCAN_MODELS from the loaded module
    scan_models: Dict[str, Any] = getattr(ref_module, "SCAN_MODELS", None)
    if not scan_models:
        raise ValueError(f"No SCAN_MODELS found in the module '{module_path}'.")

    # Retrieve the specific model for the given scan type
    reference_model = scan_models.get(scan_type)
    if not reference_model:
        raise ValueError(f"Scan type '{scan_type}' is not defined in SCAN_MODELS.")

    return reference_model

def get_compliance_summary(reference_model: BaseModel, dicom_values: Dict[str, Any], raise_errors: bool = False) -> List[Dict[str, Any]]:
    """Validate a DICOM file against the reference model.

    Args:
        reference_model (BaseModel): The reference model for validation.
        dicom_values (Dict[str, Any]): The DICOM values to validate.

    Returns:
        results (List[Dict[str, Any]]): Compliance results, including expected and actual values and pass/fail status.
    """
    compliance_summary = []

    try:
        model_instance = reference_model(**dicom_values)
    except ValidationError as e:
        if raise_errors:
            raise e
        for error in e.errors():
            
            # Check if the error has a specific location
            param = error['loc'][0] if error['loc'] else str(error['ctx'].keys()) if 'ctx' in error else "Model-Level Error"
            
            expected = (error['ctx'].get('expected') if 'ctx' in error else None) or error['msg']
            actual = dicom_values.get(param, "N/A") if param != "Model-Level Error" else "N/A"
            
            compliance_summary.append({
                "Parameter": param,
                "Expected": expected,
                "Actual": actual,
                "Pass": False
            })

    return compliance_summary

def is_compliant(reference_model: BaseModel, dicom_values: Dict[str, Any]) -> bool:
    """Validate a DICOM file against the reference model.

    Args:
        reference_model (BaseModel): The reference model for validation.
        dicom_values (Dict[str, Any]): The DICOM values to validate.

    Returns:
        is_compliant (bool): True if the DICOM values are compliant with the reference model.
    """
    is_compliant = True

    try:
        model_instance = reference_model(**dicom_values)
    except ValidationError as e:
        is_compliant = False

    return is_compliant
