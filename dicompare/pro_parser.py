"""
Siemens .pro Protocol File Parser with DICOM Mapping

Uses twixtools to parse Siemens MRI protocol files (.pro) and extract
comprehensive protocol information in both raw and DICOM-compatible formats.

This module is based on the parse_siemens_pro.py script and integrates
.pro file parsing into the dicompare package.



"""

from pathlib import Path
from typing import Dict, Any, Optional, Union
from twixtools.twixprot import parse_buffer

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

def _decode_siemens_version(ul_version: Union[int, str]) -> str:
    """
    Decode Siemens IDEA version from ulVersion field.
    Based on hr_ideaversion.m by Jacco de Zwart (NIH).
    
    Args:
        ul_version: Siemens ulVersion value (int or string)
        
    Returns:
        IDEA version string (e.g., "VE12U", "VB17A")
    """
    # Convert to string and handle potential hex formatting
    if isinstance(ul_version, int):
        vers_str = str(ul_version)
        vers_hex = hex(ul_version)
    else:
        vers_str = str(ul_version)
        # Check if it's already hex
        if vers_str.startswith('0x'):
            vers_hex = vers_str.lower()
            try:
                vers_str = str(int(vers_str, 16))
            except ValueError:
                vers_str = vers_str
        else:
            try:
                vers_hex = hex(int(vers_str))
            except ValueError:
                vers_hex = vers_str
    
    # Version mapping from hr_ideaversion.m
    version_mapping = {
        # Hex format
        '0xbee332': 'VA25A',
        '0x1421cf5': 'VB11D',
        '0x1452a3b': 'VB13A', 
        '0x1483779': 'VB15A',
        '0x14b44b6': 'VB17A',
        '0x273bf24': 'VD11D',
        '0x2765738': 'VD13A',
        '0x276a554': 'VD13C',
        '0x276cc66': 'VD13D',
        '0x30c0783': 'VE11B',
        '0x30c2e91': 'VE11C',
        # Decimal format
        '21710006': 'VB17A',
        '51110009': 'VE11A',
        '51150000': 'VE11E',
        '51180001': 'VE11K',
        '51130001': 'VE12U',
        '51280000': 'VE12U',
    }
    
    # Try exact matches first
    if vers_str in version_mapping:
        return version_mapping[vers_str]
    elif vers_hex in version_mapping:
        return version_mapping[vers_hex]
    
    # For unknown versions, try to infer based on numeric value
    try:
        version_num = int(vers_str)
        if version_num >= 66000000:
            return "VE12U+"  # Likely newer than VE12U
        elif version_num >= 51280000:
            return "VE12U"
        elif version_num >= 51000000:
            return "VE11x"   # VE11 series
        elif version_num >= 40000000:
            return "VDxx"    # VD series
        elif version_num >= 20000000:
            return "VBxx"    # VB series
        else:
            return "VAxx"    # VA series or older
    except ValueError:
        pass
    
    return f"UNKNOWN_{vers_str}"


def _decode_partial_fourier(mode: Union[int, str]) -> float:
    """
    Decode Siemens partial Fourier mode using proper lookup table.
    Based on MATLAB evalPFmode function from the provided code examples.
    
    Args:
        mode: Siemens partial Fourier mode (hex or int)
        
    Returns:
        Partial Fourier fraction (0.5, 0.625, 0.75, 0.875, or 1.0)
    """
    if isinstance(mode, str):
        mode_str = mode.lower()
    else:
        mode_str = hex(mode).lower()
    
    # Siemens partial Fourier encoding (from MATLAB evalPFmode)
    pf_mapping = {
        '0x1': 0.5,    # 4/8
        '0x01': 0.5,   # 4/8
        '0x2': 0.625,  # 5/8
        '0x02': 0.625, # 5/8
        '0x4': 0.75,   # 6/8
        '0x04': 0.75,  # 6/8
        '0x8': 0.875,  # 7/8
        '0x08': 0.875, # 7/8
        '0x10': 1.0,   # off
        '0x20': 1.0,   # auto (assume full)
    }
    
    return pf_mapping.get(mode_str, 1.0)  # Default to full if unknown


def _extract_unique_b_values(b_value_array: list) -> list:
    """
    Extract unique b-values from Siemens sDiffusion.alBValue array.
    
    Args:
        b_value_array: Siemens alBValue array containing b-values for different weightings
        
    Returns:
        List of unique b-values in ascending order
    """
    unique_b_values = set()
    
    for item in b_value_array:
        if isinstance(item, list):
            if len(item) == 0:
                # Empty array typically represents b=0 (baseline) images
                unique_b_values.add(0.0)
            else:
                # Handle nested arrays with values
                for b_val in item:
                    if isinstance(b_val, (int, float)) and b_val >= 0:
                        unique_b_values.add(float(b_val))
        elif isinstance(item, (int, float)) and item >= 0:
            # Handle direct values
            unique_b_values.add(float(item))
    
    # Return sorted list of unique b-values
    return sorted(list(unique_b_values))


