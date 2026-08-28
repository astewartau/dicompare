"""
Siemens .pro Protocol File Parser with DICOM Mapping

Uses twixtools to parse Siemens MRI protocol files (.pro) and extract
comprehensive protocol information in both raw and DICOM-compatible formats.

This module is based on the parse_siemens_pro.py script and integrates
.pro file parsing into the dicompare package.



"""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union, List
from twixtools.twixprot import parse_buffer
import itertools

from ..fields import decode as _decode_field, validate_fields as _validate_fields
from .protocol_common import generate_series_combinations


from .pro_derived import (
    calculate_other_dicom_fields,
    extract_nested_value,
    # Decoders used by PRO_TO_DICOM_MAPPING (and re-exported for
    # backwards compatibility).
    _decode_siemens_version,
    _decode_partial_fourier,
    _nominal_field_strength,
    _extract_unique_b_values,
    _decode_sequence_type,
    _physio_signal_method,
    _detect_scan_options,
    _detect_image_type,
    _detect_sequence_variant,
)

def load_pro_file(pro_file_path: str) -> Dict[str, Any]:
    """
    Load and parse a Siemens .pro protocol file into DICOM-compatible format.
    
    Args:
        pro_file_path: Path to the .pro protocol file
        
    Returns:
        Dictionary with DICOM-compatible field names and values
        
    Raises:
        FileNotFoundError: If the specified .pro file path does not exist
        Exception: If the file cannot be parsed
    """
    pro_path = Path(pro_file_path)
    if not pro_path.exists():
        raise FileNotFoundError(f"Protocol file not found: {pro_file_path}")
    
    # Parse the protocol file
    with open(pro_path, 'r', encoding='latin1') as f:
        content = f.read()
    
    try:
        parsed_data = parse_buffer(content)
    except Exception as e:
        raise Exception(f"Failed to parse .pro file {pro_file_path}: {str(e)}")
    
    # Convert to DICOM-compatible format
    dicom_fields = apply_pro_to_dicom_mapping(parsed_data)
    
    # Add source information
    dicom_fields["PRO_Path"] = str(pro_file_path)
    dicom_fields["PRO_FileName"] = pro_path.name
    
    return dicom_fields


def load_pro_file_schema_format(pro_file_path: str) -> Dict[str, Any]:
    """
    Load and parse a Siemens .pro protocol file into schema-compatible format.
    
    This function generates the series structure that would be created during
    DICOM reconstruction, including all permutations of varying parameters
    (echo times, image types, inversion times).
    
    Args:
        pro_file_path: Path to the .pro protocol file
        
    Returns:
        Dictionary in schema format:
        {
            "acquisition_info": {...},
            "fields": [{"field": "...", "value": "..."}, ...],
            "series": [
                {
                    "name": "Series 1",
                    "fields": [{"field": "EchoTime", "value": 2.5}, ...]
                },
                ...
            ]
        }
        
    Raises:
        FileNotFoundError: If the specified .pro file path does not exist
        Exception: If the file cannot be parsed
    """
    pro_path = Path(pro_file_path)
    if not pro_path.exists():
        raise FileNotFoundError(f"Protocol file not found: {pro_file_path}")
    
    # Parse the protocol file using existing logic
    with open(pro_path, 'r', encoding='latin1') as f:
        content = f.read()
    
    try:
        parsed_data = parse_buffer(content)
    except Exception as e:
        raise Exception(f"Failed to parse .pro file {pro_file_path}: {str(e)}")
    
    # Get flat DICOM-compatible data using existing function
    flat_dicom_data = apply_pro_to_dicom_mapping(parsed_data)
    calculate_other_dicom_fields(flat_dicom_data, parsed_data)
    
    # Generate schema-compatible format
    schema_result = _convert_flat_to_schema_format(flat_dicom_data, parsed_data, pro_file_path)
    
    return schema_result


