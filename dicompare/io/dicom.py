"""
DICOM file loading and processing functions for dicompare.

This module contains all DICOM-specific I/O operations including:
- Loading DICOM files and extracting metadata
- Processing enhanced and regular DICOM datasets
- Extracting CSA headers and inferred metadata
- Loading DICOM and NIfTI sessions
"""

import os
import pydicom
import re
import asyncio
import pandas as pd
import nibabel as nib
import json

from typing import List, Optional, Dict, Any, Union, Callable
from io import BytesIO
from tqdm import tqdm

from pydicom.multival import MultiValue
from pydicom.valuerep import DT, DSfloat, DSdecimal, IS

from ..utils import normalize_numeric_values, safe_convert_value
from ..config import NONZERO_FIELDS
from ..processing.parallel_utils import process_items_parallel, process_items_sequential
from ..data_utils import make_dataframe_hashable, _process_dicom_metadata, prepare_session_dataframe

# --- IMPORT FOR CSA header parsing ---
from nibabel.nicom.csareader import get_csa_header

pydicom.config.debug(False)

def extract_inferred_metadata(ds: pydicom.Dataset) -> Dict[str, Any]:
    """
    Extract inferred metadata from a DICOM dataset.

    Args:
        ds (pydicom.Dataset): The DICOM dataset.

    Returns:
        Dict[str, Any]: A dictionary of inferred metadata.
    """
    inferred_metadata = {}

    # Try to infer multiband factor from ImageComments field (CMRR multiband convention)
    # Format: "Unaliased MB3/PE3 SENSE1" or "Unaliased MB4/PE3/LB"
    if hasattr(ds, "ImageComments"):
        mb_match = re.search(r"\bMB(\d+)", ds["ImageComments"].value, re.IGNORECASE)
        if mb_match:
            accel_factor = int(mb_match.group(1))
            inferred_metadata["MultibandAccelerationFactor"] = accel_factor
            inferred_metadata["MultibandFactor"] = accel_factor
            inferred_metadata["ParallelReductionFactorOutOfPlane"] = accel_factor

    # Try to infer multiband factor from protocol name if not found in ImageComments
    if "MultibandFactor" not in inferred_metadata and hasattr(ds, "ProtocolName"):
        mb_match = re.search(r"mb(\d+)", ds["ProtocolName"].value, re.IGNORECASE)
        if mb_match:
            accel_factor = int(mb_match.group(1))
            inferred_metadata["MultibandAccelerationFactor"] = accel_factor
            inferred_metadata["MultibandFactor"] = accel_factor
            inferred_metadata["ParallelReductionFactorOutOfPlane"] = accel_factor

    return inferred_metadata

def extract_csa_metadata(ds: pydicom.Dataset) -> Dict[str, Any]:
    """
    Extract relevant acquisition-specific metadata from Siemens CSA header.

    Args:
        ds (pydicom.Dataset): The DICOM dataset.

    Returns:
        Dict[str, Any]: A dictionary of CSA-derived acquisition parameters.
    """
    import logging
    logger = logging.getLogger(__name__)

    csa_metadata = {}

    csa = get_csa_header(ds, "image")

    # Check if CSA header exists and has tags
    if csa is None:
        logger.debug("No CSA header found in DICOM file")
        return csa_metadata

    if "tags" not in csa:
        logger.debug("CSA header exists but has no 'tags' key")
        return csa_metadata

    tags = csa["tags"]

    def get_csa_value(tag_name, scalar=True):
        """
        Safely extract CSA tag value with bounds checking.
        Returns None if tag doesn't exist or has no items.
        Falls back to string representation if float conversion fails.
        """
        if tag_name not in tags:
            return None

        items = tags[tag_name]["items"]

        # Check if items list is empty
        if not items:
            logger.debug(f"CSA tag '{tag_name}' exists but has no items")
            return None

        if scalar:
            # Try to return first item as float, fall back to string if conversion fails
            try:
                return float(items[0])
            except (ValueError, TypeError):
                # Value exists but can't be converted to float - use string
                logger.warning(f"CSA tag '{tag_name}' has value '{items[0]}' that couldn't be converted to float, using string")
                return str(items[0])
            except IndexError:
                logger.warning(f"CSA tag '{tag_name}' has empty items list")
                return None
        else:
            # Return list of floats, fall back to string for items that can't be converted
            result = []
            for i, item in enumerate(items):
                try:
                    result.append(float(item))
                except (ValueError, TypeError):
                    # Value exists but can't be converted - use string
                    logger.warning(f"CSA tag '{tag_name}' item {i} value '{item}' couldn't be converted to float, using string")
                    result.append(str(item))
            return result if result else None

    # Acquisition-level CSA fields
    csa_metadata["DiffusionBValue"] = get_csa_value("B_value")
    csa_metadata["DiffusionGradientOrientation"] = get_csa_value(
        "DiffusionGradientDirection", scalar=False
    )
    csa_metadata["SliceMeasurementDuration"] = get_csa_value("SliceMeasurementDuration")
    csa_metadata["MultibandAccelerationFactor"] = get_csa_value("MultibandFactor")
    csa_metadata["EffectiveEchoSpacing"] = get_csa_value("BandwidthPerPixelPhaseEncode")
    csa_metadata["TotalReadoutTime"] = get_csa_value("TotalReadoutTime")
    csa_metadata["MosaicRefAcqTimes"] = get_csa_value("MosaicRefAcqTimes", scalar=False)
    csa_metadata["SliceTiming"] = get_csa_value("SliceTiming", scalar=False)
    csa_metadata["NumberOfImagesInMosaic"] = get_csa_value("NumberOfImagesInMosaic")
    csa_metadata["DiffusionDirectionality"] = get_csa_value("DiffusionDirectionality")
    csa_metadata["GradientMode"] = get_csa_value("GradientMode")
    csa_metadata["B_matrix"] = get_csa_value("B_matrix", scalar=False)

    return csa_metadata