def _decode_sequence_type(pro_data: Dict[str, Any]) -> str:
    """
    Decode Siemens sequence type using proper mapping with fallback.
    Based on XSL template from the provided code examples.
    
    Args:
        pro_data: Raw .pro data dictionary
        
    Returns:
        DICOM-compatible sequence type string
    """
    seq_type = extract_nested_value(pro_data, "ucSequenceType")
    protocol_name = extract_nested_value(pro_data, "tProtocolName") or ""
    sequence_filename = extract_nested_value(pro_data, "tSequenceFileName") or ""
    
    seq_mapping = {
        1: "GR",  # Flash → Gradient Echo
        2: "GR",  # SSFP → Gradient Echo 
        4: "EP",  # EPI → Echo Planar
        8: "SE",  # TurboSpinEcho → Spin Echo
        16: "GR", # ChemicalShiftImaging → Gradient Echo
        32: "GR"  # FID → Gradient Echo
    }
    
    # Try direct mapping first
    if seq_type and seq_type in seq_mapping:
        return seq_mapping[seq_type]
    
    # Fallback: analyze protocol and sequence names
    protocol_lower = protocol_name.lower()
    sequence_lower = sequence_filename.lower()
    
    # Echo Planar sequences
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["epi", "ep2d", "ep3d", "bold", "diff"]):
        return "EP"
    
    # Spin Echo sequences (including TSE, HASTE)
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["tse", "haste", "space", "flair", "t2"]):
        return "SE"
    
    # Inversion Recovery sequences
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["ir", "flair", "mprage", "mp2rage", "tfl"]):
        return "IR"
    
    # Unknown
    return None


def _detect_scan_options(pro_data: Dict[str, Any]) -> list:
    """
    Detect DICOM ScanOptions based on Siemens protocol parameters.
    
    Args:
        pro_data: Raw .pro data dictionary
        
    Returns:
        List of ScanOptions strings
    """
    scan_options = []
    
    # Phase Encode Reordering (PER)
    reordering = extract_nested_value(pro_data, "sKSpace.unReordering")
    if reordering and reordering != 1:  # 1 = linear, others = reordered
        scan_options.append("PER")
    
    # Respiratory Gating (RG)
    resp_gate = extract_nested_value(pro_data, "sPhysioImaging.sPhysioResp.lRespGateThreshold")
    if resp_gate and resp_gate > 0:
        scan_options.append("RG")
    
    # Cardiac Gating (CG)
    cardiac_trigger = extract_nested_value(pro_data, "sPhysioImaging.sPhysioECG.lTriggerPulses")
    if cardiac_trigger and cardiac_trigger > 0:
        scan_options.append("CG")
    
    # Peripheral Pulse Gating (PPG)
    pulse_trigger = extract_nested_value(pro_data, "sPhysioImaging.sPhysioPulse.lTriggerPulses")
    if pulse_trigger and pulse_trigger > 0:
        scan_options.append("PPG")
    
    # Flow Compensation (FC)
    flow_comp = extract_nested_value(pro_data, "acFlowComp")
    if flow_comp and isinstance(flow_comp, list):
        # Check if any echo has flow compensation enabled
        if any(fc > 0 for fc in flow_comp if fc is not None):
            scan_options.append("FC")
    
    # Partial Fourier - Frequency (PFF)
    pf_readout = extract_nested_value(pro_data, "sKSpace.ucReadoutPartialFourier")
    if pf_readout and pf_readout < 16:  # 16 = off, < 16 = partial Fourier
        scan_options.append("PFF")
    
    # Partial Fourier - Phase (PFP)
    pf_phase = extract_nested_value(pro_data, "sKSpace.ucPhasePartialFourier")
    if pf_phase and pf_phase < 16:  # 16 = off, < 16 = partial Fourier
        scan_options.append("PFP")
    
    # Spatial Presaturation (SP)
    # Check various saturation pulse types
    fat_sat = extract_nested_value(pro_data, "sPrepPulses.ucFatSat")
    water_sat = extract_nested_value(pro_data, "sPrepPulses.ucWaterSat")
    
    # Regional saturation pulses
    rsat_elements = extract_nested_value(pro_data, "sRSatArray.asElm") or []
    
    if (fat_sat and fat_sat > 1) or (water_sat and water_sat > 1) or len(rsat_elements) > 0:
        scan_options.append("SP")
    
    # Fat Saturation (FS) - more specific than SP
    if fat_sat and fat_sat > 1:
        scan_options.append("FS")
    
    return scan_options