def _convert_flat_to_schema_format(dicom_data: Dict[str, Any], raw_pro_data: Dict[str, Any], pro_file_path: str) -> Dict[str, Any]:
    """
    Convert flat DICOM data to schema-compatible format with series structure.
    
    Args:
        dicom_data: Flat DICOM-compatible dictionary from apply_pro_to_dicom_mapping
        raw_pro_data: Raw .pro data from twixtools
        pro_file_path: Path to source .pro file
        
    Returns:
        Schema-compatible dictionary with acquisition_info, fields, and series
    """
    # Extract series-determining parameters
    series_params = _extract_series_parameters(dicom_data, raw_pro_data)
    
    # Generate series combinations
    series_list = _generate_series_combinations(series_params)
    
    # Classify fields as acquisition-level or series-level
    acquisition_fields, series_varying_fields = _classify_fields(dicom_data, series_params)
    
    # Build result structure
    result = {
        "acquisition_info": {
            "protocol_name": dicom_data.get("ProtocolName", "Unknown"),
            "source_type": "pro_file",
            "pro_path": str(pro_file_path),
            "pro_filename": Path(pro_file_path).name
        },
        "fields": acquisition_fields,
        "series": series_list
    }
    
    return result


def _extract_series_parameters(dicom_data: Dict[str, Any], raw_pro_data: Dict[str, Any]) -> Dict[str, List]:
    """
    Extract parameters that create series variations.
    
    Returns dictionary with series-creating parameter arrays:
    {
        "EchoTime": [2.5, 5.0, 7.5, ...],
        "ImageType": [["ORIGINAL", "PRIMARY", "M"], ...],
        "InversionTime": [0.9, 2.75, ...]
    }
    """
    series_params = {}
    
    # 1. Echo Times (primary series differentiator)
    echo_times = dicom_data.get("EchoTime", [])
    if isinstance(echo_times, list) and len(echo_times) > 1:
        series_params["EchoTime"] = echo_times
    elif isinstance(echo_times, (int, float)):
        # Single echo time - only include if other parameters will create series
        pass  # We'll add this back later if needed
    
    # 2. Image Types (based on reconstruction mode)
    recon_mode = extract_nested_value(raw_pro_data, "ucReconstructionMode") or 1
    image_types = _determine_image_types_for_series(recon_mode, dicom_data)
    # Only include ImageType in series if there are multiple variants (i.e., mag+phase)
    if len(image_types) > 1:
        series_params["ImageType"] = image_types
    # If only one image type, it will stay at acquisition level
    
    # 3. Inversion Times (for sequences like MP2RAGE)
    inversion_times = dicom_data.get("InversionTime", [])
    if isinstance(inversion_times, list) and len(inversion_times) > 1:
        series_params["InversionTime"] = inversion_times
    elif isinstance(inversion_times, (int, float)):
        # Single inversion time - only include if other parameters will create series
        pass  # We'll add this back later if needed
    
    # Now add back single values if we have series-creating parameters
    if series_params:  # If we have any series-creating parameters
        # Add single echo time back if present
        if isinstance(echo_times, (int, float)):
            series_params["EchoTime"] = [echo_times]
        elif isinstance(echo_times, list) and len(echo_times) == 1:
            series_params["EchoTime"] = echo_times
            
        # DON'T add single image types - they should stay at acquisition level
        # Only add ImageType if there are multiple variants (already handled above)
            
        # DON'T add single inversion times - they should stay at acquisition level
        # Only add inversion times if they vary (already handled above)
    
    return series_params


def _determine_image_types_for_series(recon_mode: int, dicom_data: Dict[str, Any]) -> List[List[str]]:
    """
    Determine image type variations based on reconstruction mode.
    
    Args:
        recon_mode: ucReconstructionMode from .pro file
        dicom_data: DICOM-compatible data
        
    Returns:
        List of ImageType arrays that will be created
    """
    base_image_type = dicom_data.get("ImageType") or ["ORIGINAL", "PRIMARY", "M"]
    
    if recon_mode == 8:
        # Magnitude + Phase reconstruction
        mag_type = [item if item != "P" else "M" for item in base_image_type]
        phase_type = [item if item != "M" else "P" for item in base_image_type]
        if "M" not in mag_type:
            mag_type.append("M")
        if "P" not in phase_type:
            phase_type.append("P")
        return [mag_type, phase_type]
    
    elif recon_mode == 2:
        # Phase only
        phase_type = [item if item != "M" else "P" for item in base_image_type]
        if "P" not in phase_type:
            phase_type.append("P")
        return [phase_type]
    
    else:
        # Magnitude only (mode 1, 4, etc.)
        mag_type = [item if item != "P" else "M" for item in base_image_type]
        if "M" not in mag_type:
            mag_type.append("M")
        return [mag_type]


