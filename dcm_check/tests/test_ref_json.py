#!/usr/bin/env python

import pytest
import json

from dcm_check import load_ref_json, load_dicom, get_compliance_summary, is_compliant
from dcm_check.tests.utils import create_empty_dicom
from pydantic_core import PydanticUndefined
from typing import Literal

@pytest.fixture
def dicom_test_file(tmp_path):
    """Fixture to create a DICOM file used as test input."""
    dicom_path = tmp_path / "ref_dicom.dcm"
    ds = create_empty_dicom()

    ds.EchoTime = 3.0
    ds.RepetitionTime = 8.0
    ds.SeriesDescription = "T1-weighted"
    ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "ND"]

    ds.save_as(dicom_path, enforce_file_format=True)
    return str(dicom_path)

@pytest.fixture
def json_ref_no_dcm(tmp_path_factory):
    """Fixture to create a JSON reference file for testing."""
    test_json = {
        "acquisitions": {
            "T1": {
                "fields": [
                    {"field": "EchoTime", "tolerance": 0.1, "value": 3.0},
                    {"field": "RepetitionTime", "value": 8.0},
                    {"field": "SeriesDescription", "value": "*T1*"}
                ],
                "series": [
                    {
                        "name": "Series 1",
                        "fields": [
                            {"field": "ImageType", "contains": "M"}
                        ]
                    }
                ]
            }
        }
    }
    
    json_path = tmp_path_factory.mktemp("data") / "json_ref_no_dcm.json"
    with open(json_path, 'w') as f:
        json.dump(test_json, f)
    
    return str(json_path)

@pytest.fixture
def json_ref_with_dcm(tmp_path_factory, dicom_test_file):
    """Fixture to create a JSON reference file for testing."""
    test_json = {
        "acquisitions": {
            "T1": {
                "ref": dicom_test_file,
                "fields": [
                    {"field": "EchoTime", "tolerance": 0.1},
                    {"field": "RepetitionTime"},
                    {"field": "SeriesDescription"}
                ],
                "series": [
                    {
                        "name": "Series 1",
                        "fields": [
                            {"field": "ImageType", "contains": "M"}
                        ]
                    }
                ]
            }
        }
    }
    
    json_path = tmp_path_factory.mktemp("data") / "json_ref_with_dcm.json"
    with open(json_path, 'w') as f:
        json.dump(test_json, f)
    
    return str(json_path)

def test_load_ref_json(json_ref_no_dcm):
    """Test that JSON configuration can be loaded and generates a reference model."""
    reference_model = load_ref_json(json_path=json_ref_no_dcm, acquisition="T1", series_name="Series 1")

    # Verify that the model was created correctly with exact and pattern matching fields
    assert reference_model is not None
    assert "EchoTime" in reference_model.model_fields
    assert "RepetitionTime" in reference_model.model_fields
    assert "SeriesDescription" in reference_model.model_fields
    assert "ImageType" in reference_model.model_fields

    # Check EchoTime with tolerance
    assert reference_model.model_fields["EchoTime"].default == 3.0
    assert reference_model.model_fields["EchoTime"].metadata[1].ge == 2.9
    assert reference_model.model_fields["EchoTime"].metadata[1].le == 3.1

    # Check that RepetitionTime is required, with an exact match of 8.0
    assert reference_model.model_fields["RepetitionTime"].default is PydanticUndefined
    assert reference_model.model_fields["RepetitionTime"].annotation == Literal[8.0]

    # Check that pattern is correctly set on SeriesDescription using metadata
    assert reference_model.model_fields["SeriesDescription"].metadata[0].pattern == ".*T1.*"

def test_json_compliance_within_tolerance_with_dcm(json_ref_with_dcm, dicom_test_file):
    """Test compliance when values are within tolerance for JSON configuration with series."""
    t1_dicom_values = load_dicom(dicom_test_file)
    reference_model = load_ref_json(json_path=json_ref_with_dcm, acquisition="T1", series_name="Series 1")

    # Adjust EchoTime within tolerance (original value is 3.0, tolerance 0.1)
    t1_dicom_values["EchoTime"] = 3.05
    compliance_summary = get_compliance_summary(reference_model, t1_dicom_values)

    assert is_compliant(reference_model, t1_dicom_values)
    assert len(compliance_summary) == 0

def test_json_compliance_outside_tolerance_with_dcm(json_ref_with_dcm, dicom_test_file):
    """Test compliance when values exceed tolerance for JSON configuration with series."""
    t1_dicom_values = load_dicom(dicom_test_file)
    reference_model = load_ref_json(json_path=json_ref_with_dcm, acquisition="T1", series_name="Series 1")

    # Adjust EchoTime beyond tolerance (original value is 3.0, tolerance 0.1)
    t1_dicom_values["EchoTime"] = 3.2
    compliance_summary = get_compliance_summary(reference_model, t1_dicom_values)
    assert len(compliance_summary) == 1
    assert compliance_summary[0]["Parameter"] == "EchoTime"
    assert compliance_summary[0]["Expected"] == "Input should be less than or equal to 3.1"
    assert compliance_summary[0]["Value"] == 3.2

def test_json_compliance_pattern_match(json_ref_no_dcm, dicom_test_file):
    """Test compliance with a pattern match for SeriesDescription within series."""
    t1_dicom_values = load_dicom(dicom_test_file)
    reference_model = load_ref_json(json_path=json_ref_no_dcm, acquisition="T1", series_name="Series 1")

    # Change SeriesDescription to match pattern "*T1*"
    t1_dicom_values["SeriesDescription"] = "Another_T1_Sequence"
    compliance_summary = get_compliance_summary(reference_model, t1_dicom_values)
    assert len(compliance_summary) == 0  # Should pass pattern match

if __name__ == "__main__":
    pytest.main(["-v", __file__])