def _detect_image_type(pro_data: Dict[str, Any]) -> list:
    """
    Detect DICOM ImageType based on Siemens protocol parameters.
    
    Args:
        pro_data: Raw .pro data dictionary
        
    Returns:
        List of ImageType strings [pixel_data_char, patient_exam_char, modality_specific, ...]
    """
    image_type = []
    
    # Value 1: Pixel Data Characteristics (ORIGINAL vs DERIVED)
    # For .pro files, these are always acquisition protocols → ORIGINAL
    image_type.append("ORIGINAL")
    
    # Value 2: Patient Examination Characteristics (PRIMARY vs SECONDARY)
    # For .pro files, these are always direct examination results → PRIMARY
    image_type.append("PRIMARY")
    
    # Value 3+: Modality Specific Characteristics
    # Based on reconstruction mode and sequence type
    recon_mode = extract_nested_value(pro_data, "ucReconstructionMode") or 1
    
    # Reconstruction mode mapping (from the GitHub comment):
    # 1 -> Single magnitude image (M)
    # 2 -> Single phase image (P)
    # 4 -> Real part only (R)
    # 8 -> Magnitude+phase image (M)
    # 10 -> Real part+phase (R)
    # 20 -> PSIR magnitude (M)
    if recon_mode in [1, 8, 20]:
        image_type.append("M")
    if recon_mode in [2, 8, 10]:
        image_type.append("P")
    if recon_mode in [4, 10]:
        image_type.append("R")
    if recon_mode not in [1, 2, 4, 8, 10, 20]:
        image_type.append("M") # Default to Magnitude if unknown
    
    # Normalization/filtering characteristics
    # Check for standard Siemens normalization
    prescan_normalize = extract_nested_value(pro_data, "sPreScanNormalizeFilter.ucMode")
    if prescan_normalize and prescan_normalize != 1:  # 1 = off
        image_type.append("NORM")  # Normalized
    else:
        image_type.append("ND")  # Not normalized (more common for raw protocols)
    
    # Angiography characteristics
    tof_inflow = extract_nested_value(pro_data, "sAngio.ucTOFInflow") or 1
    pc_flow = extract_nested_value(pro_data, "sAngio.ucPCFlowMode") or 1
    if tof_inflow > 1 or pc_flow > 1:
        image_type.append("ANGIO")
    
    return image_type


