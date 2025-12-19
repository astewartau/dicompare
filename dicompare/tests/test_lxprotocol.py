"""
Tests for GE LxProtocol file loading functionality.

This module tests the loading and parsing of GE LxProtocol files.
"""

import pytest
import tempfile
import os
from pathlib import Path

from dicompare.io.lxprotocol import (
    load_lxprotocol_file,
    load_lxprotocol_file_schema_format,
    load_lxprotocol_session,
    apply_lxprotocol_to_dicom_mapping,
    _parse_lxprotocol,
    _convert_value,
    _calculate_derived_fields,
    _map_ge_sequence,
    _sort_output_fields,
    GE_TO_DICOM_MAPPING,
    GE_PLANE_MAPPING,
    GE_IMODE_MAPPING,
    USEFUL_GE_PARAMETERS,
    DICOM_FIELD_ORDER,
)


# Sample LxProtocol content for testing
SAMPLE_LXPROTOCOL = '''    set COIL "Head 32Ch"
    set PLANE "AXIAL"
    set IMODE "3D"
    set PSEQ "SPGR"
    set IOPT "EDR, Fast, Asset"
    set FLIPANG "12"
    set TE "3.2"
    set TR "8.1"
    set TI "450"
    set FOV "25.6"
    set SLTHICK "1.0"
    set MATRIXX "256"
    set MATRIXY "256"
    set NEX "1.00"
    set ETL "1"
    set PHASEFOV "1.00"
    set RBW "31.25"
    set PHASEACCEL "2.00"
    set SLICEACCEL "1.00"
    set NOSLC "176"
    set SWAPPF "R/L"
    set AUTOSHIM "Auto"
    set RFDRIVEMODE "Single"
    set CONTRAST "No"
'''


