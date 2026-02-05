"""
Tests for CLI entrypoint functions.
"""

import json
import pytest
from argparse import Namespace
from pathlib import Path

from dicompare.cli.main import build_command, check_command
from dicompare.tests.test_dicom_factory import create_test_dicom_series


@pytest.fixture
def dicom_session_dir(tmp_path):
    """Create a temp directory with test DICOMs."""
    create_test_dicom_series(
        str(tmp_path),
        acquisition_name="T1_MPRAGE",
        num_slices=3,
        metadata_base={
            'ProtocolName': 'T1_MPRAGE',
            'RepetitionTime': 2000.0,
            'EchoTime': 3.0,
            'FlipAngle': 9.0,
            'SliceThickness': 1.0
        }
    )
    return tmp_path


@pytest.fixture
def multi_acquisition_dir(tmp_path):
    """Create a temp directory with multiple acquisitions."""
    # T1 acquisition
    t1_dir = tmp_path / "t1"
    t1_dir.mkdir()
    create_test_dicom_series(
        str(t1_dir),
        acquisition_name="T1",
        num_slices=2,
        metadata_base={
            'ProtocolName': 'T1_MPRAGE',
            'RepetitionTime': 2000.0,
            'EchoTime': 3.0
        }
    )

    # BOLD acquisition
    bold_dir = tmp_path / "bold"
    bold_dir.mkdir()
    create_test_dicom_series(
        str(bold_dir),
        acquisition_name="BOLD",
        num_slices=2,
        metadata_base={
            'ProtocolName': 'BOLD_task',
            'RepetitionTime': 1000.0,
            'EchoTime': 30.0
        }
    )

    return tmp_path


def test_build_command_basic(dicom_session_dir, tmp_path):
    """Test that build_command generates a valid schema file."""
    schema_path = tmp_path / "schema.json"

    args = Namespace(
        dicoms=str(dicom_session_dir),
        schema=str(schema_path)
    )

    build_command(args)

    # Verify schema file was created
    assert schema_path.exists()

    # Verify schema structure
    with open(schema_path) as f:
        schema = json.load(f)

    assert "acquisitions" in schema
    assert len(schema["acquisitions"]) >= 1


def test_build_command_multiple_acquisitions(multi_acquisition_dir, tmp_path):
    """Test that build_command handles multiple acquisitions."""
    schema_path = tmp_path / "schema.json"

    args = Namespace(
        dicoms=str(multi_acquisition_dir),
        schema=str(schema_path)
    )

    build_command(args)

    with open(schema_path) as f:
        schema = json.load(f)

    # Should have 2 acquisitions
    assert len(schema["acquisitions"]) == 2


def test_check_command_passing(dicom_session_dir, tmp_path):
    """Test that check_command passes for matching DICOMs."""
    # First build a schema from the DICOMs
    schema_path = tmp_path / "schema.json"
    build_args = Namespace(
        dicoms=str(dicom_session_dir),
        schema=str(schema_path)
    )
    build_command(build_args)

    # Now check the same DICOMs against the schema
    report_path = tmp_path / "report.json"
    check_args = Namespace(
        dicoms=str(dicom_session_dir),
        schema=str(schema_path),
        report=str(report_path),
        auto_yes=True
    )

    # Should not raise any errors
    check_command(check_args)

    # Verify report was created
    assert report_path.exists()

    with open(report_path) as f:
        report = json.load(f)

    # All results should be 'ok' (schema was built from same DICOMs)
    assert all(r.get('status') == 'ok' for r in report)


def test_check_command_with_report(dicom_session_dir, tmp_path):
    """Test that check_command creates a report file."""
    schema_path = tmp_path / "schema.json"
    report_path = tmp_path / "report.json"

    # Build schema
    build_command(Namespace(
        dicoms=str(dicom_session_dir),
        schema=str(schema_path)
    ))

    # Check with report
    check_command(Namespace(
        dicoms=str(dicom_session_dir),
        schema=str(schema_path),
        report=str(report_path),
        auto_yes=True
    ))

    assert report_path.exists()

    with open(report_path) as f:
        report = json.load(f)

    assert isinstance(report, list)


def test_match_command_with_library(dicom_session_dir, tmp_path):
    """Test that match_command runs against the bundled library."""
    from dicompare.cli.match import match_command

    report_path = tmp_path / "match_report.json"

    args = Namespace(
        dicoms=str(dicom_session_dir),
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


def test_match_command_with_custom_schema(dicom_session_dir, tmp_path):
    """Test match_command with a custom schema file."""
    from dicompare.cli.match import match_command

    # Build a schema from the same data for a guaranteed match
    schema_path = tmp_path / "schema.json"
    build_command(Namespace(
        dicoms=str(dicom_session_dir),
        schema=str(schema_path)
    ))

    report_path = tmp_path / "match_report.json"
    args = Namespace(
        dicoms=str(dicom_session_dir),
        schemas=[str(schema_path)],
        library=False,
        report=str(report_path),
        top=5
    )

    match_command(args)

    assert report_path.exists()
    with open(report_path) as f:
        report = json.load(f)
    assert isinstance(report, dict)

    # The self-built schema should produce a high score
    for acq_name, matches in report.items():
        assert len(matches) > 0
        assert matches[0]['score'] > 0