def _detect_sequence_variant(pro_data: Dict[str, Any]) -> Optional[list]:
    """
    Detect DICOM SequenceVariant based on sequence parameters and names.
    Uses comprehensive detection to match real-world DICOM patterns.
    
    Args:
        pro_data: Raw .pro data dictionary
        
    Returns:
        List of SequenceVariant strings or None if no variants detected
    """
    protocol_name = extract_nested_value(pro_data, "tProtocolName") or ""
    sequence_filename = extract_nested_value(pro_data, "tSequenceFileName") or ""
    protocol_lower = protocol_name.lower()
    sequence_lower = sequence_filename.lower()
    
    variants = []
    
    # TIER 1: Hardware parameters (most reliable)
    
    # MP (MAG prepared) - check for meaningful inversion preparation
    inversion_mode = extract_nested_value(pro_data, "sPrepPulses.ucInversion")
    inversion_times = extract_nested_value(pro_data, "alTI") or []
    
    # Don't detect MP for sequences that clearly shouldn't have it
    non_mp_sequences = ["bold", "diff", "epi", "localizer", "gre"]
    is_non_mp_sequence = any(term in protocol_lower or term in sequence_lower 
                            for term in non_mp_sequences)
    
    if not is_non_mp_sequence:
        # Check for reasonable TI values (50ms - 5000ms = 50000-5000000μs) for legitimate IR sequences
        meaningful_ti = False
        if isinstance(inversion_times, list):
            meaningful_ti = any(50000.0 <= ti <= 5000000.0 for ti in inversion_times if isinstance(ti, (int, float)))
        
        # Detect MP if explicit inversion mode or meaningful TI values for appropriate sequences
        if (inversion_mode and inversion_mode > 4) or meaningful_ti:
            variants.append("MP")
    
    # MTC (magnetization transfer contrast) - check for MT pulses
    mtc_mode = extract_nested_value(pro_data, "sPrepPulses.ucMTC")
    if mtc_mode and mtc_mode > 1:
        variants.append("MTC")
    
    # SK (segmented k-space) - check for multiple segments/shots
    segments = extract_nested_value(pro_data, "sFastImaging.lSegments") or 1
    shots = extract_nested_value(pro_data, "sFastImaging.lShots") or 1
    turbo_factor = extract_nested_value(pro_data, "sFastImaging.lTurboFactor") or 1
    if segments > 1 or shots > 1 or turbo_factor > 1:
        variants.append("SK")
    
    # OSP (oversampling phase) - enhanced detection
    remove_oversample = extract_nested_value(pro_data, "sSpecPara.ucRemoveOversampling")
    phase_os = extract_nested_value(pro_data, "sSpecPara.dPhaseOS") or 1.0
    phase_resolution = extract_nested_value(pro_data, "sKSpace.dPhaseResolution") or 1.0
    readout_os = extract_nested_value(pro_data, "sSpecPara.dReadoutOS") or 1.0
    
    # More liberal OSP detection
    if (remove_oversample and remove_oversample > 1) or \
       phase_os > 1.0 or readout_os > 1.0 or phase_resolution != 1.0:
        variants.append("OSP")
    
    # SS (steady state) - check for steady state sequences
    sequence_type = extract_nested_value(pro_data, "ucSequenceType") or 1
    # SSFP sequences (type 2) or specific sequence names
    if sequence_type == 2 or \
       any(term in protocol_lower or term in sequence_lower 
           for term in ["ssfp", "fisp", "trufi", "bssfp"]):
        variants.append("SS")
    
    # TIER 2: Sequence architecture
    
    # SP (spoiled) - check for spoiling in multi-echo or GRE sequences
    echo_times = extract_nested_value(pro_data, "alTE") or []
    spoiling_mode = extract_nested_value(pro_data, "ucSpoiling")
    
    # Multi-echo GRE sequences or explicit spoiling
    if (isinstance(echo_times, list) and len(echo_times) > 1 and sequence_type == 1) or \
       (spoiling_mode and spoiling_mode > 1):
        variants.append("SP")
    
    # EP (echo planar) - based on sequence type or EPI factor
    epi_factor = extract_nested_value(pro_data, "sFastImaging.lEPIFactor") or 1
    if sequence_type == 4 or epi_factor > 1:
        variants.append("EP")
    
    # TIER 3: Sequence name analysis (additive, not exclusive)
    
    # MP sequences (additive to hardware detection)
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["mp2rage", "mprage", "mp_rage", "tfl"]):
        if "MP" not in variants:
            variants.append("MP")
    
    # Spoiled sequences (additive)
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["spgr", "flash", "spoiled", "aspire", "gre"]):
        if "SP" not in variants:
            variants.append("SP")
    
    # Segmented k-space (additive)
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["csi", "segmented", "tse", "haste"]):
        if "SK" not in variants:
            variants.append("SK")
    
    # Echo planar (additive)
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["epi", "ep2d", "ep3d", "bold", "diff"]):
        if "EP" not in variants:
            variants.append("EP")
    
    # Magnetization transfer (additive)
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["mt", "mtc"]):
        if "MTC" not in variants:
            variants.append("MTC")
    
    # Steady state (additive)
    if any(term in protocol_lower or term in sequence_lower 
           for term in ["ssfp", "fisp", "trufi"]):
        if "SS" not in variants:
            variants.append("SS")
    
    # TIER 4: Sequence-specific expectations
    
    # Localizer sequences typically have SP + OSP
    if "localizer" in protocol_lower or "localizer" in sequence_lower:
        if "SP" not in variants:
            variants.append("SP")
        if "OSP" not in variants:
            variants.append("OSP")
    
    # Return sorted unique variants or None
    if variants:
        return sorted(list(set(variants)))
    else:
        return None


