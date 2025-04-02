"""
This module contains functions for loading and processing DICOM data, JSON references, and Python validation modules.

"""

import os
import pydicom
import json
import asyncio
import pandas as pd
import importlib.util
import nibabel as nib

from pydicom.dataset import FileDataset
from pydicom.multival import MultiValue
from pydicom.uid import UID
from pydicom.valuerep import PersonName, DSfloat, IS, DSdecimal, DT
from typing import List, Optional, Dict, Any, Union, Tuple, Callable
from io import BytesIO
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

from .utils import make_hashable, normalize_numeric_values, clean_string
from .validation import BaseValidationModel

def get_dicom_values(ds: FileDataset, skip_pixel_data: bool = True) -> Dict[str, Any]:
    """
    Convert a DICOM dataset to a dictionary, filtering out binary data, NaN values, and empty fields.

    Args:
        ds (pydicom.dataset.FileDataset): The DICOM dataset to process.
        skip_pixel_data (bool): Whether to skip the pixel data element (default: True).

    Returns:
        Dict[str, Any]: A dictionary of extracted DICOM metadata, excluding binary, NaN, and empty values.
    """
    dicom_dict = {}

    def process_element(element, recurses=0):
        """Process and normalize DICOM element values, converting to the most appropriate datatype."""
        if element.tag == 0x7fe00010 and skip_pixel_data:
            return None  # Skip pixel data
        if isinstance(element.value, (bytes, memoryview)):
            return None  # Skip binary data

        def convert_value(v, recurses=0):
            """Convert value to int if possible, else float, else keep as string."""
            if recurses > 2:
                return None
            try:
                if element.VR == 'SQ' or isinstance(v, (MultiValue, list)):
                    v = [convert_value(item, recurses + 1) for item in v]
                    v = [item for item in v if item is not None]
                    return tuple(v)
                if isinstance(v, DT):
                    return v.strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(v, (int, IS)):
                    v = int(v)
                    return v if v == v else None
                if isinstance(v, (float, DSfloat, DSdecimal)):
                    v = float(v)
                    return v if v == v else None
                if isinstance(v, (UID, PersonName, str)):
                    return str(v)
            except:
                try:
                    return str(v)
                except:
                    return None
            return None

        v = convert_value(element.value)
        return v if (v == v and v != None) else None

    for element in ds:
        value = process_element(element)
        if value is not None:
            keyword = element.keyword if element.keyword else f"({element.tag.group:04X},{element.tag.element:04X})"
            dicom_dict[keyword] = value

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
        ds = pydicom.dcmread(dicom_file, stop_before_pixels=skip_pixel_data, force=True, defer_size=True)
    
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
        groups = [group.reset_index(drop=True) for _, group in session_df.groupby(acquisition_fields)]
        session_df = pd.concat(groups, ignore_index=True)

    return session_df
    
