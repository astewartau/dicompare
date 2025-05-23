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

from typing import List, Optional, Dict, Any, Union, Tuple, Callable
from io import BytesIO
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

from pydicom.multival import MultiValue
from pydicom.valuerep import DT, DSfloat, DSdecimal, IS
from pydicom.uid import UID
from pydicom.valuerep import PersonName

from .utils import make_hashable, normalize_numeric_values, clean_string
from .validation import BaseValidationModel

pydicom.config.debug(False)

def get_dicom_values(ds, skip_pixel_data=True):
    """
    Convert a DICOM dataset to a dictionary of metadata for regular files or a list of dictionaries
    for enhanced DICOM files.

    For enhanced files (those with a 'PerFrameFunctionalGroupsSequence'),
    each frame yields one dictionary merging common metadata with frame-specific details.

    This version flattens nested dictionaries (and sequences), converts any pydicom types into plain
    Python types, and automatically reduces keys by keeping only the last (leaf) part of any underscore-
    separated key. In addition, a reduced mapping is applied only where the names really need to change.
    """

    def to_plain(value):
        if isinstance(value, (list, MultiValue, tuple)):
            return tuple(to_plain(item) for item in value)
        elif isinstance(value, dict):
            return {k: to_plain(v) for k, v in value.items()}
        else:
            return value

    def flatten_dict(data, parent_key="", sep="_"):
        items = {}

        if isinstance(data, dict):
            for key, value in data.items():
                new_key = f"{parent_key}{sep}{key}" if parent_key else key

                if isinstance(value, dict):
                    items.update(flatten_dict(value, new_key, sep=sep))

                elif isinstance(value, (list, tuple)):
                    # only descend if there's at least one dict in the list
                    if any(isinstance(item, dict) for item in value):
                        for idx, item in enumerate(value):
                            item_key = f"{new_key}{sep}{idx}"
                            if isinstance(item, dict):
                                items.update(flatten_dict(item, item_key, sep=sep))
                            else:
                                items[item_key] = item
                    else:
                        # atomic list of primitives – keep it whole
                        items[new_key] = value

                else:
                    items[new_key] = value

        elif isinstance(data, (list, tuple)):
            # same logic for a top‑level list
            if any(isinstance(item, dict) for item in data):
                for idx, item in enumerate(data):
                    new_key = f"{parent_key}{sep}{idx}" if parent_key else str(idx)
                    if isinstance(item, dict):
                        items.update(flatten_dict(item, new_key, sep=sep))
                    else:
                        items[new_key] = item
            else:
                items[parent_key] = data

        else:
            items[parent_key] = data

        return items

    def reduce_keys(flat_dict):
        """
        Replace each key in the flattened dictionary with just the last underscore-separated component.
        In case of duplicates, the first non-None value is kept.
        """
        result = {}
        for key, value in flat_dict.items():
            new_key = key.split("_")[-1]
            if new_key in result:
                # if already present, update only if the existing value is None and the new one isn't
                if result[new_key] is None and value is not None:
                    result[new_key] = value
            else:
                result[new_key] = value
        return result

    def process_element(element, recurses=0, skip_pixel_data=True):
        if element.tag == 0x7FE00010 and skip_pixel_data:
            return None
        if isinstance(element.value, (bytes, memoryview)):
            return None

        def convert_value(v, recurses=0):
            if recurses > 30:
                return None

            if isinstance(v, pydicom.dataset.Dataset):
                result = {}
                for key in v.dir():
                    try:
                        sub_val = v.get(key)
                        converted = convert_value(sub_val, recurses + 1)
                        if converted is not None:
                            result[key] = converted
                    except Exception as e:
                        continue
                return result

            if isinstance(v, (list, MultiValue)):
                lst = []
                for item in v:
                    converted = convert_value(item, recurses + 1)
                    if converted is not None:
                        lst.append(converted)
                return tuple(lst)

            nonzero_keys = [
                "EchoTime",
                "FlipAngle",
                "SliceThickness",
                "RepetitionTime",
                "InversionTime",
                "NumberOfAverages",
                "ImagingFrequency",
                "MagneticFieldStrength",
                "NumberOfPhaseEncodingSteps",
                "EchoTrainLength",
                "PercentSampling",
                "PercentPhaseFieldOfView",
                "PixelBandwidth",
            ]

            if isinstance(v, DT):
                try:
                    return v.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    return None
            if isinstance(v, (int, IS)):
                try:
                    result = int(v)
                    if element.keyword in nonzero_keys and v == 0:
                        return None
                    return result
                except Exception:
                    return None
                
            if isinstance(v, (float, DSfloat, DSdecimal)):
                try:
                    result = float(v)
                    if element.keyword in nonzero_keys and v == 0:
                        return None
                    return result
                except Exception:
                    return None

            try:  # if isinstance(v, (UID, PersonName, str)):
                result = str(v)
                if result == "":
                    return None
                return result
            except Exception:
                return None

        return convert_value(element.value, recurses)

    # Mapping for enhanced to regular DICOM keys
    enhanced_to_regular = {
        "EffectiveEchoTime": "EchoTime",
        "FrameType": "ImageType",
        "FrameAcquisitionNumber": "AcquisitionNumber",
        "FrameAcquisitionDateTime": "AcquisitionDateTime",
        "FrameAcquisitionDuration": "AcquisitionDuration",
        "FrameReferenceDateTime": "ReferenceDateTime",
    }

    if "PerFrameFunctionalGroupsSequence" in ds:
        common = {}
        for element in ds:
            if element.keyword == "PerFrameFunctionalGroupsSequence":
                continue
            if element.tag == 0x7FE00010 and skip_pixel_data:
                continue
            value = process_element(
                element, recurses=0, skip_pixel_data=skip_pixel_data
            )
            if value is not None:
                key = (
                    element.keyword
                    if element.keyword
                    else f"({element.tag.group:04X},{element.tag.element:04X})"
                )
                common[key] = value

        enhanced_rows = []
        for frame_index, frame in enumerate(ds.PerFrameFunctionalGroupsSequence):
            frame_data = {}
            for key in frame.dir():
                try:
                    value = frame.get(key)
                    if isinstance(value, pydicom.sequence.Sequence):
                        if len(value) == 1:
                            sub_ds = value[0]
                            sub_dict = {}
                            for sub_key in sub_ds.dir():
                                sub_value = sub_ds.get(sub_key)
                                if hasattr(sub_value, "strftime"):
                                    sub_dict[sub_key] = sub_value.strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    )
                                else:
                                    sub_dict[sub_key] = sub_value
                            frame_data[key] = sub_dict
                        else:
                            sub_list = []
                            for item in value:
                                sub_dict = {}
                                for sub_key in item.dir():
                                    sub_value = item.get(sub_key)
                                    if hasattr(sub_value, "strftime"):
                                        sub_dict[sub_key] = sub_value.strftime(
                                            "%Y-%m-%d %H:%M:%S"
                                        )
                                    else:
                                        sub_dict[sub_key] = sub_value
                                sub_list.append(sub_dict)
                            frame_data[key] = sub_list
                    else:
                        if isinstance(value, (list, MultiValue)):
                            frame_data[key] = tuple(value)
                        else:
                            frame_data[key] = value
                except Exception as e:
                    continue
            frame_data["FrameIndex"] = frame_index
            merged = common.copy()
            merged.update(frame_data)
            flat_merged = flatten_dict(merged)
            plain_merged = {k: to_plain(v) for k, v in flat_merged.items()}
            plain_merged = reduce_keys(plain_merged)
            for src, tgt in enhanced_to_regular.items():
                if src in plain_merged:
                    plain_merged[tgt] = plain_merged.pop(src)
            enhanced_rows.append(plain_merged)
        return enhanced_rows

    else:
        dicom_dict = {}
        for element in ds:
            value = process_element(
                element, recurses=0, skip_pixel_data=skip_pixel_data
            )
            if value is not None:
                keyword = (
                    element.keyword
                    if element.keyword
                    else f"({element.tag.group:04X},{element.tag.element:04X})"
                )
                dicom_dict[keyword] = value
        flat_dict = flatten_dict(dicom_dict)
        plain_dict = {k: to_plain(v) for k, v in flat_dict.items()}
        plain_dict = reduce_keys(plain_dict)
        for src, tgt in enhanced_to_regular.items():
            if src in plain_dict:
                plain_dict[tgt] = plain_dict.pop(src)
        return plain_dict