# Mapping from .pro fields to DICOM-compatible fields
# Only includes legitimate DICOM field names from the target list
PRO_TO_DICOM_MAPPING = {
    # Core Identifiers
    "tProtocolName": "ProtocolName",
    "tSequenceFileName": "SequenceName", 
    "SeriesDescription": "SeriesDescription",
    
    # Manufacturer info
    "sProtConsistencyInfo.tSystemType": "ManufacturerModelName",
    
    # Basic timing parameters (convert from microseconds)
    "alTR": ("RepetitionTime", lambda x: [t/1000.0 for t in x] if isinstance(x, list) else x/1000.0),  # μs → ms
    "alTI": ("InversionTime", lambda x: [t/1000000.0 for t in x] if isinstance(x, list) else x/1000000.0),  # μs → s  
    "alTE": ("EchoTime", lambda x: [t/1000.0 for t in x] if isinstance(x, list) else x/1000.0),  # μs → ms
    
    # Averaging
    "lAverages": "NumberOfAverages",
    
    # Matrix dimensions (corrected - .pro files use different names than MATLAB examples)
    "sKSpace.lBaseResolution": "Rows",             # Base resolution = readout direction = DICOM Rows
    "sKSpace.lPhaseEncodingLines": "Columns",      # Phase encoding lines = DICOM Columns
    "sKSpace.lImagesPerSlab": "NumberOfTemporalPositions",  # For 3D/4D sequences
    
    # RF parameters
    "adFlipAngleDegree.0": "FlipAngle",
    
    # Parallel imaging
    "sPat.lAccelFactPE": "ParallelReductionFactorInPlane",
    "sPat.lAccelFact3D": "SliceAccelerationFactor",
    "sPat.ucPATMode": ("ParallelAcquisitionTechnique", lambda x: "GRAPPA" if x == 2 else "SENSE" if x == 1 else None),
    "sSliceAcceleration.lMultiBandFactor": "MultibandFactor",
    
    # Bandwidth  
    "sRXSPEC.alDwellTime.0": ("PixelBandwidth", lambda x: 1000000.0 / x if x > 0 else None),
    # BandwidthPerPixelPhaseEncode calculated separately from dwell time and phase encoding steps
    
    # Phase encoding direction
    "sKSpace.lPhaseEncodingType": ("InPlanePhaseEncodingDirection", lambda x: "ROW" if x == 1 else "COL"),
    
    # Scanner hardware - only real DICOM fields
    "sProtConsistencyInfo.flNominalB0": "MagneticFieldStrength",
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
    "sAngio.ucTOFInflow": ("TimeOfFlightContrast", lambda x: "YES" if x > 1 else "NO"),
    "sAngio.ucPCFlowMode": ("AngioFlag", lambda x: "Y" if x > 1 else "N"),
    
    # Triggering/Gating
    "sPhysioImaging.sPhysioECG.lTriggerPulses": ("TriggerSourceOrType", lambda x: "ECG" if x > 0 else None),
    "sPhysioImaging.sPhysioECG.lTriggerWindow": "TriggerTime",
    
    # Diffusion parameters
    "sDiffusion.alBValue": ("DiffusionBValue", lambda x: _extract_unique_b_values(x) if x else None),
}


def extract_nested_value(data: Dict[str, Any], path: str) -> Optional[Any]:
    """
    Extract a value from nested dictionary using dot notation path.
    
    Args:
        data: The nested dictionary
        path: Dot-separated path (e.g., "sSliceArray.asSlice.0.dThickness")
        
    Returns:
        The extracted value or None if path doesn't exist
    """
    keys = path.split('.')
    current = data
    
    for key in keys:
        if current is None:
            return None
            
        # Handle array indices
        if key.isdigit():
            index = int(key)
            if isinstance(current, list) and index < len(current):
                current = current[index]
            else:
                return None
        else:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
                
    return current


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
            # Apply converter function if provided
            if converter is not None:
                try:
                    value = converter(value)
                except (TypeError, ValueError, ZeroDivisionError):
                    value = None
                    
            if value is not None:
                # Handle potential duplicate keys by preferring non-None values
                if dicom_field in dicom_data:
                    if dicom_data[dicom_field] is None and value is not None:
                        dicom_data[dicom_field] = value
                else:
                    dicom_data[dicom_field] = value
    
    # Add default or calculated DICOM fields that are not directly mappable
    calculate_other_dicom_fields(dicom_data, pro_data)
    
    return dicom_data