def _process_dicom_element(element, recurses=0, skip_pixel_data=True):
    """
    Process a single DICOM element and convert its value to Python types.
    """
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
                sub_val = v.get(key)
                converted = convert_value(sub_val, recurses + 1)
                if converted is not None:
                    result[key] = converted
            return result

        if isinstance(v, (list, MultiValue)):
            lst = []
            for item in v:
                converted = convert_value(item, recurses + 1)
                if converted is not None:
                    lst.append(converted)
            return tuple(lst)

        nonzero_keys = NONZERO_FIELDS

        if isinstance(v, DT):
            return v.strftime("%Y-%m-%d %H:%M:%S")

        if isinstance(v, (int, IS)):
            return safe_convert_value(
                v, int, None, True, nonzero_keys, element.keyword
            )

        if isinstance(v, (float, DSfloat, DSdecimal)):
            return safe_convert_value(
                v, float, None, True, nonzero_keys, element.keyword
            )

        # Convert to string
        if isinstance(v, str):
            if v == "":
                return None
            return v

        result = safe_convert_value(v, str, None)
        if result == "":
            return None
        return result

    return convert_value(element.value, recurses)


def _process_enhanced_dicom(ds, skip_pixel_data=True):
    """
    Process enhanced DICOM files with PerFrameFunctionalGroupsSequence.
    """
    common = {}
    for element in ds:
        if element.keyword == "PerFrameFunctionalGroupsSequence":
            continue
        if element.tag == 0x7FE00010 and skip_pixel_data:
            continue
        value = _process_dicom_element(
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
            value = frame.get(key)
            if isinstance(value, pydicom.sequence.Sequence):
                if len(value) == 1:
                    sub_ds = value[0]
                    sub_dict = {}
                    for sub_key in sub_ds.dir():
                        sub_value = sub_ds.get(sub_key)
                        sub_dict[sub_key] = sub_value
                    frame_data[key] = sub_dict
                else:
                    sub_list = []
                    for item in value:
                        sub_dict = {}
                        for sub_key in item.dir():
                            sub_value = item.get(sub_key)
                            sub_dict[sub_key] = sub_value
                        sub_list.append(sub_dict)
                    frame_data[key] = sub_list
            else:
                if isinstance(value, (list, MultiValue)):
                    frame_data[key] = tuple(value)
                else:
                    frame_data[key] = value
        frame_data["FrameIndex"] = frame_index
        merged = common.copy()
        merged.update(frame_data)

        # Process metadata using simple function
        plain_merged = _process_dicom_metadata(merged)
        enhanced_rows.append(plain_merged)
    return enhanced_rows


def _process_regular_dicom(ds, skip_pixel_data=True):
    """
    Process regular (non-enhanced) DICOM files.
    """
    dicom_dict = {}
    for element in ds:
        value = _process_dicom_element(
            element, recurses=0, skip_pixel_data=skip_pixel_data
        )
        if value is not None:
            keyword = (
                element.keyword
                if element.keyword
                else f"({element.tag.group:04X},{element.tag.element:04X})"
            )
            dicom_dict[keyword] = value

    # Process metadata using simple function
    return _process_dicom_metadata(dicom_dict)


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
    if "PerFrameFunctionalGroupsSequence" in ds:
        return _process_enhanced_dicom(ds, skip_pixel_data)
    else:
        return _process_regular_dicom(ds, skip_pixel_data)




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
        ds_raw = pydicom.dcmread(
            BytesIO(dicom_file),
            stop_before_pixels=skip_pixel_data,
            defer_size=len(dicom_file),
        )
    else:
        ds_raw = pydicom.dcmread(
            dicom_file,
            stop_before_pixels=skip_pixel_data,
            defer_size=True,
        )

    # Convert to plain metadata dict (flattened)
    metadata = get_dicom_values(ds_raw, skip_pixel_data=skip_pixel_data)

    # Only extract CSA metadata for Siemens DICOM files
    manufacturer = getattr(ds_raw, 'Manufacturer', '').upper()
    if 'SIEMENS' in manufacturer:
        csa_metadata = extract_csa_metadata(ds_raw)
        metadata.update(csa_metadata)

    inferred_metadata = extract_inferred_metadata(ds_raw)
    metadata.update(inferred_metadata)

    # Add CoilType as a regular metadata field
    coil_field = "(0051,100F)"
    if coil_field in metadata:
        coil_value = metadata[coil_field]
        if coil_value:
            def contains_number(value):
                if pd.isna(value) or value is None or value == "":
                    return False
                return any(char.isdigit() for char in str(value))

            def is_non_numeric_special(value):
                if pd.isna(value) or value is None or value == "":
                    return False
                val_str = str(value)
                return val_str == "HEA;HEP" or not any(char.isdigit() for char in val_str)

            if contains_number(coil_value):
                metadata["CoilType"] = "Uncombined"
            elif is_non_numeric_special(coil_value):
                metadata["CoilType"] = "Combined"
            else:
                metadata["CoilType"] = None
        else:
            metadata["CoilType"] = None

    # Add GE ImageType mapping based on private tag (0043,102F)
    ge_private_tag = "(0043,102F)"
    if ge_private_tag in metadata:
        ge_value = metadata[ge_private_tag]
        # Map GE private tag values to ImageType
        ge_image_type_map = {
            0: 'M',         # Magnitude
            1: 'P',         # Phase
            2: 'REAL',      # Real
            3: 'IMAGINARY'  # Imaginary
        }

        ge_value_int = int(ge_value)
        mapped_type = ge_image_type_map[ge_value_int]

        # Set ImageType to the mapped value
        if 'ImageType' in metadata:
            current_type = metadata['ImageType']
            if isinstance(current_type, (list, tuple)):
                metadata['ImageType'] = list(current_type) + [mapped_type]
            else:
                metadata['ImageType'] = [current_type, mapped_type]
        else:
            metadata['ImageType'] = [mapped_type]

    # Add AcquisitionPlane based on ImageOrientationPatient
    if 'ImageOrientationPatient' in metadata:
        iop = metadata['ImageOrientationPatient']
        try:
            # Convert to list if it's a tuple or other sequence
            if isinstance(iop, (tuple, list)) and len(iop) == 6:
                iop_list = [float(x) for x in iop]

                # Get row and column direction cosines
                row_cosines = iop_list[:3]  # First 3 elements
                col_cosines = iop_list[3:6]  # Last 3 elements

                # Calculate slice normal using cross product
                slice_normal = [
                    row_cosines[1] * col_cosines[2] - row_cosines[2] * col_cosines[1],
                    row_cosines[2] * col_cosines[0] - row_cosines[0] * col_cosines[2],
                    row_cosines[0] * col_cosines[1] - row_cosines[1] * col_cosines[0]
                ]

                # Determine primary orientation based on largest component of slice normal
                abs_normal = [abs(x) for x in slice_normal]
                max_component = abs_normal.index(max(abs_normal))

                if max_component == 0:  # X-axis dominant
                    metadata['AcquisitionPlane'] = 'sagittal'
                elif max_component == 1:  # Y-axis dominant
                    metadata['AcquisitionPlane'] = 'coronal'
                else:  # Z-axis dominant (max_component == 2)
                    metadata['AcquisitionPlane'] = 'axial'

            else:
                metadata['AcquisitionPlane'] = 'Unknown'
        except (ValueError, TypeError, IndexError):
            # If calculation fails, mark as unknown
            metadata['AcquisitionPlane'] = 'Unknown'
    else:
        # If ImageOrientationPatient is not available, mark as unknown
        metadata['AcquisitionPlane'] = 'Unknown'

    return metadata


def _load_one_dicom_path(path: str, skip_pixel_data: bool) -> Dict[str, Any]:
    """
    Helper for parallel loading of a single DICOM file from a path.
    """
    dicom_values = load_dicom(path, skip_pixel_data=skip_pixel_data)
    dicom_values["DICOM_Path"] = path
    # If you want 'InstanceNumber' for path-based
    dicom_values["InstanceNumber"] = int(dicom_values["InstanceNumber"])
    return dicom_values


def _load_one_dicom_bytes(
    key: str, content: bytes, skip_pixel_data: bool
) -> Dict[str, Any]:
    """
    Helper for parallel loading of a single DICOM file from bytes.
    """
    dicom_values = load_dicom(content, skip_pixel_data=skip_pixel_data)
    dicom_values["DICOM_Path"] = key
    dicom_values["InstanceNumber"] = int(dicom_values["InstanceNumber"])
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
        shape = nifti_data.shape

        # Check if this is a 4D volume
        is_4d = len(shape) == 4 and shape[3] > 1
        num_volumes = shape[3] if is_4d else 1

        # Create a row for each 3D volume in the 4D data
        for vol_idx in range(num_volumes):
            nifti_values = {
                "NIfTI_Path": nifti_path,
                "NIfTI_Shape": shape,
                "NIfTI_Affine": nifti_data.affine,
                "NIfTI_Header": nifti_data.header,
            }

            # Add volume index for 4D data
            if is_4d:
                nifti_values["Volume_Index"] = vol_idx
                # Modify displayed path to show volume index
                display_path = nifti_path + f"[{vol_idx}]"
                nifti_values["NIfTI_Path_Display"] = display_path
            else:
                nifti_values["Volume_Index"] = None
                nifti_values["NIfTI_Path_Display"] = nifti_path

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

            session_data.append(nifti_values)

    session_df = pd.DataFrame(session_data)
    session_df = make_dataframe_hashable(session_df)

    if acquisition_fields:
        # Filter acquisition_fields to only include columns that exist in the DataFrame
        available_fields = [field for field in acquisition_fields if field in session_df.columns]

        # Only group if we have fields to group by
        if available_fields:
            session_df = session_df.groupby(available_fields).apply(
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
        skip_pixel_data (bool): Whether to skip pixel data elements (default: True).
        show_progress (bool): Whether to show a progress bar (using tqdm).
        parallel_workers (int): Number of threads for parallel reading (default 1 = no parallel).

    Returns:
        pd.DataFrame: A DataFrame containing metadata for all DICOM files in the session.

    Raises:
        ValueError: If neither `session_dir` nor `dicom_bytes` is provided, or if no DICOM data is found.
    """
    # Determine data source and worker function
    if dicom_bytes is not None:
        dicom_items = list(dicom_bytes.items())
        worker_func = lambda item: _load_one_dicom_bytes(item[0], item[1], skip_pixel_data)
        description = "Loading DICOM bytes"
    elif session_dir is not None:
        dicom_items = [
            os.path.join(root, file)
            for root, _, files in os.walk(session_dir)
            for file in files
        ]
        worker_func = lambda path: _load_one_dicom_path(path, skip_pixel_data)
        description = "Loading DICOM files"
    else:
        raise ValueError("Either session_dir or dicom_bytes must be provided.")

    # Process DICOM data using parallel utilities
    if parallel_workers > 1:
        session_data = await process_items_parallel(
            dicom_items,
            worker_func,
            parallel_workers,
            progress_function,
            show_progress,
            description
        )
    else:
        session_data = await process_items_sequential(
            dicom_items,
            worker_func,
            progress_function,
            show_progress,
            description
        )

    # Create and prepare session DataFrame
    return prepare_session_dataframe(session_data)


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


# Import the refactored function
from ..session import assign_acquisition_and_run_numbers
