"""
Derived DICOM field computation for Siemens .pro protocols.

Decoders for Siemens enum/bitmask parameters (software version, partial
Fourier, sequence type, scan options, image type, sequence variant, physio
gating) and :func:`calculate_other_dicom_fields`, which derives DICOM fields
that have no direct .pro counterpart. Split out of ``pro.py``, which owns
parsing, mapping, and session loading.
"""

from typing import Dict, Any, Optional, Tuple, Union, List

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
            vers_str = str(int(vers_str, 16))  # Convert hex to decimal
        else:
            vers_hex = hex(int(vers_str))  # Convert decimal to hex
    
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
    
    # For unknown versions, infer based on numeric value
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


def _nominal_field_strength(b0: Union[int, float]) -> float:
    """
    Map a Siemens nominal B0 value to the marketed field strength.

    Siemens .pro/.exar1 files store the *true* main field in flNominalB0
    (e.g. 2.89362 T for a "3T" scanner, 1.494 T for a "1.5T" scanner).
    DICOM MagneticFieldStrength (0018,0087), and every field-strength-keyed
    validation rule, expects the rounded marketed value (3.0, 1.5, ...).

    Args:
        b0: Raw nominal B0 in Tesla from flNominalB0

    Returns:
        Nearest standard clinical field strength, or the value rounded to
        3 decimals if it is not close to any known strength.
    """
    if not isinstance(b0, (int, float)):
        return b0

    # Standard clinical/research field strengths in Tesla
    known_strengths = [0.35, 0.55, 1.0, 1.5, 3.0, 7.0, 9.4, 10.5, 11.7]

    # Snap to a known strength if within 10% (2.89362 -> 3.0, 1.494 -> 1.5)
    for strength in known_strengths:
        if abs(b0 - strength) <= 0.10 * strength:
            return strength

    return round(float(b0), 3)


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


