"""
Test cases for web utility functions.
"""

import tempfile
import pytest
from dicompare.interface import analyze_dicom_files_for_web
from dicompare.tests.test_dicom_factory import create_test_dicom_series


@pytest.mark.asyncio
async def test_analyze_dicom_files_for_web_basic():
    """Test analyze_dicom_files_for_web with valid DICOM data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create real test DICOM files
        _, dicom_bytes = create_test_dicom_series(
            base_dir=tmpdir,
            acquisition_name="T1_MPRAGE",
            num_slices=3,
            metadata_base={
                'RepetitionTime': 2300.0,
                'EchoTime': 2.98,
                'FlipAngle': 9.0,
                'SeriesDescription': 'T1w anatomical'
            }
        )

        # Call function with real data
        result = await analyze_dicom_files_for_web(
            dicom_bytes,
            reference_fields=['RepetitionTime', 'EchoTime', 'FlipAngle']
        )

        # Verify results
        assert result['status'] == 'success'
        assert result['total_files'] == 3
        assert 'acquisitions' in result
        assert 'field_summary' in result


@pytest.mark.asyncio
async def test_analyze_dicom_files_for_web_default_fields():
    """Test analyze_dicom_files_for_web uses default fields when none provided."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create real test DICOM files
        _, dicom_bytes = create_test_dicom_series(
            base_dir=tmpdir,
            acquisition_name="BOLD_fMRI",
            num_slices=2,
            metadata_base={
                'RepetitionTime': 2000.0,
                'EchoTime': 30.0,
                'SeriesDescription': 'functional run'
            }
        )

        # Call with None reference_fields (should use defaults)
        result = await analyze_dicom_files_for_web(dicom_bytes, None)

        assert result['status'] == 'success'
        assert result['total_files'] == 2


@pytest.mark.asyncio
async def test_analyze_dicom_files_for_web_empty_files():
    """Test analyze_dicom_files_for_web with empty files dict."""
    result = await analyze_dicom_files_for_web({})

    assert result['status'] == 'error'
    assert 'message' in result


@pytest.mark.asyncio
async def test_analyze_dicom_files_for_web_multiple_acquisitions():
    """Test analyze_dicom_files_for_web with multiple acquisitions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create T1 series
        _, t1_bytes = create_test_dicom_series(
            base_dir=tmpdir,
            acquisition_name="T1_MPRAGE",
            num_slices=2,
            metadata_base={'RepetitionTime': 2300.0, 'EchoTime': 2.98}
        )

        # Create T2 series
        _, t2_bytes = create_test_dicom_series(
            base_dir=tmpdir,
            acquisition_name="T2_TSE",
            num_slices=2,
            metadata_base={'RepetitionTime': 5000.0, 'EchoTime': 100.0}
        )

        # Combine
        all_bytes = {**t1_bytes, **t2_bytes}

        result = await analyze_dicom_files_for_web(
            all_bytes,
            reference_fields=['RepetitionTime', 'EchoTime']
        )

        assert result['status'] == 'success'
        assert result['total_files'] == 4
        assert len(result['acquisitions']) == 2