def load_dicom(
    dicom_file: Union[str, bytes], skip_pixel_data: bool = True
) -> Dict[str, Any]:
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
        ds = pydicom.dcmread(
            BytesIO(dicom_file),
            stop_before_pixels=skip_pixel_data,
            force=True,
            defer_size=len(dicom_file),
        )
    else:
        ds = pydicom.dcmread(
            dicom_file, stop_before_pixels=skip_pixel_data, force=True, defer_size=True
        )

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


def _load_one_dicom_bytes(
    key: str, content: bytes, skip_pixel_data: bool
) -> Dict[str, Any]:
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

    nifti_files = [
        os.path.join(root, file)
        for root, _, files in os.walk(session_dir)
        for file in files
        if ".nii" in file
    ]

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
            "NIfTI_Header": nifti_data.header,
        }
        session_data.append(nifti_values)

        # extract BIDS tags from filename
        bids_tags = os.path.splitext(os.path.basename(nifti_path))[0].split("_")
        for tag in bids_tags:
            key_val = tag.split("-")
            if len(key_val) == 2:
                key, val = key_val
                nifti_values[key] = val

        # extract suffix
        if len(bids_tags) > 1:
            nifti_values["suffix"] = bids_tags[-1]

        # if corresponding json file exists
        json_path = nifti_path.replace(".nii.gz", ".nii").replace(".nii", ".json")
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                json_data = json.load(f)
            nifti_values["JSON_Path"] = json_path
            nifti_values.update(json_data)

    session_df = pd.DataFrame(session_data)

    for col in session_df.columns:
        session_df[col] = session_df[col].apply(make_hashable)

    if acquisition_fields:
        session_df = session_df.groupby(acquisition_fields).apply(
            lambda x: x.reset_index(drop=True)
        )

    return session_df


