"""Tests for match command and schema library."""

import json
import pytest
import pandas as pd
from pathlib import Path
from argparse import Namespace

from dicompare.cli.match import compute_compliance_score, load_schemas_from_paths
from dicompare.tests.test_dicom_factory import create_test_dicom_series


class TestComputeComplianceScore:
    """Tests for the compliance scoring function."""

    def test_perfect_score(self):
        """Test that matching data gets 100% score."""
        session_df = pd.DataFrame({
            "Acquisition": ["acq1", "acq1"],
            "EchoTime": [30.0, 30.0],
        })
        schema_acq = {
            "fields": [{"field": "EchoTime", "value": 30.0}],
            "series": []
        }
        result = compute_compliance_score(session_df, schema_acq, "acq1")
        assert result['score'] == 100.0
        assert result['pass_count'] > 0
        assert result['fail_count'] == 0

    def test_zero_score(self):
        """Test that completely mismatched data gets low score."""
        session_df = pd.DataFrame({
            "Acquisition": ["acq1"],
            "EchoTime": [99.0],
        })
        schema_acq = {
            "fields": [{"field": "EchoTime", "value": 30.0}],
            "series": []
        }
        result = compute_compliance_score(session_df, schema_acq, "acq1")
        assert result['score'] == 0.0
        assert result['fail_count'] > 0

    def test_partial_score(self):
        """Test partial match produces intermediate score."""
        session_df = pd.DataFrame({
            "Acquisition": ["acq1"],
            "EchoTime": [30.0],
            "RepetitionTime": [9999.0],
        })
        schema_acq = {
            "fields": [
                {"field": "EchoTime", "value": 30.0},
                {"field": "RepetitionTime", "value": 2000.0},
            ],
            "series": []
        }
        result = compute_compliance_score(session_df, schema_acq, "acq1")
        assert 0 < result['score'] < 100
        assert result['pass_count'] >= 1
        assert result['fail_count'] >= 1

    def test_empty_schema_fields(self):
        """Test scoring with no schema fields."""
        session_df = pd.DataFrame({
            "Acquisition": ["acq1"],
            "EchoTime": [30.0],
        })
        schema_acq = {
            "fields": [],
            "series": []
        }
        result = compute_compliance_score(session_df, schema_acq, "acq1")
        assert result['total_count'] == 0
        assert result['score'] == 0.0

    def test_returns_expected_keys(self):
        """Test that result dict contains all expected keys."""
        session_df = pd.DataFrame({
            "Acquisition": ["acq1"],
            "EchoTime": [30.0],
        })
        schema_acq = {
            "fields": [{"field": "EchoTime", "value": 30.0}],
            "series": []
        }
        result = compute_compliance_score(session_df, schema_acq, "acq1")
        assert 'score' in result
        assert 'pass_count' in result
        assert 'fail_count' in result
        assert 'warning_count' in result
        assert 'total_count' in result
        assert 'na_count' in result


class TestSchemaLibrary:
    """Tests for bundled schema library."""

    def test_list_bundled_schemas(self):
        from dicompare.schemas import list_bundled_schemas
        schemas = list_bundled_schemas()
        assert isinstance(schemas, list)
        assert len(schemas) == 9
        assert all(s.endswith('.json') for s in schemas)

    def test_list_contains_known_schemas(self):
        from dicompare.schemas import list_bundled_schemas
        schemas = list_bundled_schemas()
        assert "hcp_schema.json" in schemas
        assert "UK_Biobank_v1.0.json" in schemas

    def test_load_bundled_schema(self):
        from dicompare.schemas import load_bundled_schema
        ref_fields, schema_dict, validation_rules = load_bundled_schema("hcp_schema.json")
        assert 'acquisitions' in schema_dict
        assert isinstance(ref_fields, list)
        assert len(schema_dict['acquisitions']) > 0

    def test_get_bundled_schema_path(self):
        from dicompare.schemas import get_bundled_schema_path
        path = get_bundled_schema_path("hcp_schema.json")
        assert path.exists()
        assert path.name == "hcp_schema.json"

    def test_nonexistent_schema_raises(self):
        from dicompare.schemas import get_bundled_schema_path
        with pytest.raises(FileNotFoundError):
            get_bundled_schema_path("nonexistent_schema.json")

    def test_load_all_bundled_schemas(self):
        from dicompare.schemas import load_all_bundled_schemas
        all_schemas = load_all_bundled_schemas()
        assert isinstance(all_schemas, dict)
        assert len(all_schemas) > 0
        for filename, (ref_fields, schema_dict, validation_rules) in all_schemas.items():
            assert 'acquisitions' in schema_dict


