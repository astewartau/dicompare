"""
This module contains functions for loading and processing DICOM data, JSON references, and Python validation modules.

"""

import os
import pydicom
import json
import pandas as pd
import importlib.util
import numpy as np
import nibabel as nib

from pydicom.multival import MultiValue
from pydicom.uid import UID
from pydicom.valuerep import PersonName, DSfloat, IS
from typing import List, Optional, Dict, Any, Union, Tuple
from io import BytesIO
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

from .utils import clean_string, convert_jsproxy, make_hashable, normalize_numeric_values
from .validation import BaseValidationModel

def get_dicom_values(ds: pydicom.dataset.FileDataset, skip_pixel_data: bool = True) -> Dict[str, Any]:
    """
    Convert a DICOM dataset to a dictionary, handling sequences and DICOM-specific data types,
    and include private tags by using a fallback key when keyword is not known.
    
    Notes:
        - Sequences are skipped by returning None if element.VR == 'SQ'.
        - Common DICOM data types (e.g., UID, PersonName) are converted to strings.
        - Numeric values are normalized.
        - Private tags without known keywords are stored under a key like '(0043, 102F)'.

    Args:
        ds (pydicom.dataset.FileDataset): The DICOM dataset to process.
        skip_pixel_data (bool): Whether to skip the pixel data element (default: True).

    Returns:
        Dict[str, Any]: A dictionary of extracted DICOM metadata, excluding pixel data if requested.
    """
    dicom_dict = {}

    def process_element(element):
        if element.VR == 'SQ':
            # Skip sequences
            return None
        elif isinstance(element.value, MultiValue):
            try:
                # Attempt to convert each item to int if possible, else float if possible
                return [int(float(item)) if int(float(item)) == float(item) else float(item) 
                        for item in element.value]
            except ValueError:
                # If conversion fails, return as-is
                return [item for item in element.value]
        elif isinstance(element.value, (UID, PersonName)):
            return str(element.value)
        elif isinstance(element.value, (DSfloat, float)):
            return float(element.value)
        elif isinstance(element.value, (IS, int)):
            return int(element.value)
        elif element.tag == 0x7fe00010:
            # Pixel data (already handled above if skip_pixel_data=True)
            return np.array(element.value)
        else:
            # Fallback: short string representation
            return str(element.value)[:50]

    for element in ds:
        # Skip pixel data if requested
        if element.tag == 0x7fe00010 and skip_pixel_data:
            continue

        # Process the element to get a Python value
        result = process_element(element)
        if result is not None:
            # If keyword is empty or unknown, use the tag in hex notation
            keyword = element.keyword if element.keyword else f"({element.tag.group:04X},{element.tag.element:04X})"
            dicom_dict[keyword] = result

    return dicom_dict

def load_dicom(dicom_file: Union[str, bytes], skip_pixel_data: bool = True) -> Dict[str, Any]:
    """
    Load a DICOM file and extract its metadata as a dictionary.

    Args:
        dicom_file (Union[str, bytes]): Path to the DICOM file or file content in bytes.
        skip_pixel_data (bool): Whether to skip the pixel data element (default: True).

    Returns:
        Dict[str, Any]: A dictionary of DICOM metadata, with normalized and truncated values.

    Raises:
        FileNotFoundError: If the specified DICOM file path does not exist.
        pydicom.errors.InvalidDicomError: If the file is not a valid DICOM file.
    """
    if isinstance(dicom_file, (bytes, memoryview)):
        ds = pydicom.dcmread(BytesIO(dicom_file), stop_before_pixels=skip_pixel_data, force=True, defer_size=len(dicom_file))
    else:
        ds = pydicom.dcmread(dicom_file, stop_before_pixels=skip_pixel_data, force=True)
    
    return get_dicom_values(ds, skip_pixel_data=skip_pixel_data)


