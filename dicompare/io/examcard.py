"""
Philips ExamCard Parser with DICOM Mapping

Parses Philips MRI ExamCard files (.ExamCard) and extracts protocol information
in both raw and DICOM-compatible formats.

ExamCard files are SOAP-XML formatted files that contain embedded binary
parameter data in base64 encoding.

This module follows the same pattern as the Siemens .pro parser.
"""

import base64
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Tuple, Union

if TYPE_CHECKING:
    import pandas
import itertools


def load_examcard_file(examcard_path: str) -> Dict[str, Any]:
    """
    Load and parse a Philips ExamCard file into DICOM-compatible format.

    Args:
        examcard_path: Path to the .ExamCard file

    Returns:
        Dictionary with DICOM-compatible field names and values

    Raises:
        FileNotFoundError: If the specified file does not exist
        Exception: If the file cannot be parsed
    """
    path = Path(examcard_path)
    if not path.exists():
        raise FileNotFoundError(f"ExamCard file not found: {examcard_path}")

    # Parse the ExamCard
    examcard_data = _parse_examcard(examcard_path)

    # Convert to DICOM-compatible format
    dicom_fields = apply_examcard_to_dicom_mapping(examcard_data)

    # Add source information
    dicom_fields["ExamCard_Path"] = str(examcard_path)
    dicom_fields["ExamCard_FileName"] = path.name

    return dicom_fields


def load_examcard_session(session_dir: str, show_progress: bool = False) -> "pandas.DataFrame":
    """
    Load all ExamCard files from a directory and return as a DataFrame.

    Args:
        session_dir: Directory containing .ExamCard files
        show_progress: Whether to show progress bar

    Returns:
        pandas DataFrame with one row per scan/protocol
    """
    import pandas as pd

    session_path = Path(session_dir)
    if not session_path.exists():
        raise FileNotFoundError(f"Session directory not found: {session_dir}")

    examcard_files = list(session_path.glob("*.ExamCard")) + list(session_path.glob("*.examcard"))

    if not examcard_files:
        raise ValueError(f"No ExamCard files found in {session_dir}")

    all_rows = []

    for examcard_file in examcard_files:
        try:
            scans = load_examcard_file_all_scans(str(examcard_file))
            for scan in scans:
                all_rows.append(scan)
        except Exception as e:
            print(f"Warning: Failed to parse {examcard_file}: {e}")

    if not all_rows:
        raise ValueError("No valid scans found in ExamCard files")

    return pd.DataFrame(all_rows)


def load_examcard_file_all_scans(examcard_path: str) -> List[Dict[str, Any]]:
    """
    Load all scans from an ExamCard file.

    Args:
        examcard_path: Path to the .ExamCard file

    Returns:
        List of dictionaries, one per scan, with DICOM-compatible fields
    """
    path = Path(examcard_path)
    if not path.exists():
        raise FileNotFoundError(f"ExamCard file not found: {examcard_path}")

    # Parse the ExamCard to get all scans
    all_scans = _parse_examcard_all_scans(examcard_path)

    result = []
    for scan_name, scan_data in all_scans.items():
        if scan_name == "General":
            continue

        dicom_fields = apply_examcard_to_dicom_mapping(scan_data)
        dicom_fields["ExamCard_Path"] = str(examcard_path)
        dicom_fields["ExamCard_FileName"] = path.name
        dicom_fields["ScanName"] = scan_name
        result.append(dicom_fields)

    return result


def load_examcard_file_schema_format(examcard_path: str) -> List[Dict[str, Any]]:
    """
    Load and parse a Philips ExamCard file into schema-compatible format.

    This function generates the acquisition structure for each scan in the ExamCard,
    similar to the Siemens .pro schema format.

    Args:
        examcard_path: Path to the .ExamCard file

    Returns:
        List of dictionaries in schema format, one per scan:
        [
            {
                "acquisition_info": {...},
                "fields": [{"field": "...", "value": "..."}, ...],
                "series": [...]
            },
            ...
        ]
    """
    path = Path(examcard_path)
    if not path.exists():
        raise FileNotFoundError(f"ExamCard file not found: {examcard_path}")

    all_scans = _parse_examcard_all_scans(examcard_path)

    results = []
    for scan_name, scan_data in all_scans.items():
        if scan_name == "General":
            continue

        dicom_fields = apply_examcard_to_dicom_mapping(scan_data)

        # Generate schema-compatible format
        schema_result = _convert_to_schema_format(dicom_fields, scan_data, scan_name, examcard_path)
        results.append(schema_result)

    return results


