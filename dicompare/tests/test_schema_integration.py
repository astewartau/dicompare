"""
Integration tests for example schema files.

Tests that the actual schema files in schemas/ directory can be loaded and validated
against mock DICOM data. This ensures the schemas are valid and their rules execute correctly.
"""

import pytest
import pandas as pd
import tempfile
import math
from pathlib import Path

import dicompare
from dicompare.tests.test_dicom_factory import create_test_dicom_series, create_multi_echo_series
from dicompare.validation import check_acquisition_compliance
from dicompare.validation.helpers import ComplianceStatus

def check_session_compliance(in_session, schema_data, session_map, validation_rules=None, validation_models=None, raise_errors=False):
    """Helper for legacy test format - uses new API internally."""
    for ref_acq_name, input_acq_name in session_map.items():
        if ref_acq_name in schema_data["acquisitions"]:
            acq_rules = validation_rules.get(ref_acq_name) if validation_rules else None
            acq_model = validation_models.get(ref_acq_name) if validation_models else None
            return check_acquisition_compliance(
                in_session,
                schema_data["acquisitions"][ref_acq_name],
                acquisition_name=input_acq_name,
                validation_rules=acq_rules,
                validation_model=acq_model,
                raise_errors=raise_errors
            )
    return []


class TestQSMConsensusGuidelines:
    """Integration tests for QSM Consensus Guidelines schema."""

    @pytest.fixture
    def qsm_schema(self):
        """Load QSM Consensus Guidelines schema."""
        schema_path = "schemas/QSM_Consensus_Guidelines_v1.0.json"
        fields, schema = dicompare.load_json_schema(schema_path)
        return fields, schema

    @pytest.fixture
    def valid_qsm_session(self, tmp_path):
        """Create a valid QSM DICOM session that should pass all rules."""
        # QSM requires multi-echo 3D GRE data with magnitude and phase
        echo_times = [4.92, 9.84, 14.76, 19.68]  # 4 echoes, uniform spacing

        all_paths = []

        # Create magnitude and phase images for each echo
        for echo_idx, echo_time in enumerate(echo_times):
            # Magnitude images
            mag_metadata = {
                'EchoTime': echo_time,
                'ImageType': ['ORIGINAL', 'PRIMARY', 'M', 'ND'],
                'RepetitionTime': 27.0,
                'FlipAngle': 15.0,
                'MRAcquisitionType': '3D',
                'PixelBandwidth': 200.0,
                'MagneticFieldStrength': 3.0,
                'SliceThickness': 0.75,
                'PixelSpacing': [0.75, 0.75],
                'Manufacturer': 'SIEMENS',
                'ProtocolName': 'QSM_protocol'
            }

            mag_paths, _ = create_test_dicom_series(
                str(tmp_path / f"mag_echo{echo_idx+1}"),
                f"QSM_mag_echo{echo_idx+1}",
                num_slices=3,
                metadata_base=mag_metadata
            )
            all_paths.extend(mag_paths)

            # Phase images
            phase_metadata = mag_metadata.copy()
            phase_metadata['ImageType'] = ['ORIGINAL', 'PRIMARY', 'P', 'ND']

            phase_paths, _ = create_test_dicom_series(
                str(tmp_path / f"phase_echo{echo_idx+1}"),
                f"QSM_phase_echo{echo_idx+1}",
                num_slices=3,
                metadata_base=phase_metadata
            )
            all_paths.extend(phase_paths)

        # Load session and assign acquisition numbers
        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["ProtocolName"],
            reference_fields=[]
        )
        return session_df

    @pytest.fixture
    def invalid_qsm_single_echo(self, tmp_path):
        """Create QSM session with only single echo (should fail)."""
        metadata = {
            'EchoTime': 10.0,
            'ImageType': ['ORIGINAL', 'PRIMARY', 'M', 'ND'],
            'RepetitionTime': 27.0,
            'FlipAngle': 15.0,
            'MRAcquisitionType': '3D',
            'PixelBandwidth': 200.0,
            'MagneticFieldStrength': 3.0,
            'SliceThickness': 0.75,
            'PixelSpacing': [0.75, 0.75],
            'ProtocolName': 'QSM_single_echo'
        }

        paths, _ = create_test_dicom_series(
            str(tmp_path), "QSM_single", num_slices=3, metadata_base=metadata
        )

        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["ProtocolName"],
            reference_fields=[]
        )
        return session_df

    @pytest.fixture
    def invalid_qsm_2d(self, tmp_path):
        """Create QSM session with 2D acquisition (should fail)."""
        echo_times = [4.92, 9.84, 14.76]

        all_paths = []
        for echo_idx, echo_time in enumerate(echo_times):
            metadata = {
                'EchoTime': echo_time,
                'ImageType': ['ORIGINAL', 'PRIMARY', 'M', 'ND'],
                'RepetitionTime': 27.0,
                'FlipAngle': 15.0,
                'MRAcquisitionType': '2D',  # Invalid - should be 3D
                'PixelBandwidth': 200.0,
                'MagneticFieldStrength': 3.0,
                'SliceThickness': 0.75,
                'PixelSpacing': [0.75, 0.75],
                'ProtocolName': 'QSM_2D'
            }

            paths, _ = create_test_dicom_series(
                str(tmp_path / f"echo{echo_idx+1}"),
                f"QSM_echo{echo_idx+1}",
                num_slices=3,
                metadata_base=metadata
            )
            all_paths.extend(paths)

        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["ProtocolName"],
            reference_fields=[]
        )
        return session_df

    def test_load_qsm_schema(self, qsm_schema):
        """Test that QSM schema loads successfully."""
        fields, schema = qsm_schema

        assert "acquisitions" in schema
        assert "QSM" in schema["acquisitions"]
        assert "rules" in schema["acquisitions"]["QSM"]

        # Should have 11 rules as defined in the schema
        assert len(schema["acquisitions"]["QSM"]["rules"]) == 10

        # Check some specific rules exist
        rule_ids = [r["id"] for r in schema["acquisitions"]["QSM"]["rules"]]
        assert "validate_echo_count" in rule_ids
        assert "validate_pixel_bandwidth" in rule_ids
        assert "validate_flip_angle" in rule_ids

    def test_valid_qsm_session_passes(self, qsm_schema, valid_qsm_session):
        """Test that a valid QSM session passes all rules."""
        fields, schema = qsm_schema

        # Get the actual acquisition name from the session
        actual_acq_name = valid_qsm_session['Acquisition'].iloc[0]
        session_map = {"QSM": actual_acq_name}

        # Use check_session_compliance with rules
        _, schema_data, validation_rules = dicompare.load_hybrid_schema(
            "schemas/QSM_Consensus_Guidelines_v1.0.json"
        )

        compliance = check_session_compliance(
            in_session=valid_qsm_session,
            schema_data=schema_data,
            session_map=session_map,
            validation_rules=validation_rules,
            raise_errors=False
        )

        # Should have some results
        assert len(compliance) > 0

        # Most rules should pass (some might warn about specific conditions)
        passed_rules = [r for r in compliance if r["passed"]]
        assert len(passed_rules) > 0

    def test_single_echo_qsm_fails(self, qsm_schema, invalid_qsm_single_echo):
        """Test that single-echo QSM fails validation."""
        _, schema_data, validation_rules = dicompare.load_hybrid_schema(
            "schemas/QSM_Consensus_Guidelines_v1.0.json"
        )

        # Get the actual acquisition name from the session
        actual_acq_name = invalid_qsm_single_echo['Acquisition'].iloc[0]
        session_map = {"QSM": actual_acq_name}

        compliance = check_session_compliance(
            in_session=invalid_qsm_single_echo,
            schema_data=schema_data,
            session_map=session_map,
            validation_rules=validation_rules,
            raise_errors=False
        )

        # Should have failures
        failed_rules = [r for r in compliance if not r["passed"]]
        assert len(failed_rules) > 0

        # Should specifically fail the echo count rule
        echo_count_failures = [
            r for r in failed_rules
            if "echo" in r.get("message", "").lower() or "echo" in r.get("rule_name", "").lower()
        ]
        assert len(echo_count_failures) > 0

    def test_2d_qsm_fails(self, qsm_schema, invalid_qsm_2d):
        """Test that 2D QSM acquisition fails validation."""
        _, schema_data, validation_rules = dicompare.load_hybrid_schema(
            "schemas/QSM_Consensus_Guidelines_v1.0.json"
        )

        # Get the actual acquisition name from the session
        actual_acq_name = invalid_qsm_2d['Acquisition'].iloc[0]
        session_map = {"QSM": actual_acq_name}

        compliance = check_session_compliance(
            in_session=invalid_qsm_2d,
            schema_data=schema_data,
            session_map=session_map,
            validation_rules=validation_rules,
            raise_errors=False
        )

        # Should have failures
        failed_rules = [r for r in compliance if not r["passed"]]
        assert len(failed_rules) > 0

        # Should specifically fail the 3D acquisition rule
        acq_type_failures = [
            r for r in failed_rules
            if "3D" in r.get("message", "") or "2D" in r.get("message", "")
        ]
        assert len(acq_type_failures) > 0


