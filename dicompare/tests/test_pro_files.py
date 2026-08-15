"""
Tests for Siemens .pro file loading functionality.

This module tests the loading and parsing of Siemens protocol (.pro) files
using the twixtools library.
"""

import pytest
import os
import pandas as pd
from pathlib import Path

from dicompare import load_pro_file, load_pro_session, load_pro_file_schema_format


# Get the fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pro_files"


class TestLoadProFile:
    """Tests for load_pro_file function."""

    def test_load_pro_file_basic(self):
        """Test loading a single .pro file."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"
        assert pro_file.exists(), f"Test file not found: {pro_file}"

        result = load_pro_file(str(pro_file))

        # Should return a dictionary
        assert isinstance(result, dict)

        # Should contain some expected fields
        assert len(result) > 0

        # Check for common DICOM fields that should be extracted
        expected_fields = ["ProtocolName", "SequenceName"]
        for field in expected_fields:
            assert field in result, f"Expected field '{field}' not found in result"

    def test_load_pro_file_diffusion(self):
        """Test loading a diffusion .pro file."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_diff__p3_sms1.pro"
        assert pro_file.exists(), f"Test file not found: {pro_file}"

        result = load_pro_file(str(pro_file))

        assert isinstance(result, dict)
        assert len(result) > 0

    def test_load_pro_file_multiband(self):
        """Test loading a multiband .pro file."""
        pro_file = FIXTURES_DIR / "C2P__cmrr_mbep2d_bold__p3_mb2.pro"
        assert pro_file.exists(), f"Test file not found: {pro_file}"

        result = load_pro_file(str(pro_file))

        assert isinstance(result, dict)
        assert len(result) > 0

    def test_load_pro_file_returns_expected_types(self):
        """Test that returned values have appropriate types."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"
        result = load_pro_file(str(pro_file))

        # All values should be JSON-serializable types
        for key, value in result.items():
            assert isinstance(key, str), f"Key {key} is not a string"
            # Values should be basic types (str, int, float, list, dict, bool, None)
            assert isinstance(value, (str, int, float, list, dict, bool, type(None))), \
                f"Value for key '{key}' has unexpected type: {type(value)}"

    def test_load_pro_file_nonexistent(self):
        """Test loading a non-existent .pro file."""
        nonexistent_file = FIXTURES_DIR / "nonexistent.pro"

        with pytest.raises(FileNotFoundError):
            load_pro_file(str(nonexistent_file))


class TestLoadProFileSchemaFormat:
    """Tests for load_pro_file_schema_format function."""

    def test_load_pro_file_schema_format_basic(self):
        """Test loading a .pro file in schema format."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"

        result = load_pro_file_schema_format(str(pro_file))

        # Should return a dictionary
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_load_pro_file_schema_format_structure(self):
        """Test that schema format has expected structure."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"

        result = load_pro_file_schema_format(str(pro_file))

        # Check that it's structured appropriately for schema use
        assert isinstance(result, dict)

        # The schema format should contain series-level information
        # The exact structure depends on implementation, but verify it's a valid dict
        assert len(result) > 0


class TestLoadProSession:
    """Tests for load_pro_session function."""

    def test_load_pro_session_basic(self):
        """Test loading multiple .pro files from a directory."""
        result = load_pro_session(str(FIXTURES_DIR), show_progress=False)

        # Should return a pandas DataFrame
        assert isinstance(result, pd.DataFrame)

        # Should have loaded all 3 .pro files
        assert len(result) > 0

        # Should have columns
        assert len(result.columns) > 0

    def test_load_pro_session_has_expected_columns(self):
        """Test that loaded session has expected DICOM metadata columns."""
        result = load_pro_session(str(FIXTURES_DIR), show_progress=False)

        # Should have some common DICOM fields
        common_fields = ["ProtocolName", "SequenceName"]
        for field in common_fields:
            assert field in result.columns, f"Expected column '{field}' not found"

    def test_load_pro_session_correct_row_count(self):
        """Test that session loading creates appropriate number of rows."""
        result = load_pro_session(str(FIXTURES_DIR), show_progress=False)

        # Should have at least one row per .pro file
        # (could be more if files define multiple series)
        num_pro_files = len(list(FIXTURES_DIR.glob("*.pro")))
        assert len(result) >= num_pro_files, \
            f"Expected at least {num_pro_files} rows, got {len(result)}"

    def test_load_pro_session_empty_directory(self, tmp_path):
        """Test loading from an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        # Should raise ValueError when no .pro files are found
        with pytest.raises(ValueError, match="No .pro files found"):
            load_pro_session(str(empty_dir), show_progress=False)

    def test_load_pro_session_nonexistent_directory(self):
        """Test loading from a non-existent directory."""
        nonexistent_dir = FIXTURES_DIR / "nonexistent_dir"

        # Should raise ValueError when no .pro files are found (even if dir doesn't exist)
        with pytest.raises(ValueError, match="No .pro files found"):
            load_pro_session(str(nonexistent_dir), show_progress=False)

    def test_load_pro_session_with_progress(self):
        """Test that progress bar parameter works."""
        # Should not raise an error with show_progress=True
        result = load_pro_session(str(FIXTURES_DIR), show_progress=True)
        assert isinstance(result, pd.DataFrame)


