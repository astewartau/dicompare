"""
Tests for DICOM generation from schema JSON.
"""

import io
import json
import zipfile
import pytest
import pydicom
from dicompare.io import generate_test_dicoms_from_schema_json


def test_generate_from_acquisition_fields_only():
    """Test generating DICOMs from acquisition-level fields only."""
    schema = {
        "acquisitions": {
            "T1_MPRAGE": {
                "fields": [
                    {"field": "RepetitionTime", "tag": "0018,0080", "value": 2000},
                    {"field": "EchoTime", "tag": "0018,0081", "value": 2.46},
                    {"field": "FlipAngle", "tag": "0018,1314", "value": 9.0}
                ],
                "series": [],
                "rules": []
            }
        }
    }

    zip_bytes = generate_test_dicoms_from_schema_json(schema, "T1_MPRAGE")

    # Verify we got a valid ZIP with one DICOM
    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        files = zf.namelist()
        assert len(files) == 1

        # Extract and verify DICOM
        dicom_bytes = zf.read(files[0])
        ds = pydicom.dcmread(io.BytesIO(dicom_bytes))

        # Check field values
        assert str(ds.RepetitionTime) == '2000.0'
        assert str(ds.EchoTime) == '2.46'
        assert str(ds.FlipAngle) == '9.0'


def test_generate_from_series():
    """Test generating DICOMs from series definitions."""
    schema = {
        "acquisitions": {
            "Multi-echo": {
                "fields": [
                    {"field": "MagneticFieldStrength", "tag": "0018,0087", "value": 7.0}
                ],
                "series": [
                    {
                        "name": "Echo_1",
                        "fields": [
                            {"field": "EchoTime", "tag": "0018,0081", "value": 10.0},
                            {"field": "EchoNumber", "tag": "0018,0086", "value": 1}
                        ]
                    },
                    {
                        "name": "Echo_2",
                        "fields": [
                            {"field": "EchoTime", "tag": "0018,0081", "value": 20.0},
                            {"field": "EchoNumber", "tag": "0018,0086", "value": 2}
                        ]
                    }
                ],
                "rules": []
            }
        }
    }

    zip_bytes = generate_test_dicoms_from_schema_json(schema, "Multi-echo")

    # Should generate 2 DICOMs (one per series)
    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        files = sorted(zf.namelist())
        assert len(files) == 2

        # Check first DICOM
        ds1 = pydicom.dcmread(io.BytesIO(zf.read(files[0])))
        assert str(ds1.MagneticFieldStrength) == '7.0'  # From acquisition
        assert str(ds1.EchoTime) == '10.0'  # From series 1
        # Note: EchoNumber keyword maps to EchoNumbers in pydicom
        assert str(ds1.EchoNumbers) == '1'

        # Check second DICOM
        ds2 = pydicom.dcmread(io.BytesIO(zf.read(files[1])))
        assert str(ds2.MagneticFieldStrength) == '7.0'  # From acquisition
        assert str(ds2.EchoTime) == '20.0'  # From series 2
        assert str(ds2.EchoNumbers) == '2'


def test_generate_with_validation_tests():
    """Test generating DICOMs with validation test cases (no conflicts)."""
    schema = {
        "acquisitions": {
            "QSM": {
                "fields": [
                    {"field": "MagneticFieldStrength", "tag": "0018,0087", "value": 3.0}
                ],
                "series": [],
                "rules": [
                    {
                        "name": "Bandwidth Check",
                        "fields": ["PixelBandwidth"],
                        "testCases": [
                            {
                                "expectedResult": "pass",
                                "data": {
                                    "PixelBandwidth": 200
                                }
                            }
                        ]
                    }
                ]
            }
        }
    }

    zip_bytes = generate_test_dicoms_from_schema_json(schema, "QSM")

    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        ds = pydicom.dcmread(io.BytesIO(zf.read(zf.namelist()[0])))

        # Should have both acquisition and validation fields
        assert str(ds.MagneticFieldStrength) == '3.0'
        # PixelBandwidth should be added from validation test


