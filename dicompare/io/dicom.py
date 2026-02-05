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

from ..utils import safe_convert_value
from ..config import NONZERO_FIELDS
from ..processing.parallel_utils import process_items_parallel, process_items_sequential
from ..data_utils import make_dataframe_hashable, _process_dicom_metadata, prepare_session_dataframe

# --- IMPORT FOR CSA header parsing ---
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    from nibabel.nicom.csareader import get_csa_header

pydicom.config.debug(False)

def _extract_inferred_metadata(ds: pydicom.Dataset) -> Dict[str, Any]:
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

def _extract_csa_metadata(ds: pydicom.Dataset) -> Dict[str, Any]:
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

    # Phase encoding polarity (0 = negative/reversed, 1 = positive/normal)
    csa_metadata["PhaseEncodingDirectionPositive"] = get_csa_value("PhaseEncodingDirectionPositive")

    # ASL-specific CSA fields (Siemens)
    # These are extracted from research/product ASL sequences
    csa_metadata["PostLabelDelay"] = get_csa_value("PostLabelDelay")
    csa_metadata["BolusDuration"] = get_csa_value("BolusDuration")
    csa_metadata["LabelOffset"] = get_csa_value("LabelOffset")
    csa_metadata["NumRFBlocks"] = get_csa_value("NumRFBlocks")
    csa_metadata["RFGap"] = get_csa_value("RFGap")
    csa_metadata["MeanGzx10"] = get_csa_value("MeanGzx10")
    csa_metadata["PhiAdjust"] = get_csa_value("PhiAdjust")
    csa_metadata["T1"] = get_csa_value("T1")  # Blood T1 assumption

    # Vessel-encoded PCASL parameters
    csa_metadata["TagDuration"] = get_csa_value("TagDuration")
    csa_metadata["TagRFFlipAngle"] = get_csa_value("TagRFFlipAngle")
    csa_metadata["TagRFDuration"] = get_csa_value("TagRFDuration")
    csa_metadata["TagRFSeparation"] = get_csa_value("TagRFSeparation")
    csa_metadata["MeanTagGradient"] = get_csa_value("MeanTagGradient")
    csa_metadata["TagGradientAmplitude"] = get_csa_value("TagGradientAmplitude")
    csa_metadata["MaximumT1Opt"] = get_csa_value("MaximumT1Opt")
    csa_metadata["InitialPostLabelDelay"] = get_csa_value("InitialPostLabelDelay", scalar=False)
    csa_metadata["TagPlaneDThickness"] = get_csa_value("TagPlaneDThickness")

    return csa_metadata


def _extract_ascconv(ds: pydicom.Dataset) -> Dict[str, Any]:
    """
    Extract and parse the ASCCONV protocol section from Siemens DICOM CSA series header.

    The ASCCONV section contains detailed MRI protocol parameters that are not available
    in standard DICOM tags or the structured CSA header fields. This includes parameters
    like ucCoilCombineMode, detailed k-space settings, and sequence-specific options.

    Supports both Siemens V-series (VB/VD/VE using tag 0029,1020) and XA-series
    (using tag 0021,1019) scanners.

    Args:
        ds (pydicom.Dataset): The DICOM dataset.

    Returns:
        Dict[str, Any]: A dictionary of parsed ASCCONV parameters with their native types
                        (int, float, str). Returns empty dict if ASCCONV not found.

    Example:
        >>> ds = pydicom.dcmread("siemens_scan.dcm")
        >>> ascconv = extract_ascconv(ds)
        >>> print(ascconv.get('ucCoilCombineMode'))  # e.g., 1
        >>> print(ascconv.get('tProtocolName'))  # e.g., 'T1_MPRAGE'
    """
    import logging
    logger = logging.getLogger(__name__)

    # import twixtools for parsing
    from twixtools.twixprot import parse_buffer

    # Siemens CSA series header locations:
    # V-series (VB, VD, VE): (0029, 1020)
    # XA-series: (0021, 1019)
    csa_tags = [
        (0x0029, 0x1020),  # V-series CSA Series Header
        (0x0021, 0x1019),  # XA-series CSA Header
    ]

    raw_csa_data = None
    for tag in csa_tags:
        if tag in ds:
            raw_csa_data = ds[tag].value
            if isinstance(raw_csa_data, bytes) and len(raw_csa_data) > 0:
                logger.debug(f"Found CSA series header at tag {tag}")
                break
            raw_csa_data = None

    if raw_csa_data is None:
        logger.debug("No CSA series header found for ASCCONV extraction")
        return {}

    # Find ASCCONV section boundaries
    start_marker = b'### ASCCONV BEGIN'
    end_marker = b'### ASCCONV END ###'

    start_idx = raw_csa_data.find(start_marker)
    end_idx = raw_csa_data.find(end_marker)

    if start_idx == -1 or end_idx == -1:
        logger.debug("ASCCONV section not found in CSA header")
        return {}

    # Extract and decode the ASCCONV text (include end marker for complete section)
    ascconv_bytes = raw_csa_data[start_idx:end_idx + len(end_marker)]
    ascconv_text = ascconv_bytes.decode('latin-1', errors='ignore')

    # Parse using twixtools
    try:
        parsed = parse_buffer(ascconv_text)
        logger.debug(f"Successfully parsed ASCCONV with {len(parsed)} parameters")
        return parsed
    except Exception as e:
        logger.warning(f"Failed to parse ASCCONV section: {e}")
        return {}