def _generate_series_combinations(series_params: Dict[str, List]) -> List[Dict[str, Any]]:
    """Generate all series combinations using cartesian product of parameters."""
    return generate_series_combinations(
        series_params, priority=("EchoTime", "ImageType", "InversionTime"))


def _classify_fields(dicom_data: Dict[str, Any], series_params: Dict[str, List]) -> tuple:
    """
    Classify fields as acquisition-level vs series-level.
    
    Args:
        dicom_data: Flat DICOM-compatible data
        series_params: Parameters that vary at series level
        
    Returns:
        Tuple of (acquisition_fields, series_varying_fields)
    """
    acquisition_fields = []
    series_varying_fields = set(series_params.keys())
    
    for field_name, value in dicom_data.items():
        # Skip metadata fields
        if field_name in ["PRO_Path", "PRO_FileName"]:
            continue
            
        # Skip series-varying fields (they go in series)
        if field_name in series_varying_fields:
            continue
        
        # Skip empty string values (like empty SeriesDescription)
        if value == "":
            continue
            
        # Skip None values
        if value is None:
            continue
        
        # Add to acquisition level
        acquisition_fields.append({
            "field": field_name,
            "value": value
        })
    
    return acquisition_fields, series_varying_fields



PRO_TO_DICOM_MAPPING = {
    # Core Identifiers
    # Note: twixtools may parse protocol name as either tProtocolName or ProtocolName
    # depending on the file format, so we accept both
    "tProtocolName": "ProtocolName",
    "ProtocolName": "ProtocolName",  # Direct passthrough for formats that use this key
    "tSequenceFileName": "SequenceName",
    "SeriesDescription": "SeriesDescription",
    
    # Manufacturer info - ManufacturerModelName removed (only contains internal code "142")
    
    # Basic timing parameters (convert from microseconds)
    "alTR": ("RepetitionTime", lambda x: ([t/1000.0 for t in x] if len(x) > 1 else x[0]/1000.0) if isinstance(x, list) else x/1000.0),  # μs → ms
    # alTI mapping removed - handled specially in calculate_other_dicom_fields to respect IR sequences only  
    # alTE mapping removed - handled specially in calculate_other_dicom_fields to respect lContrasts
    
    # Averaging
    "lAverages": "NumberOfAverages",
    
    # Matrix dimensions (corrected - .pro files use different names than MATLAB examples)
    "sKSpace.lBaseResolution": "Rows",             # Base resolution = readout direction = DICOM Rows
    "sKSpace.lPhaseEncodingLines": "Columns",      # Phase encoding lines = DICOM Columns
    # NumberOfTemporalPositions is derived from lRepetitions in calculate_other_dicom_fields.
    # lImagesPerSlab is a *spatial* (3D partition) count, NOT a temporal one - mapping it here
    # produced spurious NumberOfTemporalPositions/TemporalResolution for static 3D scans.
    
    # RF parameters
    "adFlipAngleDegree.0": "FlipAngle",
    
    # Parallel imaging
    "sPat.lAccelFactPE": "ParallelReductionFactorInPlane",
    "sPat.lAccelFact3D": "SliceAccelerationFactor",
    # ucPATMode is the IDEA PATSelMode enum (1 none, 2 GRAPPA, 4 mSENSE); the
    # registry maps 1 -> None so unaccelerated scans drop the field like real
    # DICOM does. (Previously 1 was mislabelled "SENSE".)
    "sPat.ucPATMode": ("ParallelAcquisitionTechnique",
        lambda x: _decode_field("ParallelAcquisitionTechnique", "siemens.pro.ucPATMode", x)),
    "sSliceAcceleration.lMultiBandFactor": "MultibandFactor",
    
    # Bandwidth - PixelBandwidth calculated separately with proper formula
    # BandwidthPerPixelPhaseEncode calculated separately from dwell time and phase encoding steps
    
    # Phase encoding direction (canonical ROW/COL vocabulary from the registry)
    "sSpecPara.lPhaseEncodingType": ("InPlanePhaseEncodingDirection",
        lambda x: _decode_field("InPlanePhaseEncodingDirection",
                                "siemens.pro.lPhaseEncodingType", x) if x in (1, 2) else "COL"),
    
    # Scanner hardware - only real DICOM fields
    "sProtConsistencyInfo.flNominalB0": ("MagneticFieldStrength", lambda x: _nominal_field_strength(x)),
    "sTXSPEC.asNucleusInfo.0.tNucleus": "ImagedNucleus",
    "ulVersion": ("SoftwareVersion", lambda x: _decode_siemens_version(x)),
    
    # Coil information
    "sCoilSelectMeas.aRxCoilSelectData.0.asList.0.sCoilElementID.tCoilID": "ReceiveCoilName",
    "sCoilSelectMeas.aTxCoilSelectData.0.asList.0.sCoilElementID.tCoilID": "TransmitCoilName",
    
    # Timing
    "lScanTimeSec": ("AcquisitionDuration", lambda x: x * 1000.0),  # Convert seconds to milliseconds
    
    # Institution and study information
    "sProtConsistencyInfo.tInstitution": "InstitutionName",
    "sStudyArray.asElm.0.tStudyDescription": "StudyDescription",
    
    # Sequence options and flags
    # TimeOfFlightContrast is derived in calculate_other_dicom_fields: ucTOFInflow reads 4
    # (its default) on virtually every protocol, so the raw value cannot indicate TOF.
    "sAngio.ucPCFlowMode": ("AngioFlag", lambda x: "Y" if x > 2 else "N"),

    # Triggering/Gating is derived in calculate_other_dicom_fields, gated on the physio
    # signal/method selectors. The per-sensor lTriggerPulses fields default to 1 on every
    # protocol, so they cannot be used to detect whether gating is actually enabled.

    # Diffusion parameters
    "sDiffusion.alBValue": ("DiffusionBValue", lambda x: _extract_unique_b_values(x) if x else None),
}