# ============================================================================
# XML Parsing Functions
# ============================================================================

def _clean_tag(tag: str) -> str:
    """Remove XML namespace prefix from tag."""
    if '}' in tag:
        return tag.split('}')[-1]
    return tag


def _get_attrib_value(node, key: str) -> Optional[str]:
    """Get attribute value, handling namespaced attributes."""
    for attr in node.attrib:
        if key in attr:
            return node.attrib[attr]
    return None


def _get_nodes_by_tag(root, tag_name: str) -> List:
    """Find all nodes with given tag name (ignoring namespace)."""
    result = []
    for elem in root.iter():
        if _clean_tag(elem.tag) == tag_name:
            result.append(elem)
    return result


def _get_node_by_attrib_value(root, key: str, val: str):
    """Find node with attribute matching key=val."""
    for elem in root.iter():
        for attr in elem.attrib:
            if key in attr and elem.attrib[attr] == val:
                return elem
    return None


def _get_child_by_tag(parent, child_tag: str):
    """Get direct child with given tag."""
    for child in parent:
        if _clean_tag(child.tag) == child_tag:
            return child
    return None


def _get_child_thru_ref(root, parent, child_tag: str):
    """Get child element through href reference."""
    child = _get_child_by_tag(parent, child_tag)
    if child is None:
        return None

    href = _get_attrib_value(child, 'href')
    if href and href.startswith('#'):
        ref_id = href[1:]
        return _get_node_by_attrib_value(root, 'id', ref_id)
    return child


def _get_child_name(node) -> str:
    """Get the 'name' child element text."""
    name_elem = _get_child_by_tag(node, 'name')
    if name_elem is not None and name_elem.text:
        return name_elem.text.strip()
    return ""


def _get_item_content(item) -> Dict[str, Any]:
    """Extract text content from child elements."""
    out = {}
    for child in item:
        if child.text:
            key = _clean_tag(child.tag)
            out[key] = child.text.strip()
    return out


def _get_info_for_node(node, root) -> Dict[str, Any]:
    """Extract information from a node, following href references."""
    out = {}
    for child in node:
        key = _clean_tag(child.tag)
        if child.text:
            out[key] = child.text.strip()
        else:
            href = _get_attrib_value(child, 'href')
            if href and href.startswith('#'):
                ref_id = href[1:]
                ref_node = _get_node_by_attrib_value(root, 'id', ref_id)
                if ref_node is not None:
                    value = _get_item_content(ref_node)
                    if value:
                        out[key] = value
    return out


# ============================================================================
# Binary Parameter Parsing
# ============================================================================

def _get_param_value(typ: int, num: int, off1: int, off2: int, data: bytes) -> Tuple[Any, Optional[Tuple[str, List[str]]]]:
    """
    Extract parameter value from binary data.

    Args:
        typ: Parameter type (0=float, 1=int, 2=string, 4=enum)
        num: Number of values
        off1: Offset for enum description
        off2: Offset for actual value data
        data: Full binary data buffer

    Returns:
        Tuple of (value, enum_description)
    """
    values = []
    enum_desc = None

    try:
        if typ == 0:  # float
            for k in range(num):
                b = data[off2 + k*4 : off2 + (k+1)*4]
                if len(b) == 4:
                    flt = struct.unpack('<f', b)[0]
                    values.append(flt)

        elif typ == 1:  # int
            for k in range(num):
                b = data[off2 + k*4 : off2 + (k+1)*4]
                if len(b) == 4:
                    intval = struct.unpack('<i', b)[0]
                    values.append(intval)

        elif typ == 2:  # string
            for k in range(num):
                b = data[off2 + k*81 : off2 + (k+1)*81]
                null_pos = b.find(b'\x00')
                if null_pos >= 0:
                    b = b[:null_pos]
                s = b.decode('utf-8', errors='ignore')
                if s:
                    values.append(s)

        elif typ == 4:  # enum
            # Get enum description string
            null_pos = data.find(b'\x00', off1)
            if null_pos > off1:
                enum_str = data[off1:null_pos].decode('utf-8', errors='ignore')
                enum_list = enum_str.split(',')
                enum_desc = (enum_str, enum_list)

            # Get enum index value
            b = data[off2 : off2 + 4]
            if len(b) == 4:
                idx = struct.unpack('<i', b)[0]
                values.append(idx)

    except Exception:
        pass

    # Return single value if only one
    if len(values) == 1:
        return values[0], enum_desc
    elif len(values) == 0:
        return None, enum_desc
    return values, enum_desc


