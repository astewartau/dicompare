"""
Tests for DICOM test file generation from schema.
"""

import io
import zipfile
import pytest
import pydicom
from dicompare.io import generate_test_dicoms_from_schema


def test_generate_single_dicom():
    """Test generating a single DICOM file."""
    test_data = [
        {'RepetitionTime': 2000, 'EchoTime': 2.46, 'FlipAngle': 9.0}
    ]

    field_definitions = [
        {'name': 'RepetitionTime', 'tag': '0018,0080', 'vr': 'DS'},
        {'name': 'EchoTime', 'tag': '0018,0081', 'vr': 'DS'},
        {'name': 'FlipAngle', 'tag': '0018,1314', 'vr': 'DS'}
    ]

    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)

    # Verify we got bytes back
    assert isinstance(zip_bytes, bytes)
    assert len(zip_bytes) > 0

    # Verify it's a valid ZIP
    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        files = zf.namelist()
        assert len(files) == 1
        assert files[0] == 'test_dicom_000.dcm'

        # Extract and verify DICOM
        dicom_bytes = zf.read(files[0])
        ds = pydicom.dcmread(io.BytesIO(dicom_bytes))

        # Check schema fields were set
        assert ds.RepetitionTime == '2000.0'  # DS stores as string
        assert ds.EchoTime == '2.46'
        assert ds.FlipAngle == '9.0'


def test_generate_multiple_dicoms():
    """Test generating multiple DICOM files."""
    test_data = [
        {'RepetitionTime': 2000, 'EchoTime': 2.46},
        {'RepetitionTime': 2000, 'EchoTime': 3.5},
        {'RepetitionTime': 2000, 'EchoTime': 4.8}
    ]

    field_definitions = [
        {'name': 'RepetitionTime', 'tag': '0018,0080', 'vr': 'DS'},
        {'name': 'EchoTime', 'tag': '0018,0081', 'vr': 'DS'}
    ]

    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)

    # Verify ZIP contains 3 files
    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        files = zf.namelist()
        assert len(files) == 3

        # Check each DICOM has correct values
        echo_times = []
        for i, filename in enumerate(sorted(files)):
            dicom_bytes = zf.read(filename)
            ds = pydicom.dcmread(io.BytesIO(dicom_bytes))
            echo_times.append(float(ds.EchoTime))
            assert ds.RepetitionTime == '2000.0'

        assert echo_times == [2.46, 3.5, 4.8]


def test_vr_type_conversions():
    """Test that different VR types are handled correctly."""
    test_data = [
        {
            'RepetitionTime': 2000.0,      # DS - Decimal String
            'InstanceNumber': 5,            # IS - Integer String
            'PixelSpacing': [1.5, 1.5],    # DS - list
            'ImageType': ['ORIGINAL', 'PRIMARY', 'M', 'ND']  # CS - Code String list
        }
    ]

    field_definitions = [
        {'name': 'RepetitionTime', 'tag': '0018,0080', 'vr': 'DS'},
        {'name': 'InstanceNumber', 'tag': '0020,0013', 'vr': 'IS'},
        {'name': 'PixelSpacing', 'tag': '0028,0030', 'vr': 'DS'},
        {'name': 'ImageType', 'tag': '0008,0008', 'vr': 'CS'}
    ]

    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)

    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        dicom_bytes = zf.read(zf.namelist()[0])
        ds = pydicom.dcmread(io.BytesIO(dicom_bytes))

        # DS should be string or pydicom's DSfloat (which is a str subclass)
        assert str(ds.RepetitionTime) == '2000.0'

        # IS should be string or pydicom's IS (which is a str subclass)
        assert str(ds.InstanceNumber) == '5'

        # DS list should be list-like (pydicom wraps in MultiValue)
        assert len(ds.PixelSpacing) == 2
        assert [str(v) for v in ds.PixelSpacing] == ['1.5', '1.5']

        # CS list should be list-like
        assert len(ds.ImageType) == 4
        assert list(ds.ImageType) == ['ORIGINAL', 'PRIMARY', 'M', 'ND']


def test_with_acquisition_info():
    """Test that acquisition info is included in DICOMs."""
    test_data = [{'RepetitionTime': 2000}]
    field_definitions = [{'name': 'RepetitionTime', 'tag': '0018,0080', 'vr': 'DS'}]

    acquisition_info = {
        'protocolName': 'T1_MPRAGE',
        'seriesDescription': 'T1 Weighted Anatomical'
    }

    zip_bytes = generate_test_dicoms_from_schema(
        test_data,
        field_definitions,
        acquisition_info
    )

    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        dicom_bytes = zf.read(zf.namelist()[0])
        ds = pydicom.dcmread(io.BytesIO(dicom_bytes))

        assert ds.SeriesDescription == 'T1 Weighted Anatomical'


def test_empty_test_data():
    """Test handling of empty test data."""
    test_data = []
    field_definitions = [{'name': 'RepetitionTime', 'tag': '0018,0080', 'vr': 'DS'}]

    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)

    # Should return valid but empty ZIP
    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        assert len(zf.namelist()) == 0


def test_minimal_pixel_data():
    """Test that generated DICOMs have valid pixel data."""
    test_data = [{'RepetitionTime': 2000}]
    field_definitions = [{'name': 'RepetitionTime', 'tag': '0018,0080', 'vr': 'DS'}]

    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)

    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        dicom_bytes = zf.read(zf.namelist()[0])
        ds = pydicom.dcmread(io.BytesIO(dicom_bytes))

        # Check pixel data attributes
        assert ds.Rows == 64
        assert ds.Columns == 64
        assert ds.BitsAllocated == 16
        assert hasattr(ds, 'PixelData')
        assert len(ds.PixelData) == 64 * 64 * 2  # 64x64 uint16


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
