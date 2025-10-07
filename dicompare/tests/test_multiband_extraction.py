"""
Tests for multiband factor extraction from ImageComments field.
"""
import pytest
import pydicom
from dicompare.io.dicom import extract_inferred_metadata


class TestMultibandExtraction:
    """Test multiband factor extraction from ImageComments and ProtocolName."""

    def test_extract_from_image_comments_unaliased_mb3(self):
        """Test extraction from ImageComments 'Unaliased MB3/PE3 SENSE1'."""
        ds = pydicom.Dataset()
        ds.ImageComments = "Unaliased MB3/PE3 SENSE1"

        metadata = extract_inferred_metadata(ds)

        assert metadata["MultibandFactor"] == 3
        assert metadata["MultibandAccelerationFactor"] == 3
        assert metadata["ParallelReductionFactorOutOfPlane"] == 3

    def test_extract_from_image_comments_with_leakblock(self):
        """Test extraction from ImageComments with LeakBlock notation."""
        ds = pydicom.Dataset()
        ds.ImageComments = "Unaliased MB4/PE3/LB"

        metadata = extract_inferred_metadata(ds)

        assert metadata["MultibandFactor"] == 4
        assert metadata["MultibandAccelerationFactor"] == 4

    def test_extract_from_image_comments_mb2(self):
        """Test extraction from ImageComments with MB2."""
        ds = pydicom.Dataset()
        ds.ImageComments = "Unaliased MB2/PE2"

        metadata = extract_inferred_metadata(ds)

        assert metadata["MultibandFactor"] == 2

    def test_extract_from_protocol_name(self):
        """Test extraction from ProtocolName when ImageComments doesn't have MB."""
        ds = pydicom.Dataset()
        ds.ProtocolName = "diff_PA_MPopt_MB3_3b0_lowflip"

        metadata = extract_inferred_metadata(ds)

        assert metadata["MultibandFactor"] == 3

    def test_image_comments_takes_priority_over_protocol_name(self):
        """Test that ImageComments takes priority over ProtocolName."""
        ds = pydicom.Dataset()
        ds.ImageComments = "Unaliased MB4/PE3"
        ds.ProtocolName = "diff_MB2_test"

        metadata = extract_inferred_metadata(ds)

        # Should get MB4 from ImageComments, not MB2 from ProtocolName
        assert metadata["MultibandFactor"] == 4

    def test_fallback_to_protocol_name_when_no_mb_in_comments(self):
        """Test fallback to ProtocolName when ImageComments has no MB pattern."""
        ds = pydicom.Dataset()
        ds.ImageComments = "Single-band reference SENSE1"
        ds.ProtocolName = "diff_MB3_test"

        metadata = extract_inferred_metadata(ds)

        # Should fall back to ProtocolName
        assert metadata["MultibandFactor"] == 3

    def test_no_multiband_info_returns_empty(self):
        """Test that no multiband info returns empty dict."""
        ds = pydicom.Dataset()
        ds.ImageComments = "Single-band reference SENSE1"
        ds.ProtocolName = "T1_weighted"

        metadata = extract_inferred_metadata(ds)

        assert "MultibandFactor" not in metadata
        assert "MultibandAccelerationFactor" not in metadata

    def test_case_insensitive_matching(self):
        """Test case-insensitive matching for MB pattern."""
        ds = pydicom.Dataset()
        ds.ImageComments = "Unaliased mb5/PE3"

        metadata = extract_inferred_metadata(ds)

        assert metadata["MultibandFactor"] == 5

    def test_protocol_name_case_insensitive(self):
        """Test case-insensitive matching for ProtocolName."""
        ds = pydicom.Dataset()
        ds.ProtocolName = "diff_Mb6_test"

        metadata = extract_inferred_metadata(ds)

        assert metadata["MultibandFactor"] == 6

    def test_multidigit_multiband_factor(self):
        """Test extraction of multi-digit multiband factors."""
        ds = pydicom.Dataset()
        ds.ImageComments = "Unaliased MB12/PE3"

        metadata = extract_inferred_metadata(ds)

        assert metadata["MultibandFactor"] == 12