def apply_pro_to_dicom_mapping(pro_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert .pro data to DICOM-compatible format using the mapping.
    
    Args:
        pro_data: Raw .pro data dictionary
        
    Returns:
        Dictionary with DICOM-compatible field names and values
    """
    dicom_data = {}
    
    for pro_field, dicom_mapping in PRO_TO_DICOM_MAPPING.items():
        # Handle simple string mapping vs tuple with converter function
        if isinstance(dicom_mapping, tuple):
            dicom_field, converter = dicom_mapping
        else:
            dicom_field = dicom_mapping
            converter = None
            
        # Extract value using path notation
        value = extract_nested_value(pro_data, pro_field)
        
        if value is not None:
            # Apply converter function if provided. A converter returning None
            # means "this code carries no information" (e.g. ucPATMode 1 = PAT
            # off, where real DICOM omits the field) — drop it.
            if converter is not None:
                value = converter(value)
            if value is not None:
                dicom_data[dicom_field] = value
    
    # Add default or calculated DICOM fields that are not directly mappable
    calculate_other_dicom_fields(dicom_data, pro_data)

    # Registry boundary check: flag raw vendor codes / display strings that
    # slipped through the mapping (logged; import still succeeds).
    _validate_fields(dicom_data, context="pro import")

    return dicom_data



# --------------------------------------------------------------------------
# Session loading functions for .pro files
# --------------------------------------------------------------------------

import os
import glob
import pandas as pd
from typing import Optional, List, Callable
from ..data_utils import make_dataframe_hashable


def _load_one_pro_file(pro_path: str) -> Dict[str, Any]:
    """
    Helper function for loading a single .pro file.

    Args:
        pro_path: Path to the .pro file

    Returns:
        Dictionary with DICOM-compatible field names and values
    """
    pro_data = load_pro_file(pro_path)

    # Use ProtocolName as the equivalent of "Acquisition"
    protocol_name = pro_data.get("ProtocolName", "Unknown")
    pro_data["Acquisition"] = protocol_name

    return pro_data


def load_pro_session_simple(
    session_dir: Optional[str] = None,
    pro_files: Optional[List[str]] = None,
    pattern: str = "*.pro",
    show_progress: bool = False,
    progress_function: Optional[Callable[[int], None]] = None,
) -> pd.DataFrame:
    """
    Load and process all .pro files in a session directory or from a list of file paths.

    Args:
        session_dir: Path to a directory containing .pro files
        pro_files: List of specific .pro file paths to load
        pattern: Glob pattern for finding .pro files (default: "*.pro")
        show_progress: Whether to show a progress bar (ignored for simple loading)
        progress_function: Optional callback function for progress updates

    Returns:
        pd.DataFrame: A DataFrame containing metadata for all .pro files in the session

    Raises:
        ValueError: If neither session_dir nor pro_files is provided, or if no .pro files are found
    """
    # Determine data source
    if pro_files is not None:
        pro_items = pro_files
    elif session_dir is not None:
        pro_items = glob.glob(os.path.join(session_dir, "**", pattern), recursive=True)
    else:
        raise ValueError("Either session_dir or pro_files must be provided.")

    if not pro_items:
        raise ValueError(f"No .pro files found in the specified location.")

    # Process .pro files sequentially (simple approach)
    session_data = []
    total_files = len(pro_items)

    for idx, pro_path in enumerate(pro_items):
        try:
            pro_data = _load_one_pro_file(pro_path)
            session_data.append(pro_data)
        except Exception as e:
            print(f"Warning: Failed to load {pro_path}: {e}")
            continue

        # Update progress if callback provided
        if progress_function:
            progress = int((idx + 1) / total_files * 100)
            progress_function(progress)

    # Create DataFrame
    if not session_data:
        raise ValueError("No valid .pro files could be loaded.")

    session_df = pd.DataFrame(session_data)

    # Apply standard dataframe processing
    session_df = make_dataframe_hashable(session_df)

    return session_df


def load_pro_session(
    session_dir: Optional[str] = None,
    pro_files: Optional[List[str]] = None,
    pattern: str = "*.pro",
    show_progress: bool = False,
    progress_function: Optional[Callable[[int], None]] = None,
) -> pd.DataFrame:
    """
    Load and process all .pro files in a session directory or from a list of file paths.

    Args:
        session_dir: Path to a directory containing .pro files
        pro_files: List of specific .pro file paths to load
        pattern: Glob pattern for finding .pro files (default: "*.pro")
        show_progress: Whether to show a progress bar (ignored for simple loading)
        progress_function: Optional callback function for progress updates

    Returns:
        pd.DataFrame: A DataFrame containing metadata for all .pro files in the session

    Raises:
        ValueError: If neither session_dir nor pro_files is provided, or if no .pro files are found
    """
    return load_pro_session_simple(
        session_dir=session_dir,
        pro_files=pro_files,
        pattern=pattern,
        show_progress=show_progress,
        progress_function=progress_function,
    )


# ---------------------------------------------------------------------------
# Backwards-compatible re-exports. The .exar1 parser moved to io/exar.py and
# the derived-field engine to io/pro_derived.py; the names below remain
# importable from this module. (The exar import must stay at the bottom of the
# file: exar.py imports from this module, so it can only be imported once the
# names above exist.)
# ---------------------------------------------------------------------------
from .exar import (  # noqa: E402
    load_exar_file,
    load_exar_file_schema_format,
    load_exar_session,
    _decompress_raw_deflate,
    _extract_protocol_text_from_xprotocol,
    _describe_exar_contents,
    _extract_protocols_from_exar,
    _load_one_exar_protocol,
)