def _get_ascconv_value(ascconv: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Get a value from parsed ASCCONV data with support for nested paths and arrays.

    Supports dot-notation for nested access (e.g., 'sPat.lAccelFactPE') and
    automatically collects array elements when the key points to a list.

    Args:
        ascconv: Parsed ASCCONV dictionary from extract_ascconv()
        key: Parameter name or dot-notation path to look up
        default: Value to return if key not found

    Returns:
        The parameter value, a list of values for arrays, or the default

    Example:
        >>> ascconv = extract_ascconv(ds)
        >>> get_ascconv_value(ascconv, 'ucCoilCombineMode')  # Returns int
        >>> get_ascconv_value(ascconv, 'alTR')  # Returns list of TR values
        >>> get_ascconv_value(ascconv, 'sPat.lAccelFactPE')  # Nested access
    """
    # Handle dot-notation paths for nested dictionaries
    if '.' in key:
        keys = key.split('.')
        current = ascconv
        for k in keys:
            if current is None:
                return default
            # Handle array indices like "0", "1" in path
            if k.isdigit():
                index = int(k)
                if isinstance(current, list) and index < len(current):
                    current = current[index]
                else:
                    return default
            elif isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        return current if current is not None else default

    # Direct lookup for non-nested keys
    if key in ascconv:
        return ascconv[key]

    return default


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


def _extract_shared_functional_groups(shared_seq) -> Dict[str, Any]:
    """
    Extract metadata from SharedFunctionalGroupsSequence.

    This includes coil information from MRReceiveCoilSequence which is needed
    to determine CoilType (Combined vs Uncombined) for Enhanced DICOM files.

    Args:
        shared_seq: The first item of SharedFunctionalGroupsSequence

    Returns:
        Dictionary with extracted metadata including coil element count
    """
    result = {}

    # Extract MRReceiveCoilSequence for coil information
    if hasattr(shared_seq, 'MRReceiveCoilSequence') and shared_seq.MRReceiveCoilSequence:
        coil_seq = shared_seq.MRReceiveCoilSequence[0]

        # Get ReceiveCoilName
        if hasattr(coil_seq, 'ReceiveCoilName'):
            result['ReceiveCoilName'] = str(coil_seq.ReceiveCoilName)

        # Get ReceiveCoilType (MULTICOIL, SINGLE, etc.)
        if hasattr(coil_seq, 'ReceiveCoilType'):
            result['ReceiveCoilType'] = str(coil_seq.ReceiveCoilType)

        # Count coil elements from MultiCoilDefinitionSequence
        # This is the key for determining Combined vs Uncombined:
        # - Multiple elements = Combined (coil data has been combined)
        # - Single element = Uncombined (individual coil element data)
        if hasattr(coil_seq, 'MultiCoilDefinitionSequence'):
            num_elements = len(coil_seq.MultiCoilDefinitionSequence)
            result['MultiCoilElementCount'] = num_elements

            # Also extract element names for reference
            element_names = []
            for elem in coil_seq.MultiCoilDefinitionSequence:
                if hasattr(elem, 'MultiCoilElementName'):
                    element_names.append(str(elem.MultiCoilElementName))
            if element_names:
                result['MultiCoilElementNames'] = element_names

    # Extract MRTransmitCoilSequence if present
    if hasattr(shared_seq, 'MRTransmitCoilSequence') and shared_seq.MRTransmitCoilSequence:
        tx_coil_seq = shared_seq.MRTransmitCoilSequence[0]
        if hasattr(tx_coil_seq, 'TransmitCoilName'):
            result['TransmitCoilName'] = str(tx_coil_seq.TransmitCoilName)

    return result


def _process_enhanced_dicom(ds, skip_pixel_data=True):
    """
    Process enhanced DICOM files with PerFrameFunctionalGroupsSequence.
    Also extracts SharedFunctionalGroupsSequence for common metadata like coil info.
    """
    common = {}
    for element in ds:
        if element.keyword == "PerFrameFunctionalGroupsSequence":
            continue
        if element.keyword == "SharedFunctionalGroupsSequence":
            continue  # Process separately below
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

    # Process SharedFunctionalGroupsSequence for common metadata
    if hasattr(ds, 'SharedFunctionalGroupsSequence') and ds.SharedFunctionalGroupsSequence:
        shared_data = _extract_shared_functional_groups(ds.SharedFunctionalGroupsSequence[0])
        common.update(shared_data)

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




def _update_metadata(metadata: Union[Dict[str, Any], List[Dict[str, Any]]],
                     update_dict: Dict[str, Any]) -> None:
    """
    Helper to update metadata whether it's a dict or list of dicts.

    Args:
        metadata: Either a single dict or list of dicts
        update_dict: Dictionary of values to merge in
    """
    if isinstance(metadata, list):
        for item in metadata:
            item.update(update_dict)
    else:
        metadata.update(update_dict)


def _get_metadata_value(metadata: Union[Dict[str, Any], List[Dict[str, Any]]],
                        key: str,
                        default: Any = None) -> Any:
    """
    Helper to get a value from metadata whether it's a dict or list of dicts.
    For lists, returns the first non-None value found.

    Args:
        metadata: Either a single dict or list of dicts
        key: The key to look up
        default: Default value if key not found

    Returns:
        The value associated with the key, or default if not found
    """
    if isinstance(metadata, list):
        for item in metadata:
            if key in item and item[key] is not None:
                return item[key]
        return default
    else:
        return metadata.get(key, default)


def _set_metadata_value(metadata: Union[Dict[str, Any], List[Dict[str, Any]]],
                        key: str,
                        value: Any) -> None:
    """
    Helper to set a value in metadata whether it's a dict or list of dicts.

    Args:
        metadata: Either a single dict or list of dicts
        key: The key to set
        value: The value to set
    """
    if isinstance(metadata, list):
        for item in metadata:
            item[key] = value
    else:
        metadata[key] = value


def _key_in_metadata(metadata: Union[Dict[str, Any], List[Dict[str, Any]]],
                     key: str) -> bool:
    """
    Helper to check if a key exists in metadata whether it's a dict or list of dicts.

    Args:
        metadata: Either a single dict or list of dicts
        key: The key to check

    Returns:
        True if key exists in metadata (or any item in list), False otherwise
    """
    if isinstance(metadata, list):
        return any(key in item for item in metadata)
    else:
        return key in metadata


def load_dicom(
    dicom_file: Union[str, bytes], skip_pixel_data: bool = True
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Load a DICOM file and extract its metadata as a dictionary or list of dictionaries.

    Args:
        dicom_file (Union[str, bytes]): Path to the DICOM file or file content in bytes.
        skip_pixel_data (bool): Whether to skip the pixel data element (default: True).

    Returns:
        Union[Dict[str, Any], List[Dict[str, Any]]]:
            - For regular DICOM: A dictionary of DICOM metadata
            - For enhanced DICOM: A list of dictionaries (one per frame)

    Raises:
        FileNotFoundError: If the specified DICOM file path does not exist.
        pydicom.errors.InvalidDicomError: If the file is not a valid DICOM file.
    """
    # Log a warning if CSA metadata is not a dict
    import logging
    logger = logging.getLogger(__name__)

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

    # Convert to plain metadata dict (flattened) or list of dicts for enhanced DICOM
    metadata = get_dicom_values(ds_raw, skip_pixel_data=skip_pixel_data)

    # Only extract CSA metadata for Siemens DICOM files
    manufacturer = getattr(ds_raw, 'Manufacturer', '').upper()
    if 'SIEMENS' in manufacturer:
        csa_metadata = _extract_csa_metadata(ds_raw)
        if isinstance(csa_metadata, dict) and csa_metadata:
            _update_metadata(metadata, csa_metadata)
        elif csa_metadata and not isinstance(csa_metadata, dict):
            logger.warning(f"Unexpected format of CSA metadata extracted from Siemens DICOM file {dicom_file}")

    inferred_metadata = _extract_inferred_metadata(ds_raw)
    if not inferred_metadata:
        logger.debug(f"No inferred metadata extracted from DICOM file {dicom_file}")
    elif isinstance(inferred_metadata, dict):
        _update_metadata(metadata, inferred_metadata)
    else:
        logger.warning(f"Unexpected format of inferred metadata extracted from DICOM file {dicom_file}")

    # Add CoilType as a regular metadata field
    # Combined = multiple coil elements combined (e.g., HC1-6, HEA;HEP)
    # Uncombined = individual coil element (e.g., H1, H15, A32)
    #
    # Two methods to determine CoilType:
    # 1. Classic DICOM: Siemens private tag (0051,100F) with coil element string
    # 2. Enhanced DICOM: _MultiCoilElementCount from MRReceiveCoilSequence
    coil_field = "(0051,100F)"
    coil_value = _get_metadata_value(metadata, coil_field)

    def is_combined_coil_from_string(value):
        """Check if the coil value string indicates combined coil data.

        Combined indicators:
        - Range notation with hyphen between numbers (e.g., HC1-6, 1-32)
        - Semicolon notation (e.g., HEA;HEP)
        - No numbers at all (e.g., HEA, HEP)
        """
        if pd.isna(value) or value is None or value == "":
            return None  # Unknown
        val_str = str(value)

        # Semicolon indicates combined coil groups
        if ';' in val_str:
            return True

        # Check for range notation (hyphen between numbers, e.g., 1-6 in HC1-6)
        # Pattern: digit(s) followed by hyphen followed by digit(s)
        if re.search(r'\d+-\d+', val_str):
            return True

        # No numbers at all = combined
        if not any(char.isdigit() for char in val_str):
            return True

        # Has number but no range/semicolon = single coil element = uncombined
        return False

    def is_combined_coil_from_element_count(count):
        """Check if coil is combined based on MultiCoilElementCount.

        For Enhanced DICOM, the _MultiCoilElementCount field indicates
        how many coil elements were used:
        - Multiple elements (>1) = Combined (data from multiple coils combined)
        - Single element (1) = Uncombined (individual coil element data)
        """
        if count is None:
            return None
        try:
            count_int = int(count)
            if count_int > 1:
                return True  # Combined
            elif count_int == 1:
                return False  # Uncombined
            return None  # Unknown (0 or invalid)
        except (ValueError, TypeError):
            return None

    # Try classic DICOM method first (private tag)
    coil_combined = is_combined_coil_from_string(coil_value)

    # If classic method didn't work, try Enhanced DICOM method
    # Note: Key is 'MultiCoilElementCount' (not '_MultiCoilElementCount') after key reduction
    if coil_combined is None:
        multi_coil_count = _get_metadata_value(metadata, 'MultiCoilElementCount')
        coil_combined = is_combined_coil_from_element_count(multi_coil_count)

    if coil_combined is True:
        _set_metadata_value(metadata, "CoilType", "Combined")
    elif coil_combined is False:
        _set_metadata_value(metadata, "CoilType", "Uncombined")

    # Add GE ImageType mapping based on private tag (0043,102F)
    ge_private_tag = "(0043,102F)"
    if _key_in_metadata(metadata, ge_private_tag):
        ge_value = _get_metadata_value(metadata, ge_private_tag)
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
        if _key_in_metadata(metadata, 'ImageType'):
            current_type = _get_metadata_value(metadata, 'ImageType')
            if isinstance(current_type, (list, tuple)):
                new_image_type = list(current_type) + [mapped_type]
            else:
                new_image_type = [current_type, mapped_type]
            _set_metadata_value(metadata, 'ImageType', new_image_type)
        else:
            _set_metadata_value(metadata, 'ImageType', [mapped_type])

    # Extract Siemens XA PhaseEncodingDirectionPositive from private tag (0021,111C)
    # This is used for enhanced DICOM (Siemens XA series) where CSA header is not available
    siemens_xa_pe_tag = "(0021,111C)"
    if _key_in_metadata(metadata, siemens_xa_pe_tag):
        siemens_xa_pe_value = _get_metadata_value(metadata, siemens_xa_pe_tag)
        if siemens_xa_pe_value is not None:
            try:
                # Value is 0 (negative/reversed) or 1 (positive/normal)
                pe_positive = int(siemens_xa_pe_value)
                # Only set if not already set from CSA header
                if not _key_in_metadata(metadata, 'PhaseEncodingDirectionPositive'):
                    _set_metadata_value(metadata, 'PhaseEncodingDirectionPositive', pe_positive)
            except (ValueError, TypeError):
                logger.debug(f"Could not parse Siemens XA PhaseEncodingDirectionPositive: {siemens_xa_pe_value}")

    # Extract additional Siemens-specific fields from ASCCONV protocol section
    # Only for Siemens scanners where ASCCONV is available
    if 'SIEMENS' in manufacturer:
        ascconv = _extract_ascconv(ds_raw)
        if ascconv:
            # CoilCombinationMethod from ucCoilCombineMode
            coil_combine_mode = _get_ascconv_value(ascconv, 'ucCoilCombineMode')
            if coil_combine_mode is not None:
                # Map Siemens ucCoilCombineMode values to human-readable strings
                coil_combine_method_map = {
                    1: 'Sum of Squares',
                    2: 'Adaptive Combine',
                }
                method_name = coil_combine_method_map.get(coil_combine_mode, f'Unknown ({coil_combine_mode})')
                _set_metadata_value(metadata, 'CoilCombinationMethod', method_name)

            # AccelerationFactorPE from sPat.lAccelFactPE (GRAPPA/SENSE acceleration factor)
            accel_factor_pe = _get_ascconv_value(ascconv, 'sPat.lAccelFactPE')
            if accel_factor_pe is not None and accel_factor_pe > 1:
                _set_metadata_value(metadata, 'AccelerationFactorPE', accel_factor_pe)

            # --- Siemens ASL parameter extraction from ASCCONV ---
            # Check ASL mode: 1 = pCASL (2D), 2 = PASL, 4 = pCASL (3D)
            asl_mode = _get_ascconv_value(ascconv, 'sAsl.ulMode')

            # Detect vessel-encoded (Oxford) ASL sequences via tSequenceFileName
            # Oxford sequences use alFree array with different indices than product sequences
            # Note: VEPCASL sequences may report sAsl.ulMode=2 but are actually pCASL
            # Reference: dcm2niix source - checks for "VEPCASL" in sequence filename
            sequence_filename = _get_ascconv_value(ascconv, 'tSequenceFileName') or ''
            is_vessel_encoded = 'VEPCASL' in sequence_filename.upper()

            # Also detect sequence type from sequence name as fallback
            # Mode values can be unreliable (e.g., tgse_pasl reports mode 4 like pCASL 3D)
            seq_name_lower = sequence_filename.lower()
            is_pasl_by_name = '_pasl' in seq_name_lower or 'pasl_' in seq_name_lower

            # Store sequence filename for debugging/reference
            if sequence_filename:
                _set_metadata_value(metadata, 'PulseSequenceDetails', sequence_filename)

            if is_vessel_encoded:
                # Oxford/vessel-encoded pCASL: Parameters in sWipMemBlock.alFree array
                # Reference: dcm2niix source code (nii_dicom_batch.cpp)
                # 2D and 3D sequences use different array indices:
                # - to_ep2d_VEPCASL (2D): alFree[4-6] for params, alFree[11-30] for PLDs
                # - jw_tgse_VEPCASL (3D): alFree[6-9] for params, alFree[30-37] for PLDs
                # Reference: https://github.com/neurolabusc/dcm_qa_asl
                is_3d_vepcasl = 'jw_tgse' in seq_name_lower or 'tgse_vepcasl' in seq_name_lower

                alFree = _get_ascconv_value(ascconv, 'sWipMemBlock.alFree')
                if alFree and isinstance(alFree, list):
                    if is_3d_vepcasl:
                        # 3D jw_tgse_VEPCASL indices (from dcm2niix)
                        idx_flip = 6
                        idx_duration = 7
                        idx_separation = 8
                        idx_t1opt = 9
                        pld_start = 30
                        pld_end = 38
                    else:
                        # 2D to_ep2d_VEPCASL indices (from dcm2niix)
                        idx_flip = 4
                        idx_duration = 5
                        idx_separation = 6
                        idx_t1opt = 10
                        pld_start = 11
                        pld_end = 31

                    # TagRFFlipAngle (degrees)
                    if len(alFree) > idx_flip and alFree[idx_flip] and alFree[idx_flip] != []:
                        try:
                            _set_metadata_value(metadata, 'TagRFFlipAngle', float(alFree[idx_flip]))
                        except (ValueError, TypeError):
                            pass
                    # TagRFDuration in µs -> seconds
                    if len(alFree) > idx_duration and alFree[idx_duration] and alFree[idx_duration] != []:
                        try:
                            _set_metadata_value(metadata, 'TagRFDuration', float(alFree[idx_duration]) / 1_000_000)
                        except (ValueError, TypeError):
                            pass
                    # TagRFSeparation in µs -> seconds
                    if len(alFree) > idx_separation and alFree[idx_separation] and alFree[idx_separation] != []:
                        try:
                            _set_metadata_value(metadata, 'TagRFSeparation', float(alFree[idx_separation]) / 1_000_000)
                        except (ValueError, TypeError):
                            pass
                    # MaximumT1Opt in ms -> seconds
                    if len(alFree) > idx_t1opt and alFree[idx_t1opt] and alFree[idx_t1opt] != []:
                        try:
                            _set_metadata_value(metadata, 'MaximumT1Opt', float(alFree[idx_t1opt]) / 1000)
                        except (ValueError, TypeError):
                            pass
                    # Extract full PLD array as InitialPostLabelDelay (ms -> seconds)
                    pld_array = []
                    for i in range(pld_start, min(pld_end, len(alFree))):
                        if alFree[i] and alFree[i] != [] and alFree[i] != 0:
                            try:
                                pld_array.append(float(alFree[i]) / 1000)
                            except (ValueError, TypeError):
                                pass
                    if pld_array:
                        _set_metadata_value(metadata, 'InitialPostLabelDelay', pld_array)

                # Set ASL type - vessel-encoded is always PCASL
                _set_metadata_value(metadata, 'ArterialSpinLabelingType', 'PCASL')

            elif (asl_mode == 1 or asl_mode == 4) and not is_pasl_by_name:
                # Product pCASL: Parameters stored in sWipMemBlock.adFree array
                # Reference: dcm2niix source code
                # Note: Skip if sequence name indicates PASL (mode values can be unreliable)
                adFree = _get_ascconv_value(ascconv, 'sWipMemBlock.adFree')
                if adFree and isinstance(adFree, list):
                    # adFree[1] = LabelOffset in mm
                    if len(adFree) > 1 and adFree[1] and adFree[1] != []:
                        try:
                            _set_metadata_value(metadata, 'LabelOffset', float(adFree[1]))
                        except (ValueError, TypeError):
                            pass
                    # adFree[2] = PostLabelDelay in µs
                    if len(adFree) > 2 and adFree[2] and adFree[2] != []:
                        try:
                            pld_us = float(adFree[2])
                            _set_metadata_value(metadata, 'PostLabelDelay', pld_us / 1_000_000)
                        except (ValueError, TypeError):
                            pass
                    # Note: Product sequences don't expose LabelingDuration in WIP memory
                    # The value in adFree[12] for mode 4 appears to be T1 (blood T1), not LabelingDuration

                # Set ASL type
                _set_metadata_value(metadata, 'ArterialSpinLabelingType', 'PCASL')

            elif asl_mode == 2 or is_pasl_by_name:
                # PASL: Parameters stored in alTI array
                alTI = _get_ascconv_value(ascconv, 'alTI')
                if alTI and isinstance(alTI, list):
                    # alTI[0] = BolusDuration in µs
                    if len(alTI) > 0 and alTI[0] and alTI[0] != []:
                        try:
                            bolus_us = float(alTI[0])
                            _set_metadata_value(metadata, 'BolusDuration', bolus_us / 1_000_000)
                        except (ValueError, TypeError):
                            pass
                    # alTI[2] = InversionTime (TI) in µs
                    if len(alTI) > 2 and alTI[2] and alTI[2] != []:
                        try:
                            ti_us = float(alTI[2])
                            _set_metadata_value(metadata, 'InversionTime', ti_us / 1_000_000)
                        except (ValueError, TypeError):
                            pass

                # Set ASL type
                _set_metadata_value(metadata, 'ArterialSpinLabelingType', 'PASL')

            # Extract lRepetitions from ASCCONV and map to NumberOfTemporalPositions
            # lRepetitions is 0-indexed, so actual volumes = lRepetitions + 1
            # This provides the same information as the standard DICOM NumberOfTemporalPositions field
            l_repetitions = _get_ascconv_value(ascconv, 'lRepetitions')
            if l_repetitions is not None and not _key_in_metadata(metadata, 'NumberOfTemporalPositions'):
                try:
                    # lRepetitions = 17 means 18 volumes (0 through 17)
                    num_volumes = int(l_repetitions) + 1
                    _set_metadata_value(metadata, 'NumberOfTemporalPositions', num_volumes)
                except (ValueError, TypeError):
                    pass

    # --- ASL-specific metadata extraction ---
    # Infer ArterialSpinLabelingType from available parameters and ImageType
    image_type = _get_metadata_value(metadata, 'ImageType')
    image_type_str = ''
    if image_type:
        if isinstance(image_type, (list, tuple)):
            image_type_str = ' '.join(str(t) for t in image_type).upper()
        else:
            image_type_str = str(image_type).upper()

    is_asl_scan = 'ASL' in image_type_str or 'PERFUSION' in image_type_str

    # Philips ASL: Extract TriggerDelayTime as PostLabelDelay
    if 'PHILIPS' in manufacturer:
        # Philips stores PLD in TriggerDelayTime (in ms) for multi-phase ASL
        trigger_delay = _get_metadata_value(metadata, 'TriggerDelayTime')
        if trigger_delay is not None and not _key_in_metadata(metadata, 'PostLabelDelay'):
            try:
                # Convert from ms to seconds for consistency with Siemens
                pld_seconds = float(trigger_delay) / 1000.0
                _set_metadata_value(metadata, 'PostLabelDelay', pld_seconds)
            except (ValueError, TypeError):
                pass

    # Infer ASL labeling type if not already set
    if not _key_in_metadata(metadata, 'ArterialSpinLabelingType') or _get_metadata_value(metadata, 'ArterialSpinLabelingType') is None:
        asl_type = None

        # Check for PCASL indicators
        has_pcasl_params = (
            _get_metadata_value(metadata, 'PostLabelDelay') is not None or
            _get_metadata_value(metadata, 'TagDuration') is not None or
            _get_metadata_value(metadata, 'NumRFBlocks') is not None or
            _get_metadata_value(metadata, 'RFGap') is not None
        )

        # Check for PASL indicators
        has_pasl_params = (
            _get_metadata_value(metadata, 'BolusDuration') is not None and
            _get_metadata_value(metadata, 'InversionTime') is not None
        )

        # Check sequence name / protocol name for hints
        seq_name = str(_get_metadata_value(metadata, 'SequenceName', '')).lower()
        protocol_name = str(_get_metadata_value(metadata, 'ProtocolName', '')).lower()
        series_desc = str(_get_metadata_value(metadata, 'SeriesDescription', '')).lower()
        pulse_seq = str(_get_metadata_value(metadata, 'PulseSequenceDetails', '')).lower()

        name_str = f"{seq_name} {protocol_name} {series_desc} {pulse_seq}"

        if 'pcasl' in name_str or 'pseudo' in name_str:
            asl_type = 'PCASL'
        elif 'pasl' in name_str or 'ep2d_pasl' in name_str:
            asl_type = 'PASL'
        elif 'casl' in name_str:
            asl_type = 'CASL'
        elif has_pcasl_params and is_asl_scan:
            asl_type = 'PCASL'
        elif has_pasl_params and is_asl_scan:
            asl_type = 'PASL'

        if asl_type:
            _set_metadata_value(metadata, 'ArterialSpinLabelingType', asl_type)

    # Compute LabelingDuration for PCASL if we have the components
    # LabelingDuration = NumRFBlocks * (RFGap + TagRFDuration) or use TagDuration directly
    if not _key_in_metadata(metadata, 'LabelingDuration') or _get_metadata_value(metadata, 'LabelingDuration') is None:
        tag_duration = _get_metadata_value(metadata, 'TagDuration')
        if tag_duration is not None:
            _set_metadata_value(metadata, 'LabelingDuration', tag_duration)
        else:
            # Try to compute from NumRFBlocks and RFGap
            num_rf_blocks = _get_metadata_value(metadata, 'NumRFBlocks')
            rf_gap = _get_metadata_value(metadata, 'RFGap')
            if num_rf_blocks is not None and rf_gap is not None:
                try:
                    # Approximate labeling duration (RF gap dominates)
                    labeling_duration = float(num_rf_blocks) * float(rf_gap)
                    _set_metadata_value(metadata, 'LabelingDuration', labeling_duration)
                except (ValueError, TypeError):
                    pass

    # For PASL, BolusDuration is the labeling duration equivalent
    if _get_metadata_value(metadata, 'ArterialSpinLabelingType') == 'PASL':
        bolus_duration = _get_metadata_value(metadata, 'BolusDuration')
        if bolus_duration is not None and not _key_in_metadata(metadata, 'LabelingDuration'):
            _set_metadata_value(metadata, 'LabelingDuration', bolus_duration)

    # Add AcquisitionPlane based on ImageOrientationPatient
    if _key_in_metadata(metadata, 'ImageOrientationPatient'):
        iop = _get_metadata_value(metadata, 'ImageOrientationPatient')
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
                    _set_metadata_value(metadata, 'AcquisitionPlane', 'sagittal')
                elif max_component == 1:  # Y-axis dominant
                    _set_metadata_value(metadata, 'AcquisitionPlane', 'coronal')
                else:  # Z-axis dominant (max_component == 2)
                    _set_metadata_value(metadata, 'AcquisitionPlane', 'axial')

            else:
                _set_metadata_value(metadata, 'AcquisitionPlane', 'Unknown')
        except (ValueError, TypeError, IndexError):
            # If calculation fails, mark as unknown
            _set_metadata_value(metadata, 'AcquisitionPlane', 'Unknown')

    return metadata


def _load_one_dicom_path(path: str, skip_pixel_data: bool) -> Dict[str, Any]:
    """
    Helper for parallel loading of a single DICOM file from a path.
    """
    # First, load the raw DICOM to check if it's a valid image
    ds_raw = pydicom.dcmread(path, stop_before_pixels=skip_pixel_data, defer_size=True, force=True)

    # Validate that this is a real DICOM image by checking for required Modality field
    if not hasattr(ds_raw, 'Modality') or ds_raw.Modality is None:
        raise ValueError(f"File lacks required Modality field - likely not a valid DICOM image: {path}")

    dicom_values = load_dicom(path, skip_pixel_data=skip_pixel_data)

    if isinstance(dicom_values, list):
        for item in dicom_values:
            item["DICOM_Path"] = path
            # If you want 'InstanceNumber' for path-based
            item["InstanceNumber"] = int(item["InstanceNumber"])
    else:
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
    # First, load the raw DICOM to check if it's a valid image
    ds_raw = pydicom.dcmread(
        BytesIO(content),
        stop_before_pixels=skip_pixel_data,
        defer_size=len(content),
        force=True
    )

    # Validate that this is a real DICOM image by checking for required Modality field
    if not hasattr(ds_raw, 'Modality') or ds_raw.Modality is None:
        raise ValueError(f"File lacks required Modality field - likely not a valid DICOM image: {key}")

    dicom_values = load_dicom(content, skip_pixel_data=skip_pixel_data)

    if isinstance(dicom_values, list):
        for item in dicom_values:
            item["DICOM_Path"] = key
            item["InstanceNumber"] = int(item["InstanceNumber"])
    else:
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

    # Flatten session_data in case of enhanced DICOM files
    # (which return lists of dicts instead of single dicts)
    flattened_data = []
    for item in session_data:
        if isinstance(item, list):
            flattened_data.extend(item)
        else:
            flattened_data.append(item)

    # Create and prepare session DataFrame
    return prepare_session_dataframe(flattened_data)


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