async def async_load_dicom_session(
    session_dir: Optional[str] = None,
    dicom_bytes: Optional[Union[Dict[str, bytes], Any]] = None,
    skip_pixel_data: bool = True,
    show_progress: bool = False,
    progress_function: Optional[Callable[[int], None]] = None,
    parallel_workers: int = 1,
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
                    executor.submit(
                        _load_one_dicom_bytes, key, content, skip_pixel_data
                    )
                    for key, content in dicom_items
                ]
                if show_progress:
                    from tqdm import tqdm

                    for fut in tqdm(
                        asyncio.as_completed(futures),
                        total=len(futures),
                        desc="Loading DICOM bytes in parallel",
                    ):
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
                    if isinstance(dicom_values, list):
                        for dicom_value in dicom_values:
                            dicom_value["DICOM_Path"] = key
                            dicom_value["InstanceNumber"] = int(
                                dicom_value.get("InstanceNumber", 0)
                            )
                            session_data.append(dicom_value)
                    else:
                        dicom_values["DICOM_Path"] = key
                        dicom_values["InstanceNumber"] = int(
                            dicom_values.get("InstanceNumber", 0)
                        )
                        session_data.append(dicom_values)
                except Exception as e:
                    print(f"Error reading {key}: {e}")
    # 2) Session directory branch
    elif session_dir is not None:
        all_files = [
            os.path.join(root, file)
            for root, _, files in os.walk(session_dir)
            for file in files
        ]
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

                    for fut in tqdm(
                        asyncio.as_completed(futures),
                        total=len(futures),
                        desc="Reading DICOMs in parallel",
                    ):
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
                dicom_values = load_dicom(dicom_path, skip_pixel_data=skip_pixel_data)
                if isinstance(dicom_values, list):
                    for dicom_value in dicom_values:
                        dicom_value["DICOM_Path"] = dicom_path
                        dicom_value["InstanceNumber"] = int(
                            dicom_value.get("InstanceNumber", 0)
                        )
                        session_data.append(dicom_value)
                else:
                    dicom_values["DICOM_Path"] = dicom_path
                    dicom_values["InstanceNumber"] = int(
                        dicom_values.get("InstanceNumber", 0)
                    )
                    session_data.append(dicom_values)
    else:
        raise ValueError("Either session_dir or dicom_bytes must be provided.")

    if not session_data:
        raise ValueError("No DICOM data found to process.")

    session_df = pd.DataFrame(session_data)
    for col in session_df.columns:
        session_df[col] = session_df[col].apply(make_hashable)
    session_df.dropna(axis=1, how="all", inplace=True)
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
    parallel_workers: int = 1,
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
            parallel_workers=parallel_workers,
        )
    )