class TestLoadSchemasFromPaths:
    """Tests for loading schemas from file paths."""

    def test_load_from_file(self, tmp_path):
        """Test loading a single schema file."""
        schema = {
            "name": "Test Schema",
            "acquisitions": {
                "TestAcq": {
                    "fields": [{"field": "EchoTime", "value": 30.0, "tag": "0018,0081"}],
                    "series": []
                }
            }
        }
        schema_path = tmp_path / "test_schema.json"
        with open(schema_path, "w") as f:
            json.dump(schema, f)

        result = load_schemas_from_paths([str(schema_path)])
        assert len(result) == 1

    def test_load_from_directory(self, tmp_path):
        """Test loading schemas from a directory."""
        for name in ["schema1.json", "schema2.json"]:
            schema = {
                "name": f"Test {name}",
                "acquisitions": {
                    "Acq": {
                        "fields": [{"field": "EchoTime", "value": 30.0, "tag": "0018,0081"}],
                        "series": []
                    }
                }
            }
            with open(tmp_path / name, "w") as f:
                json.dump(schema, f)

        result = load_schemas_from_paths([str(tmp_path)])
        assert len(result) == 2

    def test_skips_index_json(self, tmp_path):
        """Test that index.json is skipped when loading from directory."""
        # Create a real schema
        schema = {
            "name": "Test",
            "acquisitions": {
                "Acq": {
                    "fields": [{"field": "EchoTime", "value": 30.0, "tag": "0018,0081"}],
                    "series": []
                }
            }
        }
        with open(tmp_path / "real_schema.json", "w") as f:
            json.dump(schema, f)

        # Create index.json
        with open(tmp_path / "index.json", "w") as f:
            json.dump(["real_schema.json"], f)

        result = load_schemas_from_paths([str(tmp_path)])
        assert len(result) == 1
        assert not any("index.json" in k for k in result.keys())

    def test_handles_invalid_schema(self, tmp_path):
        """Test that invalid schemas are skipped with a warning."""
        with open(tmp_path / "bad.json", "w") as f:
            f.write("not valid json")

        result = load_schemas_from_paths([str(tmp_path)])
        assert len(result) == 0


class TestMatchCommand:
    """Tests for the match_command function."""

    def test_match_with_library(self, tmp_path):
        """Test match command against bundled library."""
        from dicompare.cli.match import match_command

        # Create test DICOMs
        create_test_dicom_series(
            str(tmp_path),
            acquisition_name="T1_MPRAGE",
            num_slices=3,
            metadata_base={
                'ProtocolName': 'T1_MPRAGE',
                'RepetitionTime': 2000.0,
                'EchoTime': 3.0,
                'FlipAngle': 9.0,
            }
        )

        report_path = tmp_path / "match_report.json"
        args = Namespace(
            dicoms=str(tmp_path),
            schemas=None,
            library=True,
            report=str(report_path),
            top=3
        )

        match_command(args)

        assert report_path.exists()
        with open(report_path) as f:
            report = json.load(f)
        assert isinstance(report, dict)
        assert len(report) >= 1

        # Each acquisition should have ranked matches
        for acq_name, matches in report.items():
            assert isinstance(matches, list)
            assert len(matches) <= 3  # --top 3
            if matches:
                assert 'score' in matches[0]
                assert 'schema_name' in matches[0]
                assert 'ref_acquisition' in matches[0]

    def test_match_with_custom_schema(self, tmp_path):
        """Test match command with a custom schema directory."""
        from dicompare.cli.match import match_command

        # Create test DICOMs
        dicom_dir = tmp_path / "dicoms"
        dicom_dir.mkdir()
        create_test_dicom_series(
            str(dicom_dir),
            acquisition_name="T1",
            num_slices=2,
            metadata_base={
                'ProtocolName': 'T1_MPRAGE',
                'RepetitionTime': 2000.0,
                'EchoTime': 3.0,
            }
        )

        # Create a custom schema
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        schema = {
            "name": "Custom Schema",
            "acquisitions": {
                "T1w": {
                    "fields": [
                        {"field": "RepetitionTime", "value": 2000.0, "tag": "0018,0080"},
                        {"field": "EchoTime", "value": 3.0, "tag": "0018,0081"},
                    ],
                    "series": []
                }
            }
        }
        with open(schema_dir / "custom.json", "w") as f:
            json.dump(schema, f)

        report_path = tmp_path / "report.json"
        args = Namespace(
            dicoms=str(dicom_dir),
            schemas=[str(schema_dir)],
            library=False,
            report=str(report_path),
            top=5
        )

        match_command(args)

        assert report_path.exists()
        with open(report_path) as f:
            report = json.load(f)
        assert len(report) >= 1
