"""
GE LxProtocol Parser with DICOM Mapping

Parses GE MRI LxProtocol files and extracts protocol information
in both raw and DICOM-compatible formats.

LxProtocol files are simple Tcl-like text files with 'set KEY "VALUE"' pairs,
used by GE scanners for protocol exchange.

This module follows the same pattern as the Siemens .pro and Philips ExamCard parsers.
"""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Union


def load_lxprotocol_file(lxprotocol_path: str) -> Dict[str, Any]:
    """
    Load and parse a GE LxProtocol file into DICOM-compatible format.

    Args:
        lxprotocol_path: Path to the LxProtocol file

    Returns:
        Dictionary with DICOM-compatible field names and values

    Raises:
        FileNotFoundError: If the specified file does not exist
        Exception: If the file cannot be parsed
    """
    path = Path(lxprotocol_path)
    if not path.exists():
        raise FileNotFoundError(f"LxProtocol file not found: {lxprotocol_path}")

    # Parse the LxProtocol
    raw_params = _parse_lxprotocol(lxprotocol_path)

    # Convert to DICOM-compatible format
    dicom_fields = apply_lxprotocol_to_dicom_mapping(raw_params)

    # Add source information
    dicom_fields["LxProtocol_Path"] = str(lxprotocol_path)
    dicom_fields["LxProtocol_FileName"] = path.name

    return dicom_fields


def load_lxprotocol_session(session_dir: str, show_progress: bool = False) -> "pd.DataFrame":
    """
    Load all LxProtocol files from a directory and return as a DataFrame.

    Args:
        session_dir: Directory containing LxProtocol files (searches recursively)
        show_progress: Whether to show progress bar

    Returns:
        pandas DataFrame with one row per scan/protocol
    """
    import pandas as pd

    session_path = Path(session_dir)
    if not session_path.exists():
        raise FileNotFoundError(f"Session directory not found: {session_dir}")

    # Find all LxProtocol files recursively
    lxprotocol_files = list(session_path.rglob("LxProtocol"))

    if not lxprotocol_files:
        raise ValueError(f"No LxProtocol files found in {session_dir}")

    all_rows = []

    for lxprotocol_file in lxprotocol_files:
        try:
            scan = load_lxprotocol_file(str(lxprotocol_file))
            # Try to extract scan name from parent directory
            scan["ScanName"] = lxprotocol_file.parent.name
            all_rows.append(scan)
        except Exception as e:
            print(f"Warning: Failed to parse {lxprotocol_file}: {e}")

    if not all_rows:
        raise ValueError("No valid scans found in LxProtocol files")

    return pd.DataFrame(all_rows)


def load_lxprotocol_file_schema_format(lxprotocol_path: str) -> List[Dict[str, Any]]:
    """
    Load and parse a GE LxProtocol file into schema-compatible format.

    Args:
        lxprotocol_path: Path to the LxProtocol file

    Returns:
        List with single dictionary in schema format:
        [
            {
                "acquisition_info": {...},
                "fields": [{"field": "...", "value": "..."}, ...],
                "series": [...]
            }
        ]
    """
    path = Path(lxprotocol_path)
    if not path.exists():
        raise FileNotFoundError(f"LxProtocol file not found: {lxprotocol_path}")

    raw_params = _parse_lxprotocol(lxprotocol_path)
    dicom_fields = apply_lxprotocol_to_dicom_mapping(raw_params)

    # Extract scan name from parent directory
    scan_name = path.parent.name

    # Build schema-compatible format
    schema_result = _convert_to_schema_format(dicom_fields, raw_params, scan_name, lxprotocol_path)

    return [schema_result]


# ============================================================================
# Parsing Functions
# ============================================================================