def calculate_other_dicom_fields(dicom_data: Dict[str, Any], pro_data: Dict[str, Any]) -> None:
    """
    Add default values for DICOM fields that are expected but might not be mappable from .pro files.
    Calculate composite fields from .pro data where possible.
    """
    # Default values for Siemens .pro files
    defaults = {
        "Manufacturer": "Siemens",
    }
    
    for field, default_value in defaults.items():
        if field not in dicom_data:
            dicom_data[field] = default_value
    
    # Calculate ImagePositionPatient from position components
    pos_sag = extract_nested_value(pro_data, "sSliceArray.asSlice.0.sPosition.dSag")
    pos_cor = extract_nested_value(pro_data, "sSliceArray.asSlice.0.sPosition.dCor") 
    pos_tra = extract_nested_value(pro_data, "sSliceArray.asSlice.0.sPosition.dTra")
    
    if all(v is not None for v in [pos_sag, pos_cor, pos_tra]):
        dicom_data["ImagePositionPatient"] = [pos_sag, pos_cor, pos_tra]
    
    # Calculate ImageOrientationPatient from normal vector components
    # Note: DICOM ImageOrientationPatient needs 6 values (row direction + column direction)
    # .pro only gives us slice normal, so we can't fully reconstruct this
    norm_sag = extract_nested_value(pro_data, "sSliceArray.asSlice.0.sNormal.dSag")
    norm_cor = extract_nested_value(pro_data, "sSliceArray.asSlice.0.sNormal.dCor")
    norm_tra = extract_nested_value(pro_data, "sSliceArray.asSlice.0.sNormal.dTra")
    
    if all(v is not None for v in [norm_sag, norm_cor, norm_tra]):
        # Store as slice normal for now - would need more complex calculation for full orientation
        dicom_data["SliceNormal"] = [norm_sag, norm_cor, norm_tra]
    
    # Calculate additional derived fields
    cols = dicom_data.get("Columns")
    rows = dicom_data.get("Rows")

    # Calculate Slices - handle 2D vs 3D sequences differently
    if "Slices" not in dicom_data:
        # Try multiple sources based on acquisition type
        images_per_slab = extract_nested_value(pro_data, "sKSpace.lImagesPerSlab")
        partitions = extract_nested_value(pro_data, "sKSpace.lPartitions")
        slice_array_size = extract_nested_value(pro_data, "sSliceArray.lSize")
        
        # Determine if this is a 3D acquisition
        if (images_per_slab and images_per_slab > 1) or (partitions and partitions > 1):
            # 3D sequence - use partitions or images per slab
            if partitions and partitions > 1:
                dicom_data["Slices"] = partitions
            elif images_per_slab and images_per_slab > 1:
                dicom_data["Slices"] = images_per_slab
        elif slice_array_size:
            # 2D sequence - use slice array size
            dicom_data["Slices"] = slice_array_size
    
    # NumberOfPhaseEncodingSteps typically equals Columns
    if cols and "NumberOfPhaseEncodingSteps" not in dicom_data:
        dicom_data["NumberOfPhaseEncodingSteps"] = cols
        
    # AcquisitionMatrix format: [freq_rows, freq_cols, phase_rows, phase_cols]
    # For Siemens, typically frequency is in read direction, phase in phase-encode direction
    if rows and cols and "AcquisitionMatrix" not in dicom_data:
        dicom_data["AcquisitionMatrix"] = [rows, 0, 0, cols]  # Standard format
        
    # Calculate PixelSpacing if FOV data is available 
    fov_read = extract_nested_value(pro_data, "sSliceArray.asSlice.0.dReadoutFOV")
    fov_phase = extract_nested_value(pro_data, "sSliceArray.asSlice.0.dPhaseFOV")
    
    if all(v is not None for v in [fov_read, fov_phase, rows, cols]):
        pixel_spacing_read = fov_read / rows
        pixel_spacing_phase = fov_phase / cols
        dicom_data["PixelSpacing"] = [pixel_spacing_read, pixel_spacing_phase]
        
    # Calculate PercentPhaseFieldOfView with oversampling consideration
    phase_res = extract_nested_value(pro_data, "sKSpace.dPhaseResolution")
    remove_oversample = extract_nested_value(pro_data, "sSpecPara.ucRemoveOversampling")
    readout_os = extract_nested_value(pro_data, "sSpecPara.dReadoutOS") or 1.0
    
    if phase_res and "PercentPhaseFieldOfView" not in dicom_data:
        percent_phase_fov = phase_res * 100.0
        # Adjust for oversampling if applicable
        if remove_oversample and readout_os > 1.0:
            percent_phase_fov = percent_phase_fov / readout_os
        dicom_data["PercentPhaseFieldOfView"] = percent_phase_fov
        
    # Calculate BandwidthPerPixelPhaseEncode from dwell time and phase encoding steps
    dwell_time = extract_nested_value(pro_data, "sRXSPEC.alDwellTime.0")  # in nanoseconds
    phase_steps = dicom_data.get("NumberOfPhaseEncodingSteps") or cols
    
    if dwell_time and phase_steps and "BandwidthPerPixelPhaseEncode" not in dicom_data:
        # Convert dwell time from nanoseconds to seconds, then calculate bandwidth
        dwell_time_sec = dwell_time / 1000000.0  # ns to μs to s 
        total_readout_time = dwell_time_sec * phase_steps
        if total_readout_time > 0:
            dicom_data["BandwidthPerPixelPhaseEncode"] = 1.0 / total_readout_time
            
    # Calculate ImagingFrequency from nominal B0 (if available)
    b0_field = dicom_data.get("MagneticFieldStrength")
    if b0_field and "ImagingFrequency" not in dicom_data:
        # Approximate proton frequency: 42.58 MHz/T for 1H
        dicom_data["ImagingFrequency"] = b0_field * 42.58
        
    # Calculate SliceThickness and MRAcquisitionType - handle 2D vs 3D sequences
    if "SliceThickness" not in dicom_data:
        slab_thickness = extract_nested_value(pro_data, "sSliceArray.asSlice.0.dThickness")
        images_per_slab = extract_nested_value(pro_data, "sKSpace.lImagesPerSlab")
        
        if slab_thickness is not None:
            if images_per_slab and images_per_slab > 1:
                # 3D sequence - calculate actual slice thickness from slab thickness
                slice_thickness = slab_thickness / images_per_slab
                dicom_data["SliceThickness"] = slice_thickness
                # Store original slab thickness for reference
                dicom_data["SlabThickness"] = slab_thickness
                # Set MR acquisition type
                dicom_data["MRAcquisitionType"] = "3D"
            else:
                # 2D sequence - use thickness directly
                dicom_data["SliceThickness"] = slab_thickness
                # Set MR acquisition type
                dicom_data["MRAcquisitionType"] = "2D"
                
    # Calculate SpacingBetweenSlices from dDistFact and slice thickness
    if "SpacingBetweenSlices" not in dicom_data:
        dist_fact = extract_nested_value(pro_data, "sGroupArray.asGroup.0.dDistFact")
        slice_thickness = dicom_data.get("SliceThickness")
        
        if dist_fact is not None and slice_thickness is not None:
            # Siemens dDistFact: 0.0 = no gap, 0.2 = 20% gap relative to slice thickness
            # SpacingBetweenSlices = slice_thickness * (1.0 + dDistFact)
            spacing_between_slices = slice_thickness * (1.0 + dist_fact)
            dicom_data["SpacingBetweenSlices"] = spacing_between_slices
            
    # Add enhanced sequence variant detection
    if "SequenceVariant" not in dicom_data:
        sequence_variant = _detect_sequence_variant(pro_data)
        if sequence_variant is not None:
            dicom_data["SequenceVariant"] = sequence_variant
        
    # Add PatientPosition if available
    if "PatientPosition" not in dicom_data:
        patient_position = extract_nested_value(pro_data, "sPatientPosition.ucPatientPosition")
        if patient_position is not None:
            # Map Siemens patient position codes to DICOM
            position_mapping = {
                1: "HFS",  # Head First Supine
                2: "HFP",  # Head First Prone
                3: "HFDR", # Head First Decubitus Right
                4: "HFDL", # Head First Decubitus Left
                5: "FFS",  # Feet First Supine
                6: "FFP",  # Feet First Prone
                7: "FFDR", # Feet First Decubitus Right
                8: "FFDL"  # Feet First Decubitus Left
            }
            dicom_data["PatientPosition"] = position_mapping.get(patient_position, "UNKNOWN")
            
    # Add AcquisitionTime if available (scan start time)
    acq_time = extract_nested_value(pro_data, "sMeasStartTime.lTime")
    if acq_time and "AcquisitionTime" not in dicom_data:
        # Convert from Siemens time format to DICOM time format (HHMMSS.FFFFFF)
        # Note: This is a simplified conversion - real implementation might need more complex handling
        hours = (acq_time // 3600000) % 24
        minutes = (acq_time // 60000) % 60
        seconds = (acq_time // 1000) % 60
        milliseconds = acq_time % 1000
        dicom_data["AcquisitionTime"] = f"{hours:02d}{minutes:02d}{seconds:02d}.{milliseconds:03d}000"
        
    # Calculate PercentSampling as fraction of k-space lines acquired
    if "PercentSampling" not in dicom_data:
        # Get parallel imaging acceleration factor
        accel_factor_pe = extract_nested_value(pro_data, "sPat.lAccelFactPE") or 1
        accel_factor_3d = extract_nested_value(pro_data, "sPat.lAccelFact3D") or 1
        
        # Get partial Fourier factor (already calculated by _decode_partial_fourier)
        pf_phase_code = extract_nested_value(pro_data, "sKSpace.ucPhasePartialFourier") or 16
        pf_readout_code = extract_nested_value(pro_data, "sKSpace.ucReadoutPartialFourier") or 16
        
        # Calculate partial Fourier fractions
        pf_phase_fraction = _decode_partial_fourier(pf_phase_code)
        pf_readout_fraction = _decode_partial_fourier(pf_readout_code)
        
        # Calculate percentage of k-space lines actually acquired
        # Start with 100% and apply reduction factors
        percent_sampling = 100.0
        
        # Apply parallel imaging reduction (PE direction)
        if accel_factor_pe > 1:
            percent_sampling = percent_sampling / accel_factor_pe
            
        # Apply 3D acceleration if present
        if accel_factor_3d > 1:
            percent_sampling = percent_sampling / accel_factor_3d
            
        # Apply partial Fourier reductions
        if pf_phase_fraction < 1.0:
            percent_sampling = percent_sampling * pf_phase_fraction
            
        if pf_readout_fraction < 1.0:
            percent_sampling = percent_sampling * pf_readout_fraction
            
        dicom_data["PercentSampling"] = round(percent_sampling, 3)
        
    # Calculate PartialFourier and PartialFourierDirection
    if "PartialFourier" not in dicom_data:
        phase_pf = extract_nested_value(pro_data, "sKSpace.ucPhasePartialFourier")
        readout_pf = extract_nested_value(pro_data, "sKSpace.ucReadoutPartialFourier")
        slice_pf = extract_nested_value(pro_data, "sKSpace.ucSlicePartialFourier")
        
        # Check which directions have partial Fourier active (< 16 means active)
        phase_active = phase_pf is not None and phase_pf < 16
        readout_active = readout_pf is not None and readout_pf < 16
        slice_active = slice_pf is not None and slice_pf < 16
        
        # Set PartialFourier based on whether any direction is active
        if phase_active or readout_active or slice_active:
            dicom_data["PartialFourier"] = "YES"
            
            # Determine PartialFourierDirection
            active_count = sum([phase_active, readout_active, slice_active])
            if active_count > 1:
                dicom_data["PartialFourierDirection"] = "COMBINATION"
            elif phase_active:
                dicom_data["PartialFourierDirection"] = "PHASE"
            elif readout_active:
                dicom_data["PartialFourierDirection"] = "FREQUENCY"
            elif slice_active:
                dicom_data["PartialFourierDirection"] = "SLICE_SELECT"
        else:
            dicom_data["PartialFourier"] = "NO"
            # Don't set PartialFourierDirection when PartialFourier is NO
        
    # Calculate ScanningSequence with fallback detection
    if "ScanningSequence" not in dicom_data:
        scanning_sequence = _decode_sequence_type(pro_data)
        dicom_data["ScanningSequence"] = scanning_sequence
        
    # Generate ImageType
    if "ImageType" not in dicom_data:
        image_type = _detect_image_type(pro_data)
        dicom_data["ImageType"] = image_type
        
    # Generate ScanOptions
    if "ScanOptions" not in dicom_data:
        scan_options = _detect_scan_options(pro_data)
        if scan_options:  # Only add if there are scan options
            dicom_data["ScanOptions"] = scan_options
            
    # Calculate GradientEchoTrainLength based on sequence architecture
    if "GradientEchoTrainLength" not in dicom_data:
        turbo_factor = extract_nested_value(pro_data, "sFastImaging.lTurboFactor") or 1
        epi_factor = extract_nested_value(pro_data, "sFastImaging.lEPIFactor") or 1
        sequence_type = extract_nested_value(pro_data, "ucSequenceType") or 1
        echo_times = extract_nested_value(pro_data, "alTE") or []
        
        if turbo_factor > 1:
            # TSE/FSE sequence - RF echo train, no gradient echoes
            gradient_echo_train_length = 0
        elif epi_factor > 1:
            # EPI sequence - gradient echo train based on EPI factor
            gradient_echo_train_length = epi_factor
        elif isinstance(echo_times, list) and len(echo_times) > 1 and sequence_type == 1:
            # Multi-echo GRE (Flash) - all echoes are gradient echoes
            gradient_echo_train_length = len(echo_times)
        elif sequence_type == 1:  # Flash/GRE
            # Single-echo GRE - one gradient echo
            gradient_echo_train_length = 1
        else:
            # TSE or other RF-based sequences - no gradient echoes
            gradient_echo_train_length = 0
            
        dicom_data["GradientEchoTrainLength"] = gradient_echo_train_length
        
    # Calculate EchoTrainLength - total k-space lines acquired per excitation
    if "EchoTrainLength" not in dicom_data:
        turbo_factor = extract_nested_value(pro_data, "sFastImaging.lTurboFactor") or 1
        epi_factor = extract_nested_value(pro_data, "sFastImaging.lEPIFactor") or 1
        segments = extract_nested_value(pro_data, "sFastImaging.lSegments") or 1
        sequence_type = extract_nested_value(pro_data, "ucSequenceType") or 1
        echo_times = extract_nested_value(pro_data, "alTE") or []
        
        if turbo_factor > 1:
            # TSE/FSE sequence - use turbo factor
            # For segmented sequences (like GRASE), multiply by segments
            echo_train_length = turbo_factor * segments
        elif epi_factor > 1:
            # EPI sequence - use EPI factor
            echo_train_length = epi_factor
        elif isinstance(echo_times, list) and len(echo_times) > 1:
            # Multi-echo sequence (GRE, etc.) - number of echoes equals echo train length
            echo_train_length = len(echo_times)
        else:
            # Standard single-echo sequences - 1 line per excitation
            echo_train_length = 1
            
        dicom_data["EchoTrainLength"] = echo_train_length
        
    # Calculate TemporalResolution for dynamic/multi-temporal sequences
    if "TemporalResolution" not in dicom_data:
        temporal_positions = dicom_data.get("NumberOfTemporalPositions", 1)
        tr_values = extract_nested_value(pro_data, "alTR") or []
        
        if temporal_positions > 1 and tr_values:
            # Convert from microseconds to milliseconds for temporal resolution
            temporal_resolution = tr_values[0] / 1000.0
            dicom_data["TemporalResolution"] = temporal_resolution