class TestProFileIntegration:
    """Integration tests for .pro file functionality."""

    def test_all_pro_files_loadable(self):
        """Test that all fixture .pro files can be loaded."""
        pro_files = list(FIXTURES_DIR.glob("*.pro"))

        assert len(pro_files) > 0, "No .pro files found in fixtures"

        for pro_file in pro_files:
            # Should not raise an error
            result = load_pro_file(str(pro_file))
            assert isinstance(result, dict)
            assert len(result) > 0, f"Empty result from {pro_file.name}"

    def test_consistency_between_load_methods(self):
        """Test that different loading methods are consistent."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"

        # Load with standard method
        result_standard = load_pro_file(str(pro_file))

        # Load with schema format
        result_schema = load_pro_file_schema_format(str(pro_file))

        # Both should return dictionaries
        assert isinstance(result_standard, dict)
        assert isinstance(result_schema, dict)

        # Both should have content
        assert len(result_standard) > 0
        assert len(result_schema) > 0

    def test_session_loading_vs_individual_files(self):
        """Test that session loading is consistent with individual file loading."""
        # Load entire session
        session_df = load_pro_session(str(FIXTURES_DIR), show_progress=False)

        # Load individual files
        pro_files = list(FIXTURES_DIR.glob("*.pro"))
        individual_results = []
        for pro_file in pro_files:
            result = load_pro_file(str(pro_file))
            individual_results.append(result)

        # Session should have at least as many rows as individual files
        # (could be more if files define multiple series)
        assert len(session_df) >= len(individual_results), \
            "Session loading returned fewer results than individual files"

    def test_pro_file_path_handling(self):
        """Test that both string and Path objects work."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"

        # Test with string
        result_str = load_pro_file(str(pro_file))

        # Test with Path object (converted to string internally)
        result_path = load_pro_file(str(Path(pro_file)))

        # Both should work
        assert isinstance(result_str, dict)
        assert isinstance(result_path, dict)
        assert len(result_str) > 0
        assert len(result_path) > 0


