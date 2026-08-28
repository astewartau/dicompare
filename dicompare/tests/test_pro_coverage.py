"""
Additional coverage tests for dicompare/io/pro.py.

These tests target the pure helper functions (sequence/image type detection,
version/partial-Fourier/b-value decoding, physio detection), the schema-format
generation helpers, and the .exar1 archive path. They use small synthetic
pro_data dicts to hit specific branches and synthesize a tiny SQLite .exar1
archive so the DB-read code path is exercised without a real fixture.

They deliberately avoid duplicating what test_pro_files.py already covers.
"""

import sqlite3
import zlib
import json
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from dicompare.io import pro as pro_mod
from dicompare.io.pro import (
    apply_pro_to_dicom_mapping,
    calculate_other_dicom_fields,
    extract_nested_value,
    _decode_siemens_version,
    _decode_partial_fourier,
    _nominal_field_strength,
    _extract_unique_b_values,
    _decode_sequence_type,
    _physio_signal_method,
    _detect_scan_options,
    _detect_image_type,
    _detect_sequence_variant,
    _determine_image_types_for_series,
    _extract_series_parameters,
    _generate_series_combinations,
    _classify_fields,
    _convert_flat_to_schema_format,
    load_pro_file,
    load_pro_file_schema_format,
    load_pro_session,
    load_pro_session_simple,
    _decompress_raw_deflate,
    _extract_protocol_text_from_xprotocol,
    _describe_exar_contents,
    _extract_protocols_from_exar,
    load_exar_file,
    load_exar_file_schema_format,
    load_exar_session,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pro_files"


# ---------------------------------------------------------------------------
# extract_nested_value
# ---------------------------------------------------------------------------

class TestExtractNestedValue:
    def test_simple_and_nested(self):
        data = {"a": {"b": {"c": 5}}}
        assert extract_nested_value(data, "a.b.c") == 5

    def test_list_index(self):
        data = {"a": [{"x": 1}, {"x": 2}]}
        assert extract_nested_value(data, "a.1.x") == 2

    def test_missing_key_returns_none(self):
        assert extract_nested_value({"a": 1}, "a.b") is None
        assert extract_nested_value({"a": 1}, "z") is None

    def test_list_index_out_of_range(self):
        assert extract_nested_value({"a": [1]}, "a.5") is None

    def test_index_into_non_list(self):
        assert extract_nested_value({"a": {"b": 1}}, "a.0") is None

    def test_none_current_short_circuits(self):
        assert extract_nested_value({"a": None}, "a.b.c") is None


# ---------------------------------------------------------------------------
# _decode_siemens_version
# ---------------------------------------------------------------------------

class TestDecodeSiemensVersion:
    def test_decimal_exact_match(self):
        assert _decode_siemens_version(21710006) == "VB17A"
        assert _decode_siemens_version(51130001) == "VE12U"

    def test_hex_exact_match(self):
        assert _decode_siemens_version(0xbee332) == "VA25A"

    def test_string_hex_input(self):
        assert _decode_siemens_version("0xbee332") == "VA25A"

    def test_string_decimal_input(self):
        assert _decode_siemens_version("21710006") == "VB17A"

    def test_infer_newest(self):
        assert _decode_siemens_version(70000000) == "VE12U+"

    def test_infer_ve12u_range(self):
        assert _decode_siemens_version(51290000) == "VE12U"

    def test_infer_ve11x_range(self):
        assert _decode_siemens_version(51000000) == "VE11x"

    def test_infer_vd_range(self):
        assert _decode_siemens_version(45000000) == "VDxx"

    def test_infer_vb_range(self):
        assert _decode_siemens_version(25000000) == "VBxx"

    def test_infer_va_or_older(self):
        assert _decode_siemens_version(1000) == "VAxx"


# ---------------------------------------------------------------------------
# _decode_partial_fourier
# ---------------------------------------------------------------------------

class TestDecodePartialFourier:
    @pytest.mark.parametrize("mode,expected", [
        (1, 0.5), (2, 0.625), (4, 0.75), (8, 0.875), (16, 1.0), (32, 1.0),
    ])
    def test_int_modes(self, mode, expected):
        assert _decode_partial_fourier(mode) == expected

    def test_string_mode(self):
        assert _decode_partial_fourier("0x4") == 0.75

    def test_unknown_defaults_to_full(self):
        assert _decode_partial_fourier(999) == 1.0


# ---------------------------------------------------------------------------
# _nominal_field_strength (non-numeric branch)
# ---------------------------------------------------------------------------

class TestNominalFieldStrengthExtra:
    def test_non_numeric_passthrough(self):
        assert _nominal_field_strength("3T") == "3T"


# ---------------------------------------------------------------------------
# _extract_unique_b_values
# ---------------------------------------------------------------------------

class TestExtractUniqueBValues:
    def test_empty_nested_is_b0(self):
        assert _extract_unique_b_values([[]]) == [0.0]

    def test_nested_values(self):
        assert _extract_unique_b_values([[1000], [2000, 1000]]) == [1000.0, 2000.0]

    def test_direct_values(self):
        assert _extract_unique_b_values([0, 1000, 1000]) == [0.0, 1000.0]

    def test_ignores_negative(self):
        assert _extract_unique_b_values([-1, 500]) == [500.0]

    def test_mixed(self):
        assert _extract_unique_b_values([[], [1000], 2000]) == [0.0, 1000.0, 2000.0]


# ---------------------------------------------------------------------------
# _decode_sequence_type
# ---------------------------------------------------------------------------

class TestDecodeSequenceType:
    def test_direct_mapping_gr(self):
        assert _decode_sequence_type({"ucSequenceType": 1}) == "GR"

    def test_direct_mapping_ep(self):
        assert _decode_sequence_type({"ucSequenceType": 4}) == "EP"

    def test_direct_mapping_se(self):
        assert _decode_sequence_type({"ucSequenceType": 8}) == "SE"

    def test_fallback_epi_name(self):
        assert _decode_sequence_type({"tProtocolName": "ep2d_bold"}) == "EP"

    def test_fallback_se_name(self):
        assert _decode_sequence_type({"tSequenceFileName": "tse_t2"}) == "SE"

    def test_fallback_default_gr(self):
        assert _decode_sequence_type({"tProtocolName": "something_else"}) == "GR"

    def test_inversion_mode_2_adds_ir(self):
        result = _decode_sequence_type({"ucSequenceType": 1,
                                        "sPrepPulses": {"ucInversion": 2}})
        assert result == ["GR", "IR"]

    def test_inversion_mode_ge_8_adds_ir(self):
        result = _decode_sequence_type({"ucSequenceType": 8,
                                        "sPrepPulses": {"ucInversion": 16}})
        assert result == ["SE", "IR"]

    def test_inversion_mode_4_not_ir(self):
        result = _decode_sequence_type({"ucSequenceType": 1,
                                        "sPrepPulses": {"ucInversion": 4}})
        assert result == "GR"


# ---------------------------------------------------------------------------
# _physio_signal_method
# ---------------------------------------------------------------------------

class TestPhysioSignalMethod:
    def test_returns_values(self):
        data = {"sPhysioImaging": {"lSignal1": 2, "lMethod1": 4}}
        assert _physio_signal_method(data) == (2, 4)

    def test_absent_returns_none(self):
        assert _physio_signal_method({}) == (None, None)


# ---------------------------------------------------------------------------
# _detect_scan_options - specific branches
# ---------------------------------------------------------------------------

class TestDetectScanOptions:
    def test_per_reordering(self):
        assert "PER" in _detect_scan_options({"sKSpace": {"unReordering": 2}})

    def test_respiratory_gating(self):
        data = {"sPhysioImaging": {"lSignal1": 16, "lMethod1": 4}}
        assert "RG" in _detect_scan_options(data)

    def test_peripheral_pulse_gating(self):
        data = {"sPhysioImaging": {"lSignal1": 4, "lMethod1": 4}}
        assert "PPG" in _detect_scan_options(data)

    def test_partial_fourier_freq_and_phase(self):
        data = {"sKSpace": {"ucReadoutPartialFourier": 4, "ucPhasePartialFourier": 8}}
        opts = _detect_scan_options(data)
        assert "PFF" in opts and "PFP" in opts

    def test_water_sat_spatial_presat(self):
        data = {"sPrepPulses": {"ucWaterSatMode": 2}}
        assert "SP" in _detect_scan_options(data)

    def test_empty_returns_empty_list(self):
        assert _detect_scan_options({}) == []


# ---------------------------------------------------------------------------
# _detect_image_type - recon modes
# ---------------------------------------------------------------------------

class TestDetectImageType:
    def test_magnitude_default(self):
        it = _detect_image_type({"ucReconstructionMode": 1})
        assert it[:3] == ["ORIGINAL", "PRIMARY", "M"]

    def test_phase_only(self):
        it = _detect_image_type({"ucReconstructionMode": 2})
        assert "P" in it and "M" not in it[2:4]

    def test_real_part(self):
        it = _detect_image_type({"ucReconstructionMode": 4})
        assert "R" in it

    def test_mag_and_phase(self):
        it = _detect_image_type({"ucReconstructionMode": 8})
        assert "M" in it and "P" in it

    def test_real_and_phase(self):
        it = _detect_image_type({"ucReconstructionMode": 10})
        assert "P" in it and "R" in it

    def test_unknown_recon_defaults_m(self):
        it = _detect_image_type({"ucReconstructionMode": 99})
        assert "M" in it

    def test_norm_flag(self):
        it = _detect_image_type({"ucReconstructionMode": 1,
                                 "sPreScanNormalizeFilter": {"ucMode": 2}})
        assert "NORM" in it

    def test_nd_flag(self):
        it = _detect_image_type({"ucReconstructionMode": 1})
        assert "ND" in it

    def test_angio_flag(self):
        it = _detect_image_type({"ucReconstructionMode": 1,
                                 "sAngio": {"ucTOFInflow": 8}})
        assert "ANGIO" in it

    def test_distortion_correction_flag(self):
        it = _detect_image_type({"ucReconstructionMode": 1,
                                 "sDistortionCorrFilter": {"ucMode": 2}})
        assert "DIS2D" in it


# ---------------------------------------------------------------------------
# _detect_sequence_variant - many branches
# ---------------------------------------------------------------------------

class TestDetectSequenceVariant:
    def test_none_when_nothing(self):
        assert _detect_sequence_variant({"tProtocolName": "plain",
                                         "ucSequenceType": 99}) is None

    def test_mp_from_inversion_mode(self):
        v = _detect_sequence_variant({"tProtocolName": "irtse",
                                      "sPrepPulses": {"ucInversion": 8}})
        assert "MP" in v

    def test_mp_from_meaningful_ti(self):
        v = _detect_sequence_variant({"tProtocolName": "irscan",
                                      "alTI": [1000000.0]})
        assert "MP" in v

    def test_non_mp_sequence_suppresses_mp(self):
        v = _detect_sequence_variant({"tProtocolName": "bold_epi",
                                      "alTI": [1000000.0]}) or []
        assert "MP" not in v

    def test_mtc(self):
        v = _detect_sequence_variant({"tProtocolName": "x",
                                      "sPrepPulses": {"lMTCMode": 2}})
        assert "MTC" in v

    def test_sk_from_segments(self):
        v = _detect_sequence_variant({"tProtocolName": "x",
                                      "sFastImaging": {"lSegments": 4}})
        assert "SK" in v

    def test_osp_from_phase_os(self):
        v = _detect_sequence_variant({"tProtocolName": "x",
                                      "sSpecPara": {"dPhaseOS": 1.5}})
        assert "OSP" in v

    def test_ss_from_sequence_type_2(self):
        v = _detect_sequence_variant({"tProtocolName": "x", "ucSequenceType": 2})
        assert "SS" in v

    def test_sp_from_multi_echo_gre(self):
        v = _detect_sequence_variant({"tProtocolName": "x", "ucSequenceType": 1,
                                      "alTE": [2000, 5000]})
        assert "SP" in v

    def test_ep_from_epi_factor(self):
        v = _detect_sequence_variant({"tProtocolName": "x",
                                      "sFastImaging": {"lEPIFactor": 64}})
        assert "EP" in v

    def test_mp_from_name_additive(self):
        v = _detect_sequence_variant({"tProtocolName": "t1_mprage"})
        assert "MP" in v

    def test_sp_from_name_additive(self):
        v = _detect_sequence_variant({"tProtocolName": "flash_2d"})
        assert "SP" in v

    def test_sk_from_name_additive(self):
        v = _detect_sequence_variant({"tProtocolName": "haste_cor"})
        assert "SK" in v

    def test_ep_from_name_additive(self):
        v = _detect_sequence_variant({"tProtocolName": "ep2d_diff"})
        assert "EP" in v

    def test_mtc_from_name_additive(self):
        v = _detect_sequence_variant({"tProtocolName": "mtc_prep"})
        assert "MTC" in v

    def test_ss_from_name_additive(self):
        v = _detect_sequence_variant({"tProtocolName": "trufi_cine"})
        assert "SS" in v

    def test_ss_name_additive_without_type2(self):
        # 'ssfp' in name but ucSequenceType != 2 -> SS added via additive branch
        v = _detect_sequence_variant({"tProtocolName": "my_ssfp_scan",
                                      "ucSequenceType": 1})
        assert "SS" in v

    def test_localizer_adds_sp_osp(self):
        v = _detect_sequence_variant({"tProtocolName": "localizer"})
        assert "SP" in v and "OSP" in v


# ---------------------------------------------------------------------------
# apply_pro_to_dicom_mapping - converters
# ---------------------------------------------------------------------------

class TestApplyProToDicomMapping:
    def test_tr_list_multiple(self):
        d = apply_pro_to_dicom_mapping({"alTR": [2000000, 3000000]})
        assert d["RepetitionTime"] == [2000.0, 3000.0]

    def test_tr_single_element_list(self):
        d = apply_pro_to_dicom_mapping({"alTR": [2000000]})
        assert d["RepetitionTime"] == 2000.0

    def test_tr_scalar(self):
        d = apply_pro_to_dicom_mapping({"alTR": 2000000})
        assert d["RepetitionTime"] == 2000.0

    def test_pat_mode_grappa(self):
        d = apply_pro_to_dicom_mapping({"sPat": {"ucPATMode": 2}})
        assert d["ParallelAcquisitionTechnique"] == "GRAPPA"

    def test_pat_mode_msense(self):
        # IDEA PATSelMode: 0x04 is (m)SENSE.
        d = apply_pro_to_dicom_mapping({"sPat": {"ucPATMode": 4}})
        assert d["ParallelAcquisitionTechnique"] == "mSENSE"

    def test_pat_mode_none_drops_field(self):
        # 0x01 means PAT off; real DICOM omits the field entirely.
        d = apply_pro_to_dicom_mapping({"sPat": {"ucPATMode": 1}})
        assert "ParallelAcquisitionTechnique" not in d

    def test_pat_mode_slice_accel_drops_field(self):
        # 0x20: product SMS-framework mode; no technique emitted (factors
        # carry the quantitative info), matching dcm2niix behaviour.
        d = apply_pro_to_dicom_mapping({"sPat": {"ucPATMode": 32}})
        assert "ParallelAcquisitionTechnique" not in d

    def test_phase_encoding_row(self):
        d = apply_pro_to_dicom_mapping({"sSpecPara": {"lPhaseEncodingType": 1}})
        assert d["InPlanePhaseEncodingDirection"] == "ROW"

    def test_phase_encoding_col(self):
        d = apply_pro_to_dicom_mapping({"sSpecPara": {"lPhaseEncodingType": 2}})
        assert d["InPlanePhaseEncodingDirection"] == "COL"

    def test_angio_flag(self):
        d = apply_pro_to_dicom_mapping({"sAngio": {"ucPCFlowMode": 4}})
        assert d["AngioFlag"] == "Y"

    def test_bvalue_mapping(self):
        d = apply_pro_to_dicom_mapping({"sDiffusion": {"alBValue": [[], [1000]]}})
        assert d["DiffusionBValue"] == [0.0, 1000.0]

    def test_software_version_mapping(self):
        d = apply_pro_to_dicom_mapping({"ulVersion": 21710006})
        assert d["SoftwareVersion"] == "VB17A"

    def test_field_strength_mapping(self):
        d = apply_pro_to_dicom_mapping(
            {"sProtConsistencyInfo": {"flNominalB0": 2.89362}})
        assert d["MagneticFieldStrength"] == 3.0


# ---------------------------------------------------------------------------
# calculate_other_dicom_fields - many derived-field branches
# ---------------------------------------------------------------------------

class TestCalculateOtherDicomFields:
    def test_echo_time_single_from_list(self):
        d = {}
        calculate_other_dicom_fields(d, {"alTE": [5000], "lContrasts": 1})
        assert d["EchoTime"] == 5.0

    def test_echo_time_scalar(self):
        d = {}
        calculate_other_dicom_fields(d, {"alTE": 5000})
        assert d["EchoTime"] == 5.0

    def test_echo_time_multi_limited_by_contrasts(self):
        d = {}
        calculate_other_dicom_fields(d, {"alTE": [5000, 10000, 15000], "lContrasts": 2})
        assert d["EchoTime"] == [5.0, 10.0]

    def test_slice_normal(self):
        d = {}
        calculate_other_dicom_fields(d, {
            "sSliceArray": {"asSlice": [{"sNormal": {"dSag": 1.0, "dCor": 0.0, "dTra": 0.0}}]}})
        assert d["SliceNormal"] == [1.0, 0.0, 0.0]

    def test_slices_3d_partitions(self):
        d = {}
        calculate_other_dicom_fields(d, {"sKSpace": {"lPartitions": 64}})
        assert d["Slices"] == 64

    def test_slices_3d_images_per_slab(self):
        d = {}
        calculate_other_dicom_fields(d, {"sKSpace": {"lImagesPerSlab": 100}})
        assert d["Slices"] == 100

    def test_slices_2d_slice_array(self):
        d = {}
        calculate_other_dicom_fields(d, {"sSliceArray": {"lSize": 30}})
        assert d["Slices"] == 30

    def test_acquisition_matrix_row(self):
        d = {"Rows": 128, "Columns": 96, "InPlanePhaseEncodingDirection": "ROW"}
        calculate_other_dicom_fields(d, {})
        assert d["AcquisitionMatrix"] == [0, 128, 96, 0]

    def test_acquisition_matrix_col(self):
        d = {"Rows": 128, "Columns": 96}
        calculate_other_dicom_fields(d, {})
        assert d["AcquisitionMatrix"] == [128, 0, 0, 96]

    def test_pixel_spacing_and_percent_phase_fov(self):
        d = {"Rows": 100, "Columns": 100}
        calculate_other_dicom_fields(d, {
            "sSliceArray": {"asSlice": [{"dReadoutFOV": 200.0, "dPhaseFOV": 150.0}]}})
        assert d["PixelSpacing"] == [2.0, 1.5]
        assert d["PercentPhaseFieldOfView"] == pytest.approx(75.0)

    def test_pixel_bandwidth_with_oversampling(self):
        d = {"Rows": 128, "Columns": 128}
        calculate_other_dicom_fields(d, {
            "sRXSPEC": {"alDwellTime": [10000]},
            "sSpecPara": {"ucRemoveOversampling": 1}})
        assert "PixelBandwidth" in d
        assert "BandwidthPerPixelPhaseEncode" in d

    def test_slice_thickness_3d(self):
        d = {}
        calculate_other_dicom_fields(d, {
            "sSliceArray": {"asSlice": [{"dThickness": 160.0}]},
            "sKSpace": {"lImagesPerSlab": 80}})
        assert d["SliceThickness"] == 2.0
        assert d["SlabThickness"] == 160.0
        assert d["MRAcquisitionType"] == "3D"

    def test_slice_thickness_2d(self):
        d = {}
        calculate_other_dicom_fields(d, {
            "sSliceArray": {"asSlice": [{"dThickness": 3.0}]}})
        assert d["SliceThickness"] == 3.0
        assert d["MRAcquisitionType"] == "2D"

    def test_spacing_between_slices(self):
        d = {"SliceThickness": 4.0}
        calculate_other_dicom_fields(d, {
            "sGroupArray": {"asGroup": [{"dDistFact": 0.2}]}})
        assert d["SpacingBetweenSlices"] == pytest.approx(4.8)

    def test_patient_position_mapping(self):
        d = {}
        calculate_other_dicom_fields(d, {"sPatientPosition": {"ucPatientPosition": 1}})
        assert d["PatientPosition"] == "HFS"

    def test_patient_position_unknown(self):
        d = {}
        calculate_other_dicom_fields(d, {"sPatientPosition": {"ucPatientPosition": 99}})
        assert d["PatientPosition"] == "Unknown"

    def test_acquisition_time(self):
        d = {}
        calculate_other_dicom_fields(d, {"sMeasStartTime": {"lTime": 3661500}})
        # 1h 1m 1s 500ms
        assert d["AcquisitionTime"] == "010101.500000"

    def test_partial_fourier_yes_phase(self):
        d = {}
        calculate_other_dicom_fields(d, {"sKSpace": {"ucPhasePartialFourier": 8}})
        assert d["PartialFourier"] == "YES"
        assert d["PartialFourierDirection"] == "PHASE"

    def test_partial_fourier_frequency(self):
        d = {}
        calculate_other_dicom_fields(d, {"sKSpace": {"ucReadoutPartialFourier": 8}})
        assert d["PartialFourierDirection"] == "FREQUENCY"

    def test_partial_fourier_slice(self):
        d = {}
        calculate_other_dicom_fields(d, {"sKSpace": {"ucSlicePartialFourier": 8}})
        assert d["PartialFourierDirection"] == "SLICE_SELECT"

    def test_partial_fourier_combination(self):
        d = {}
        calculate_other_dicom_fields(d, {
            "sKSpace": {"ucPhasePartialFourier": 8, "ucReadoutPartialFourier": 4}})
        assert d["PartialFourierDirection"] == "COMBINATION"

    def test_partial_fourier_no(self):
        d = {}
        calculate_other_dicom_fields(d, {"sKSpace": {"ucPhasePartialFourier": 16}})
        assert d["PartialFourier"] == "NO"
        assert "PartialFourierDirection" not in d

    def test_temporal_resolution(self):
        d = {}
        calculate_other_dicom_fields(d, {"lRepetitions": 10, "alTR": [2000000]})
        assert d["NumberOfTemporalPositions"] == 11
        assert d["TemporalResolution"] == 2000.0

    def test_gradient_echo_train_length_tse(self):
        d = {}
        calculate_other_dicom_fields(d, {"sFastImaging": {"lTurboFactor": 8}})
        assert d["GradientEchoTrainLength"] == 0

    def test_gradient_echo_train_length_epi(self):
        d = {}
        calculate_other_dicom_fields(d, {"sFastImaging": {"lEPIFactor": 64}})
        assert d["GradientEchoTrainLength"] == 64

    def test_gradient_echo_train_length_multi_echo_gre(self):
        d = {}
        calculate_other_dicom_fields(d, {
            "ucSequenceType": 1, "alTE": [2000, 5000, 8000], "lContrasts": 3})
        assert d["GradientEchoTrainLength"] == 3

    def test_gradient_echo_train_length_single_gre(self):
        d = {}
        calculate_other_dicom_fields(d, {"ucSequenceType": 1, "alTE": [2000]})
        assert d["GradientEchoTrainLength"] == 1

    def test_echo_train_length_tse_segmented(self):
        d = {}
        calculate_other_dicom_fields(d, {
            "sFastImaging": {"lTurboFactor": 4, "lSegments": 2}})
        assert d["EchoTrainLength"] == 8

    def test_echo_train_length_epi(self):
        d = {}
        calculate_other_dicom_fields(d, {"sFastImaging": {"lEPIFactor": 32}})
        assert d["EchoTrainLength"] == 32

    def test_echo_train_length_contrasts(self):
        d = {}
        calculate_other_dicom_fields(d, {"lContrasts": 4, "alTE": [1, 2, 3, 4, 5]})
        assert d["EchoTrainLength"] == 4

    def test_echo_train_length_from_alte_length(self):
        d = {}
        calculate_other_dicom_fields(d, {"alTE": [1000, 2000]})
        assert d["EchoTrainLength"] == 2

    def test_multiple_inversion_times_ir(self):
        # MP2RAGE-style: ucInversion=16 -> IR, two TIs -> list of TIs in ms
        d = {}
        calculate_other_dicom_fields(d, {
            "ucSequenceType": 1,
            "sPrepPulses": {"ucInversion": 16},
            "alTI": [900000, 2750000]})
        assert d["InversionTime"] == [900.0, 2750.0]

    def test_scalar_inversion_time_ir(self):
        # scalar alTI (non-list) with IR sequence -> single ms value
        d = {}
        calculate_other_dicom_fields(d, {
            "ucSequenceType": 1,
            "sPrepPulses": {"ucInversion": 8},
            "alTI": 1000000})
        assert d["InversionTime"] == 1000.0

    def test_trigger_source_and_time(self):
        d = {}
        calculate_other_dicom_fields(d, {
            "sPhysioImaging": {"lSignal1": 2, "lMethod1": 4,
                               "sPhysioECG": {"lTriggerWindow": 50}}})
        assert d["TriggerSourceOrType"] == "ECG"
        assert d["TriggerTime"] == 50


# ---------------------------------------------------------------------------
# Schema-format helpers
# ---------------------------------------------------------------------------

class TestDetermineImageTypesForSeries:
    def test_mag_phase_recon8(self):
        types = _determine_image_types_for_series(8, {"ImageType": ["ORIGINAL", "PRIMARY", "M"]})
        assert len(types) == 2
        assert any("P" in t for t in types)

    def test_phase_only_recon2(self):
        types = _determine_image_types_for_series(2, {"ImageType": ["ORIGINAL", "PRIMARY", "M"]})
        assert len(types) == 1
        assert "P" in types[0]

    def test_magnitude_default(self):
        types = _determine_image_types_for_series(1, {})
        assert len(types) == 1
        assert "M" in types[0]

    def test_mag_phase_appends_missing(self):
        # base without M or P forces the append branches
        types = _determine_image_types_for_series(8, {"ImageType": ["ORIGINAL", "PRIMARY"]})
        assert "M" in types[0] and "P" in types[1]

    def test_phase_only_appends_missing(self):
        types = _determine_image_types_for_series(2, {"ImageType": ["ORIGINAL", "PRIMARY"]})
        assert "P" in types[0]

    def test_magnitude_appends_missing(self):
        types = _determine_image_types_for_series(1, {"ImageType": ["ORIGINAL", "PRIMARY"]})
        assert "M" in types[0]


class TestExtractSeriesParameters:
    def test_multi_echo_creates_series(self):
        params = _extract_series_parameters({"EchoTime": [2.5, 5.0]}, {})
        assert params["EchoTime"] == [2.5, 5.0]

    def test_single_echo_no_series(self):
        params = _extract_series_parameters({"EchoTime": 2.5}, {})
        assert params == {}

    def test_mag_phase_recon_creates_image_type_series(self):
        params = _extract_series_parameters(
            {"EchoTime": 2.5, "ImageType": ["ORIGINAL", "PRIMARY", "M"]},
            {"ucReconstructionMode": 8})
        assert "ImageType" in params
        # single echo added back once series-creating params exist
        assert params["EchoTime"] == [2.5]

    def test_multi_inversion_times(self):
        params = _extract_series_parameters({"InversionTime": [0.9, 2.75]}, {})
        assert params["InversionTime"] == [0.9, 2.75]

    def test_scalar_inversion_with_multi_echo(self):
        # scalar InversionTime hits the elif branch; stays at acquisition level
        params = _extract_series_parameters(
            {"EchoTime": [2.5, 5.0], "InversionTime": 0.9}, {})
        assert "EchoTime" in params
        assert "InversionTime" not in params

    def test_single_echo_list_added_back(self):
        params = _extract_series_parameters(
            {"EchoTime": [2.5], "InversionTime": [0.9, 2.75]}, {})
        assert params["EchoTime"] == [2.5]


class TestGenerateSeriesCombinations:
    def test_empty_returns_empty(self):
        assert _generate_series_combinations({}) == []

    def test_single_param(self):
        series = _generate_series_combinations({"EchoTime": [2.5, 5.0]})
        assert len(series) == 2
        assert series[0]["name"] == "Series 01"
        assert series[0]["fields"][0] == {"field": "EchoTime", "value": 2.5}

    def test_cartesian_product(self):
        series = _generate_series_combinations({
            "EchoTime": [2.5, 5.0],
            "ImageType": [["ORIGINAL", "PRIMARY", "M"], ["ORIGINAL", "PRIMARY", "P"]]})
        assert len(series) == 4

    def test_other_param_ordering(self):
        series = _generate_series_combinations({"CustomParam": [1, 2]})
        assert len(series) == 2
        assert series[0]["fields"][0]["field"] == "CustomParam"


class TestClassifyFields:
    def test_skips_metadata_and_empty_and_none(self):
        dicom = {"ProtocolName": "x", "PRO_Path": "/a", "PRO_FileName": "a.pro",
                 "SeriesDescription": "", "Missing": None, "EchoTime": 2.5}
        acq, series_varying = _classify_fields(dicom, {"EchoTime": [2.5, 5.0]})
        field_names = {f["field"] for f in acq}
        assert "ProtocolName" in field_names
        assert "PRO_Path" not in field_names
        assert "SeriesDescription" not in field_names
        assert "Missing" not in field_names
        assert "EchoTime" not in field_names  # series-varying
        assert "EchoTime" in series_varying


class TestConvertFlatToSchemaFormat:
    def test_structure(self):
        dicom = {"ProtocolName": "test", "EchoTime": [2.5, 5.0]}
        result = _convert_flat_to_schema_format(dicom, {}, "/tmp/x.pro")
        assert result["acquisition_info"]["protocol_name"] == "test"
        assert result["acquisition_info"]["source_type"] == "pro_file"
        assert result["acquisition_info"]["pro_filename"] == "x.pro"
        assert len(result["series"]) == 2
        assert isinstance(result["fields"], list)


# ---------------------------------------------------------------------------
# .pro loader error paths and schema format on real fixtures
# ---------------------------------------------------------------------------

class TestProLoaderErrorPaths:
    def test_load_pro_file_parse_error(self, tmp_path, monkeypatch):
        bad = tmp_path / "bad.pro"
        bad.write_text("### ASCCONV BEGIN ###\nalTE[0] = 5\n### ASCCONV END ###\n")

        def boom(*a, **k):
            raise ValueError("parse blew up")

        monkeypatch.setattr(pro_mod, "parse_buffer", boom)
        with pytest.raises(Exception, match="Failed to parse .pro file"):
            load_pro_file(str(bad))

    def test_load_pro_file_schema_format_parse_error(self, tmp_path, monkeypatch):
        bad = tmp_path / "bad2.pro"
        bad.write_text("### ASCCONV BEGIN ###\nalTE[0] = 5\n### ASCCONV END ###\n")

        def boom(*a, **k):
            raise ValueError("parse blew up")

        monkeypatch.setattr(pro_mod, "parse_buffer", boom)
        with pytest.raises(Exception, match="Failed to parse .pro file"):
            load_pro_file_schema_format(str(bad))

    def test_load_pro_file_schema_format_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            load_pro_file_schema_format(str(FIXTURES_DIR / "nope.pro"))

    def test_load_pro_file_schema_format_real_fixture(self):
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"
        result = load_pro_file_schema_format(str(pro_file))
        assert "acquisition_info" in result
        assert "series" in result
        assert result["acquisition_info"]["source_type"] == "pro_file"


class TestProSessionSimple:
    def test_no_source_raises(self):
        with pytest.raises(ValueError, match="Either session_dir or pro_files"):
            load_pro_session_simple()

    def test_pro_files_list(self):
        files = [str(p) for p in FIXTURES_DIR.glob("*.pro")]
        df = load_pro_session_simple(pro_files=files)
        assert isinstance(df, pd.DataFrame)
        assert "Acquisition" in df.columns

    def test_progress_callback(self):
        files = [str(p) for p in FIXTURES_DIR.glob("*.pro")]
        seen = []
        load_pro_session_simple(pro_files=files, progress_function=seen.append)
        assert seen and seen[-1] == 100

    def test_failed_file_warns_and_continues(self, tmp_path, monkeypatch, capsys):
        good = str(next(FIXTURES_DIR.glob("*.pro")))
        real = pro_mod.load_pro_file

        def maybe_fail(path):
            if path == "FAKE.pro":
                raise RuntimeError("nope")
            return real(path)

        monkeypatch.setattr(pro_mod, "load_pro_file", maybe_fail)
        df = load_pro_session_simple(pro_files=["FAKE.pro", good])
        assert len(df) == 1
        assert "Failed to load" in capsys.readouterr().out

    def test_all_fail_raises(self, tmp_path, monkeypatch):
        def boom(path):
            raise RuntimeError("nope")

        monkeypatch.setattr(pro_mod, "load_pro_file", boom)
        with pytest.raises(ValueError, match="No valid .pro files"):
            load_pro_session_simple(pro_files=["a.pro"])


# ---------------------------------------------------------------------------
# EXAR: pure helpers
# ---------------------------------------------------------------------------

class TestExarHelpers:
    def test_decompress_raw_deflate_roundtrip(self):
        raw = b"hello protocol world"
        comp = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        data = comp.compress(raw) + comp.flush()
        assert _decompress_raw_deflate(data) == raw

    def test_decompress_raw_deflate_invalid(self):
        assert _decompress_raw_deflate(b"not compressed") is None

    def test_extract_protocol_text_json_wrapper(self):
        wrapped = ('EDF V1: ContentType=...EdfProtocolContent;'
                   '{"Data": "tProtocolName = \\"abc\\""}')
        assert _extract_protocol_text_from_xprotocol(wrapped) == 'tProtocolName = "abc"'

    def test_extract_protocol_text_no_json(self):
        assert _extract_protocol_text_from_xprotocol("no braces here") is None

    def test_extract_protocol_text_fallback(self):
        text = 'garbage {not json} but has tProtocolName inside'
        assert _extract_protocol_text_from_xprotocol(text) == text

    def test_extract_protocol_text_empty_data(self):
        assert _extract_protocol_text_from_xprotocol('{"Data": ""}') is None


# ---------------------------------------------------------------------------
# EXAR: synthesize a tiny SQLite .exar1 archive to exercise DB-read paths
# ---------------------------------------------------------------------------

def _build_exar(path, protocol_texts, include_string=True, include_branch=True,
                only_non_protocol=False):
    """Build a minimal .exar1-like SQLite DB."""
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE Content (Hash TEXT PRIMARY KEY, Data BLOB)")
    cur.execute("CREATE TABLE Instance (Id INTEGER PRIMARY KEY, "
                "InstanceType TEXT, ContentHash TEXT)")
    cur.execute("CREATE TABLE Branch (Baseline TEXT)")

    def raw_deflate(b):
        c = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        return c.compress(b) + c.flush()

    inst_id = 0
    if not only_non_protocol:
        for text in protocol_texts:
            wrapper = 'EDF V1;' + json.dumps({"Data": text})
            blob = raw_deflate(wrapper.encode("utf-8"))
            h = hashlib.sha1(blob).hexdigest()
            cur.execute("INSERT INTO Content VALUES (?, ?)", (h, blob))
            inst_id += 1
            cur.execute("INSERT INTO Instance VALUES (?, ?, ?)",
                        (inst_id, "EdfProtocol", h))

    if include_string:
        name_blob = raw_deflate(json.dumps({"Texts": {"en": "MyFolder"}}).encode("utf-8"))
        h = hashlib.sha1(name_blob).hexdigest()
        cur.execute("INSERT INTO Content VALUES (?, ?)", (h, name_blob))
        inst_id += 1
        cur.execute("INSERT INTO Instance VALUES (?, ?, ?)", (inst_id, "EdfString", h))

    if include_branch:
        cur.execute("INSERT INTO Branch VALUES (?)",
                    ("MAJORVERSION:VA60A, PROTOCOL:66010002",))

    conn.commit()
    conn.close()


PROTO_TEXT_SIMPLE = (
    "### ASCCONV BEGIN ###\n"
    'tProtocolName = "exar_test"\n'
    "ucSequenceType = 1\n"
    "alTE[0] = 5000\n"
    "alTR[0] = 2000000\n"
    "lContrasts = 1\n"
    "### ASCCONV END ###\n"
)

PROTO_TEXT_MULTIECHO = (
    "### ASCCONV BEGIN ###\n"
    'tProtocolName = "exar_multiecho"\n'
    "ucSequenceType = 1\n"
    "alTE[0] = 5000\n"
    "alTE[1] = 10000\n"
    "lContrasts = 2\n"
    "### ASCCONV END ###\n"
)


class TestExarDescribeContents:
    def test_describe_with_protocols(self, tmp_path):
        p = tmp_path / "a.exar1"
        _build_exar(p, [PROTO_TEXT_SIMPLE])
        summary, has_protocols = _describe_exar_contents(str(p))
        assert has_protocols is True
        assert "software version VA60A" in summary
        assert "MyFolder" in summary
        assert "EdfProtocol" in summary

    def test_describe_no_protocols(self, tmp_path):
        p = tmp_path / "b.exar1"
        _build_exar(p, [], only_non_protocol=True)
        summary, has_protocols = _describe_exar_contents(str(p))
        assert has_protocols is False

    def test_describe_malformed_string_entries(self, tmp_path):
        # EdfString entries that fail to decompress / have no JSON / bad JSON,
        # and no Branch row (version stays None) -> exercises the continue branches.
        p = tmp_path / "malformed.exar1"
        conn = sqlite3.connect(str(p))
        cur = conn.cursor()
        cur.execute("CREATE TABLE Content (Hash TEXT PRIMARY KEY, Data BLOB)")
        cur.execute("CREATE TABLE Instance (Id INTEGER PRIMARY KEY, "
                    "InstanceType TEXT, ContentHash TEXT)")
        cur.execute("CREATE TABLE Branch (Baseline TEXT)")

        def deflate(b):
            c = zlib.compressobj(wbits=-zlib.MAX_WBITS)
            return c.compress(b) + c.flush()

        entries = [
            b"\x00not deflate",                 # fails decompress -> continue
            deflate(b"no braces at all"),        # no '{' -> continue
            deflate(b"prefix {not valid json}"), # bad JSON -> continue
        ]
        for i, blob in enumerate(entries, 1):
            h = f"h{i}"
            cur.execute("INSERT INTO Content VALUES (?, ?)", (h, blob))
            cur.execute("INSERT INTO Instance VALUES (?, ?, ?)", (i, "EdfString", h))
        # one EdfProtocol so has_protocols is True
        cur.execute("INSERT INTO Content VALUES (?, ?)", ("hp", deflate(b"proto")))
        cur.execute("INSERT INTO Instance VALUES (?, ?, ?)", (99, "EdfProtocol", "hp"))
        conn.commit()
        conn.close()

        summary, has_protocols = _describe_exar_contents(str(p))
        assert has_protocols is True
        assert "software version" not in summary  # no Branch/version
        assert "folder tree" not in summary        # no valid names

    def test_describe_empty_instance_table(self, tmp_path):
        # Valid DB but no Instance rows -> "contains no entries at all"
        p = tmp_path / "emptytables.exar1"
        conn = sqlite3.connect(str(p))
        cur = conn.cursor()
        cur.execute("CREATE TABLE Content (Hash TEXT PRIMARY KEY, Data BLOB)")
        cur.execute("CREATE TABLE Instance (Id INTEGER PRIMARY KEY, "
                    "InstanceType TEXT, ContentHash TEXT)")
        cur.execute("CREATE TABLE Branch (Baseline TEXT)")
        conn.commit()
        conn.close()
        summary, has_protocols = _describe_exar_contents(str(p))
        assert has_protocols is False
        assert "contains no entries at all" in summary

    def test_describe_bad_db_returns_empty(self, tmp_path):
        p = tmp_path / "notdb.exar1"
        p.write_bytes(b"this is not sqlite")
        summary, has_protocols = _describe_exar_contents(str(p))
        assert summary == "" and has_protocols is False


class TestExtractProtocolsFromExar:
    def test_extract(self, tmp_path):
        p = tmp_path / "c.exar1"
        _build_exar(p, [PROTO_TEXT_SIMPLE, PROTO_TEXT_MULTIECHO])
        texts = _extract_protocols_from_exar(str(p))
        assert len(texts) == 2
        assert any("exar_test" in t for t in texts)

    def test_skips_null_and_bad_content(self, tmp_path):
        p = tmp_path / "skip.exar1"
        conn = sqlite3.connect(str(p))
        cur = conn.cursor()
        cur.execute("CREATE TABLE Content (Hash TEXT PRIMARY KEY, Data BLOB)")
        cur.execute("CREATE TABLE Instance (Id INTEGER PRIMARY KEY, "
                    "InstanceType TEXT, ContentHash TEXT)")

        def deflate(b):
            c = zlib.compressobj(wbits=-zlib.MAX_WBITS)
            return c.compress(b) + c.flush()

        # NULL content (LEFT JOIN miss) -> `if not data: continue`
        cur.execute("INSERT INTO Instance VALUES (?, ?, ?)", (1, "EdfProtocol", "missing"))
        # undecompressible content -> `if not decompressed: continue`
        cur.execute("INSERT INTO Content VALUES (?, ?)", ("bad", b"\x00not deflate"))
        cur.execute("INSERT INTO Instance VALUES (?, ?, ?)", (2, "EdfProtocol", "bad"))
        # a good one
        wrapper = 'EDF;' + json.dumps({"Data": PROTO_TEXT_SIMPLE})
        cur.execute("INSERT INTO Content VALUES (?, ?)", ("good", deflate(wrapper.encode())))
        cur.execute("INSERT INTO Instance VALUES (?, ?, ?)", (3, "EdfProtocol", "good"))
        conn.commit()
        conn.close()

        texts = _extract_protocols_from_exar(str(p))
        assert len(texts) == 1

    def test_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _extract_protocols_from_exar(str(tmp_path / "no.exar1"))

    def test_bad_sqlite_raises(self, tmp_path):
        p = tmp_path / "bad.exar1"
        p.write_bytes(b"not a sqlite database at all")
        with pytest.raises(Exception, match="Failed to read EXAR"):
            _extract_protocols_from_exar(str(p))


class TestLoadExarFile:
    def test_load_ok(self, tmp_path):
        p = tmp_path / "d.exar1"
        _build_exar(p, [PROTO_TEXT_SIMPLE, PROTO_TEXT_MULTIECHO])
        results = load_exar_file(str(p))
        assert len(results) == 2
        assert all("EXAR_Path" in r for r in results)
        assert all(r["Manufacturer"] == "Siemens" for r in results)

    def test_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_exar_file(str(tmp_path / "no.exar1"))

    def test_no_protocols_message(self, tmp_path):
        p = tmp_path / "empty.exar1"
        _build_exar(p, [], only_non_protocol=True)
        with pytest.raises(Exception, match="no protocol"):
            load_exar_file(str(p))

    def test_protocol_entries_but_undecodable(self, tmp_path):
        # EdfProtocol content decompresses but yields no protocol text -> the
        # "contains protocol entries, but none could be decoded" branch.
        p = tmp_path / "undecodable.exar1"
        conn = sqlite3.connect(str(p))
        cur = conn.cursor()
        cur.execute("CREATE TABLE Content (Hash TEXT PRIMARY KEY, Data BLOB)")
        cur.execute("CREATE TABLE Instance (Id INTEGER PRIMARY KEY, "
                    "InstanceType TEXT, ContentHash TEXT)")
        cur.execute("CREATE TABLE Branch (Baseline TEXT)")
        c = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        blob = c.compress(b"no json and no protocol marker") + c.flush()
        cur.execute("INSERT INTO Content VALUES (?, ?)", ("h", blob))
        cur.execute("INSERT INTO Instance VALUES (?, ?, ?)", (1, "EdfProtocol", "h"))
        conn.commit()
        conn.close()
        with pytest.raises(Exception, match="none of them could be decoded"):
            load_exar_file(str(p))

    def test_schema_format_undecodable_returns_empty(self, tmp_path):
        # No protocol texts but load_exar_file raises inside -> schema variant
        # re-raises via the diagnostics call.
        p = tmp_path / "undecodable2.exar1"
        conn = sqlite3.connect(str(p))
        cur = conn.cursor()
        cur.execute("CREATE TABLE Content (Hash TEXT PRIMARY KEY, Data BLOB)")
        cur.execute("CREATE TABLE Instance (Id INTEGER PRIMARY KEY, "
                    "InstanceType TEXT, ContentHash TEXT)")
        cur.execute("CREATE TABLE Branch (Baseline TEXT)")
        c = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        blob = c.compress(b"nothing useful") + c.flush()
        cur.execute("INSERT INTO Content VALUES (?, ?)", ("h", blob))
        cur.execute("INSERT INTO Instance VALUES (?, ?, ?)", (1, "EdfProtocol", "h"))
        conn.commit()
        conn.close()
        with pytest.raises(Exception):
            load_exar_file_schema_format(str(p))

    def test_load_schema_format(self, tmp_path):
        p = tmp_path / "e.exar1"
        _build_exar(p, [PROTO_TEXT_MULTIECHO])
        results = load_exar_file_schema_format(str(p))
        assert len(results) == 1
        info = results[0]["acquisition_info"]
        assert info["source_type"] == "exar1"
        assert info["exar_filename"] == "e.exar1"
        # multi-echo should expand into >1 series
        assert len(results[0]["series"]) >= 2

    def test_schema_format_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_exar_file_schema_format(str(tmp_path / "no.exar1"))

    def test_schema_format_no_protocols_raises(self, tmp_path):
        p = tmp_path / "empty2.exar1"
        _build_exar(p, [], only_non_protocol=True)
        with pytest.raises(Exception):
            load_exar_file_schema_format(str(p))

    def test_load_exar_file_protocol_parse_warning(self, tmp_path, monkeypatch, capsys):
        # Force apply_pro_to_dicom_mapping to raise so the per-protocol warning
        # path (with tProtocolName regex extraction) is exercised.
        p = tmp_path / "warn.exar1"
        _build_exar(p, [PROTO_TEXT_SIMPLE])

        def boom(*a, **k):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(pro_mod, "apply_pro_to_dicom_mapping", boom)
        results = load_exar_file(str(p))
        assert results == []
        out = capsys.readouterr().out
        assert "exar_test" in out and "kaboom" in out

    def test_load_exar_schema_protocol_parse_warning(self, tmp_path, monkeypatch, capsys):
        p = tmp_path / "warn2.exar1"
        _build_exar(p, [PROTO_TEXT_SIMPLE])

        def boom(*a, **k):
            raise RuntimeError("kaboom2")

        monkeypatch.setattr(pro_mod, "apply_pro_to_dicom_mapping", boom)
        results = load_exar_file_schema_format(str(p))
        assert results == []
        out = capsys.readouterr().out
        assert "exar_test" in out and "kaboom2" in out


class TestLoadExarSession:
    def test_no_source_raises(self):
        with pytest.raises(ValueError, match="Either session_dir or exar_files"):
            load_exar_session()

    def test_no_files_raises(self, tmp_path):
        with pytest.raises(ValueError, match="No .exar1 files"):
            load_exar_session(session_dir=str(tmp_path))

    def test_load_session_from_list(self, tmp_path):
        p = tmp_path / "f.exar1"
        _build_exar(p, [PROTO_TEXT_SIMPLE, PROTO_TEXT_MULTIECHO])
        df = load_exar_session(exar_files=[str(p)])
        assert isinstance(df, pd.DataFrame)
        assert "Acquisition" in df.columns
        assert len(df) == 2

    def test_load_session_from_dir_with_progress(self, tmp_path):
        p = tmp_path / "g.exar1"
        _build_exar(p, [PROTO_TEXT_SIMPLE])
        seen = []
        df = load_exar_session(session_dir=str(tmp_path),
                               progress_function=seen.append)
        assert isinstance(df, pd.DataFrame)
        assert seen and seen[-1] == 100

    def test_all_fail_raises(self, tmp_path):
        p = tmp_path / "bad.exar1"
        p.write_bytes(b"not sqlite")
        with pytest.raises(ValueError, match="No valid protocols"):
            load_exar_session(exar_files=[str(p)])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
