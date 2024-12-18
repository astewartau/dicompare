import pytest
import json
from io import BytesIO
from pydicom.dataset import Dataset
from .fixtures.fixtures import t1

from dicompare import (
    load_dicom,
    get_dicom_values,
    load_dicom_session,
    load_json_session,
)

from dicompare.cli.gen_session import create_json_reference

@pytest.fixture
def temp_json(tmp_path):
    def _write_json(data):
        path = tmp_path / "temp.json"
        with open(path, "w") as f:
            json.dump(data, f)
        return str(path)
    return _write_json

# Test for `get_dicom_values`
def test_get_dicom_values(t1: Dataset):
    dicom_dict = get_dicom_values(t1)
    assert isinstance(dicom_dict, dict)
    assert dicom_dict["PatientName"] == "Test^Patient"
    assert dicom_dict["PixelSpacing"] == [0.5, 0.5]

# Test for `load_dicom`
def test_load_dicom_from_path(t1: Dataset, tmp_path):
    dicom_path = tmp_path / "test.dcm"
    t1.save_as(dicom_path, enforce_file_format=True)
    dicom_values = load_dicom(str(dicom_path))
    assert dicom_values["PatientID"] == "123456"

def test_load_dicom_from_bytes(t1: Dataset):
    buffer = BytesIO()
    t1.save_as(buffer, enforce_file_format=True)
    dicom_bytes = buffer.getvalue()
    dicom_values = load_dicom(dicom_bytes)
    assert dicom_values["PatientName"] == "Test^Patient"

def test_load_dicom_from_bytes(t1: Dataset):
    buffer = BytesIO()
    t1.save_as(buffer, enforce_file_format=True)
    dicom_bytes = buffer.getvalue()
    dicom_values = load_dicom(dicom_bytes)
    assert dicom_values["PixelSpacing"] == [0.5, 0.5]

# Test for `read_dicom_session` with session_dir
def test_read_dicom_session_directory(t1: Dataset, tmp_path):
    dicom_dir = tmp_path / "dicom_dir"
    dicom_dir.mkdir()
    dicom_path = dicom_dir / "test.dcm"
    t1.save_as(dicom_path, enforce_file_format=True)
    result = load_dicom_session(
        session_dir=str(dicom_dir)
    )
    assert "acq-t1" in result["Acquisition"].values
    assert len(result['Acquisition']) == 1

def test_read_dicom_session_bytes(t1: Dataset):
    # Save DICOM to bytes
    buffer = BytesIO()
    t1.save_as(buffer, enforce_file_format=True)
    dicom_content = buffer.getvalue()

    # Simulate the `dicom_bytes` dictionary
    dicom_bytes = {"test.dcm": dicom_content}

    # Call `read_dicom_session` with the simulated byte data
    result = load_dicom_session(
        dicom_bytes=dicom_bytes
    )

    # Validate the results
    assert "acq-t1" in result["Acquisition"].values
    assert "Test^Patient" in result["PatientName"].values
    assert "T1-weighted" in result["SeriesDescription"].values
    assert len(result['Acquisition']) == 1

def test_read_dicom_session_bytes_partial(t1: Dataset):
    # Save full DICOM to bytes
    buffer = BytesIO()
    t1.save_as(buffer, enforce_file_format=True)
    dicom_content_full = buffer.getvalue()

    # Simulate partial DICOM bytes (first 2048 bytes)
    partial_content = dicom_content_full[:2048]

    # Simulate the `dicom_bytes` dictionary
    dicom_bytes = {"partial_test.dcm": partial_content}

    # Call `read_dicom_session` with the partial byte data
    result = load_dicom_session(
        dicom_bytes=dicom_bytes
    )

    # Validate the results
    assert "acq-t1" in result["Acquisition"].values
    assert "Test^Patient" in result["PatientName"].values
    assert "T1-weighted" in result["SeriesDescription"].values
    assert len(result['Acquisition']) == 1

def test_read_json_session(temp_json):
    json_data = {
        "acquisitions": {
            "acq-Example": {
                "series": [
                    {
                        "name": "Series 1",
                        "fields": [{"field": "SeriesDescription", "value": "Example Series"},
                                   {"field": "EchoTime", "value": 25.0, "tolerance": 0.1},
                                   {"field": "ImageType", "contains": "M"}]
                    }
                ],
            }
        }
    }
    json_path = temp_json(json_data)
    reference_fields, acquisitions = load_json_session(json_path)

    # Validate reference fields
    assert set(reference_fields) == {"SeriesDescription", "EchoTime", "ImageType"}

    # Validate acquisitions structure
    assert "acq-Example" in acquisitions["acquisitions"]

# Edge case: Test invalid JSON file for `read_json_session`
def test_read_json_session_invalid_file():
    with pytest.raises(FileNotFoundError):
        load_json_session("non_existent.json")

# Edge case: Test DICOM file with no Pixel Data for `get_dicom_values`
def test_get_dicom_values_no_pixel_data(t1: Dataset):
    t1.PixelData = None  # Remove PixelData
    dicom_dict = get_dicom_values(t1)
    assert "PixelData" not in dicom_dict

def test_read_dicom_session_read_json_session_numeric_datatype_encoding(tmp_path, t1: Dataset):
    # Create two DICOM files with different EchoTime values
    dicom_dir = tmp_path / "dicom_dir"
    dicom_dir.mkdir()

    # First file: EchoTime as a float
    t1.EchoTime = 25.0
    dicom_path_float = dicom_dir / "float_echotime.dcm"
    t1.save_as(dicom_path_float, enforce_file_format=True)

    # Second file: EchoTime as an int
    t1.EchoTime = 26  # Set as int
    dicom_path_int = dicom_dir / "int_echotime.dcm"
    t1.save_as(dicom_path_int, enforce_file_format=True)

    # Read the DICOM session
    result = load_dicom_session(
        session_dir=str(dicom_dir)
    )

    result_json = create_json_reference(result, ["EchoTime", "SeriesDescription"])

    # Save the dataframe as a JSON file
    json_path = tmp_path / "session_output.json"
    with open(json_path, "w") as json_file:
        json.dump(result_json, json_file, indent=4)

    # Use `read_json_session` to load the JSON
    reference_fields, loaded_result = load_json_session(str(json_path))

    # Validate that the reference fields are loaded correctly
    assert set(reference_fields) == {"EchoTime", "SeriesDescription"}

    # Validate the EchoTime values and their types in the JSON
    acquisitions = loaded_result["acquisitions"]
    assert len(acquisitions) == 1  # Ensure one acquisition
    acquisition = list(acquisitions.values())[0]
    series = acquisition["series"]
    assert len(series) == 2  # Ensure two series

    # Validate each series' EchoTime
    for series_entry in series:
        fields = {field["field"]: field["value"] for field in series_entry["fields"]}
        if fields["EchoTime"] == 25.0:
            assert isinstance(fields["EchoTime"], float)
        elif fields["EchoTime"] == 26.0:
            assert isinstance(fields["EchoTime"], float)
        else:
            pytest.fail("Unexpected EchoTime value found in the output.")


# Test for empty DICOM directory
def test_read_dicom_session_empty_directory(tmp_path):
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="No DICOM data found to process."):
        load_dicom_session(
            session_dir=str(empty_dir),
        )