def _decode_sequence_type(pro_data: Dict[str, Any]) -> Union[str, List[str]]:
    """
    Decode Siemens sequence type using proper mapping with fallback.
    Based on XSL template from the provided code examples.
    
    Args:
        pro_data: Raw .pro data dictionary
        
    Returns:
        DICOM-compatible sequence type string or list of strings for compound sequences
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
    
    # Get base sequence type
    base_sequence = None
    
    # Try direct mapping first
    if seq_type and seq_type in seq_mapping:
        base_sequence = seq_mapping[seq_type]
    else:
        # Fallback: analyze protocol and sequence names
        protocol_lower = protocol_name.lower()
        sequence_lower = sequence_filename.lower()
        
        # Echo Planar sequences
        if any(term in protocol_lower or term in sequence_lower 
               for term in ["epi", "ep2d", "ep3d", "bold", "diff"]):
            base_sequence = "EP"
        
        # Spin Echo sequences (including TSE, HASTE)
        elif any(term in protocol_lower or term in sequence_lower 
               for term in ["tse", "haste", "space", "flair", "t2"]):
            base_sequence = "SE"
        
        # Default to GR if unknown
        else:
            base_sequence = "GR"
    
    # Check for inversion recovery preparation.
    # ucInversion enum: 1 = off, 4 = default/reapply (not IR), while 2 (MPRAGE-style
    # volume inversion) and >=8 (e.g. 8 = slice-selective FLAIR, 16 = MP2RAGE) are real
    # inversion-recovery modes. Only 1 and 4 are non-IR in observed protocols.
    ucInversion = extract_nested_value(pro_data, "sPrepPulses.ucInversion")

    if ucInversion == 2 or (isinstance(ucInversion, int) and ucInversion >= 8):
        return [base_sequence, "IR"]
    else:
        return base_sequence


def _physio_signal_method(pro_data: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """
    Return the selected physiological (lSignal1, lMethod1) selectors.

    lSignal1 bitmask: 1=None, 2=ECG, 4=Pulse, 8=External, 16=Respiratory.
    lMethod1: 1=None, others = triggered / gated / retro-gated.

    Both being 1 (or absent) means no physiological synchronisation is active. These
    are the only reliable indicators - the per-sensor lTriggerPulses/lRespGateThreshold
    fields carry non-zero defaults on every protocol.
    """
    signal = extract_nested_value(pro_data, "sPhysioImaging.lSignal1")
    method = extract_nested_value(pro_data, "sPhysioImaging.lMethod1")
    return signal, method


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

    # Physiological gating - only when a physio signal AND method are actually selected.
    # lSignal1 bitmask: 1=None, 2=ECG, 4=Pulse, 8=External, 16=Respiratory.
    # lMethod1: 1=None (anything else = triggered/gated/retro-gated).
    # The per-sensor lTriggerPulses/lRespGateThreshold fields default to 1/20 on every
    # protocol, so they cannot be used to decide whether gating is on.
    physio_signal, physio_method = _physio_signal_method(pro_data)
    if physio_signal not in (None, 0, 1) and physio_method not in (None, 0, 1):
        if physio_signal & 16:  # Respiratory Gating (RG)
            scan_options.append("RG")
        if physio_signal & 2:   # Cardiac Gating (CG)
            scan_options.append("CG")
        if physio_signal & 4:   # Peripheral Pulse Gating (PPG)
            scan_options.append("PPG")

    # Flow Compensation (FC). Per-echo acFlowComp values default to 1 (= off); a value
    # greater than 1 selects a flow-compensation mode (e.g. 16 on TOF, 2 on field maps).
    flow_comp = extract_nested_value(pro_data, "acFlowComp")
    if flow_comp and isinstance(flow_comp, list):
        if any(fc > 1 for fc in flow_comp if fc is not None):
            scan_options.append("FC")
    
    # Partial Fourier - Frequency (PFF)
    pf_readout = extract_nested_value(pro_data, "sKSpace.ucReadoutPartialFourier")
    if pf_readout and pf_readout < 16:  # 16 = off, < 16 = partial Fourier
        scan_options.append("PFF")
    
    # Partial Fourier - Phase (PFP)
    pf_phase = extract_nested_value(pro_data, "sKSpace.ucPhasePartialFourier")
    if pf_phase and pf_phase < 16:  # 16 = off, < 16 = partial Fourier
        scan_options.append("PFP")
    
    # Fat/water saturation - correct Siemens keys are ucFatSatMode / ucWaterSatMode
    # (value 1 = off, >1 = on). The old ucFatSat/ucWaterSat keys never exist, so fat
    # saturation was never detected.
    fat_sat = extract_nested_value(pro_data, "sPrepPulses.ucFatSatMode")
    water_sat = extract_nested_value(pro_data, "sPrepPulses.ucWaterSatMode")

    # Regional (spatial) saturation bands. The sRSatArray always contains default,
    # empty slots ({"ulShape": 1}); only elements with a real slab thickness are actual
    # saturation bands.
    rsat_elements = extract_nested_value(pro_data, "sRSatArray.asElm") or []
    real_rsat = [
        e for e in rsat_elements
        if isinstance(e, dict) and (e.get("dThickness") or 0) > 0
    ]

    # Spatial Presaturation (SP) - regional sat bands or water suppression
    if (water_sat and water_sat > 1) or len(real_rsat) > 0:
        scan_options.append("SP")

    # Fat Saturation (FS)
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
    if tof_inflow > 4 or pc_flow > 2:
        image_type.append("ANGIO")
    
    # Distortion correction
    distortion_corr = extract_nested_value(pro_data, "sDistortionCorrFilter.ucMode")
    if distortion_corr and distortion_corr > 1:  # > 1 = enabled
        image_type.append("DIS2D")
    
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
    
    # MTC (magnetization transfer contrast) - correct key is lMTCMode (1 = off, >1 = on)
    mtc_mode = extract_nested_value(pro_data, "sPrepPulses.lMTCMode")
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



def calculate_other_dicom_fields(dicom_data: Dict[str, Any], pro_data: Dict[str, Any]) -> None:
    """
    Add default values for DICOM fields that are expected but might not be mappable from .pro files.
    Calculate composite fields from .pro data where possible.
    """
    # Handle EchoTime array with lContrasts limiting
    echo_times_raw = extract_nested_value(pro_data, "alTE")
    contrasts = extract_nested_value(pro_data, "lContrasts")
    
    if echo_times_raw is not None:
        # Convert from microseconds to milliseconds
        if isinstance(echo_times_raw, list):
            echo_times_ms = [t/1000.0 for t in echo_times_raw]
            # Limit to lContrasts if available
            if contrasts is not None and contrasts > 0:
                echo_times_ms = echo_times_ms[:contrasts]
            # Return single value if only one, array if multiple
            if len(echo_times_ms) == 1:
                dicom_data["EchoTime"] = echo_times_ms[0]
            else:
                dicom_data["EchoTime"] = echo_times_ms
        else:
            # Single echo time
            dicom_data["EchoTime"] = echo_times_raw / 1000.0
    
    
    # Default values for Siemens .pro files
    defaults = {
        "Manufacturer": "Siemens",
    }
    
    for field, default_value in defaults.items():
        if field not in dicom_data:
            dicom_data[field] = default_value
    
    # ImagePositionPatient removed - represents actual patient positioning at scan time,
    # not predictable from protocol file alone
    
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
    
    # NumberOfPhaseEncodingSteps = Columns adjusted for partial Fourier
    if cols and "NumberOfPhaseEncodingSteps" not in dicom_data:
        # Get partial Fourier factor for phase encoding direction
        pf_phase_code = extract_nested_value(pro_data, "sKSpace.ucPhasePartialFourier") or 16
        pf_phase_fraction = _decode_partial_fourier(pf_phase_code)
        
        # Calculate actual number of phase encoding steps acquired
        # This is the k-space lines actually sampled (after partial Fourier, before parallel imaging)
        # Use traditional rounding (0.5 rounds up) to match DICOM behavior
        import math
        actual_pe_steps = int(math.floor(cols * pf_phase_fraction + 0.5))
        dicom_data["NumberOfPhaseEncodingSteps"] = actual_pe_steps
        
    # AcquisitionMatrix format: [freq_rows, freq_cols, phase_rows, phase_cols]
    # Construct based on actual phase encoding direction
    if rows and cols and "AcquisitionMatrix" not in dicom_data:
        # Get phase encoding direction to determine correct matrix format
        phase_encoding_direction = dicom_data.get("InPlanePhaseEncodingDirection")
        
        if phase_encoding_direction == "ROW":
            # Phase encoding in row direction, frequency in column direction
            dicom_data["AcquisitionMatrix"] = [0, rows, cols, 0]
        else:
            # Phase encoding in column direction (or unknown), frequency in row direction  
            dicom_data["AcquisitionMatrix"] = [rows, 0, 0, cols]
        
    # Calculate PixelSpacing if FOV data is available 
    fov_read = extract_nested_value(pro_data, "sSliceArray.asSlice.0.dReadoutFOV")
    fov_phase = extract_nested_value(pro_data, "sSliceArray.asSlice.0.dPhaseFOV")
    
    if all(v is not None for v in [fov_read, fov_phase, rows, cols]):
        pixel_spacing_read = fov_read / rows
        pixel_spacing_phase = fov_phase / cols
        dicom_data["PixelSpacing"] = [pixel_spacing_read, pixel_spacing_phase]
        
    # Calculate PercentPhaseFieldOfView using correct FOV ratio formula
    if fov_phase and fov_read and "PercentPhaseFieldOfView" not in dicom_data:
        # PercentPhaseFieldOfView = (Phase FOV / Readout FOV) * 100
        percent_phase_fov = (fov_phase / fov_read) * 100.0
        dicom_data["PercentPhaseFieldOfView"] = percent_phase_fov
        
    # Calculate PixelBandwidth using correct formula: 1 / (dwell_time * N_FE_effective)
    dwell_time = extract_nested_value(pro_data, "sRXSPEC.alDwellTime.0")  # in nanoseconds
    if dwell_time and "PixelBandwidth" not in dicom_data:
        # Get frequency encoding matrix size (typically rows = base resolution)
        frequency_encoding_pixels = rows or extract_nested_value(pro_data, "sKSpace.lBaseResolution")
        
        if frequency_encoding_pixels:
            # Check for readout oversampling
            remove_oversample = extract_nested_value(pro_data, "sSpecPara.ucRemoveOversampling")
            oversampling_factor = 2.0 if remove_oversample else 1.0
            
            # Calculate effective frequency encoding pixels
            effective_fe_pixels = frequency_encoding_pixels * oversampling_factor
            
            # Convert dwell time from nanoseconds to seconds
            dwell_time_sec = dwell_time * 1e-9
            
            # Calculate pixel bandwidth: PixelBW = 1 / (dwell_time * N_FE_effective)
            dicom_data["PixelBandwidth"] = 1.0 / (dwell_time_sec * effective_fe_pixels)
    
    # Calculate BandwidthPerPixelPhaseEncode from dwell time and phase encoding steps
    phase_steps = dicom_data.get("NumberOfPhaseEncodingSteps") or cols
    
    if dwell_time and phase_steps and "BandwidthPerPixelPhaseEncode" not in dicom_data:
        # Convert dwell time from nanoseconds to seconds, then calculate bandwidth
        dwell_time_sec = dwell_time / 1000000.0  # ns to μs to s 
        total_readout_time = dwell_time_sec * phase_steps
        if total_readout_time > 0:
            dicom_data["BandwidthPerPixelPhaseEncode"] = 1.0 / total_readout_time
            
    # Calculate ImagingFrequency from the TRUE main field, not the rounded
    # marketed MagneticFieldStrength (e.g. 2.89362 T -> 123.2 MHz, not 3.0 T -> 127.7 MHz)
    true_b0 = extract_nested_value(pro_data, "sProtConsistencyInfo.flNominalB0")
    if true_b0 is None:
        true_b0 = dicom_data.get("MagneticFieldStrength")
    if true_b0 and "ImagingFrequency" not in dicom_data:
        # Proton gyromagnetic ratio: 42.577 MHz/T for 1H
        dicom_data["ImagingFrequency"] = true_b0 * 42.577
        
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
            dicom_data["PatientPosition"] = position_mapping.get(patient_position, "Unknown")
            
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
        
    # Calculate PercentSampling following Siemens DICOM convention
    if "PercentSampling" not in dicom_data:
        # Siemens convention: PercentSampling = 100% for successful scan completion
        # Acceleration factors are encoded in separate DICOM fields
        dicom_data["PercentSampling"] = 100.0
        
        # Alternative calculation (physical k-space coverage):
        # This would give the actual fraction of full k-space sampled:
        #
        # accel_factor_pe = extract_nested_value(pro_data, "sPat.lAccelFactPE") or 1
        # accel_factor_3d = extract_nested_value(pro_data, "sPat.lAccelFact3D") or 1
        # pf_phase_code = extract_nested_value(pro_data, "sKSpace.ucPhasePartialFourier") or 16
        # pf_readout_code = extract_nested_value(pro_data, "sKSpace.ucReadoutPartialFourier") or 16
        # pf_phase_fraction = _decode_partial_fourier(pf_phase_code)
        # pf_readout_fraction = _decode_partial_fourier(pf_readout_code)
        #
        # percent_sampling = 100.0
        # if accel_factor_pe > 1:
        #     percent_sampling = percent_sampling / accel_factor_pe
        # if accel_factor_3d > 1:
        #     percent_sampling = percent_sampling / accel_factor_3d
        # if pf_phase_fraction < 1.0:
        #     percent_sampling = percent_sampling * pf_phase_fraction
        # if pf_readout_fraction < 1.0:
        #     percent_sampling = percent_sampling * pf_readout_fraction
        # dicom_data["PercentSampling"] = round(percent_sampling, 3)
        #
        # Example: GRAPPA R=2 + 6/8 PF would give 37.5% physical coverage
        
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
        
    # Handle InversionTime - only extract for sequences that use inversion recovery
    # Check if ScanningSequence contains IR
    if "InversionTime" not in dicom_data:
        scanning_sequence = dicom_data.get("ScanningSequence")
        uses_inversion = False
        
        if isinstance(scanning_sequence, list):
            uses_inversion = "IR" in scanning_sequence
        elif isinstance(scanning_sequence, str):
            uses_inversion = scanning_sequence == "IR"
        
        if uses_inversion:
            inversion_times_raw = extract_nested_value(pro_data, "alTI")
            if inversion_times_raw is not None:
                # Convert from microseconds to milliseconds (DICOM InversionTime is in ms,
                # like EchoTime/RepetitionTime)
                if isinstance(inversion_times_raw, list):
                    inversion_times_ms = [t/1000.0 for t in inversion_times_raw if t != 0]
                    # Return single value if only one, array if multiple
                    if len(inversion_times_ms) == 1:
                        dicom_data["InversionTime"] = inversion_times_ms[0]
                    elif len(inversion_times_ms) > 1:
                        dicom_data["InversionTime"] = inversion_times_ms
                else:
                    # Single inversion time, only if non-zero
                    if inversion_times_raw != 0:
                        dicom_data["InversionTime"] = inversion_times_raw / 1000.0
        
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
        contrasts = extract_nested_value(pro_data, "lContrasts")

        # Number of active echoes, honouring lContrasts (alTE is padded with unused slots)
        num_echoes = len(echo_times) if isinstance(echo_times, list) else 1
        if contrasts and contrasts > 0:
            num_echoes = min(num_echoes, contrasts)

        if turbo_factor > 1:
            # TSE/FSE sequence - RF echo train, no gradient echoes
            gradient_echo_train_length = 0
        elif epi_factor > 1:
            # EPI sequence - gradient echo train based on EPI factor
            gradient_echo_train_length = epi_factor
        elif num_echoes > 1 and sequence_type == 1:
            # Multi-echo GRE (Flash) - all echoes are gradient echoes
            gradient_echo_train_length = num_echoes
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
        contrasts = extract_nested_value(pro_data, "lContrasts")
        
        if turbo_factor > 1:
            # TSE/FSE sequence - use turbo factor
            # For segmented sequences (like GRASE), multiply by segments
            echo_train_length = turbo_factor * segments
        elif epi_factor > 1:
            # EPI sequence - use EPI factor
            echo_train_length = epi_factor
        elif contrasts and contrasts > 1:
            # Multi-echo sequence - use actual number of contrasts (preferred over alTE length)
            echo_train_length = contrasts
        elif isinstance(echo_times, list) and len(echo_times) > 1:
            # Multi-echo sequence (fallback) - use number of echo times defined
            echo_train_length = len(echo_times)
        else:
            # Standard single-echo sequences - 1 line per excitation
            echo_train_length = 1
            
        dicom_data["EchoTrainLength"] = echo_train_length
        
    # NumberOfTemporalPositions - only dynamic (multi-measurement) sequences have >1.
    # Siemens lRepetitions counts repetitions in addition to the first measurement, so
    # the number of temporal positions is lRepetitions + 1. Static scans have no
    # lRepetitions and get a single temporal position.
    if "NumberOfTemporalPositions" not in dicom_data:
        repetitions = extract_nested_value(pro_data, "lRepetitions")
        if repetitions and repetitions > 0:
            dicom_data["NumberOfTemporalPositions"] = repetitions + 1
        else:
            dicom_data["NumberOfTemporalPositions"] = 1

    # Calculate TemporalResolution for dynamic/multi-temporal sequences
    if "TemporalResolution" not in dicom_data:
        temporal_positions = dicom_data.get("NumberOfTemporalPositions", 1)
        tr_values = extract_nested_value(pro_data, "alTR") or []

        if temporal_positions > 1 and tr_values:
            # Convert from microseconds to milliseconds for temporal resolution
            temporal_resolution = tr_values[0] / 1000.0
            dicom_data["TemporalResolution"] = temporal_resolution

    # TimeOfFlightContrast - ucTOFInflow defaults to 4 on every protocol and cannot
    # distinguish TOF angiography, so rely on the sequence/protocol name (with the raw
    # value only as a strong secondary signal).
    if "TimeOfFlightContrast" not in dicom_data:
        protocol_name = (extract_nested_value(pro_data, "tProtocolName") or "").lower()
        sequence_name = (extract_nested_value(pro_data, "tSequenceFileName") or "").lower()
        tof_inflow = extract_nested_value(pro_data, "sAngio.ucTOFInflow") or 0
        is_tof = "tof" in protocol_name or "tof" in sequence_name or tof_inflow > 4
        dicom_data["TimeOfFlightContrast"] = "YES" if is_tof else "NO"

    # Triggering/Gating - only emit when a physio signal + method are actually selected.
    if "TriggerSourceOrType" not in dicom_data:
        physio_signal, physio_method = _physio_signal_method(pro_data)
        if physio_signal not in (None, 0, 1) and physio_method not in (None, 0, 1):
            signal_sources = {2: ("ECG", "sPhysioECG"), 4: ("PULSE", "sPhysioPulse"),
                              8: ("EXT", "sPhysioExt"), 16: ("RESP", "sPhysioResp")}
            for bit, (source, sensor) in signal_sources.items():
                if physio_signal & bit:
                    dicom_data["TriggerSourceOrType"] = source
                    window = extract_nested_value(
                        pro_data, f"sPhysioImaging.{sensor}.lTriggerWindow")
                    if window is not None and "TriggerTime" not in dicom_data:
                        dicom_data["TriggerTime"] = window
                    break