async def async_load_dicom_session(
    session_dir: Optional[str] = None,
    dicom_bytes: Optional[Union[Dict[str, bytes], Any]] = None,
    skip_pixel_data: bool = True,
    show_progress: bool = False,
    progress_function: Optional[Callable[[int], None]] = None,
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
                    from tqdm import tqdm
                    for fut in tqdm(asyncio.as_completed(futures), total=len(futures), desc="Loading DICOM bytes in parallel"):
                        session_data.append(fut.result())
                else:
                    total_completed = 0
                    progress_prev = 0
                    for fut in asyncio.as_completed(futures):
                        if progress_function is not None:
                            progress = round(100 * total_completed / len(dicom_items))
                            if progress > progress_prev:
                                progress_prev = progress
                                progress_function(progress)
                                await asyncio.sleep(0)  # yield control
                        session_data.append(fut.result())
                        total_completed += 1
        else:
            if show_progress:
                from tqdm import tqdm
                dicom_items = tqdm(dicom_items, desc="Loading DICOM bytes")
            progress_prev = 0
            for i, (key, content) in enumerate(dicom_items):
                if progress_function is not None:
                    progress = round(100 * i / len(dicom_items))
                    if progress > progress_prev:
                        progress_prev = progress
                        progress_function(progress)
                        await asyncio.sleep(0)
                try:
                    dicom_values = load_dicom(content, skip_pixel_data=skip_pixel_data)
                    dicom_values["DICOM_Path"] = key
                    dicom_values["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))
                    session_data.append(dicom_values)
                except Exception as e:
                    print(f"Error reading {key}: {e}")
    # 2) Session directory branch
    elif session_dir is not None:
        all_files = [os.path.join(root, file)
                     for root, _, files in os.walk(session_dir) for file in files]
        if not all_files:
            raise ValueError("No DICOM data found to process.")
        if parallel_workers > 1:
            with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
                futures = [
                    executor.submit(_load_one_dicom_path, fpath, skip_pixel_data)
                    for fpath in all_files
                ]
                if show_progress:
                    from tqdm import tqdm
                    for fut in tqdm(asyncio.as_completed(futures), total=len(futures), desc="Reading DICOMs in parallel"):
                        session_data.append(fut.result())
                else:
                    total_completed = 0
                    progress_prev = 0
                    for fut in asyncio.as_completed(futures):
                        if progress_function is not None:
                            progress = round(100 * total_completed / len(all_files))
                            if progress > progress_prev:
                                progress_prev = progress
                                progress_function(progress)
                                await asyncio.sleep(0)
                        session_data.append(fut.result())
                        total_completed += 1
        else:
            if show_progress:
                from tqdm import tqdm
                all_files = tqdm(all_files, desc="Loading DICOMs")
            progress_prev = 0
            for i, dicom_path in enumerate(all_files):
                if progress_function is not None:
                    progress = round(100 * i / len(all_files))
                    if progress > progress_prev:
                        progress_prev = progress
                        progress_function(progress)
                        await asyncio.sleep(0)
                try:
                    dicom_values = load_dicom(dicom_path, skip_pixel_data=skip_pixel_data)
                    dicom_values["DICOM_Path"] = dicom_path
                    dicom_values["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))
                    session_data.append(dicom_values)
                except Exception as e:
                    print(f"Error reading {dicom_path}: {e}")
    else:
        raise ValueError("Either session_dir or dicom_bytes must be provided.")

    if not session_data:
        raise ValueError("No DICOM data found to process.")

    session_df = pd.DataFrame(session_data)
    for col in session_df.columns:
        session_df[col] = session_df[col].apply(make_hashable)
    session_df.dropna(axis=1, how='all', inplace=True)
    if "InstanceNumber" in session_df.columns:
        session_df.sort_values("InstanceNumber", inplace=True)
    elif "DICOM_Path" in session_df.columns:
        session_df.sort_values("DICOM_Path", inplace=True)
    return session_df


# Synchronous wrapper
def load_dicom_session(
    session_dir: Optional[str] = None,
    dicom_bytes: Optional[Union[Dict[str, bytes], Any]] = None,
    skip_pixel_data: bool = True,
    show_progress: bool = False,
    progress_function: Optional[Callable[[int], None]] = None,
    parallel_workers: int = 1
) -> pd.DataFrame:
    """
    Synchronous version of load_dicom_session.
    It reuses the async version by calling it via asyncio.run().
    """
    return asyncio.run(
        async_load_dicom_session(
            session_dir=session_dir,
            dicom_bytes=dicom_bytes,
            skip_pixel_data=skip_pixel_data,
            show_progress=show_progress,
            progress_function=progress_function,
            parallel_workers=parallel_workers
        )
    )

def assign_acquisition_and_run_numbers(
        session_df,
        reference_fields=[
            "SeriesDescription",
            "ScanOptions",
            "MRAcquisitionType",
            "SequenceName",
            "AngioFlag",
            "SliceThickness",
            "AcquisitionMatrix",
            "RepetitionTime",
            "EchoTime",
            "InversionTime",
            "NumberOfAverages",
            "ImagingFrequency",
            "ImagedNucleus",
            "EchoNumbers",
            "MagneticFieldStrength",
            "NumberOfPhaseEncodingSteps",
            "EchoTrainLength",
            "PercentSampling",
            "PercentPhaseFieldOfView",
            "PixelBandwidth",
            "ReceiveCoilName",
            "TransmitCoilName",
            "FlipAngle",
            "ReconstructionDiameter",
            "InPlanePhaseEncodingDirection",
            "ParallelReductionFactorInPlane",
            "ParallelAcquisitionTechnique",
            "TriggerTime",
            "TriggerSourceOrType",
            "HeartRate",
            "BeatRejectionFlag",
            "LowRRValue",
            "HighRRValue",
            "SAR",
            "dBdt",
            "GradientEchoTrainLength",
            "SpoilingRFPhaseAngle",
            "DiffusionBValue",
            "DiffusionGradientDirectionSequence",
            "PerfusionTechnique",
            "SpectrallySelectedExcitation",
            "SaturationRecovery",
            "SpectrallySelectedSuppression",
            "TimeOfFlightContrast",
            "SteadyStatePulseSequence",
            "PartialFourierDirection",
        ],
        acquisition_fields=["ProtocolName"],
        run_group_fields=["PatientName", "PatientID", "ProtocolName", "StudyDate"]
    ):
    
    if acquisition_fields:
        groups = [group.reset_index(drop=True) for _, group in session_df.groupby(acquisition_fields)]
        session_df = pd.concat(groups, ignore_index=True)

    def clean_acquisition_values(row):
        return "-".join(str(val) if pd.notnull(val) else "NA" for val in row)

    session_df["Acquisition"] = (
        "acq-"
        + session_df[acquisition_fields]
        .apply(clean_acquisition_values, axis=1)
        .apply(clean_string)
    )

    run_group_fields = [field for field in run_group_fields if field in session_df.columns]
    session_df.reset_index(drop=True, inplace=True)
    for run_group, group_df in session_df.groupby(run_group_fields):
        group_df.sort_values("SeriesNumber", inplace=True)

        for key, sub_df in group_df.groupby(["SeriesDescription", "ImageType"]):
            series_num = sub_df["SeriesNumber"].unique()
            if len(series_num) > 1:
                run_number = 1
                for series_id in series_num:
                    session_df.loc[sub_df.index[sub_df["SeriesNumber"] == series_id], "RunNumber"] = run_number
                    run_number += 1
            else:
                session_df.loc[sub_df.index, "RunNumber"] = 1

    if reference_fields:
        for pn, protocol_df in session_df.groupby(['ProtocolName']):
            settings_group_fields = [field for field in ["PatientName", "PatientID", "StudyDate", "RunNumber"] if field in protocol_df.columns]
            param_to_settings = {}
            settings_counter = 1

            for settings_group, group_df in protocol_df.groupby(settings_group_fields):
                param_tuple = tuple(
                    (field, tuple(sorted(group_df[field].dropna().unique())))
                    for field in reference_fields
                    if field in group_df.columns
                )
                if param_tuple not in param_to_settings:
                    param_to_settings[param_tuple] = settings_counter
                    settings_counter += 1
                session_df.loc[group_df.index, "SettingsNumber"] = param_to_settings[param_tuple]

        if "SettingsNumber" in session_df.columns:
            acq_counts = session_df.groupby("Acquisition")["SettingsNumber"].nunique()
            acq_to_update = acq_counts[acq_counts > 1].index

            mask = session_df["Acquisition"].isin(acq_to_update)
            session_df.loc[mask, "Acquisition"] = session_df.loc[mask].apply(
                lambda row: f"{row['Acquisition']}-{int(row['SettingsNumber'])}", axis=1
            )

            del session_df["SettingsNumber"]

            session_df.reset_index(drop=True, inplace=True)
            for run_group, group_df in session_df.groupby(["Acquisition"] + run_group_fields):
                group_df.sort_values("SeriesNumber", inplace=True)
                for key, sub_df in group_df.groupby(["SeriesDescription", "ImageType"]):
                    series_num = sub_df["SeriesNumber"].unique()
                    if len(series_num) > 1:
                        run_number = 1
                        for series_id in series_num:
                            session_df.loc[sub_df.index[sub_df["SeriesNumber"] == series_id], "RunNumber"] = run_number
                            run_number += 1
                    else:
                        session_df.loc[sub_df.index, "RunNumber"] = 1

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