class TestProFileFieldExtraction:
    """Tests for specific field extraction from .pro files."""

    def test_extract_protocol_name(self):
        """Test extraction of ProtocolName field."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"
        result = load_pro_file(str(pro_file))

        assert "ProtocolName" in result
        assert isinstance(result["ProtocolName"], str)
        assert len(result["ProtocolName"]) > 0

    def test_extract_sequence_name(self):
        """Test extraction of SequenceName field."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"
        result = load_pro_file(str(pro_file))

        assert "SequenceName" in result
        assert isinstance(result["SequenceName"], str)

    def test_extract_timing_parameters(self):
        """Test extraction of timing parameters (TR, TE, etc.)."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"
        result = load_pro_file(str(pro_file))

        # At least one timing parameter should be present
        timing_params = ["RepetitionTime", "EchoTime"]
        has_timing = any(param in result for param in timing_params)
        assert has_timing, "No timing parameters found in .pro file"


class TestNominalFieldStrength:
    """Tests for mapping Siemens flNominalB0 to marketed MagneticFieldStrength."""

    def test_snaps_true_b0_to_marketed_value(self):
        """A 3T scanner reports flNominalB0 ~2.8936 T; DICOM expects 3.0."""
        from dicompare.io.pro import _nominal_field_strength

        assert _nominal_field_strength(2.89362001419) == 3.0
        assert _nominal_field_strength(1.494) == 1.5
        assert _nominal_field_strength(6.98) == 7.0

    def test_exact_marketed_values_unchanged(self):
        from dicompare.io.pro import _nominal_field_strength

        for strength in (1.5, 3.0, 7.0):
            assert _nominal_field_strength(strength) == strength

    def test_unknown_field_strength_passes_through(self):
        """Values not near any standard strength are preserved (rounded)."""
        from dicompare.io.pro import _nominal_field_strength

        assert _nominal_field_strength(2.0) == 2.0

    def test_pro_file_reports_nominal_field_strength(self):
        """End-to-end: a parsed .pro reports the marketed field strength,
        while ImagingFrequency stays consistent with the true B0."""
        pro_file = FIXTURES_DIR / "PRODUCT__ep2d_bold__p2_sms1.pro"
        result = load_pro_file(str(pro_file))

        # Marketed value, not the raw ~2.8936 T
        assert result["MagneticFieldStrength"] == 3.0
        # ImagingFrequency derives from the true B0 (~123.2 MHz at 3T), not 3.0*42.58
        assert abs(result["ImagingFrequency"] - 123.2) < 1.0


class TestScanOptionAndFlagDetection:
    """Regression tests for false positives caused by treating Siemens defaults as 'on'.

    Every protocol in a real archive carries non-zero physio trigger defaults,
    ucTOFInflow=4, acFlowComp=1 and lImagesPerSlab, so the old detections fired
    on essentially every scan.
    """

    def _base(self):
        # A minimal static, non-gated, non-TOF GRE protocol
        return {
            "tProtocolName": "gre_static",
            "sPhysioImaging": {"lSignal1": 1, "lMethod1": 1,
                               "sPhysioECG": {"lTriggerPulses": 1, "lTriggerWindow": 5},
                               "sPhysioResp": {"lRespGateThreshold": 20}},
            "sAngio": {"ucTOFInflow": 4, "ucPCFlowMode": 2},
            "acFlowComp": [1.0, 1.0],
            "sPrepPulses": {"ucFatSatMode": 2},
            "sRSatArray": {"asElm": [{"ulShape": 1}, {"ulShape": 1}]},
        }

    def test_no_gating_when_no_physio_signal_selected(self):
        from dicompare.io.pro import _detect_scan_options
        opts = _detect_scan_options(self._base())
        assert "RG" not in opts and "CG" not in opts and "PPG" not in opts

    def test_cardiac_gating_detected_when_selected(self):
        from dicompare.io.pro import _detect_scan_options
        data = self._base()
        data["sPhysioImaging"]["lSignal1"] = 2   # ECG
        data["sPhysioImaging"]["lMethod1"] = 4   # gated
        assert "CG" in _detect_scan_options(data)

    def test_fat_sat_uses_correct_key(self):
        from dicompare.io.pro import _detect_scan_options
        assert "FS" in _detect_scan_options(self._base())          # ucFatSatMode=2 -> on
        data = self._base()
        data["sPrepPulses"]["ucFatSatMode"] = 1                    # off
        assert "FS" not in _detect_scan_options(data)

    def test_empty_rsat_slots_do_not_trigger_sp(self):
        from dicompare.io.pro import _detect_scan_options
        assert "SP" not in _detect_scan_options(self._base())
        data = self._base()
        data["sRSatArray"]["asElm"][0]["dThickness"] = 40.0        # a real sat band
        assert "SP" in _detect_scan_options(data)

    def test_flow_comp_default_not_flagged(self):
        from dicompare.io.pro import _detect_scan_options
        assert "FC" not in _detect_scan_options(self._base())      # all 1.0 = off
        data = self._base()
        data["acFlowComp"] = [1.0, 16.0]                           # a real FC mode
        assert "FC" in _detect_scan_options(data)

    def test_tof_default_not_flagged_but_name_is(self):
        from dicompare.io.pro import calculate_other_dicom_fields
        d = {}
        calculate_other_dicom_fields(d, self._base())
        assert d["TimeOfFlightContrast"] == "NO"
        d2 = {}
        calculate_other_dicom_fields(d2, {**self._base(), "tProtocolName": "TOF_3D_neck"})
        assert d2["TimeOfFlightContrast"] == "YES"

    def test_temporal_positions_from_repetitions_not_partitions(self):
        from dicompare.io.pro import calculate_other_dicom_fields
        # Static 3D scan: many partitions, no repetitions -> a single temporal position
        d = {}
        calculate_other_dicom_fields(d, {**self._base(), "sKSpace": {"lImagesPerSlab": 176}})
        assert d["NumberOfTemporalPositions"] == 1
        # Dynamic scan: lRepetitions drives temporal positions
        d2 = {}
        calculate_other_dicom_fields(d2, {**self._base(), "lRepetitions": 494})
        assert d2["NumberOfTemporalPositions"] == 495


class TestInversionRecovery:
    """Regression tests for inversion-recovery detection and InversionTime units."""

    def test_mprage_inversion_time_in_milliseconds(self):
        """alTI is stored in microseconds; DICOM InversionTime must be in ms."""
        from dicompare.io.pro import calculate_other_dicom_fields
        d = {}
        # ucInversion=2 (MPRAGE volume inversion), TI = 1.1 s
        calculate_other_dicom_fields(d, {
            "ucSequenceType": 1,
            "sPrepPulses": {"ucInversion": 2},
            "alTI": [1100000],
        })
        assert d["InversionTime"] == 1100.0

    def test_flair_slice_selective_inversion_detected(self):
        """ucInversion=8 (e.g. FLAIR) is inversion recovery and must yield IR + TI."""
        from dicompare.io.pro import calculate_other_dicom_fields, _decode_sequence_type
        data = {"ucSequenceType": 8, "sPrepPulses": {"ucInversion": 8},
                "alTI": [1800000]}
        assert "IR" in _decode_sequence_type(data)
        d = {}
        calculate_other_dicom_fields(d, data)
        assert d["InversionTime"] == 1800.0

    def test_non_ir_default_not_flagged(self):
        """ucInversion=4 is a default/reapply value, not inversion recovery."""
        from dicompare.io.pro import calculate_other_dicom_fields, _decode_sequence_type
        data = {"ucSequenceType": 1, "sPrepPulses": {"ucInversion": 4},
                "alTI": [300000]}
        assert _decode_sequence_type(data) == "GR"
        d = {}
        calculate_other_dicom_fields(d, data)
        assert "InversionTime" not in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