class TestParseLxprotocol:
    """Tests for the LxProtocol parsing function."""

    def test_parse_basic_file(self):
        """Test parsing a basic LxProtocol file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='', delete=False) as f:
            f.write(SAMPLE_LXPROTOCOL)
            f.flush()

            try:
                result = _parse_lxprotocol(f.name)

                assert "COIL" in result
                assert result["COIL"] == "Head 32Ch"
                assert result["PLANE"] == "AXIAL"
                assert result["IMODE"] == "3D"
                assert result["PSEQ"] == "SPGR"
            finally:
                os.unlink(f.name)

    def test_parse_numeric_values(self):
        """Test that numeric values are converted correctly."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='', delete=False) as f:
            f.write(SAMPLE_LXPROTOCOL)
            f.flush()

            try:
                result = _parse_lxprotocol(f.name)

                # Integer values
                assert result["FLIPANG"] == 12
                assert result["MATRIXX"] == 256
                assert result["NOSLC"] == 176

                # Float values
                assert result["TE"] == 3.2
                assert result["TR"] == 8.1
                assert result["FOV"] == 25.6
                assert result["NEX"] == 1.0
            finally:
                os.unlink(f.name)

    def test_parse_file_not_found(self):
        """Test FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            _parse_lxprotocol("/nonexistent/path/LxProtocol")


class TestConvertValue:
    """Tests for value conversion."""

    def test_convert_integer(self):
        """Test integer conversion."""
        assert _convert_value("42") == 42
        assert _convert_value("0") == 0
        assert _convert_value("-5") == -5

    def test_convert_float(self):
        """Test float conversion."""
        assert _convert_value("3.14") == 3.14
        assert _convert_value("0.5") == 0.5
        assert _convert_value("-2.5") == -2.5

    def test_convert_string(self):
        """Test string passthrough."""
        assert _convert_value("AXIAL") == "AXIAL"
        assert _convert_value("Head 32Ch") == "Head 32Ch"
        assert _convert_value("Minimum") == "Minimum"

    def test_convert_empty(self):
        """Test empty string."""
        assert _convert_value("") == ""


class TestApplyLxprotocolToDicomMapping:
    """Tests for DICOM mapping."""

    def test_basic_mapping(self):
        """Test basic parameter mapping."""
        params = {
            "TR": 2000.0,
            "TE": 30.0,
            "FLIPANG": 90,
            "SLTHICK": 3.0,
        }

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["Manufacturer"] == "GE"
        assert result["RepetitionTime"] == 2000.0
        assert result["EchoTime"] == 30.0
        assert result["FlipAngle"] == 90
        assert result["SliceThickness"] == 3.0

    def test_fov_conversion(self):
        """Test FOV conversion from cm to mm."""
        params = {"FOV": 25.6}  # cm

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["FieldOfView"] == 256.0  # mm

    def test_phasefov_conversion(self):
        """Test PercentPhaseFieldOfView conversion."""
        params = {"PHASEFOV": 0.75}  # 75%

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["PercentPhaseFieldOfView"] == 75.0

    def test_plane_mapping(self):
        """Test image plane orientation mapping."""
        for ge_plane, dicom_plane in GE_PLANE_MAPPING.items():
            params = {"PLANE": ge_plane}
            result = apply_lxprotocol_to_dicom_mapping(params)
            assert result["ImagePlaneOrientation"] == dicom_plane

    def test_imode_mapping(self):
        """Test acquisition mode mapping."""
        params = {"IMODE": "3D"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert result["MRAcquisitionType"] == "3D"

        params = {"IMODE": "2D"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert result["MRAcquisitionType"] == "2D"

    def test_parallel_imaging_asset(self):
        """Test ASSET parallel imaging detection."""
        params = {"IOPT": "EDR, Fast, Asset"}

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["ParallelAcquisition"] == "YES"
        assert result["ParallelAcquisitionTechnique"] == "ASSET"

    def test_parallel_imaging_arc(self):
        """Test ARC parallel imaging detection."""
        params = {"IOPT": "FC, NPW, ARC"}

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["ParallelAcquisition"] == "YES"
        assert result["ParallelAcquisitionTechnique"] == "ARC"

    def test_no_parallel_imaging(self):
        """Test no parallel imaging."""
        params = {"IOPT": "EDR, Fast"}

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["ParallelAcquisition"] == "NO"

    def test_pixel_spacing_calculation(self):
        """Test PixelSpacing calculation from FOV and matrix."""
        params = {
            "FOV": 25.6,  # cm
            "MATRIXX": 256,
            "MATRIXY": 256,
            "PHASEFOV": 1.0,
        }

        result = apply_lxprotocol_to_dicom_mapping(params)

        # 256mm / 256 = 1.0mm
        assert "PixelSpacing" in result
        assert result["PixelSpacing"][0] == 1.0
        assert result["PixelSpacing"][1] == 1.0

    def test_pixel_spacing_with_phasefov(self):
        """Test PixelSpacing with non-unity PHASEFOV."""
        params = {
            "FOV": 25.6,  # cm
            "MATRIXX": 256,
            "MATRIXY": 256,
            "PHASEFOV": 0.75,
        }

        result = apply_lxprotocol_to_dicom_mapping(params)

        # Row: 256mm / 256 = 1.0mm
        # Col: (256mm * 0.75) / 256 = 0.75mm
        assert result["PixelSpacing"][0] == 1.0
        assert result["PixelSpacing"][1] == 0.75

    def test_minimum_te_skipped(self):
        """Test that TE 'Minimum' is skipped."""
        params = {"TE": "Minimum", "TR": 2000.0}

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert "EchoTime" not in result
        assert result["RepetitionTime"] == 2000.0

    def test_diffusion_bvalue_single(self):
        """Test single diffusion b-value parsing."""
        params = {"MULTIBVALUE": "1000.0;"}

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["DiffusionBValue"] == 1000.0

    def test_diffusion_bvalue_multiple(self):
        """Test multiple diffusion b-values parsing."""
        params = {"MULTIBVALUE": "0;500;1000;"}

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["DiffusionBValue"] == [0.0, 500.0, 1000.0]

    def test_useful_ge_parameters_included(self):
        """Test that useful GE parameters are included."""
        params = {
            "AUTOSHIM": "Auto",
            "RFDRIVEMODE": "Dual",
        }

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["GE_AUTOSHIM"] == "Auto"
        assert result["GE_RFDRIVEMODE"] == "Dual"

    def test_phase_encoding_direction(self):
        """Test PhaseEncodingDirection from SWAPPF."""
        params = {"SWAPPF": "A/P"}

        result = apply_lxprotocol_to_dicom_mapping(params)

        assert result["PhaseEncodingDirection"] == "A/P"


class TestMapGeSequence:
    """Tests for GE sequence mapping."""

    def test_gradient_echo_sequences(self):
        """Test gradient echo sequence mapping."""
        assert _map_ge_sequence("SPGR") == "GR"
        assert _map_ge_sequence("FSPGR") == "GR"
        assert _map_ge_sequence("BRAVO") == "GR"
        assert _map_ge_sequence("LAVA") == "GR"

    def test_spin_echo_sequences(self):
        """Test spin echo sequence mapping."""
        assert _map_ge_sequence("SE") == "SE"
        assert _map_ge_sequence("FSE") == "SE"
        assert _map_ge_sequence("FRFSE") == "SE"
        assert _map_ge_sequence("CUBE") == "SE"

    def test_inversion_recovery_sequences(self):
        """Test inversion recovery sequence mapping."""
        assert _map_ge_sequence("IR") == "IR"
        assert _map_ge_sequence("FLAIR") == "IR"
        assert _map_ge_sequence("STIR") == "IR"

    def test_epi_sequences(self):
        """Test EPI sequence mapping."""
        assert _map_ge_sequence("EPI") == "EP"
        assert _map_ge_sequence("DIFF") == "EP"
        assert _map_ge_sequence("DWI") == "EP"

    def test_unknown_sequence(self):
        """Test unknown sequence returns None."""
        assert _map_ge_sequence("UNKNOWN") is None
        assert _map_ge_sequence("") is None


class TestSortOutputFields:
    """Tests for field ordering."""

    def test_dicom_fields_before_ge(self):
        """Test DICOM fields come before GE fields."""
        fields = {
            "GE_test": 1,
            "RepetitionTime": 2000,
            "Manufacturer": "GE",
        }

        result = _sort_output_fields(fields)
        keys = list(result.keys())

        ge_idx = keys.index("GE_test")
        assert keys.index("Manufacturer") < ge_idx
        assert keys.index("RepetitionTime") < ge_idx

    def test_ge_fields_alphabetical(self):
        """Test GE fields are sorted alphabetically."""
        fields = {
            "GE_Z_field": 1,
            "GE_A_field": 2,
            "GE_M_field": 3,
        }

        result = _sort_output_fields(fields)
        keys = list(result.keys())

        assert keys == ["GE_A_field", "GE_M_field", "GE_Z_field"]


class TestFileOperations:
    """Tests for file loading operations."""

    def test_load_lxprotocol_file_basic(self):
        """Test loading a basic LxProtocol file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='', delete=False) as f:
            f.write(SAMPLE_LXPROTOCOL)
            f.flush()

            try:
                result = load_lxprotocol_file(f.name)

                assert "Manufacturer" in result
                assert result["Manufacturer"] == "GE"
                assert "RepetitionTime" in result
                assert "EchoTime" in result
                assert "LxProtocol_Path" in result
                assert "LxProtocol_FileName" in result
            finally:
                os.unlink(f.name)

    def test_load_lxprotocol_file_not_found(self):
        """Test FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_lxprotocol_file("/nonexistent/path/LxProtocol")

    def test_load_lxprotocol_session_not_found(self):
        """Test FileNotFoundError for non-existent directory."""
        with pytest.raises(FileNotFoundError):
            load_lxprotocol_session("/nonexistent/path/")

    def test_load_lxprotocol_session_no_files(self):
        """Test ValueError when no LxProtocol files found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="No LxProtocol files found"):
                load_lxprotocol_session(tmpdir)

    def test_load_lxprotocol_session_with_files(self):
        """Test session loading with multiple files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create subdirectories with LxProtocol files
            scan1_dir = Path(tmpdir) / "scan1"
            scan2_dir = Path(tmpdir) / "scan2"
            scan1_dir.mkdir()
            scan2_dir.mkdir()

            # Write LxProtocol files
            (scan1_dir / "LxProtocol").write_text(SAMPLE_LXPROTOCOL)
            (scan2_dir / "LxProtocol").write_text(SAMPLE_LXPROTOCOL.replace("8.1", "2500"))

            result = load_lxprotocol_session(tmpdir)

            assert len(result) == 2
            assert "ScanName" in result.columns
            assert "RepetitionTime" in result.columns

    def test_load_lxprotocol_file_schema_format(self):
        """Test loading in schema format."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='', delete=False) as f:
            f.write(SAMPLE_LXPROTOCOL)
            f.flush()

            try:
                result = load_lxprotocol_file_schema_format(f.name)

                assert isinstance(result, list)
                assert len(result) == 1
                assert "acquisition_info" in result[0]
                assert "fields" in result[0]
                assert "series" in result[0]
                assert result[0]["acquisition_info"]["source_type"] == "lxprotocol"
            finally:
                os.unlink(f.name)

    def test_load_lxprotocol_file_schema_format_not_found(self):
        """Test FileNotFoundError for schema format loading."""
        with pytest.raises(FileNotFoundError):
            load_lxprotocol_file_schema_format("/nonexistent/path/LxProtocol")