def _load_one_dicom_path(path: str, skip_pixel_data: bool) -> Dict[str, Any]:
    """
    Helper for parallel loading of a single DICOM file from a path.
    """
    dicom_values = load_dicom(path, skip_pixel_data=skip_pixel_data)
    dicom_values["DICOM_Path"] = path
    # If you want 'InstanceNumber' for path-based
    dicom_values["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))
    return dicom_values


def _load_one_dicom_bytes(key: str, content: bytes, skip_pixel_data: bool) -> Dict[str, Any]:
    """
    Helper for parallel loading of a single DICOM file from bytes.
    """
    dicom_values = load_dicom(content, skip_pixel_data=skip_pixel_data)
    dicom_values["DICOM_Path"] = key
    # If you want 'InstanceNumber' for bytes-based
    dicom_values["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))
    return dicom_values

def load_nifti_session(
    session_dir: Optional[str] = None,
    acquisition_fields: Optional[List[str]] = ["ProtocolName"],
    show_progress: bool = False,
) -> pd.DataFrame:

    session_data = []

    nifti_files = [os.path.join(root, file) for root, _, files in os.walk(session_dir) for file in files if '.nii' in file]

    if not nifti_files:
        raise ValueError(f"No NIfTI files found in {session_dir}.")
    
    if show_progress:
        nifti_files = tqdm(nifti_files, desc="Loading NIfTIs")

    for nifti_path in nifti_files:
        nifti_data = nib.load(nifti_path)
        nifti_values = {
            "NIfTI_Path": nifti_path,
            "NIfTI_Shape": nifti_data.shape,
            "NIfTI_Affine": nifti_data.affine,
            "NIfTI_Header": nifti_data.header
        }
        session_data.append(nifti_values)

        # extract BIDS tags from filename
        bids_tags = os.path.splitext(os.path.basename(nifti_path))[0].split('_')
        for tag in bids_tags:
            key_val = tag.split('-')
            if len(key_val) == 2:
                key, val = key_val
                nifti_values[key] = val
        
        # extract suffix
        if len(bids_tags) > 1:
            nifti_values["suffix"] = bids_tags[-1]

        # if corresponding json file exists
        json_path = nifti_path.replace('.nii.gz', '.nii').replace('.nii', '.json')
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                json_data = json.load(f)
            nifti_values["JSON_Path"] = json_path
            nifti_values.update(json_data)
    
    session_df = pd.DataFrame(session_data)

    for col in session_df.columns:
        session_df[col] = session_df[col].apply(make_hashable)

    if acquisition_fields:
        session_df = session_df.groupby(acquisition_fields).apply(lambda x: x.reset_index(drop=True))

    return session_df
    

def load_dicom_session(
    session_dir: Optional[str] = None,
    dicom_bytes: Optional[Union[Dict[str, bytes], Any]] = None,
    acquisition_fields: Optional[List[str]] = ["ProtocolName"],
    skip_pixel_data: bool = True,
    show_progress: bool = False,
    parallel_workers: int = 1
) -> pd.DataFrame:
    """
    Load and process all DICOM files in a session directory or a dictionary of byte content.

    Notes:
        - The function can process files directly from a directory or byte content.
        - Metadata is grouped and sorted based on the acquisition fields.
        - Missing fields are normalized with default values.
        - If parallel_workers > 1, files in session_dir are read in parallel to improve speed.

    Args:
        session_dir (Optional[str]): Path to a directory containing DICOM files.
        dicom_bytes (Optional[Union[Dict[str, bytes], Any]]): Dictionary of file paths and their byte content.
        acquisition_fields (Optional[List[str]]): Fields used to uniquely identify each acquisition.
        skip_pixel_data (bool): Whether to skip pixel data elements (default: True).
        show_progress (bool): Whether to show a progress bar (using tqdm).
        parallel_workers (int): Number of threads for parallel reading (default 1 = no parallel).

    Returns:
        pd.DataFrame: A DataFrame containing metadata for all DICOM files in the session.

    Raises:
        ValueError: If neither `session_dir` nor `dicom_bytes` is provided, or if no DICOM data is found.
    """
    session_data = []

    # 1) DICOM bytes branch
    if dicom_bytes is not None:
        dicom_items = list(dicom_bytes.items())
        if not dicom_items:
            raise ValueError("No DICOM data found in dicom_bytes.")

        if parallel_workers > 1:
            with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
                futures = [
                    executor.submit(_load_one_dicom_bytes, key, content, skip_pixel_data)
                    for key, content in dicom_items
                ]
                if show_progress:
                    for fut in tqdm(as_completed(futures), total=len(futures), desc="Loading DICOM bytes in parallel"):
                        session_data.append(fut.result())
                else:
                    for fut in as_completed(futures):
                        session_data.append(fut.result())
        else:
            if show_progress:
                dicom_items = tqdm(dicom_items, desc="Loading DICOM bytes")
            for key, content in dicom_items:
                dicom_values = load_dicom(content, skip_pixel_data=skip_pixel_data)
                dicom_values["DICOM_Path"] = key
                dicom_values["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))
                session_data.append(dicom_values)

    # 2) Session directory branch
    elif session_dir is not None:
        all_files = [os.path.join(root, file) for root, _, files in os.walk(session_dir) for file in files]

        if not all_files:
            raise ValueError(f"No DICOM data found to process.")

        if parallel_workers > 1:
            with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
                futures = [
                    executor.submit(_load_one_dicom_path, fpath, skip_pixel_data)
                    for fpath in all_files
                ]
                if show_progress:
                    for fut in tqdm(as_completed(futures), total=len(futures), desc="Reading DICOMs in parallel"):
                        session_data.append(fut.result())
                else:
                    for fut in as_completed(futures):
                        session_data.append(fut.result())
        else:
            if show_progress:
                all_files = tqdm(all_files, desc="Loading DICOMs")
            for dicom_path in all_files:
                dicom_values = load_dicom(dicom_path, skip_pixel_data=skip_pixel_data)
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

def load_json_session(json_ref: str) -> Tuple[List[str], Dict[str, Any]]:
    """
    Load a JSON reference file and extract fields for acquisitions and series.

    Notes:
        - Fields are normalized for easier comparison.
        - Nested fields in acquisitions and series are processed recursively.

    Args:
        json_ref (str): Path to the JSON reference file.

    Returns:
        Tuple[List[str], Dict[str, Any]]:
            - Sorted list of all reference fields encountered.
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

def load_python_session(module_path: str) -> Dict[str, BaseValidationModel]:
    """
    Load validation models from a Python module for DICOM compliance checks.

    Notes:
        - The module must define `ACQUISITION_MODELS` as a dictionary mapping acquisition names to validation models.
        - Validation models must inherit from `BaseValidationModel`.

    Args:
        module_path (str): Path to the Python module containing validation models.

    Returns:
        Dict[str, BaseValidationModel]: The acquisition validation models from the module.

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