def _get_a_param(data: bytes, i: int) -> Tuple[Optional[str], Any, Optional[Tuple]]:
    """
    Extract one parameter from binary data.

    Args:
        data: Base64-decoded binary parameter data
        i: Parameter index

    Returns:
        Tuple of (name, value, enum_description)
    """
    pos0 = 32  # Initial offset
    param_size = 50  # Each parameter entry is 50 bytes

    start = pos0 + i * param_size
    end = start + param_size

    if end > len(data):
        return None, None, None

    param_block = data[start:end]

    # Extract name (first 33 bytes, null-terminated)
    name_bytes = param_block[0:33]
    null_pos = name_bytes.find(b'\x00')
    if null_pos >= 0:
        name_bytes = name_bytes[:null_pos]

    name = name_bytes.decode('utf-8', errors='ignore')

    # Validate name format (should be EX_, GEX_, IF_, etc.)
    if len(name) < 5:
        return None, None, None
    if name[2] != '_' and name[3] != '_':
        return None, None, None

    # Extract type (bytes 34-37)
    typ = int.from_bytes(param_block[34:38], byteorder='little', signed=False)
    if typ > 4:
        return None, None, None

    # Extract count (bytes 38-41)
    num = int.from_bytes(param_block[38:42], byteorder='little', signed=False)

    # Extract offset1 (bytes 42-45, relative to current position)
    off1_rel = int.from_bytes(param_block[42:46], byteorder='little', signed=False)
    off1 = off1_rel + start + 42

    # Extract offset2 (bytes 46-49, relative to current position)
    off2_rel = int.from_bytes(param_block[46:50], byteorder='little', signed=False)
    off2 = off2_rel + start + 46

    # Get the actual value
    value, enum_desc = _get_param_value(typ, num, off1, off2, data)

    return name, value, enum_desc


def _parse_parameter_data(node) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    """
    Parse the base64-encoded parameter data from a node.

    Args:
        node: XML node containing base64 parameter data

    Returns:
        Tuple of (parameters dict, enum_map dict)
    """
    params = {}
    enum_map = {}

    if node is None or node.text is None:
        return params, enum_map

    try:
        data = base64.b64decode(node.text)
    except Exception:
        return params, enum_map

    for i in range(4096):  # Max parameters to check
        name, value, enum_desc = _get_a_param(data, i)
        if name is None:
            break

        params[name] = value

        if enum_desc is not None:
            enum_map[name] = enum_desc[1]

    return params, enum_map


# ============================================================================
# Main Parsing Functions
# ============================================================================

def _parse_examcard(examcard_path: str) -> Dict[str, Any]:
    """
    Parse an ExamCard file and return the first scan's data.

    Args:
        examcard_path: Path to .ExamCard file

    Returns:
        Dictionary with scan parameters
    """
    all_scans = _parse_examcard_all_scans(examcard_path)

    # Return first non-General scan
    for name, data in all_scans.items():
        if name != "General":
            return data

    return {}