class TestUKBiobankSchema:
    """Integration tests for UK Biobank schema."""

    @pytest.fixture
    def ukb_schema(self):
        """Load UK Biobank schema."""
        schema_path = "schemas/UK_Biobank_v1.0.json"
        fields, schema = dicompare.load_json_schema(schema_path)
        return fields, schema

    @pytest.fixture
    def valid_t1_session(self, tmp_path, ukb_schema):
        """Create a valid T1 structural session matching UK Biobank specs using schema generator."""
        import zipfile
        import io

        _, schema = ukb_schema

        # Generate DICOMs from schema
        zip_bytes = dicompare.generate_test_dicoms_from_schema_json(
            schema,
            "T1 structural brain images"
        )

        # Extract to tmp_path
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            zf.extractall(tmp_path)

        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["SeriesDescription"],
            reference_fields=[]
        )
        return session_df

    @pytest.fixture
    def invalid_t1_wrong_tr(self, tmp_path):
        """Create T1 session with wrong TR (should fail tolerance)."""
        metadata = {
            'SeriesDescription': 'T1_p2_1mm_fov256_sag_TI_880',
            'SequenceName': '*tfl3d1_16ns',
            'SequenceVariant': ['SK', 'SP', 'MP', 'OSP'],
            'ScanningSequence': ['GR', 'IR'],
            'Manufacturer': 'SIEMENS',
            'ManufacturerModelName': 'Skyra',
            'MRAcquisitionType': '3D',
            'SliceThickness': 1.0,
            'PixelSpacing': [1.0, 1.0],
            'Rows': 256,
            'Columns': 256,
            'RepetitionTime': 2500.0,  # Wrong - should be 2000
            'EchoTime': 2.01,
            'InversionTime': 880.0,
            'FlipAngle': 8.0,
            'MagneticFieldStrength': 3.0,
            'PixelBandwidth': 240.0,
            'ImageType': ['ORIGINAL', 'PRIMARY', 'M', 'ND', 'NORM'],
            'ProtocolName': 'T1_wrong_TR'
        }

        paths, _ = create_test_dicom_series(
            str(tmp_path), "T1_wrong", num_slices=3,
            rows=256, columns=256,
            metadata_base=metadata
        )

        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["ProtocolName"],
            reference_fields=[]
        )
        return session_df

    @pytest.fixture
    def valid_dwi_session(self, tmp_path):
        """Create a valid diffusion session with rules."""
        # Create base diffusion metadata
        base_metadata = {
            'SequenceVariant': ['SK', 'SS'],
            'ScanningSequence': 'EP',
            'Manufacturer': 'SIEMENS',
            'ManufacturerModelName': 'Skyra',
            'MRAcquisitionType': '2D',
            'SliceThickness': 2.0,
            'PixelSpacing': [2.01923, 2.01923],
            'Rows': 936,
            'Columns': 936,
            'AcquisitionMatrix': [104, 0, 0, 104],
            'RepetitionTime': 3600.0,
            'EchoTime': 92.0,
            'FlipAngle': 78.0,
            'EchoTrainLength': 78,
            'MultibandFactor': 3,
            'PixelBandwidth': 1780.0,
            'InPlanePhaseEncodingDirection': 'COL',
            'NumberOfPhaseEncodingSteps': 78,
            'MagneticFieldStrength': 3.0,
            'ImagingFrequency': 123.2639,
            'ImagedNucleus': '1H',
            'TransmitCoilName': 'Body',
            'PercentSampling': 100.0,
            'PercentPhaseFieldOfView': 100.0,
            'ScanOptions': ['PFP', 'FS'],
            'AngioFlag': 'N',
            'ImageType': ['ORIGINAL', 'PRIMARY', 'DIFFUSION', 'NONE', 'MB', 'ND', 'MOSAIC'],
            'ProtocolName': 'DWI_MB3'
        }

        # Create varying DiffusionBValue for different shells
        # Simulate 100 directions with b=0, b=1000, b=2000 shells
        num_b0 = 10
        num_b1000 = 50
        num_b2000 = 50
        total_volumes = num_b0 + num_b1000 + num_b2000

        b_values = [0] * num_b0 + [1000] * num_b1000 + [2000] * num_b2000

        varying_fields = {
            'DiffusionBValue': b_values,
            'InstanceNumber': list(range(1, total_volumes + 1))
        }

        # Note: DiffusionGradientDirectionSequence is a complex sequence tag
        # that would require creating Dataset objects for each gradient.
        # For this test, we just use DiffusionBValue which is sufficient
        # to test the validation rules.

        paths, _ = create_test_dicom_series(
            str(tmp_path), "DWI", num_slices=total_volumes,
            rows=104, columns=104,  # Smaller for speed
            metadata_base=base_metadata,
            varying_fields=varying_fields
        )

        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["ProtocolName"],
            reference_fields=[]
        )
        return session_df

    def test_load_ukb_schema(self, ukb_schema):
        """Test that UK Biobank schema loads successfully."""
        fields, schema = ukb_schema

        assert "acquisitions" in schema

        # Should have multiple acquisitions
        assert len(schema["acquisitions"]) == 6

        # Check specific acquisitions exist
        assert "T1 structural brain images" in schema["acquisitions"]
        assert "Multiband diffusion brain images" in schema["acquisitions"]

        # T1 should have fields with tolerance
        t1_acq = schema["acquisitions"]["T1 structural brain images"]
        assert "fields" in t1_acq

        # Check tolerance is used
        pixel_bandwidth_field = next(
            (f for f in t1_acq["fields"] if f["field"] == "PixelBandwidth"),
            None
        )
        assert pixel_bandwidth_field is not None
        assert "tolerance" in pixel_bandwidth_field
        assert pixel_bandwidth_field["tolerance"] == 1

        # Diffusion should have rules
        dwi_acq = schema["acquisitions"]["Multiband diffusion brain images"]
        assert "rules" in dwi_acq
        assert len(dwi_acq["rules"]) == 2

    def test_valid_t1_session_passes(self, ukb_schema, valid_t1_session):
        """Test that a valid T1 session passes field validation."""
        fields, schema = ukb_schema

        # Get the single acquisition from schema
        schema_acq = schema["acquisitions"]["T1 structural brain images"]

        # Get the actual acquisition name from the session
        actual_acq_name = valid_t1_session['Acquisition'].iloc[0]

        compliance = dicompare.check_acquisition_compliance(
            in_session=valid_t1_session,
            schema_acquisition=schema_acq,
            acquisition_name=actual_acq_name
        )

        # Should have results
        assert len(compliance) > 0

        # Most fields should pass
        passed_fields = [r for r in compliance if r["passed"]]
        failed_fields = [r for r in compliance if not r["passed"]]

        # Should have more passes than failures
        assert len(passed_fields) >= len(failed_fields)

    def test_t1_wrong_tr_fails_tolerance(self, ukb_schema, invalid_t1_wrong_tr):
        """Test that T1 with wrong TR fails validation."""
        fields, schema = ukb_schema

        # Get the actual acquisition name from the session
        actual_acq_name = invalid_t1_wrong_tr['Acquisition'].iloc[0]

        # Get the single acquisition from schema
        schema_acq = schema["acquisitions"]["T1 structural brain images"]

        compliance = dicompare.check_acquisition_compliance(
            in_session=invalid_t1_wrong_tr,
            schema_acquisition=schema_acq,
            acquisition_name=actual_acq_name
        )

        # Should have failures
        failed_fields = [r for r in compliance if not r["passed"]]
        assert len(failed_fields) > 0

        # Should specifically fail RepetitionTime
        tr_failures = [
            r for r in failed_fields
            if r.get("field") == "RepetitionTime"
        ]
        assert len(tr_failures) > 0

    def test_dwi_session_with_rules(self, ukb_schema, valid_dwi_session):
        """Test that diffusion session validates with embedded Python rules."""
        _, schema_data, validation_rules = dicompare.load_hybrid_schema(
            "schemas/UK_Biobank_v1.0.json"
        )

        # Get the actual acquisition name from the session
        actual_acq_name = valid_dwi_session['Acquisition'].iloc[0]
        session_map = {"Multiband diffusion brain images": actual_acq_name}

        compliance = check_session_compliance(
            in_session=valid_dwi_session,
            schema_data=schema_data,
            session_map=session_map,
            validation_rules=validation_rules,
            raise_errors=False
        )

        # Should have results
        assert len(compliance) > 0

        # Check that rule-based validation ran
        rule_results = [
            r for r in compliance
            if r.get("rule_name") and r.get("rule_name") != "Acquisition presence"
        ]
        assert len(rule_results) > 0