def assign_acquisition_and_run_numbers(
    session_df, reference_fields=None, acquisition_fields=None, run_group_fields=None
):
    if reference_fields is None:
        reference_fields = [
            #"SeriesDescription",
            #"ScanOptions",
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
            #"ImageType",
            #"EchoNumbers",
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
        ]
    if acquisition_fields is None:
        acquisition_fields = ["ProtocolName"]

    # initial grouping so we can label acquisitions
    if acquisition_fields:
        session_df = session_df.groupby(acquisition_fields).apply(
            lambda x: x.reset_index(drop=True)
        )

    def clean_acquisition_values(row):
        return "-".join(str(val) if pd.notnull(val) else "NA" for val in row)

    session_df["Acquisition"] = "acq-" + session_df[acquisition_fields].apply(
        clean_acquisition_values, axis=1
    ).apply(clean_string)

    session_df = session_df.reset_index(drop=True)
    #print(f"Created initial acquisition labels: {session_df['Acquisition'].unique().tolist()}")

    # identify runs: group by subject+protocol+date
    if run_group_fields is None:
        run_group_fields = ["PatientName", "PatientID", "ProtocolName", "StudyDate"]
    run_keys = [f for f in run_group_fields if f in session_df.columns]
    #print(f"Using run group fields: {run_keys}")
    
    for key_vals, group in session_df.groupby(run_keys):
        if "SeriesTime" in group.columns:
            series_differentiator = "SeriesTime"
        else:
            series_differentiator = "SeriesInstanceUID"
        group = group.sort_values(series_differentiator)
        for (desc, imgtype), subgrp in group.groupby(["SeriesDescription", "ImageType"]):
            times = sorted(
                group.loc[
                      (group["SeriesDescription"] == desc)
                    & (group["ImageType"] == imgtype),
                    series_differentiator,
                ].unique()
            )
            if len(times) > 1:
                #print(f"Found multiple series times for {desc}, {imgtype}: {times}")
                for rn, t in enumerate(times, start=1):
                    mask = (
                        (session_df["SeriesDescription"] == desc)
                        & (session_df["ImageType"] == imgtype)
                        & (session_df[series_differentiator] == t)
                        & pd.concat(
                            [
                                session_df[k] == v
                                for k, v in zip(
                                    run_keys,
                                    (
                                        key_vals
                                        if isinstance(key_vals, tuple)
                                        else [key_vals]
                                    ),
                                )
                            ],
                            axis=1,
                        ).all(axis=1)
                    )
                    session_df.loc[mask, "RunNumber"] = rn
                    #print(f"Assigned RunNumber {rn} to {desc}, {imgtype}, {t}")
            else:
                idx = group[group["SeriesDescription"] == desc].index
                session_df.loc[idx, "RunNumber"] = 1

    # split acquisitions by differing reference‐field settings
    if reference_fields:
        #print("Starting settings number assignment based on reference fields")
        
        # First, let's create a special handling for the coil field
        coil_field = "(0051,100F)"
        if coil_field in session_df.columns:
            #print(f"Special handling for coil field {coil_field}")
            
            # Function to check if a value contains a number
            def contains_number(value):
                if pd.isna(value) or value is None or value == "":
                    return False
                value_str = str(value)
                return any(char.isdigit() for char in value_str)
            
            # Function to check if a value is purely non-numeric (like "HEA;HEP")
            def is_non_numeric_special(value):
                if pd.isna(value) or value is None or value == "":
                    return False
                value_str = str(value)
                return value_str == "HEA;HEP" or not any(char.isdigit() for char in value_str)
            
            # Create a new column to mark rows as having numeric or non-numeric coil values
            session_df['CoilType'] = 'Unknown'
            numeric_mask = session_df[coil_field].apply(lambda x: contains_number(x) if pd.notnull(x) else False)
            non_numeric_mask = session_df[coil_field].apply(lambda x: is_non_numeric_special(x) if pd.notnull(x) else False)
            
            session_df.loc[numeric_mask, 'CoilType'] = 'Numeric'
            session_df.loc[non_numeric_mask, 'CoilType'] = 'NonNumeric'
            
            # Log the distribution of coil types
            coil_type_counts = session_df['CoilType'].value_counts()
            #print(f"Coil type distribution: {coil_type_counts.to_dict()}")
            
            # Check if we have both types
            has_numeric = 'Numeric' in coil_type_counts.index
            has_non_numeric = 'NonNumeric' in coil_type_counts.index
            
            if has_numeric and has_non_numeric:
                #print("Dataset contains both numeric and non-numeric coil values")
                # Add CoilType to the settings group fields to ensure separation
                settings_group_fields = [
                    f for f in ["PatientName", "PatientID", "StudyDate", "RunNumber", "CoilType"]
                    if f in session_df.columns
                ]
            else:
                # No need to separate by coil type
                settings_group_fields = [
                    f for f in ["PatientName", "PatientID", "StudyDate", "RunNumber"]
                    if f in session_df.columns
                ]
        else:
            # No coil field, use standard grouping
            settings_group_fields = [
                f for f in ["PatientName", "PatientID", "StudyDate", "RunNumber"]
                if f in session_df.columns
            ]
        
        #print(f"Using settings group fields: {settings_group_fields}")
        
        # Now process each protocol
        for pn, protocol_group in session_df.groupby("ProtocolName"):
            #print(f"Processing protocol: {pn}")
            
            # Debug: Show RunNumber distribution
            if 'RunNumber' in protocol_group.columns:
                run_counts = protocol_group['RunNumber'].value_counts()
                #print(f"RunNumber distribution for protocol {pn}: {run_counts.to_dict()}")
            
            # Debug: Show CoilType distribution by RunNumber if applicable
            if 'CoilType' in protocol_group.columns and 'RunNumber' in protocol_group.columns:
                for run_num in protocol_group['RunNumber'].unique():
                    run_group = protocol_group[protocol_group['RunNumber'] == run_num]
                    coil_counts = run_group['CoilType'].value_counts()
                    #print(f"RunNumber {run_num} coil type distribution: {coil_counts.to_dict()}")
                    
                    # Show sample values for each coil type in this run
                    for coil_type in run_group['CoilType'].unique():
                        sample_values = run_group[run_group['CoilType'] == coil_type][coil_field].unique()[:5]
                        #print(f"RunNumber {run_num}, CoilType {coil_type} sample values: {sample_values}")
            
            param_to_idx = {}
            counter = 1

            # Group by the settings fields
            for settings_vals, sg in protocol_group.groupby(settings_group_fields):
                # Debug: Show detailed info about this settings group
                if isinstance(settings_vals, tuple):
                    settings_dict = {field: val for field, val in zip(settings_group_fields, settings_vals)}
                else:
                    settings_dict = {settings_group_fields[0]: settings_vals}
                
                #print(f"Processing settings group: {settings_dict}")
                
                if coil_field in sg.columns:
                    unique_values = sg[coil_field].dropna().unique()
                    #print(f"Coil field values in this group: {unique_values}")
                    
                    # Check if this group has numeric or non-numeric values
                    has_numeric_in_group = any(contains_number(val) for val in unique_values)
                    has_non_numeric_in_group = any(is_non_numeric_special(val) for val in unique_values)
                    #print(f"Group has numeric values: {has_numeric_in_group}, non-numeric values: {has_non_numeric_in_group}")
                
                # Create parameter tuple for this group
                param_tuple = tuple(
                    (fld, tuple(sorted(sg[fld].dropna().unique(), key=str)))
                    for fld in reference_fields
                    if fld in sg
                )
                
                # If we're using CoilType for grouping, add it to the parameter tuple
                if 'CoilType' in settings_group_fields and 'CoilType' in sg.columns:
                    coil_types = tuple(sorted(sg['CoilType'].dropna().unique()))
                    param_tuple += (('CoilType', coil_types),)
                
                # Create a readable dict of the parameters
                params = {fld: vals for fld, vals in param_tuple}
                
                if param_tuple not in param_to_idx:
                    param_to_idx[param_tuple] = counter
                    #print(f"Created new SettingsNumber {counter} for parameter set")
                    #print(f"Fields contributing to SettingsNumber {counter}:")
                    #for field, values in params.items():
                    #    print(f"  {field}: {values}")
                    counter += 1
                #else:
                #    print(f"Using existing SettingsNumber {param_to_idx[param_tuple]} for parameter set")
                
                session_df.loc[sg.index, "SettingsNumber"] = param_to_idx[param_tuple]
                #print(f"Assigned SettingsNumber {param_to_idx[param_tuple]} to {len(sg)} rows")

        # Clean up the temporary column if it exists
        if 'CoilType' in session_df.columns:
            session_df = session_df.drop(columns='CoilType')

        # any acquisition with >1 settings → rename Acquisition
        counts = session_df.groupby("Acquisition")["SettingsNumber"].nunique()
        multi = counts[counts > 1].index
        if len(multi) > 0:
            #print(f"Found {len(multi)} acquisitions with multiple settings numbers: {multi.tolist()}")
            mask = session_df["Acquisition"].isin(multi)
            session_df.loc[mask, "Acquisition"] = (
                session_df.loc[mask, "Acquisition"]
                + "-"
                + session_df.loc[mask, "SettingsNumber"].astype(int).astype(str)
            )
            #print(f"Renamed acquisitions with settings numbers: {session_df.loc[mask, 'Acquisition'].unique().tolist()}")
        #else:
        #    print("No acquisitions with multiple settings numbers found")
            
        session_df = session_df.drop(columns="SettingsNumber").reset_index(drop=True)

        # recalc runs on true acquisitions
        #print("Recalculating run numbers based on final acquisition labels")
        final_run_keys = ["Acquisition", "SeriesDescription", "ImageType"] + [
            f for f in ["PatientName", "PatientID", "StudyDate"] if f in session_df
        ]
        #print(f"Using final run keys: {final_run_keys}")
        
        for key_vals, group in session_df.groupby(final_run_keys):
            if "SeriesTime" in group.columns:
                series_differentiator = "SeriesTime"
            else:
                series_differentiator = "SeriesInstanceUID"
            group = group.sort_values(series_differentiator)
            for desc in group["SeriesDescription"].unique():
                times = sorted(
                    group.loc[
                        group["SeriesDescription"] == desc, series_differentiator
                    ].unique()
                )
                if len(times) > 1:
                    #print(f"Found multiple series times for {desc} in final acquisition: {times}")
                    for rn, t in enumerate(times, start=1):
                        idx = group[
                            (group["SeriesDescription"] == desc)
                            & (group[series_differentiator] == t)
                        ].index
                        session_df.loc[idx, "RunNumber"] = rn
                        #print(f"Assigned final RunNumber {rn} to {desc}, {t}")
                else:
                    idx = group[group["SeriesDescription"] == desc].index
                    session_df.loc[idx, "RunNumber"] = 1

    #print("Finished assigning acquisition and run numbers")
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
                processed["value"] = (
                    tuple(field["value"])
                    if isinstance(field["value"], list)
                    else field["value"]
                )
            if "tolerance" in field:
                processed["tolerance"] = field["tolerance"]
            if "contains" in field:
                processed["contains"] = field["contains"]
            processed_fields.append(processed)
        return processed_fields

    with open(json_ref, "r") as f:
        reference_data = json.load(f)

    reference_data = normalize_numeric_values(reference_data)

    acquisitions = {}
    reference_fields = set()

    for acq_name, acquisition in reference_data.get("acquisitions", {}).items():
        acq_entry = {
            "fields": process_fields(acquisition.get("fields", [])),
            "series": [],
        }
        reference_fields.update(
            field["field"] for field in acquisition.get("fields", [])
        )

        for series in acquisition.get("series", []):
            series_entry = {
                "name": series["name"],
                "fields": process_fields(series.get("fields", [])),
            }
            acq_entry["series"].append(series_entry)
            reference_fields.update(
                field["field"] for field in series.get("fields", [])
            )

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
        raise ValueError(
            f"The module {module_path} does not define 'ACQUISITION_MODELS'."
        )

    acquisition_models = getattr(validation_module, "ACQUISITION_MODELS")
    if not isinstance(acquisition_models, dict):
        raise ValueError("'ACQUISITION_MODELS' must be a dictionary.")

    return acquisition_models