def _parse_lxprotocol(lxprotocol_path: str) -> Dict[str, Any]:
    """
    Parse an LxProtocol file and return raw parameters.

    Args:
        lxprotocol_path: Path to LxProtocol file

    Returns:
        Dictionary with raw parameter names and values
    """
    path = Path(lxprotocol_path)
    if not path.exists():
        raise FileNotFoundError(f"LxProtocol file not found: {lxprotocol_path}")

    params = {}

    # Pattern to match: set VARNAME "value" or set VARNAME "value with spaces"
    # Also handles values without quotes
    pattern = re.compile(r'^\s*set\s+(\w+)\s+"?([^"]*)"?\s*$')

    with open(lxprotocol_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            match = pattern.match(line)
            if match:
                key = match.group(1)
                value = match.group(2).strip()

                # Try to convert to appropriate type
                params[key] = _convert_value(value)

    return params


def _convert_value(value: str) -> Any:
    """
    Convert string value to appropriate Python type.

    Args:
        value: String value from LxProtocol

    Returns:
        Converted value (int, float, or str)
    """
    if not value:
        return value

    # Try integer first
    try:
        return int(value)
    except ValueError:
        pass

    # Try float
    try:
        return float(value)
    except ValueError:
        pass

    # Keep as string
    return value


# ============================================================================
# DICOM Mapping
# ============================================================================

# Mapping from GE LxProtocol parameter names to DICOM field names
GE_TO_DICOM_MAPPING = {
    # Timing parameters
    "TR": "RepetitionTime",
    "TE": "EchoTime",
    "TI": "InversionTime",
    "FLIPANG": "FlipAngle",
    "ETL": "EchoTrainLength",

    # Geometry - FOV handled specially (cm to mm conversion)
    "SLTHICK": "SliceThickness",
    "MATRIXX": "Columns",
    "MATRIXY": "Rows",
    "NOSLC": "NumberOfSlices",

    # Averaging
    "NEX": "NumberOfAverages",

    # Bandwidth
    "RBW": "PixelBandwidth",

    # Parallel imaging
    "PHASEACCEL": "ParallelReductionFactorInPlane",
    "SLICEACCEL": "MultibandFactor",

    # Coil
    "COIL": "ReceiveCoilName",
    "CLINICALCOIL": "ReceiveCoilName",
    "COILCOMPONENT": "CoilString",

    # Sequence info
    "PSEQ": "SequenceName",
    "IOPT": "ScanOptions",

    # Diffusion
    "NUMBVALUE": "NumberOfDiffusionBValues",
}

# Parameters that need special handling
GE_PLANE_MAPPING = {
    "SAGITTAL": "SAGITTAL",
    "AXIAL": "AXIAL",
    "CORONAL": "CORONAL",
    "OBLIQUE": "OBLIQUE",
}

GE_IMODE_MAPPING = {
    "2D": "2D",
    "3D": "3D",
    "3DE": "3D",  # 3D Enhanced
}

# Field ordering for output - matches DEFAULT_DICOM_FIELDS order
DICOM_FIELD_ORDER = [
    # Core Identifiers
    'SeriesDescription',
    'ProtocolName',
    'SequenceName',
    'SequenceVariant',
    'ScanningSequence',
    'ImageType',
    'Manufacturer',
    'ManufacturerModelName',
    'SoftwareVersion',

    # Geometry
    'MRAcquisitionType',
    'SliceThickness',
    'PixelSpacing',
    'Rows',
    'Columns',
    'NumberOfSlices',
    'AcquisitionMatrix',
    'ReconstructionDiameter',
    'FieldOfView',
    'ImagePlaneOrientation',
    'PatientPosition',

    # Timing / Contrast
    'RepetitionTime',
    'EchoTime',
    'InversionTime',
    'FlipAngle',
    'EchoTrainLength',
    'GradientEchoTrainLength',
    'NumberOfTemporalPositions',
    'AcquisitionDuration',

    # Diffusion-specific
    'DiffusionDirectionality',
    'DiffusionBValue',
    'NumberOfDiffusionDirections',
    'NumberOfDiffusionBValues',

    # Parallel Imaging / Multiband
    'ParallelAcquisition',
    'ParallelAcquisitionTechnique',
    'ParallelReductionFactorInPlane',
    'MultibandFactor',
    'PartialFourier',

    # Bandwidth / Readout
    'PixelBandwidth',
    'SpectralWidth',

    # Phase encoding
    'InPlanePhaseEncodingDirection',
    'NumberOfPhaseEncodingSteps',
    'PercentPhaseFieldOfView',
    'PhaseEncodingDirection',

    # Scanner hardware
    'MagneticFieldStrength',
    'ImagingFrequency',
    'ImagedNucleus',
    'TransmitCoilName',
    'ReceiveCoilName',
    'CoilString',
    'NumberOfAverages',
    'PatientWeight',

    # Scan options
    'ScanOptions',
    'ContrastBolusAgent',

    # Advanced / niche
    'FlowCompensation',
    'MagnetizationTransfer',
    'InversionRecovery',
    'CardiacSynchronizationTechnique',
]


# GE-specific parameters to keep (no direct DICOM equivalent)
USEFUL_GE_PARAMETERS = {
    "SWAPPF",           # Phase/Frequency swap direction
    "AUTOSHIM",         # Auto shimming mode
    "RFDRIVEMODE",      # RF drive mode (Single/Dual)
    "EXCITATIONMODE",   # Excitation mode (Selective/Non-selective)
    "VIEWORDER",        # View ordering
    "SLICEORDER",       # Slice ordering
    "FILTCHOICE",       # Filter choice
    "TAG_TYPE",         # Tagging type (for ASL/tagging sequences)
    "TEMPORALPHASES",   # Number of temporal phases
}


def apply_lxprotocol_to_dicom_mapping(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert GE LxProtocol parameters to DICOM-compatible field names.

    Args:
        params: Dictionary of raw LxProtocol parameters

    Returns:
        Dictionary with DICOM-compatible field names and values
    """
    dicom_fields = {}

    # GE-specific manufacturer
    dicom_fields["Manufacturer"] = "GE"

    # Map direct parameters
    for ge_name, value in params.items():
        if value is None or value == "":
            continue

        # Check if we have a direct mapping
        if ge_name in GE_TO_DICOM_MAPPING:
            dicom_name = GE_TO_DICOM_MAPPING[ge_name]

            # Handle special cases
            if ge_name == "TE" and value == "Minimum":
                # Skip "Minimum" - actual value will be in DICOM
                continue

            dicom_fields[dicom_name] = value

        elif ge_name in USEFUL_GE_PARAMETERS:
            # Keep useful GE-specific parameters
            dicom_fields[f"GE_{ge_name}"] = value

    # Handle special mappings
    _calculate_derived_fields(dicom_fields, params)

    # Sort fields in standard order
    return _sort_output_fields(dicom_fields)


def _calculate_derived_fields(dicom_fields: Dict[str, Any], params: Dict[str, Any]):
    """
    Calculate derived DICOM fields from raw parameters.

    Args:
        dicom_fields: Dictionary to update with derived fields
        params: Raw GE parameters
    """
    # Image plane orientation
    plane = params.get("PLANE")
    if plane and plane in GE_PLANE_MAPPING:
        dicom_fields["ImagePlaneOrientation"] = GE_PLANE_MAPPING[plane]

    # MR Acquisition Type (2D/3D)
    imode = params.get("IMODE")
    if imode and imode in GE_IMODE_MAPPING:
        dicom_fields["MRAcquisitionType"] = GE_IMODE_MAPPING[imode]

    # Field of View - GE uses cm, DICOM uses mm
    fov = params.get("FOV")
    if fov is not None:
        try:
            fov_mm = float(fov) * 10  # Convert cm to mm
            dicom_fields["FieldOfView"] = fov_mm
        except (ValueError, TypeError):
            pass

    # PercentPhaseFieldOfView - GE stores as decimal (0.80 = 80%)
    phasefov = params.get("PHASEFOV")
    if phasefov is not None:
        try:
            percent = float(phasefov) * 100
            dicom_fields["PercentPhaseFieldOfView"] = percent
        except (ValueError, TypeError):
            pass

    # Calculate PixelSpacing from FOV and matrix
    fov = params.get("FOV")
    matrixx = params.get("MATRIXX")
    matrixy = params.get("MATRIXY")
    if fov is not None and matrixx is not None and matrixy is not None:
        try:
            fov_mm = float(fov) * 10  # cm to mm
            # Assuming square pixels for now - actual may differ with PHASEFOV
            phasefov_factor = float(params.get("PHASEFOV", 1.0))
            row_spacing = fov_mm / float(matrixy)
            col_spacing = (fov_mm * phasefov_factor) / float(matrixx)
            dicom_fields["PixelSpacing"] = [round(row_spacing, 6), round(col_spacing, 6)]
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # Parallel acquisition detection from IOPT
    iopt = params.get("IOPT", "")
    if isinstance(iopt, str):
        iopt_upper = iopt.upper()
        if "ASSET" in iopt_upper or "ARC" in iopt_upper:
            dicom_fields["ParallelAcquisition"] = "YES"
            if "ASSET" in iopt_upper:
                dicom_fields["ParallelAcquisitionTechnique"] = "ASSET"
            elif "ARC" in iopt_upper:
                dicom_fields["ParallelAcquisitionTechnique"] = "ARC"
        else:
            dicom_fields["ParallelAcquisition"] = "NO"

    # Contrast agent
    contrast = params.get("CONTRAST")
    if contrast and contrast.upper() != "NO":
        dicom_fields["ContrastBolusAgent"] = contrast

    # Phase encoding direction from SWAPPF
    swappf = params.get("SWAPPF")
    if swappf:
        dicom_fields["PhaseEncodingDirection"] = swappf

    # Parse diffusion b-values if present
    multibvalue = params.get("MULTIBVALUE")
    if multibvalue and isinstance(multibvalue, str):
        # Format is "1000.0;" or "0;500;1000;"
        try:
            bvals = [float(b) for b in multibvalue.rstrip(";").split(";") if b]
            if len(bvals) == 1:
                dicom_fields["DiffusionBValue"] = bvals[0]
            elif len(bvals) > 1:
                dicom_fields["DiffusionBValue"] = bvals
        except ValueError:
            pass

    # Determine ScanningSequence from PSEQ
    pseq = params.get("PSEQ", "")
    if pseq:
        scanning_seq = _map_ge_sequence(pseq)
        if scanning_seq:
            dicom_fields["ScanningSequence"] = scanning_seq


def _map_ge_sequence(pseq: str) -> Optional[str]:
    """
    Map GE pulse sequence name to DICOM ScanningSequence.

    Args:
        pseq: GE pulse sequence name (e.g., SPGR, Cube, EPI)

    Returns:
        DICOM ScanningSequence value or None
    """
    pseq_upper = pseq.upper()

    # Gradient echo sequences
    if pseq_upper in ["SPGR", "FSPGR", "BRAVO", "LAVA", "SWAN", "MERGE"]:
        return "GR"

    # Spin echo sequences
    if pseq_upper in ["SE", "FSE", "FRFSE", "CUBE", "PROPELLER"]:
        return "SE"

    # Inversion recovery
    if pseq_upper in ["IR", "FLAIR", "STIR", "BRAVO"]:
        return "IR"

    # Echo planar
    if pseq_upper in ["EPI", "DIFF", "DWI"]:
        return "EP"

    return None


def _sort_output_fields(dicom_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sort output fields in standard DICOM order.

    Standard DICOM fields are ordered according to DICOM_FIELD_ORDER,
    followed by any other DICOM fields alphabetically,
    then GE-specific fields alphabetically at the end.

    Args:
        dicom_fields: Dictionary of field names to values

    Returns:
        Ordered dictionary with fields in standard order
    """
    # Create order index for known fields
    order_index = {field: i for i, field in enumerate(DICOM_FIELD_ORDER)}

    # Separate fields into categories
    ordered_dicom = []      # Fields in DICOM_FIELD_ORDER
    other_dicom = []        # Other DICOM fields (not GE_)
    ge_fields = []          # GE_ prefixed fields

    for key in dicom_fields.keys():
        if key.startswith('GE_'):
            ge_fields.append(key)
        elif key in order_index:
            ordered_dicom.append(key)
        else:
            other_dicom.append(key)

    # Sort each category
    ordered_dicom.sort(key=lambda k: order_index[k])
    other_dicom.sort()
    ge_fields.sort()

    # Build ordered result
    result = {}
    for key in ordered_dicom + other_dicom + ge_fields:
        result[key] = dicom_fields[key]

    return result


def _convert_to_schema_format(dicom_fields: Dict[str, Any], raw_params: Dict[str, Any],
                              scan_name: str, lxprotocol_path: str) -> Dict[str, Any]:
    """
    Convert DICOM fields to schema-compatible format.

    Args:
        dicom_fields: DICOM-compatible field dictionary
        raw_params: Raw LxProtocol parameters
        scan_name: Name of the scan
        lxprotocol_path: Path to source LxProtocol file

    Returns:
        Schema-compatible dictionary
    """
    # Build acquisition-level fields
    acquisition_fields = []

    for field_name, value in dicom_fields.items():
        # Skip metadata fields
        if field_name in ["LxProtocol_Path", "LxProtocol_FileName", "ScanName"]:
            continue
        if value is None or value == "":
            continue

        acquisition_fields.append({
            "field": field_name,
            "value": value
        })

    return {
        "acquisition_info": {
            "protocol_name": scan_name,
            "source_type": "lxprotocol",
            "lxprotocol_path": str(lxprotocol_path),
            "lxprotocol_filename": Path(lxprotocol_path).name
        },
        "fields": acquisition_fields,
        "series": []
    }