def test_conflict_acquisition_vs_validation(capfd):
    """Test that acquisition field values take precedence over validation tests."""
    schema = {
        "acquisitions": {
            "Test": {
                "fields": [
                    {"field": "EchoTime", "tag": "0018,0081", "value": 10.0}
                ],
                "series": [],
                "rules": [
                    {
                        "name": "Echo Check",
                        "fields": ["EchoTime"],
                        "testCases": [
                            {
                                "expectedResult": "pass",
                                "data": {
                                    "EchoTime": 9.76  # Different from acquisition value
                                }
                            }
                        ]
                    }
                ]
            }
        }
    }

    with pytest.warns(UserWarning, match="has schema value.*but validation test expects"):
        zip_bytes = generate_test_dicoms_from_schema_json(schema, "Test")

    # Verify acquisition value was used
    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        ds = pydicom.dcmread(io.BytesIO(zf.read(zf.namelist()[0])))
        assert str(ds.EchoTime) == '10.0'  # Acquisition value, not 9.76


def test_conflict_series_vs_validation(capfd):
    """Test that series field values take precedence over validation tests."""
    schema = {
        "acquisitions": {
            "Test": {
                "fields": [],
                "series": [
                    {
                        "name": "Series1",
                        "fields": [
                            {"field": "EchoTime", "tag": "0018,0081", "value": 15.0}
                        ]
                    }
                ],
                "rules": [
                    {
                        "name": "Echo Check",
                        "fields": ["EchoTime"],
                        "testCases": [
                            {
                                "expectedResult": "pass",
                                "data": {
                                    "EchoTime": 20.0  # Different from series value
                                }
                            }
                        ]
                    }
                ]
            }
        }
    }

    with pytest.warns(UserWarning, match="has series values.*but validation test expects"):
        zip_bytes = generate_test_dicoms_from_schema_json(schema, "Test")

    # Verify series value was used
    zip_buffer = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        ds = pydicom.dcmread(io.BytesIO(zf.read(zf.namelist()[0])))
        assert str(ds.EchoTime) == '15.0'  # Series value, not 20.0


def test_warn_on_missing_test_cases():
    """Test warning when validation rules have no test cases."""
    schema = {
        "acquisitions": {
            "Test": {
                "fields": [
                    {"field": "RepetitionTime", "tag": "0018,0080", "value": 2000}
                ],
                "series": [],
                "rules": [
                    {
                        "name": "Some Rule",
                        "fields": ["EchoTime"],
                        "testCases": []  # No test cases
                    }
                ]
            }
        }
    }

    with pytest.warns(UserWarning, match="has no test cases"):
        zip_bytes = generate_test_dicoms_from_schema_json(schema, "Test")

    # Should still generate DICOM from acquisition fields
    assert isinstance(zip_bytes, bytes)


def test_return_datasets_not_zip():
    """Test returning Dataset objects instead of ZIP."""
    schema = {
        "acquisitions": {
            "T1": {
                "fields": [
                    {"field": "RepetitionTime", "tag": "0018,0080", "value": 2000}
                ],
                "series": [],
                "rules": []
            }
        }
    }

    datasets = generate_test_dicoms_from_schema_json(schema, "T1", as_zip=False)

    assert isinstance(datasets, list)
    assert len(datasets) == 1
    assert isinstance(datasets[0], pydicom.Dataset)
    assert str(datasets[0].RepetitionTime) == '2000.0'


def test_missing_acquisition_name():
    """Test error when acquisition name not found."""
    schema = {
        "acquisitions": {
            "T1": {"fields": [], "series": [], "rules": []}
        }
    }

    with pytest.raises(KeyError, match="Acquisition 'T2' not found"):
        generate_test_dicoms_from_schema_json(schema, "T2")


def test_no_valid_data():
    """Test error when schema has no usable data."""
    schema = {
        "acquisitions": {
            "Empty": {
                "fields": [],  # No fields
                "series": [],  # No series
                "rules": []    # No rules
            }
        }
    }

    with pytest.raises(ValueError, match="No test data generated"):
        generate_test_dicoms_from_schema_json(schema, "Empty")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
