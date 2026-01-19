"""
Tests for Philips ExamCard file loading functionality.

This module tests the loading and parsing of Philips ExamCard files.
"""

import pytest
import tempfile
import os
from pathlib import Path

from dicompare.io.examcard import (
    load_examcard_file,
    load_examcard_file_schema_format,
    apply_examcard_to_dicom_mapping,
    _sort_output_fields,
    _calculate_derived_fields,
    PHILIPS_TO_DICOM_MAPPING,
    PHILIPS_ENUM_MAPPINGS,
    USEFUL_PHILIPS_PARAMETERS,
    DERIVED_FIELD_SOURCES,
    DICOM_FIELD_ORDER,
)


class TestApplyExamcardToDicomMapping:
    """Tests for the DICOM mapping function."""

    def test_basic_mapping(self):
        """Test basic parameter to DICOM mapping."""
        scan_data = {
            "name": "Test Scan",
            "parameters": {
                "EX_ACQ_flip_angle": 90.0,
                "EX_ACQ_se_rep_time": 2000.0,
                "EX_ACQ_first_echo_time": 30.0,
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert result["Manufacturer"] == "Philips"
        assert result["ProtocolName"] == "Test Scan"
        assert result["FlipAngle"] == 90.0
        assert result["RepetitionTime"] == 2000.0
        assert result["EchoTime"] == 30.0

    def test_enum_mapping(self):
        """Test enum value translation."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_ACQ_scan_mode": 0,  # Should map to "2D"
                "EX_ACQ_imaging_sequence": 0,  # Should map to "SE"
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert result["MRAcquisitionType"] == "2D"
        assert result["ScanningSequence"] == "SE"

    def test_enum_mapping_3d(self):
        """Test 3D acquisition mode mapping."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_ACQ_scan_mode": 1,  # Should map to "3D"
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)
        assert result["MRAcquisitionType"] == "3D"

    def test_dual_echo_time(self):
        """Test dual echo time handling."""
        scan_data = {
            "name": "Dual Echo",
            "parameters": {
                "EX_ACQ_first_echo_time": 10.0,
                "EX_ACQ_second_echo_time": 20.0,
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        # Should be a list of two echo times
        assert result["EchoTime"] == [10.0, 20.0]

    def test_pixel_spacing_calculation(self):
        """Test PixelSpacing calculation from voxel sizes."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_PROC_recon_voxel_size_m": 1.5,
                "EX_PROC_recon_voxel_size_p": 1.5,
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert "PixelSpacing" in result
        assert result["PixelSpacing"] == [1.5, 1.5]

    def test_percent_phase_fov_calculation(self):
        """Test PercentPhaseFieldOfView calculation."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_GEO_fov": 256.0,
                "EX_GEO_fov_p": 192.0,
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert "PercentPhaseFieldOfView" in result
        assert result["PercentPhaseFieldOfView"] == 75.0  # 192/256 * 100

    def test_number_of_slices_sum(self):
        """Test NumberOfSlices is summed from stacks."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_GEO_stacks_slices": [4, 1, 1, 1, 1],  # Total = 8
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert result["NumberOfSlices"] == 8

    def test_number_of_slices_single_value(self):
        """Test NumberOfSlices with single integer value."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_GEO_stacks_slices": 32,
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert result["NumberOfSlices"] == 32

    def test_derived_fields_excluded(self):
        """Test that derived field sources are excluded from Philips_ prefix."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_GEO_voxel_size_m": 1.0,  # Used for PixelSpacing
                "EX_GEO_voxel_size_p": 1.0,
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        # Should not have Philips_GEO_voxel_size_m
        assert "Philips_GEO_voxel_size_m" not in result
        assert "Philips_GEO_voxel_size_p" not in result

    def test_useful_philips_parameters_included(self):
        """Test that useful Philips parameters are included."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_SPIR_fat_suppression": 1,  # In USEFUL_PHILIPS_PARAMETERS
            },
            "enum_map": {
                "EX_SPIR_fat_suppression": ["NO", "SPIR", "SPAIR"]
            }
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert "Philips_SPIR_fat_suppression" in result
        assert result["Philips_SPIR_fat_suppression"] == "SPIR"

    def test_series_description(self):
        """Test SeriesDescription from methodDescription."""
        scan_data = {
            "name": "Test",
            "methodDescription": "  T2W TSE AXIAL  ",
            "parameters": {},
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert result["SeriesDescription"] == "T2W TSE AXIAL"

    def test_patient_position_mapping(self):
        """Test PatientPosition enum mapping."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_GEO_patient_body_position": 0,  # HFS
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert result["PatientPosition"] == "HFS"

    def test_diffusion_fields(self):
        """Test diffusion-related field mapping."""
        scan_data = {
            "name": "DWI",
            "parameters": {
                "EX_DIFF_enable": 1,  # ISOTROPIC/DWI
                "EX_DIFF_b_value": 1000.0,
                "EX_DIFF_nr_directions": 6,
            },
            "enum_map": {}
        }

        result = apply_examcard_to_dicom_mapping(scan_data)

        assert result["DiffusionDirectionality"] == "ISOTROPIC"
        assert result["DiffusionBValue"] == 1000.0
        assert result["NumberOfDiffusionDirections"] == 6


class TestSortOutputFields:
    """Tests for field ordering."""

    def test_dicom_fields_first(self):
        """Test that DICOM fields come before Philips fields."""
        fields = {
            "Philips_test": 1,
            "RepetitionTime": 2000,
            "Manufacturer": "Philips",
            "EchoTime": 30,
        }

        result = _sort_output_fields(fields)
        keys = list(result.keys())

        # Philips_ should be last
        philips_idx = keys.index("Philips_test")
        for key in ["RepetitionTime", "Manufacturer", "EchoTime"]:
            assert keys.index(key) < philips_idx

    def test_ordered_dicom_fields(self):
        """Test that DICOM fields follow DICOM_FIELD_ORDER."""
        fields = {
            "EchoTime": 30,
            "RepetitionTime": 2000,
            "Manufacturer": "Philips",
            "SeriesDescription": "Test",
        }

        result = _sort_output_fields(fields)
        keys = list(result.keys())

        # SeriesDescription should come before Manufacturer
        # Manufacturer should come before RepetitionTime
        # RepetitionTime should come before EchoTime
        assert keys.index("SeriesDescription") < keys.index("Manufacturer")
        assert keys.index("Manufacturer") < keys.index("RepetitionTime")
        assert keys.index("RepetitionTime") < keys.index("EchoTime")

    def test_philips_fields_alphabetical(self):
        """Test that Philips fields are sorted alphabetically."""
        fields = {
            "Philips_Z_field": 1,
            "Philips_A_field": 2,
            "Philips_M_field": 3,
            "Manufacturer": "Philips",
        }

        result = _sort_output_fields(fields)
        keys = list(result.keys())

        philips_keys = [k for k in keys if k.startswith("Philips_")]
        assert philips_keys == sorted(philips_keys)


class TestCalculateDerivedFields:
    """Tests for derived field calculations."""

    def test_echo_time_single(self):
        """Test single echo time."""
        dicom_fields = {}
        params = {"EX_ACQ_first_echo_time": 25.0}

        _calculate_derived_fields(dicom_fields, params)

        assert dicom_fields["EchoTime"] == 25.0

    def test_echo_time_dual(self):
        """Test dual echo time creates list."""
        dicom_fields = {}
        params = {
            "EX_ACQ_first_echo_time": 10.0,
            "EX_ACQ_second_echo_time": 20.0,
        }

        _calculate_derived_fields(dicom_fields, params)

        assert dicom_fields["EchoTime"] == [10.0, 20.0]

    def test_echo_time_second_zero_ignored(self):
        """Test second echo time of 0 is ignored."""
        dicom_fields = {}
        params = {
            "EX_ACQ_first_echo_time": 10.0,
            "EX_ACQ_second_echo_time": 0,
        }

        _calculate_derived_fields(dicom_fields, params)

        assert dicom_fields["EchoTime"] == 10.0

    def test_acquisition_duration_parsing(self):
        """Test AcquisitionDuration parsing from time string."""
        dicom_fields = {}
        params = {"IF_str_total_scan_time": "03:30.5"}

        _calculate_derived_fields(dicom_fields, params)

        assert dicom_fields["AcquisitionDuration"] == 210.5  # 3*60 + 30.5

    def test_tr_from_combined_string(self):
        """Test TR parsing from combined TR/TE string."""
        dicom_fields = {}
        params = {"IF_act_rep_time_echo_time": "2500.0 / 80.0"}

        _calculate_derived_fields(dicom_fields, params)

        assert dicom_fields["RepetitionTime"] == 2500.0
        assert dicom_fields["EchoTime"] == 80.0


class TestConstants:
    """Tests for module constants."""

    def test_dicom_mapping_not_empty(self):
        """Test PHILIPS_TO_DICOM_MAPPING has entries."""
        assert len(PHILIPS_TO_DICOM_MAPPING) > 0

    def test_enum_mappings_not_empty(self):
        """Test PHILIPS_ENUM_MAPPINGS has entries."""
        assert len(PHILIPS_ENUM_MAPPINGS) > 0

    def test_useful_parameters_not_empty(self):
        """Test USEFUL_PHILIPS_PARAMETERS has entries."""
        assert len(USEFUL_PHILIPS_PARAMETERS) > 0

    def test_derived_sources_not_empty(self):
        """Test DERIVED_FIELD_SOURCES has entries."""
        assert len(DERIVED_FIELD_SOURCES) > 0

    def test_field_order_not_empty(self):
        """Test DICOM_FIELD_ORDER has entries."""
        assert len(DICOM_FIELD_ORDER) > 0

    def test_key_dicom_fields_in_order(self):
        """Test key DICOM fields are in order list."""
        key_fields = [
            "RepetitionTime",
            "EchoTime",
            "FlipAngle",
            "SliceThickness",
            "Manufacturer",
        ]
        for field in key_fields:
            assert field in DICOM_FIELD_ORDER


class TestEdgeCases:
    """Edge case tests for additional coverage."""

    def test_empty_scan_data(self):
        """Test with empty parameters."""
        scan_data = {
            "name": "Empty",
            "parameters": {},
            "enum_map": {}
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        assert result["Manufacturer"] == "Philips"
        assert result["ProtocolName"] == "Empty"

    def test_none_values_skipped(self):
        """Test that None values are skipped."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_ACQ_flip_angle": None,
                "EX_ACQ_se_rep_time": 2000.0,
            },
            "enum_map": {}
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        assert "FlipAngle" not in result
        assert result["RepetitionTime"] == 2000.0

    def test_empty_string_values_skipped(self):
        """Test that empty string values are skipped."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_ACQ_flip_angle": "",
            },
            "enum_map": {}
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        assert "FlipAngle" not in result

    def test_zero_second_echo_ignored(self):
        """Test that zero second echo time is ignored."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_ACQ_first_echo_time": 20.0,
                "EX_ACQ_second_echo_time": 0,
            },
            "enum_map": {}
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        assert result["EchoTime"] == 20.0

    def test_acquisition_duration_invalid_format(self):
        """Test AcquisitionDuration with invalid format."""
        dicom_fields = {}
        params = {"IF_str_total_scan_time": "invalid"}
        _calculate_derived_fields(dicom_fields, params)
        assert "AcquisitionDuration" not in dicom_fields

    def test_tr_te_string_invalid(self):
        """Test TR/TE parsing with invalid format."""
        dicom_fields = {}
        params = {"IF_act_rep_time_echo_time": "invalid"}
        _calculate_derived_fields(dicom_fields, params)
        assert "RepetitionTime" not in dicom_fields

    def test_percent_fov_zero_fov(self):
        """Test PercentPhaseFieldOfView with zero FOV."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_GEO_fov": 0,
                "EX_GEO_fov_p": 192.0,
            },
            "enum_map": {}
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        # Should not crash or have PercentPhaseFieldOfView
        assert "PercentPhaseFieldOfView" not in result

    def test_enum_fallback_to_file_map(self):
        """Test enum value uses file's enum_map as fallback."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_ACQ_imaging_sequence": 10,  # Not in PHILIPS_ENUM_MAPPINGS
            },
            "enum_map": {
                "EX_ACQ_imaging_sequence": ["SE", "IR", "GR", "EP", "RM", "SS", "OTHER", "X1", "X2", "X3", "CUSTOM"]
            }
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        assert result["ScanningSequence"] == "CUSTOM"

    def test_3d_acquisition_mode(self):
        """Test 3D acquisition mode mapping."""
        scan_data = {
            "name": "Test",
            "parameters": {
                "EX_ACQ_scan_mode": 1,
            },
            "enum_map": {}
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        assert result["MRAcquisitionType"] == "3D"


class TestFileOperations:
    """Tests for file loading operations."""

    def test_load_examcard_file_not_found(self):
        """Test FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_examcard_file("/nonexistent/path/test.ExamCard")

    def test_load_examcard_file_schema_format_not_found(self):
        """Test FileNotFoundError for schema format loading."""
        with pytest.raises(FileNotFoundError):
            load_examcard_file_schema_format("/nonexistent/path/test.ExamCard")
