"""
Tests for CSA header writing functionality.
"""
import pytest
import pydicom
import struct
from dicompare.io.csa_writer import (
    encode_csa_header,
    add_csa_tags_to_dicom,
    extract_csa_fields_from_test_data
)
from nibabel.nicom.csareader import read as read_csa_header


class TestCSAHeaderEncoding:
    """Test CSA header encoding and writing."""

    def test_encode_simple_csa_header(self):
        """Test encoding a simple CSA header with a few tags."""
        tags = {
            'MultibandFactor': 3,
            'B_value': 1000,
        }

        csa_data = encode_csa_header(tags, 'image')

        # Check magic number
        assert csa_data[:4] == b'SV10', "CSA header should start with SV10 magic"

        # Check header can be parsed by nibabel
        try:
            parsed = read_csa_header(csa_data)
            assert 'tags' in parsed
            assert 'MultibandFactor' in parsed['tags']
            assert 'B_value' in parsed['tags']

            # Check values
            mb_items = parsed['tags']['MultibandFactor']['items']
            assert len(mb_items) == 1
            assert int(mb_items[0]) == 3

            b_items = parsed['tags']['B_value']['items']
            assert len(mb_items) == 1
            assert int(b_items[0]) == 1000
        except Exception as e:
            pytest.fail(f"nibabel failed to parse CSA header: {e}")

    def test_encode_csa_header_with_list_values(self):
        """Test encoding CSA header with list values."""
        tags = {
            'SliceTiming': [0.0, 0.5, 1.0, 1.5],
            'DiffusionGradientDirection': [0.707, 0.707, 0.0]
        }

        csa_data = encode_csa_header(tags, 'image')

        # Parse with nibabel
        parsed = read_csa_header(csa_data)

        # Check SliceTiming
        assert 'SliceTiming' in parsed['tags']
        slice_timing_items = parsed['tags']['SliceTiming']['items']
        assert len(slice_timing_items) == 4
        assert float(slice_timing_items[0]) == 0.0
        assert float(slice_timing_items[3]) == 1.5

        # Check DiffusionGradientDirection
        assert 'DiffusionGradientDirection' in parsed['tags']
        diff_grad_items = parsed['tags']['DiffusionGradientDirection']['items']
        assert len(diff_grad_items) == 3

    def test_encode_csa_header_with_string_values(self):
        """Test encoding CSA header with string values."""
        tags = {
            'DiffusionDirectionality': 'DIRECTIONAL',
            'GradientMode': 'FAST'
        }

        csa_data = encode_csa_header(tags, 'image')
        parsed = read_csa_header(csa_data)

        assert parsed['tags']['DiffusionDirectionality']['items'][0] == 'DIRECTIONAL'
        assert parsed['tags']['GradientMode']['items'][0] == 'FAST'

    def test_add_csa_tags_to_dicom(self):
        """Test adding CSA tags to a pydicom Dataset."""
        ds = pydicom.Dataset()
        csa_tags = {
            'MultibandFactor': 3,
            'B_value': 1000
        }

        add_csa_tags_to_dicom(ds, csa_tags, 'image')

        # Check that CSA header was added to correct tag
        assert (0x0029, 0x1010) in ds
        csa_data = ds[0x0029, 0x1010].value

        # Verify it's valid CSA data
        assert csa_data[:4] == b'SV10'

        # Parse and verify
        parsed = read_csa_header(csa_data)
        assert 'MultibandFactor' in parsed['tags']
        assert int(parsed['tags']['MultibandFactor']['items'][0]) == 3

    def test_add_csa_tags_series_header(self):
        """Test adding CSA tags to series header."""
        ds = pydicom.Dataset()
        csa_tags = {
            'ImagedNucleus': '1H'
        }

        add_csa_tags_to_dicom(ds, csa_tags, 'series')

        # Check that CSA header was added to series tag
        assert (0x0029, 0x1020) in ds
        csa_data = ds[0x0029, 0x1020].value

        # Verify it's valid CSA data
        assert csa_data[:4] == b'SV10'

    def test_extract_csa_fields_from_test_data(self):
        """Test extraction of CSA fields from test data."""
        field_defs = [
            {'name': 'RepetitionTime', 'tag': '0018,0080'},
            {'name': 'MultibandFactor', 'tag': ''},
            {'name': 'B_value', 'tag': ''},
            {'name': 'EchoTime', 'tag': '0018,0081'}
        ]

        row_data = {
            'RepetitionTime': 2000,
            'MultibandFactor': 3,
            'B_value': 1000,
            'EchoTime': 30
        }

        result = extract_csa_fields_from_test_data(field_defs, row_data)

        # Check standard fields
        assert 'RepetitionTime' in result['standard']
        assert 'EchoTime' in result['standard']
        assert result['standard']['RepetitionTime'] == 2000
        assert result['standard']['EchoTime'] == 30

        # Check CSA image fields
        assert 'MultibandFactor' in result['image_csa']
        assert 'B_value' in result['image_csa']
        assert result['image_csa']['MultibandFactor'] == 3
        assert result['image_csa']['B_value'] == 1000

        # Check series CSA is empty
        assert len(result['series_csa']) == 0

    def test_roundtrip_csa_header(self):
        """Test that we can write and read back CSA headers."""
        original_tags = {
            'MultibandFactor': 3,
            'B_value': 1000,
            'SliceTiming': [0.0, 0.5, 1.0, 1.5, 2.0],
            'DiffusionDirectionality': 'DIRECTIONAL'
        }

        # Encode
        csa_data = encode_csa_header(original_tags, 'image')

        # Decode
        parsed = read_csa_header(csa_data)

        # Verify all tags present
        for tag_name in original_tags.keys():
            assert tag_name in parsed['tags'], f"Tag {tag_name} not found in parsed CSA"

        # Verify values
        assert int(parsed['tags']['MultibandFactor']['items'][0]) == 3
        assert int(parsed['tags']['B_value']['items'][0]) == 1000
        assert len(parsed['tags']['SliceTiming']['items']) == 5
        assert parsed['tags']['DiffusionDirectionality']['items'][0] == 'DIRECTIONAL'
