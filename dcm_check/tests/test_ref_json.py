#!/usr/bin/env python

import pytest
import json
from io import BytesIO

from dcm_check import load_ref_json, load_dicom, get_compliance_summary, is_compliant, get_compliance_summaries_json
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
def dicom_test_bytes():
    """Fixture to create DICOM byte content for testing."""
    ds = create_empty_dicom()
    ds.EchoTime = 3.0
    ds.RepetitionTime = 8.0
    ds.SeriesDescription = "T1-weighted"
    ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "ND"]

    dicom_bytes = BytesIO()
    ds.save_as(dicom_bytes, enforce_file_format=True)
    dicom_bytes.seek(0)
    return dicom_bytes.getvalue()


@pytest.fixture
def dicom_test_bytes_group():
    """Fixture to create a simulated folder structure with multiple DICOM byte contents for testing."""
    dicom_groups = {}

    # Group 1: Two similar DICOMs with the same SeriesDescription and ProtocolName
    group1_dicom1 = create_empty_dicom()
    group1_dicom1.SeriesDescription = "T1-weighted"
    group1_dicom1.ProtocolName = "Head_MRI"
    group1_dicom1.EchoTime = 3.0
    group1_dicom1.RepetitionTime = 8.0
    dicom_bytes_1 = BytesIO()
    group1_dicom1.save_as(dicom_bytes_1, enforce_file_format=True)
    dicom_bytes_1.seek(0)

    group1_dicom2 = create_empty_dicom()
    group1_dicom2.SeriesDescription = "T1-weighted"
    group1_dicom2.ProtocolName = "Head_MRI"
    group1_dicom2.EchoTime = 3.0
    group1_dicom2.RepetitionTime = 8.0
    dicom_bytes_2 = BytesIO()
    group1_dicom2.save_as(dicom_bytes_2, enforce_file_format=True)
    dicom_bytes_2.seek(0)

    dicom_groups["Group1_DICOM1"] = dicom_bytes_1.getvalue()
    dicom_groups["Group1_DICOM2"] = dicom_bytes_2.getvalue()

    # Group 2: Two DICOMs with different SeriesDescription and ProtocolName
    group2_dicom1 = create_empty_dicom()
    group2_dicom1.SeriesDescription = "T2-weighted"
    group2_dicom1.ProtocolName = "Abdomen_MRI"
    group2_dicom1.EchoTime = 90.0
    group2_dicom1.RepetitionTime = 2000.0
    dicom_bytes_3 = BytesIO()
    group2_dicom1.save_as(dicom_bytes_3, enforce_file_format=True)
    dicom_bytes_3.seek(0)

    group2_dicom2 = create_empty_dicom()
    group2_dicom2.SeriesDescription = "T2-weighted"
    group2_dicom2.ProtocolName = "Abdomen_MRI"
    group2_dicom2.EchoTime = 90.0
    group2_dicom2.RepetitionTime = 2000.0
    dicom_bytes_4 = BytesIO()
    group2_dicom2.save_as(dicom_bytes_4, enforce_file_format=True)
    dicom_bytes_4.seek(0)

    dicom_groups["Group2_DICOM1"] = dicom_bytes_3.getvalue()
    dicom_groups["Group2_DICOM2"] = dicom_bytes_4.getvalue()

    return dicom_groups

@pytest.fixture
def json_ref_multiple_dicom(tmp_path_factory):
    """Fixture to create a JSON reference for multiple DICOM series for testing."""
    test_json = {
        "acquisitions": {
            "T1": {
                "fields": [
                    {"field": "EchoTime", "tolerance": 0.1, "value": 3.0},
                    {"field": "RepetitionTime", "value": 8.0},
                    {"field": "SeriesDescription", "value": "T1-weighted"},
                    {"field": "ProtocolName", "value": "Head_MRI"}
                ],
                "series": []
            },
            "T2": {
                "fields": [
                    {"field": "EchoTime", "tolerance": 10.0, "value": 90.0},
                    {"field": "RepetitionTime", "value": 2000.0},
                    {"field": "SeriesDescription", "value": "T2-weighted"},
                    {"field": "ProtocolName", "value": "Abdomen_MRI"}
                ],
                "series": []
            }
        }
    }

    json_path = tmp_path_factory.mktemp("data") / "json_ref_multiple_dicom.json"
    with open(json_path, 'w') as f:
        json.dump(test_json, f)

    return str(json_path)

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

def test_load_dicom_from_bytes(dicom_test_bytes):
    """Test loading a DICOM from byte content."""
    dicom_values = load_dicom(dicom_test_bytes)
    
    # Check that values match what was expected from the test data
    assert dicom_values["EchoTime"] == 3.0
    assert dicom_values["RepetitionTime"] == 8.0
    assert dicom_values["SeriesDescription"] == "T1-weighted"
    assert dicom_values["ImageType"] == ["ORIGINAL", "PRIMARY", "M", "ND"]