def _parse_examcard_all_scans(examcard_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse an ExamCard file and return all scans' data.

    Args:
        examcard_path: Path to .ExamCard file

    Returns:
        Dictionary mapping scan names to their parameters
    """
    path = Path(examcard_path)
    if not path.exists():
        raise FileNotFoundError(f"ExamCard file not found: {examcard_path}")

    try:
        # Read file content and clean it up
        # Some ExamCard files have trailing garbage after closing tag
        with open(examcard_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        # Find the closing envelope tag and truncate there
        closing_tag = '</SOAP-ENV:Envelope>'
        closing_pos = content.find(closing_tag)
        if closing_pos > 0:
            content = content[:closing_pos + len(closing_tag)]

        # Parse from string instead of file
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise RuntimeError(f"Error parsing ExamCard: {e}")

    result = {}

    # Get general ExamCard info
    examcard_nodes = _get_nodes_by_tag(root, 'ExamCard')
    if examcard_nodes:
        general_info = _get_info_for_node(examcard_nodes[0], root)
        result["General"] = general_info

    # Get execution steps (each step is a scan)
    exec_steps = _get_nodes_by_tag(root, 'ExecutionStep')

    for i, step in enumerate(exec_steps):
        try:
            # Navigate: ExecutionStep -> singleScan -> scanProcedure -> parameterData
            single_scan = _get_child_thru_ref(root, step, 'singleScan')
            if single_scan is None:
                continue

            scan_proc = _get_child_thru_ref(root, single_scan, 'scanProcedure')
            if scan_proc is None:
                continue

            # Get scan name
            name = _get_child_name(single_scan)
            if not name:
                name = _get_child_name(scan_proc)
            if not name:
                name = f"Scan_{i+1}"

            # Get parameter data
            param_data_node = _get_child_thru_ref(root, scan_proc, 'parameterData')
            params, enum_map = _parse_parameter_data(param_data_node)

            # Get additional info from scan procedure
            scan_info = _get_info_for_node(scan_proc, root)

            # Get scan properties if available
            scan_props = _get_child_thru_ref(root, single_scan, 'scanProperties')
            if scan_props:
                props_info = _get_info_for_node(scan_props, root)
                scan_info.update(props_info)

            # Merge all data
            scan_data = {
                "name": name,
                "parameters": params,
                "enum_map": enum_map,
                **scan_info
            }

            result[name] = scan_data

        except Exception as e:
            # Skip scans that fail to parse
            continue

    return result


# ============================================================================
# DICOM Mapping
# ============================================================================

# Mapping from Philips EX_* parameter names to DICOM field names
# Note: EchoTime and PixelSpacing are handled specially in _calculate_derived_fields
PHILIPS_TO_DICOM_MAPPING = {
    # Acquisition parameters
    # EX_ACQ_first_echo_time and EX_ACQ_second_echo_time handled in _calculate_derived_fields
    "EX_ACQ_flip_angle": "FlipAngle",
    "EX_ACQ_se_rep_time": "RepetitionTime",      # SE sequences
    "EX_ACQ_ffe_rep_time": "RepetitionTime",     # FFE/GRE sequences
    "EX_ACQ_tfe_rep_time": "RepetitionTime",     # TFE sequences
    "EX_ACQ_epi_factor": "EchoTrainLength",      # Standard DICOM (0018,0091) - EPI echo train
    "EX_ACQ_turbo_factor": "EchoTrainLength",    # Standard DICOM (0018,0091) - TSE/FSE echo train
    "EX_ACQ_measurements": "NumberOfAverages",
    "EX_ACQ_scan_mode": "MRAcquisitionType",
    "EX_ACQ_imaging_sequence": "ScanningSequence",
    "EX_ACQ_fast_imaging_mode": "SequenceVariant",
    "EX_ACQ_scan_resolution": "AcquisitionMatrix",
    "EX_ACQ_patient_weight": "PatientWeight",
    "EX_ACQ_nucleus": "ImagedNucleus",
    "EX_ACQ_partial_matrix": "PartialFourier",
    "EX_ACQ_partial_echo": "PartialFourier",
    "EX_ACQ_flow_compensation": "FlowCompensation",  # (0018,9010)

    # Geometry parameters
    # EX_GEO_voxel_size_m and EX_GEO_voxel_size_p combined into PixelSpacing in _calculate_derived_fields
    # EX_GEO_fov and EX_GEO_fov_p used to calculate PercentPhaseFieldOfView in _calculate_derived_fields
    # EX_GEO_stacks_slices is summed to get NumberOfSlices in _calculate_derived_fields
    "EX_GEO_voxel_size_s": "SliceThickness",
    "EX_GEO_slice_thickness": "SliceThickness",
    "EX_GEO_stacks_orientations": "ImagePlaneOrientation",

    # Patient position - combined in _calculate_derived_fields
    "EX_GEO_patient_body_position": "PatientPosition",  # (0018,5100)
    "EX_GEO_patient_body_orientation": "PatientPosition",

    # Parallel imaging
    "EX_GEO_sense_enable": "ParallelAcquisition",
    "EX_GEO_sense_p_red_factor": "ParallelReductionFactorInPlane",

    # Contrast parameters
    "EX_ACQ_inversion_time": "InversionTime",
    "EX_BBI_type_enum": "InversionRecovery",  # Standard DICOM (0018,9009)
    "EX_MTC_enable": "MagnetizationTransfer",  # (0018,9020)

    # Dynamic scanning
    "EX_DYN_nr_scans": "NumberOfTemporalPositions",

    # Diffusion
    "EX_DIFF_enable": "DiffusionDirectionality",  # (0018,9075) - NO/DWI/DTI
    "EX_DIFF_b_value": "DiffusionBValue",
    "EX_DIFF_nr_directions": "NumberOfDiffusionDirections",

    # Processing - map to standard DICOM matrix fields
    "EX_PROC_recon_resolution": "Rows",     # Standard DICOM (0028,0010)
    "EX_PROC_recon_resol": "Columns",       # Standard DICOM (0028,0011)

    # Cardiac
    "EX_CARD_sync": "CardiacSynchronizationTechnique",  # Standard DICOM (0018,9037)

    # Spectroscopy
    "EX_ACQ_spectro_bandwidth": "SpectralWidth",
}

# Enum value mappings for specific parameters - translate indices to DICOM-compatible values
PHILIPS_ENUM_MAPPINGS = {
    "EX_ACQ_scan_mode": {
        0: "2D",
        1: "3D",
        2: "MS",   # Multi-slice 2D
        3: "M2D",  # Multi-2D
    },
    "EX_ACQ_imaging_sequence": {
        0: "SE",   # Spin Echo
        1: "IR",   # Inversion Recovery
        2: "SE",   # Mixed -> SE
        3: "GR",   # FFE -> Gradient Recalled
        4: "EP",   # Echo -> Echo Planar
        5: "GR",   # FID -> Gradient
    },
    "EX_ACQ_fast_imaging_mode": {
        0: "NONE",
        1: "OSP",  # TSE
        2: "SK",   # TFE
        3: "SK",   # EPI
        4: "OSP",  # GRASE
    },
    "EX_ACQ_nucleus": {
        0: "1H",
        1: "31P",
        2: "13C",
        3: "23NA",
        4: "19F",
    },
    "EX_GEO_patient_body_position": {
        0: "HFS",  # Head First Supine
        1: "FFS",  # Feet First Supine
    },
    "EX_GEO_patient_body_orientation": {
        0: "HFS",  # Supine
        1: "HFP",  # Prone
        2: "HFDL", # Left Decubitus
        3: "HFDR", # Right Decubitus
    },
    "EX_CARD_sync": {
        0: "NONE",
        1: "PROSPECTIVE",  # Triggered
        2: "PROSPECTIVE",  # Gated
        3: "RETROSPECTIVE",
    },
    "EX_GEO_sense_enable": {
        0: "NO",
        1: "YES",
    },
    "EX_DIFF_enable": {
        0: "NONE",
        1: "ISOTROPIC",  # DWI
        2: "BMATRIX",    # DTI
    },
    "EX_MTC_enable": {
        0: "OFF",
        1: "ON_RESONANCE",
        2: "OFF_RESONANCE",
    },
    "EX_ACQ_flow_compensation": {
        0: "NONE",
        1: "OTHER",
    },
    "EX_BBI_type_enum": {
        0: "NO",
        1: "YES",
        2: "YES",  # Improved
    },
    "EX_GEO_stacks_orientations": {
        0: "AXIAL",
        1: "SAGITTAL",
        2: "CORONAL",
    },
    "EX_ACQ_partial_matrix": {
        0: "NO",
        1: "YES",
    },
    "EX_ACQ_partial_echo": {
        0: "NO",
        1: "YES",
    },
}

# Field ordering for output - matches DEFAULT_DICOM_FIELDS order from config.py
# Fields not in this list will be placed at the end alphabetically
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

    # Parallel Imaging / Multiband
    'ParallelAcquisition',
    'ParallelAcquisitionTechnique',
    'ParallelReductionFactorInPlane',
    'PartialFourier',

    # Bandwidth / Readout
    'PixelBandwidth',
    'SpectralWidth',

    # Phase encoding
    'InPlanePhaseEncodingDirection',
    'NumberOfPhaseEncodingSteps',
    'PercentPhaseFieldOfView',

    # Scanner hardware
    'MagneticFieldStrength',
    'ImagingFrequency',
    'ImagedNucleus',
    'TransmitCoilName',
    'ReceiveCoilName',
    'NumberOfAverages',
    'PatientWeight',

    # Advanced / niche
    'FlowCompensation',
    'MagnetizationTransfer',
    'InversionRecovery',
    'CardiacSynchronizationTechnique',
]


# Philips-specific parameters that are useful to keep (no direct DICOM equivalent)
# Use a whitelist approach - only include known useful vendor-specific parameters
USEFUL_PHILIPS_PARAMETERS = {
    # Fat/water suppression techniques (Philips-specific)
    "EX_SPIR_fat_suppression",
    "EX_SPIR_water_suppression",
    # Acquisition parameters useful for QA/research
    "EX_ACQ_gradient_mode",
    "EX_ACQ_shot_mode",
    "EX_ACQ_slice_order",
    "EX_ACQ_water_fat_shift",
    "EX_ACQ_echoes",       # Number of echoes
    "EX_ACQ_bandwidth",    # Receiver bandwidth
    # Geometry settings
    "EX_GEO_slice_gap_mode",
    "EX_GEO_stacks",       # Number of stacks/slabs
    # Respiratory/cardiac gating
    "EX_RESP_synch",
    "EX_RNAV_resp_comp",
    # Processing settings
    "EX_PROC_geometry_correction",
    "EX_PROC_reconstruction_mode",
}


# Parameters that are handled in _calculate_derived_fields() or are redundant with standard DICOM fields
DERIVED_FIELD_SOURCES = {
    # Used to calculate EchoTime
    "EX_ACQ_first_echo_time",
    "EX_ACQ_second_echo_time",
    # Used to calculate PixelSpacing (reconstruction or acquisition voxel sizes)
    "EX_GEO_voxel_size_m",
    "EX_GEO_voxel_size_p",
    "EX_PROC_recon_voxel_size_m",
    "EX_PROC_recon_voxel_size_p",
    # Redundant with SliceThickness
    "EX_GEO_acq_voxel_size_s",
    "EX_GEO_acq_slice_thickness",
    # Redundant with PercentPhaseFieldOfView
    "EX_GEO_rect_fov_perc",
    # Internal flag, not useful
    "EX_GEO_voxel_size_conv_done",
    # Used to calculate PercentPhaseFieldOfView
    "EX_GEO_fov",
    "EX_GEO_fov_p",
    # Used to calculate AcquisitionDuration
    "IF_str_total_scan_time",
    # Used as fallback for TR/TE
    "IF_act_rep_time_echo_time",
    # Used to calculate NumberOfSlices (summed from per-stack values)
    "EX_GEO_stacks_slices",
}


def apply_examcard_to_dicom_mapping(scan_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert Philips ExamCard parameters to DICOM-compatible field names.

    Args:
        scan_data: Dictionary from _parse_examcard containing 'parameters' and 'enum_map'

    Returns:
        Dictionary with DICOM-compatible field names and values
    """
    dicom_fields = {}

    params = scan_data.get("parameters", {})
    enum_map = scan_data.get("enum_map", {})

    # ExamCard files are Philips-specific
    dicom_fields["Manufacturer"] = "Philips"

    # Add scan name as ProtocolName
    if "name" in scan_data:
        dicom_fields["ProtocolName"] = scan_data["name"]

    # Add method description if available
    if "methodDescription" in scan_data:
        dicom_fields["SeriesDescription"] = scan_data["methodDescription"].strip()

    # Map parameters to DICOM fields
    for philips_name, value in params.items():
        if value is None or value == "":
            continue

        # Check if we have a direct mapping
        if philips_name in PHILIPS_TO_DICOM_MAPPING:
            dicom_name = PHILIPS_TO_DICOM_MAPPING[philips_name]

            # Handle enum values
            if philips_name in PHILIPS_ENUM_MAPPINGS and isinstance(value, int):
                enum_mapping = PHILIPS_ENUM_MAPPINGS[philips_name]
                if value in enum_mapping:
                    value = enum_mapping[value]
                elif philips_name in enum_map and isinstance(value, int):
                    # Use the enum description from the file
                    enum_list = enum_map[philips_name]
                    if 0 <= value < len(enum_list):
                        value = enum_list[value]

            dicom_fields[dicom_name] = value
        else:
            # Skip parameters that are used in _calculate_derived_fields()
            if philips_name in DERIVED_FIELD_SOURCES:
                continue

            # Only include parameters in the whitelist of useful Philips-specific parameters
            if philips_name not in USEFUL_PHILIPS_PARAMETERS:
                continue

            # For unmapped enum parameters, translate the value using file's enum_map
            if philips_name in enum_map and isinstance(value, int):
                enum_list = enum_map[philips_name]
                if 0 <= value < len(enum_list):
                    value = enum_list[value]

            # Keep unmapped parameters with cleaned names
            clean_name = philips_name
            if clean_name.startswith("EX_"):
                clean_name = clean_name[3:]
            elif clean_name.startswith("GEX_"):
                clean_name = clean_name[4:]
            elif clean_name.startswith("IF_"):
                clean_name = clean_name[3:]

            # Only include if it has a non-empty value
            if isinstance(value, (int, float, str)) and value != "" and value != 0:
                dicom_fields[f"Philips_{clean_name}"] = value

    # Calculate derived fields
    _calculate_derived_fields(dicom_fields, params)

    # Sort fields in standard order
    return _sort_output_fields(dicom_fields)


def _calculate_derived_fields(dicom_fields: Dict[str, Any], params: Dict[str, Any]):
    """
    Calculate derived DICOM fields from raw parameters.

    Args:
        dicom_fields: Dictionary to update with derived fields
        params: Raw Philips parameters
    """
    # Calculate EchoTime - combine first and second if both present
    first_te = params.get("EX_ACQ_first_echo_time")
    second_te = params.get("EX_ACQ_second_echo_time")

    if first_te is not None:
        if second_te is not None and second_te > 0:
            # Multi-echo: store as list
            dicom_fields["EchoTime"] = [first_te, second_te]
        else:
            # Single echo
            dicom_fields["EchoTime"] = first_te

    # Calculate PixelSpacing from reconstruction voxel sizes (standard DICOM format: [row, col])
    # Use reconstruction values as these match what the actual DICOM image would contain
    row_spacing = params.get("EX_PROC_recon_voxel_size_m") or params.get("EX_GEO_voxel_size_m")
    col_spacing = params.get("EX_PROC_recon_voxel_size_p") or params.get("EX_GEO_voxel_size_p")
    if row_spacing is not None and col_spacing is not None:
        dicom_fields["PixelSpacing"] = [row_spacing, col_spacing]

    # Calculate PercentPhaseFieldOfView from FOV values
    # PercentPhaseFieldOfView = (Phase FOV / Readout FOV) * 100
    fov_read = params.get("EX_GEO_fov")
    fov_phase = params.get("EX_GEO_fov_p")
    if fov_read is not None and fov_phase is not None and fov_read > 0:
        dicom_fields["PercentPhaseFieldOfView"] = (fov_phase / fov_read) * 100.0

    # Calculate ReconstructionDiameter from resolution and voxel size
    recon_res = params.get("EX_PROC_recon_resolution")
    if recon_res and row_spacing:
        dicom_fields["ReconstructionDiameter"] = recon_res * row_spacing

    # Parse TR from IF_act_rep_time_echo_time if not already set
    # Format is typically "9.8 / 4.6" (TR / TE in ms)
    if "RepetitionTime" not in dicom_fields:
        tr_te_str = params.get("IF_act_rep_time_echo_time")
        if tr_te_str and isinstance(tr_te_str, str) and "/" in tr_te_str:
            try:
                parts = tr_te_str.split("/")
                tr_val = float(parts[0].strip())
                dicom_fields["RepetitionTime"] = tr_val
            except (ValueError, IndexError):
                pass

    # Parse TE from the combined string if not already set
    if "EchoTime" not in dicom_fields:
        tr_te_str = params.get("IF_act_rep_time_echo_time")
        if tr_te_str and isinstance(tr_te_str, str) and "/" in tr_te_str:
            try:
                parts = tr_te_str.split("/")
                if len(parts) >= 2:
                    te_val = float(parts[1].strip())
                    dicom_fields["EchoTime"] = te_val
            except (ValueError, IndexError):
                pass

    # Parse acquisition duration from IF_str_total_scan_time
    # Format is typically "03:56.3" (MM:SS.s)
    # Maps to standard DICOM AcquisitionDuration (0018,9073)
    scan_time_str = params.get("IF_str_total_scan_time")
    if scan_time_str and isinstance(scan_time_str, str):
        try:
            if ":" in scan_time_str:
                parts = scan_time_str.split(":")
                minutes = int(parts[0])
                seconds = float(parts[1])
                total_seconds = minutes * 60 + seconds
                dicom_fields["AcquisitionDuration"] = total_seconds
        except (ValueError, IndexError):
            pass

    # Calculate NumberOfSlices from EX_GEO_stacks_slices
    # Philips stores slice counts per stack as a list; DICOM expects total as single integer
    stacks_slices = params.get("EX_GEO_stacks_slices")
    if stacks_slices is not None:
        if isinstance(stacks_slices, list):
            # Sum all slice counts across stacks
            dicom_fields["NumberOfSlices"] = sum(stacks_slices)
        elif isinstance(stacks_slices, (int, float)):
            dicom_fields["NumberOfSlices"] = int(stacks_slices)


def _sort_output_fields(dicom_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sort output fields in standard DICOM order.

    Standard DICOM fields are ordered according to DICOM_FIELD_ORDER,
    followed by any other DICOM fields alphabetically,
    then Philips-specific fields alphabetically at the end.

    Args:
        dicom_fields: Dictionary of field names to values

    Returns:
        Ordered dictionary with fields in standard order
    """
    # Create order index for known fields
    order_index = {field: i for i, field in enumerate(DICOM_FIELD_ORDER)}

    # Separate fields into categories
    ordered_dicom = []      # Fields in DICOM_FIELD_ORDER
    other_dicom = []        # Other DICOM fields (not Philips_)
    philips_fields = []     # Philips_ prefixed fields

    for key in dicom_fields.keys():
        if key.startswith('Philips_'):
            philips_fields.append(key)
        elif key in order_index:
            ordered_dicom.append(key)
        else:
            other_dicom.append(key)

    # Sort each category
    ordered_dicom.sort(key=lambda k: order_index[k])
    other_dicom.sort()
    philips_fields.sort()

    # Build ordered result
    result = {}
    for key in ordered_dicom + other_dicom + philips_fields:
        result[key] = dicom_fields[key]

    return result


def _convert_to_schema_format(dicom_fields: Dict[str, Any], raw_data: Dict[str, Any],
                              scan_name: str, examcard_path: str) -> Dict[str, Any]:
    """
    Convert DICOM fields to schema-compatible format.

    Args:
        dicom_fields: DICOM-compatible field dictionary
        raw_data: Raw scan data from parsing
        scan_name: Name of the scan
        examcard_path: Path to source ExamCard file

    Returns:
        Schema-compatible dictionary
    """
    # Extract series-varying parameters (e.g., multiple echo times)
    series_params = _extract_series_parameters(dicom_fields, raw_data)

    # Generate series combinations
    series_list = _generate_series_combinations(series_params)

    # Build acquisition-level fields (excluding series-varying ones)
    acquisition_fields = []
    series_varying_keys = set(series_params.keys())

    for field_name, value in dicom_fields.items():
        # Skip metadata and series-varying fields
        if field_name in ["ExamCard_Path", "ExamCard_FileName", "ScanName"]:
            continue
        if field_name in series_varying_keys:
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
            "source_type": "examcard",
            "examcard_path": str(examcard_path),
            "examcard_filename": Path(examcard_path).name
        },
        "fields": acquisition_fields,
        "series": series_list
    }


def _extract_series_parameters(dicom_fields: Dict[str, Any], raw_data: Dict[str, Any]) -> Dict[str, List]:
    """
    Extract parameters that create series variations (e.g., multiple echo times).

    Args:
        dicom_fields: DICOM-compatible fields
        raw_data: Raw scan data

    Returns:
        Dictionary mapping field names to lists of values
    """
    params = raw_data.get("parameters", {})
    series_params = {}

    # Check for multiple echo times
    first_echo = params.get("EX_ACQ_first_echo_time")
    second_echo = params.get("EX_ACQ_second_echo_time")

    if first_echo is not None and second_echo is not None and second_echo > 0:
        series_params["EchoTime"] = [first_echo, second_echo]

    # Check for explicit echo list if available
    # (Would need to look for EX_ACQ_echo_times array)

    return series_params


def _generate_series_combinations(series_params: Dict[str, List]) -> List[Dict[str, Any]]:
    """
    Generate series combinations from varying parameters.

    Args:
        series_params: Dictionary of parameter names to value lists

    Returns:
        List of series dictionaries
    """
    if not series_params:
        return []

    # Get all parameter names and their value lists
    param_names = list(series_params.keys())
    value_lists = [series_params[name] for name in param_names]

    # Generate all combinations
    series_list = []
    for i, combo in enumerate(itertools.product(*value_lists)):
        series_fields = []
        for j, param_name in enumerate(param_names):
            series_fields.append({
                "field": param_name,
                "value": combo[j]
            })

        series_list.append({
            "name": f"Series {i+1:02d}",
            "fields": series_fields
        })

    return series_list