class TestConstants:
    """Tests for module constants."""

    def test_ge_mapping_not_empty(self):
        """Test GE_TO_DICOM_MAPPING has entries."""
        assert len(GE_TO_DICOM_MAPPING) > 0

    def test_plane_mapping_not_empty(self):
        """Test GE_PLANE_MAPPING has entries."""
        assert len(GE_PLANE_MAPPING) > 0

    def test_imode_mapping_not_empty(self):
        """Test GE_IMODE_MAPPING has entries."""
        assert len(GE_IMODE_MAPPING) > 0

    def test_useful_parameters_not_empty(self):
        """Test USEFUL_GE_PARAMETERS has entries."""
        assert len(USEFUL_GE_PARAMETERS) > 0

    def test_field_order_not_empty(self):
        """Test DICOM_FIELD_ORDER has entries."""
        assert len(DICOM_FIELD_ORDER) > 0

    def test_key_fields_in_mapping(self):
        """Test key fields are in mapping."""
        # Note: FOV is handled in _calculate_derived_fields, not direct mapping
        key_fields = ["TR", "TE", "FLIPANG", "SLTHICK", "NEX", "ETL"]
        for field in key_fields:
            assert field in GE_TO_DICOM_MAPPING


class TestEdgeCases:
    """Edge case tests for additional coverage."""

    def test_empty_iopt(self):
        """Test empty IOPT field."""
        params = {"IOPT": ""}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert result["ParallelAcquisition"] == "NO"

    def test_contrast_yes(self):
        """Test contrast agent present."""
        params = {"CONTRAST": "Gadolinium"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert result["ContrastBolusAgent"] == "Gadolinium"

    def test_contrast_no(self):
        """Test no contrast agent."""
        params = {"CONTRAST": "No"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert "ContrastBolusAgent" not in result

    def test_invalid_bvalue_string(self):
        """Test invalid b-value string handling."""
        params = {"MULTIBVALUE": "invalid;"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        # Should not crash, just skip the field
        assert "DiffusionBValue" not in result

    def test_empty_multibvalue(self):
        """Test empty MULTIBVALUE string."""
        params = {"MULTIBVALUE": ""}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert "DiffusionBValue" not in result

    def test_fov_invalid(self):
        """Test invalid FOV value."""
        params = {"FOV": "invalid"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert "FieldOfView" not in result

    def test_phasefov_invalid(self):
        """Test invalid PHASEFOV value."""
        params = {"PHASEFOV": "invalid"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert "PercentPhaseFieldOfView" not in result

    def test_pixel_spacing_missing_matrix(self):
        """Test PixelSpacing not calculated when matrix missing."""
        params = {"FOV": 25.6}  # Missing MATRIXX/MATRIXY
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert "PixelSpacing" not in result

    def test_pixel_spacing_zero_matrix(self):
        """Test PixelSpacing handles zero matrix gracefully."""
        params = {"FOV": 25.6, "MATRIXX": 0, "MATRIXY": 256, "PHASEFOV": 1.0}
        result = apply_lxprotocol_to_dicom_mapping(params)
        # Should not crash due to division by zero
        assert "PixelSpacing" not in result

    def test_3de_imode(self):
        """Test 3DE (3D Enhanced) mode mapping."""
        params = {"IMODE": "3DE"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert result["MRAcquisitionType"] == "3D"

    def test_oblique_plane(self):
        """Test oblique plane mapping."""
        params = {"PLANE": "OBLIQUE"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert result["ImagePlaneOrientation"] == "OBLIQUE"

    def test_unknown_plane(self):
        """Test unknown plane not mapped."""
        params = {"PLANE": "UNKNOWN"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert "ImagePlaneOrientation" not in result

    def test_unknown_imode(self):
        """Test unknown IMODE not mapped."""
        params = {"IMODE": "UNKNOWN"}
        result = apply_lxprotocol_to_dicom_mapping(params)
        assert "MRAcquisitionType" not in result

    def test_case_insensitive_sequence(self):
        """Test sequence mapping is case insensitive."""
        assert _map_ge_sequence("spgr") == "GR"
        assert _map_ge_sequence("Spgr") == "GR"
        assert _map_ge_sequence("SPGR") == "GR"


class TestIntegration:
    """Integration tests for end-to-end functionality."""

    def test_full_pipeline(self):
        """Test full parsing and mapping pipeline."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='', delete=False) as f:
            f.write(SAMPLE_LXPROTOCOL)
            f.flush()

            try:
                result = load_lxprotocol_file(f.name)

                # Check key fields
                assert result["Manufacturer"] == "GE"
                assert result["MRAcquisitionType"] == "3D"
                assert result["ImagePlaneOrientation"] == "AXIAL"
                assert result["SequenceName"] == "SPGR"
                assert result["ScanningSequence"] == "GR"
                assert result["RepetitionTime"] == 8.1
                assert result["EchoTime"] == 3.2
                assert result["FlipAngle"] == 12
                assert result["InversionTime"] == 450
                assert result["SliceThickness"] == 1.0
                assert result["FieldOfView"] == 256.0  # 25.6cm * 10
                assert result["NumberOfSlices"] == 176
                assert result["ParallelAcquisition"] == "YES"
                assert result["ParallelAcquisitionTechnique"] == "ASSET"
            finally:
                os.unlink(f.name)
