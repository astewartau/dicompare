import os
import pydicom
import json
import pandas as pd

from typing import List, Optional, Dict, Any, Union
from pydicom.multival import MultiValue
from pydicom.uid import UID
from pydicom.valuerep import PersonName, DSfloat, IS
from io import BytesIO

from .utils import clean_string

def normalize_numeric_values(data):
    """
    Recursively convert all numeric values in a data structure to floats.
    """
    if isinstance(data, dict):
        return {k: normalize_numeric_values(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_numeric_values(v) for v in data]
    elif isinstance(data, (int, float)):  # Normalize ints and floats to float
        return float(data)
    return data  # Return other types unchanged

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

def convert_jsproxy(obj):
    if hasattr(obj, "to_py"):  # Check if it's a JsProxy
        return convert_jsproxy(obj.to_py())  # Recursively convert nested JsProxy
    elif isinstance(obj, dict):
        return {k: convert_jsproxy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_jsproxy(v) for v in obj]
    else:
        return obj  # Return as is if it's already a native Python type

def read_dicom_session(
    reference_fields: List[str],
    session_dir: Optional[str] = None,
    dicom_bytes: Optional[Union[Dict[str, bytes], Any]] = None,
    acquisition_fields: List[str] = ["ProtocolName"]
) -> dict:
    """
    Read all files in a DICOM session directory or a dictionary of DICOM files and produce a dictionary resembling the JSON structure.
    """
    session_data = []

    if dicom_bytes is not None:
        dicom_bytes = convert_jsproxy(dicom_bytes)
        
        for dicom_path, dicom_content in dicom_bytes.items():
            dicom_values = load_dicom(dicom_content)
            dicom_entry = {
                str(field): tuple(dicom_values[field]) if isinstance(dicom_values.get(field), list)
                else dicom_values.get(field, "N/A")
                for field in acquisition_fields + reference_fields
            }
            dicom_entry["DICOM_Path"] = str(dicom_path)
            dicom_entry["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))
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

    if not session_data:
        raise ValueError("No DICOM data found to process.")

    session_df = pd.DataFrame(session_data)

    # Sort data for consistency
    if "InstanceNumber" in session_df.columns:
        session_df.sort_values("InstanceNumber", inplace=True)
    else:
        session_df.sort_values("DICOM_Path", inplace=True)

    # Ensure all fields used for grouping are hashable
    for field in acquisition_fields + reference_fields:
        if field in session_df.columns:
            session_df[field] = session_df[field].apply(
                lambda x: tuple(x) if isinstance(x, list) else x
            )

    # Group data by acquisition fields
    grouped = session_df.groupby(acquisition_fields)

    acquisitions = {}

    for acq_key, group in grouped:
        acq_name = "acq-" + clean_string("-".join(
            f"{group[field].iloc[0]}" for field in acquisition_fields if field in group
        ))
        acq_entry = {"fields": [], "series": []}

        for field in acquisition_fields:
            unique_values = group[field].unique()
            if len(unique_values) == 1:
                acq_entry["fields"].append({"field": field, "value": unique_values[0]})

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

    # Normalize all numeric values to floats
    reference_data = normalize_numeric_values(reference_data)

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