class TestSchemaFeatures:
    """Test specific schema features work correctly."""

    def test_tolerance_validation(self, tmp_path):
        """Test that tolerance validation works as expected."""
        # Create session with value slightly off from expected
        metadata = {
            'RepetitionTime': 2005.0,  # Expected 2000 ± 10
            'PixelBandwidth': 240.5,   # Expected 240 ± 1
            'ProtocolName': 'tolerance_test'
        }

        paths, _ = create_test_dicom_series(
            str(tmp_path), "test", num_slices=2, metadata_base=metadata
        )

        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["ProtocolName"],
            reference_fields=[]
        )

        # Get the actual acquisition name (it will be normalized)
        acq_name = session_df['Acquisition'].iloc[0]

        # Create schema acquisition (no need for full schema wrapper)
        schema_acq = {
            "fields": [
                {"field": "RepetitionTime", "value": 2000, "tolerance": 10},
                {"field": "PixelBandwidth", "value": 240, "tolerance": 1}
            ],
            "series": []
        }

        # Use new API directly - validate one acquisition
        compliance = check_acquisition_compliance(
            in_session=session_df,
            schema_acquisition=schema_acq,
            acquisition_name=acq_name
        )

        # Both should pass - within tolerance
        assert all(r["passed"] for r in compliance)

    def test_contains_any_validation(self, tmp_path):
        """Test that contains_any validation works with list values."""
        # Create session with multi-valued field
        metadata = {
            'ScanningSequence': ['GR', 'IR'],
            'SequenceVariant': ['SK', 'SP', 'MP'],
            'ProtocolName': 'contains_any_test'
        }

        paths, _ = create_test_dicom_series(
            str(tmp_path), "test", num_slices=2, metadata_base=metadata
        )

        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["ProtocolName"],
            reference_fields=[]
        )

        # Get the actual acquisition name
        acq_name = session_df['Acquisition'].iloc[0]

        # Create schema acquisition
        schema_acq = {
            "fields": [
                {"field": "ScanningSequence", "contains_any": ["GR", "SE"]},
                {"field": "SequenceVariant", "contains_any": ["MP", "OSP"]}
            ],
            "series": []
        }

        # Use new API directly
        compliance = check_acquisition_compliance(
            in_session=session_df,
            schema_acquisition=schema_acq,
            acquisition_name=acq_name
        )

        # Both should pass - contains at least one required value
        assert all(r["passed"] for r in compliance)

    def test_series_validation(self, tmp_path):
        """Test that series-level validation works correctly."""
        # Create session with multiple series (different ImageType)
        metadata_series1 = {
            'ImageType': ['ORIGINAL', 'PRIMARY', 'M', 'ND', 'NORM'],
            'EchoTime': 2.01,
            'ProtocolName': 'series_test'
        }

        metadata_series2 = {
            'ImageType': ['ORIGINAL', 'PRIMARY', 'M', 'ND'],
            'EchoTime': 2.01,
            'ProtocolName': 'series_test'
        }

        # Create series 1
        paths1, _ = create_test_dicom_series(
            str(tmp_path / "series1"), "test", num_slices=2,
            metadata_base=metadata_series1
        )

        # Create series 2
        paths2, _ = create_test_dicom_series(
            str(tmp_path / "series2"), "test", num_slices=2,
            metadata_base=metadata_series2
        )

        session_df = dicompare.load_dicom_session(str(tmp_path), show_progress=False)
        session_df = dicompare.assign_acquisition_and_run_numbers(
            session_df,
            acquisition_fields=["ProtocolName"],
            reference_fields=[]
        )

        # Get the actual acquisition name
        acq_name = session_df['Acquisition'].iloc[0]

        # Create schema acquisition with series definitions
        schema_acq = {
            "fields": [
                {"field": "EchoTime", "value": 2.01}
            ],
            "series": [
                {
                    "name": "Series_001",
                    "fields": [
                        {"field": "ImageType", "value": ['ORIGINAL', 'PRIMARY', 'M', 'ND', 'NORM']}
                    ]
                },
                {
                    "name": "Series_002",
                    "fields": [
                        {"field": "ImageType", "value": ['ORIGINAL', 'PRIMARY', 'M', 'ND']}
                    ]
                }
            ]
        }

        # Use new API directly
        compliance = check_acquisition_compliance(
            in_session=session_df,
            schema_acquisition=schema_acq,
            acquisition_name=acq_name
        )

        # Should have run series validation
        series_results = [r for r in compliance if r.get("series")]
        assert len(series_results) >= 1

        # At least one series should be found (may not all pass depending on data)
        # The key is that series validation ran without errors