def test_json_compliance_within_tolerance_with_dicom_bytes(json_ref_with_dcm, dicom_test_bytes):
    """Test compliance when values are within tolerance for JSON configuration using DICOM bytes."""
    t1_dicom_values = load_dicom(dicom_test_bytes)
    reference_model = load_ref_json(json_path=json_ref_with_dcm, acquisition="T1", series_name="Series 1")

    # Adjust EchoTime within tolerance (original value is 3.0, tolerance 0.1)
    t1_dicom_values["EchoTime"] = 3.05
    compliance_summary = get_compliance_summary(reference_model, t1_dicom_values)

    assert is_compliant(reference_model, t1_dicom_values)
    assert len(compliance_summary) == 0

def test_json_compliance_outside_tolerance_with_dicom_bytes(json_ref_with_dcm, dicom_test_bytes):
    """Test compliance when values exceed tolerance for JSON configuration using DICOM bytes."""
    t1_dicom_values = load_dicom(dicom_test_bytes)
    reference_model = load_ref_json(json_path=json_ref_with_dcm, acquisition="T1", series_name="Series 1")

    # Adjust EchoTime beyond tolerance (original value is 3.0, tolerance 0.1)
    t1_dicom_values["EchoTime"] = 3.2
    compliance_summary = get_compliance_summary(reference_model, t1_dicom_values)
    assert len(compliance_summary) == 1
    assert compliance_summary[0]["Parameter"] == "EchoTime"
    assert compliance_summary[0]["Expected"] == "Input should be less than or equal to 3.1"
    assert compliance_summary[0]["Value"] == 3.2

def test_json_compliance_pattern_match_with_dicom_bytes(json_ref_no_dcm, dicom_test_bytes):
    """Test compliance with a pattern match for SeriesDescription within series using DICOM bytes."""
    t1_dicom_values = load_dicom(dicom_test_bytes)
    reference_model = load_ref_json(json_path=json_ref_no_dcm, acquisition="T1", series_name="Series 1")

    # Change SeriesDescription to match pattern "*T1*"
    t1_dicom_values["SeriesDescription"] = "Another_T1_Sequence"
    compliance_summary = get_compliance_summary(reference_model, t1_dicom_values)
    assert len(compliance_summary) == 0  # Should pass pattern match

def test_compliance_summaries_multiple_dicoms(json_ref_multiple_dicom, dicom_test_bytes_group):
    """Test get_compliance_summaries_json on a simulated folder with multiple DICOM byte contents."""
    # Generate compliance summaries using byte content for each DICOM file in the group
    compliance_df = get_compliance_summaries_json(json_ref_multiple_dicom, dicom_bytes=dicom_test_bytes_group)

    print(f"Compliance DataFrame:\n{compliance_df}")

    # Verify the compliance summary structure and results
    assert compliance_df.empty
    assert "Acquisition" in compliance_df.columns
    assert "Series" in compliance_df.columns
    assert "Parameter" in compliance_df.columns
    assert "Value" in compliance_df.columns
    assert "Expected" in compliance_df.columns

    # Verify compliance results for each group
    t1_rows = compliance_df[compliance_df["Acquisition"] == "T1"]
    assert len(t1_rows) == 0  # T1 series should be compliant as all fields match the reference exactly

    t2_rows = compliance_df[compliance_df["Acquisition"] == "T2"]
    assert len(t2_rows) == 0  # T2 series should also be compliant as fields are within tolerance or exact

def test_compliance_summaries_multiple_dicoms_noncompliant(tmp_path, json_ref_multiple_dicom, dicom_test_bytes_group):
    """Test get_compliance_summaries_json on a simulated folder with multiple DICOM byte contents."""

    # Change the EchoTime in the JSON reference to be outside the tolerance
    with open(json_ref_multiple_dicom, 'r') as f:
        json_data = json.load(f)
        json_data["acquisitions"]["T1"]["fields"][0]["value"] = 3.2
    
    # Save the updated JSON reference to tmp_path
    updated_json_ref = tmp_path / "updated_json_ref_multiple_dicom.json"
    with open(updated_json_ref, 'w') as f:
        json.dump(json_data, f)

    # Generate compliance summaries using byte content for each DICOM file in the group
    compliance_df = get_compliance_summaries_json(updated_json_ref, dicom_bytes=dicom_test_bytes_group)

    print(f"Compliance DataFrame:\n{compliance_df}")

    # Verify the compliance summary structure and results
    assert not compliance_df.empty
    assert "Acquisition" in compliance_df.columns
    assert "Series" in compliance_df.columns
    assert "Parameter" in compliance_df.columns
    assert "Value" in compliance_df.columns
    assert "Expected" in compliance_df.columns

    # Verify compliance results for each group
    t1_rows = compliance_df[compliance_df["Acquisition"] == "T1"]
    assert len(t1_rows) == 1  # T1 series should be non-compliant as EchoTime is outside the tolerance

    t2_rows = compliance_df[compliance_df["Acquisition"] == "T2"]
    assert len(t2_rows) == 0  # T2 series should be compliant as fields are within tolerance or exact

if __name__ == "__main__":
    pytest.main(["-v", __file__])
