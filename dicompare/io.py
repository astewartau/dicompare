import os
import pydicom
import json
import pandas as pd
import importlib.util

from typing import List, Optional, Dict, Any, Union, Tuple
from pydicom.multival import MultiValue
from pydicom.uid import UID
from pydicom.valuerep import PersonName, DSfloat, IS
from io import BytesIO

from .utils import clean_string
from .validation import BaseValidationModel

def normalize_numeric_values(data):
    """
    Recursively convert all numeric values in a data structure to floats.
    """
    if isinstance(data, dict):
        return {k: normalize_numeric_values(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_numeric_values(v) for v in data]
    elif isinstance(data, (int, float)):
        return float(data)
    return data

def convert_jsproxy(obj):
    if hasattr(obj, "to_py"):
        return convert_jsproxy(obj.to_py())
    elif isinstance(obj, dict):
        return {k: convert_jsproxy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_jsproxy(v) for v in obj]
    else:
        return obj
    
def make_hashable(value):
    """
    Convert a value into a hashable format.
    Handles lists, dictionaries, and other non-hashable types.
    """
    if isinstance(value, list):
        return tuple(value)
    elif isinstance(value, dict):
        return tuple((k, make_hashable(v)) for k, v in value.items())
    elif isinstance(value, set):
        return tuple(sorted(make_hashable(v) for v in value))
    return value

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
            try:
                return [int(float(item)) if int(float(item)) == float(item) else float(item) for item in element.value]
            except ValueError:
                return [item for item in element.value]
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

def load_dicom_session(
    session_dir: Optional[str] = None,
    dicom_bytes: Optional[Union[Dict[str, bytes], Any]] = None,
    acquisition_fields: Optional[List[str]] = ["ProtocolName"],
) -> pd.DataFrame:
    """
    Read all files in a DICOM session directory or a dictionary of DICOM files 
    and return a single DataFrame containing all DICOM metadata.

    Args:
        session_dir (Optional[str]): Path to the directory containing DICOM files.
        dicom_bytes (Optional[Union[Dict[str, bytes], Any]]): A dictionary of file paths and their respective byte content.
        acquisition_fields (Optional[List[str]]): Fields to uniquely identify each acquisition.

    Returns:
        pd.DataFrame: DataFrame containing all extracted DICOM metadata.
    """
    session_data = []

    if dicom_bytes is not None:
        dicom_bytes = convert_jsproxy(dicom_bytes)
        for dicom_path, dicom_content in dicom_bytes.items():
            dicom_values = load_dicom(dicom_content)
            dicom_values["DICOM_Path"] = str(dicom_path)
            dicom_values["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))
            session_data.append(dicom_values)
    elif session_dir is not None:
        for root, _, files in os.walk(session_dir):
            for file in files:
                if file.endswith((".dcm", ".IMA")):
                    dicom_path = os.path.join(root, file)
                    dicom_values = load_dicom(dicom_path)
                    dicom_values["DICOM_Path"] = dicom_path
                    dicom_values["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))
                    session_data.append(dicom_values)
    else:
        raise ValueError("Either session_dir or dicom_bytes must be provided.")

    if not session_data:
        raise ValueError("No DICOM data found to process.")

    # Create a DataFrame
    session_df = pd.DataFrame(session_data)

    # Ensure all values are hashable
    for col in session_df.columns:
        session_df[col] = session_df[col].apply(make_hashable)

    # Sort data by InstanceNumber if present
    if "InstanceNumber" in session_df.columns:
        session_df.sort_values("InstanceNumber", inplace=True)
    elif "DICOM_Path" in session_df.columns:
        session_df.sort_values("DICOM_Path", inplace=True)

    # Group by unique combinations of acquisition fields
    if acquisition_fields:
        session_df = session_df.groupby(acquisition_fields).apply(lambda x: x.reset_index(drop=True))

    # Convert acquisition fields to strings and handle missing values
    def clean_acquisition_values(row):
        return "-".join(str(val) if pd.notnull(val) else "NA" for val in row)

    # Add 'Acquisition' field
    session_df["Acquisition"] = (
        "acq-"
        + session_df[acquisition_fields]
        .apply(clean_acquisition_values, axis=1)
        .apply(clean_string)
    )

    return session_df



def load_json_session(json_ref: str) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """
    Load a JSON reference file and extract acquisition and series fields.

    Args:
        json_ref (str): Path to the JSON file.

    Returns:
        Tuple: (acquisition_fields, series_fields, acquisitions_dict)
    """
    def process_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process fields to standardize them for comparison.
        """
        processed_fields = []
        for field in fields:
            processed = {"field": field["field"]}
            if "value" in field:
                processed["value"] = tuple(field["value"]) if isinstance(field["value"], list) else field["value"]
            if "tolerance" in field:
                processed["tolerance"] = field["tolerance"]
            if "contains" in field:
                processed["contains"] = field["contains"]
            processed_fields.append(processed)
        return processed_fields

    with open(json_ref, 'r') as f:
        reference_data = json.load(f)

    reference_data = normalize_numeric_values(reference_data)

    acquisitions = {}
    acquisition_fields = set()
    series_fields = set()

    for acq_name, acquisition in reference_data.get("acquisitions", {}).items():
        acq_entry = {
            "fields": process_fields(acquisition.get("fields", [])),
            "series": []
        }
        acquisition_fields.update(field["field"] for field in acquisition.get("fields", []))

        for series in acquisition.get("series", []):
            series_entry = {
                "name": series["name"],
                "fields": process_fields(series.get("fields", []))
            }
            acq_entry["series"].append(series_entry)
            series_fields.update(field["field"] for field in series.get("fields", []))

        acquisitions[acq_name] = acq_entry

    return sorted(acquisition_fields), sorted(series_fields), {"acquisitions": acquisitions}

def load_python_session(module_path: str) -> Tuple[List[str], List[str], Dict[str, BaseValidationModel]]:
    """
    Load a Python module containing Pydantic models for validation.

    Args:
        module_path (str): Path to the Python module.

    Returns:
        Tuple[List[str], List[str], Dict[str, BaseValidationModel]]:
        - The `ACQUISITION_MODELS` dictionary from the module.
        - Combined acquisition fields.
        - Combined reference fields.
    """
    spec = importlib.util.spec_from_file_location("validation_module", module_path)
    validation_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validation_module)

    if not hasattr(validation_module, "ACQUISITION_MODELS"):
        raise ValueError(f"The module {module_path} does not define 'ACQUISITION_MODELS'.")

    acquisition_models = getattr(validation_module, "ACQUISITION_MODELS")
    if not isinstance(acquisition_models, dict):
        raise ValueError("'ACQUISITION_MODELS' must be a dictionary.")

    return acquisition_models


