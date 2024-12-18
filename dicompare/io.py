"""
This module contains functions for loading and processing DICOM data, JSON references, and Python validation modules.

"""

import os
import pydicom
import json
import pandas as pd
import importlib.util

from pydicom.multival import MultiValue
from pydicom.uid import UID
from pydicom.valuerep import PersonName, DSfloat, IS
from typing import List, Optional, Dict, Any, Union, Tuple
from io import BytesIO

from .utils import clean_string, convert_jsproxy, make_hashable, normalize_numeric_values
from .validation import BaseValidationModel

def get_dicom_values(ds: pydicom.dataset.FileDataset) -> Dict[str, Any]:
    """
    Convert a DICOM dataset to a dictionary, handling sequences and DICOM-specific data types.
    
    Notes:
        - Sequences are recursively processed.
        - Common DICOM data types (e.g., UID, PersonName) are converted to strings.
        - Numeric values are normalized.

    Args:
        ds (pydicom.dataset.FileDataset): The DICOM dataset to process.

    Returns:
        Dict[str, Any]: A dictionary of extracted DICOM metadata, excluding pixel data.
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
    """
    Load a DICOM file and extract its metadata as a dictionary.

    Args:
        dicom_file (Union[str, bytes]): Path to the DICOM file or file content in bytes.

    Returns:
        Dict[str, Any]: A dictionary of DICOM metadata, with normalized and truncated values.

    Raises:
        FileNotFoundError: If the specified DICOM file path does not exist.
        pydicom.errors.InvalidDicomError: If the file is not a valid DICOM file.
    """

    if isinstance(dicom_file, (bytes, memoryview)):
        ds = pydicom.dcmread(BytesIO(dicom_file), stop_before_pixels=False, force=True, defer_size=len(dicom_file))
    else:
        ds = pydicom.dcmread(dicom_file, stop_before_pixels=True)
    
    return get_dicom_values(ds)

def load_dicom_session(
    session_dir: Optional[str] = None,
    dicom_bytes: Optional[Union[Dict[str, bytes], Any]] = None,
    acquisition_fields: Optional[List[str]] = ["ProtocolName"],
) -> pd.DataFrame:
    """
    Load and process all DICOM files in a session directory or a dictionary of byte content.

    Notes:
        - The function can process files directly from a directory or byte content.
        - Metadata is grouped and sorted based on the acquisition fields and `InstanceNumber`.
        - Missing fields are normalized with default values.

    Args:
        session_dir (Optional[str]): Path to a directory containing DICOM files.
        dicom_bytes (Optional[Union[Dict[str, bytes], Any]]): Dictionary of file paths and their byte content.
        acquisition_fields (Optional[List[str]]): List of fields used to uniquely identify each acquisition.

    Returns:
        pd.DataFrame: A DataFrame containing metadata for all DICOM files in the session.

    Raises:
        ValueError: If neither `session_dir` nor `dicom_bytes` is provided, or if no DICOM data is found.
    """
    session_data = []

    if dicom_bytes is not None:
        dicom_bytes = convert_jsproxy(dicom_bytes)
        for dicom_path, dicom_byte_content in dicom_bytes.items():
            dicom_values = load_dicom(dicom_byte_content)
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
    Load a JSON reference file and extract fields for acquisitions and series.

    Notes:
        - Fields are normalized for easier comparison.
        - Nested fields in acquisitions and series are processed recursively.

    Args:
        json_ref (str): Path to the JSON reference file.

    Returns:
        Tuple[List[str], List[str], Dict[str, Any]]:
            - List of acquisition-level fields.
            - List of series-level fields.
            - Processed reference data as a dictionary.

    Raises:
        FileNotFoundError: If the specified JSON file path does not exist.
        JSONDecodeError: If the file is not a valid JSON file.
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
    reference_fields = set()

    for acq_name, acquisition in reference_data.get("acquisitions", {}).items():
        acq_entry = {
            "fields": process_fields(acquisition.get("fields", [])),
            "series": []
        }
        reference_fields.update(field["field"] for field in acquisition.get("fields", []))

        for series in acquisition.get("series", []):
            series_entry = {
                "name": series["name"],
                "fields": process_fields(series.get("fields", []))
            }
            acq_entry["series"].append(series_entry)
            reference_fields.update(field["field"] for field in series.get("fields", []))

        acquisitions[acq_name] = acq_entry

    return sorted(reference_fields), {"acquisitions": acquisitions}

def load_python_session(module_path: str) -> Tuple[List[str], List[str], Dict[str, BaseValidationModel]]:
    """
    Load validation models from a Python module for DICOM compliance checks.

    Notes:
        - The module must define `ACQUISITION_MODELS` as a dictionary mapping acquisition names to validation models.
        - Validation models must inherit from `BaseValidationModel`.

    Args:
        module_path (str): Path to the Python module containing validation models.

    Returns:
        Tuple[List[str], List[str], Dict[str, BaseValidationModel]]:
            - Dictionary of acquisition validation models from the module.
            - List of combined acquisition fields.
            - List of combined series fields.

    Raises:
        FileNotFoundError: If the specified Python module path does not exist.
        ValueError: If the module does not define `ACQUISITION_MODELS` or its format is incorrect.
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


