import pytest
import json
from io import BytesIO
from pydicom.dataset import Dataset
from annotated_types import Interval
from .fixtures.fixtures import t1

from dcm_check import (
    load_dicom,
    get_dicom_values,
    read_dicom_session,
    read_json_session
)

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

# Test for `read_dicom_session` with session_dir
def test_read_dicom_session_directory(t1: Dataset, tmp_path):
    dicom_dir = tmp_path / "dicom_dir"
    dicom_dir.mkdir()
    dicom_path = dicom_dir / "test.dcm"
    t1.save_as(dicom_path, enforce_file_format=True)
    result = read_dicom_session(
        reference_fields=["PatientName", "SeriesDescription"],
        session_dir=str(dicom_dir),
    )
    assert "acq-t1" in result["acquisitions"]
    assert len(result["acquisitions"]["acq-t1"]["series"]) > 0

def test_read_dicom_session_bytes(t1: Dataset):
    # Save DICOM to bytes
    buffer = BytesIO()
    t1.save_as(buffer, enforce_file_format=True)
    dicom_content = buffer.getvalue()

    # Simulate the `dicom_bytes` dictionary
    dicom_bytes = {"test.dcm": dicom_content}

    # Call `read_dicom_session` with the simulated byte data
    result = read_dicom_session(
        reference_fields=["PatientName", "SeriesDescription"],
        dicom_bytes=dicom_bytes,
        acquisition_fields=["ProtocolName"]
    )

    # Validate the results
    assert "acq-t1" in result["acquisitions"]
    acquisition = result["acquisitions"]["acq-t1"]

    # Check acquisition-level fields
    acquisition_fields = {field["field"]: field["value"] for field in acquisition["fields"]}
    assert acquisition_fields["ProtocolName"] == "T1"

    # Check series-level fields
    assert len(acquisition["series"]) == 1
    series = acquisition["series"][0]
    series_fields = {field["field"]: field["value"] for field in series["fields"]}
    assert series_fields["PatientName"] == "Test^Patient"
    assert series_fields["SeriesDescription"] == "T1-weighted"

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
    result = read_dicom_session(
        reference_fields=["PatientName", "SeriesDescription"],
        dicom_bytes=dicom_bytes,
        acquisition_fields=["ProtocolName"]
    )

    # Validate the results
    assert "acq-t1" in result["acquisitions"]
    acquisition = result["acquisitions"]["acq-t1"]

    # Check acquisition-level fields
    acquisition_fields = {field["field"]: field["value"] for field in acquisition["fields"]}
    assert acquisition_fields["ProtocolName"] == "T1"

    # Check series-level fields
    assert len(acquisition["series"]) == 1
    series = acquisition["series"][0]
    series_fields = {field["field"]: field["value"] for field in series["fields"]}
    assert series_fields["PatientName"] == "Test^Patient"
    assert series_fields["SeriesDescription"] == "T1-weighted"


# Test for `read_dicom_session` with missing data
def test_read_dicom_session_no_input():
    with pytest.raises(ValueError, match="Either session_dir or dicom_bytes must be provided."):
        read_dicom_session(reference_fields=["PatientName"])

def test_read_json_session(temp_json):
    json_data = {
        "acquisitions": {
            "acq-Example": {
                "fields": [{"field": "ProtocolName", "value": "Example"}],
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
    acq_fields, series_fields, acquisitions, ref_models = read_json_session(json_path)

    # Validate acquisition fields
    assert acq_fields == ["ProtocolName"]

    # Validate series fields
    assert set(series_fields) == {"SeriesDescription", "EchoTime", "ImageType"}

    # Validate acquisitions structure
    assert "acq-Example" in acquisitions["acquisitions"]

    # Validate the model is properly generated for Series 1
    model = ref_models.get(("acq-Example", "Series 1"))
    assert model is not None

    # Validate the model fields
    model_fields = model.model_fields
    assert "SeriesDescription" in model_fields
    assert "EchoTime" in model_fields
    assert "ImageType" in model_fields

    # Validate the constraints for EchoTime
    echo_time_field = model_fields["EchoTime"]
    assert echo_time_field.default == 25.0

    # Extract and validate constraints from metadata
    metadata_constraints = next(
        (item for item in echo_time_field.metadata if isinstance(item, Interval)),
        None
    )
    assert metadata_constraints is not None
    assert metadata_constraints.ge == 24.9  # Lower bound
    assert metadata_constraints.le == 25.1  # Upper bound

# Edge case: Test invalid JSON file for `read_json_session`
def test_read_json_session_invalid_file():
    with pytest.raises(FileNotFoundError):
        read_json_session("non_existent.json")

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
    result = read_dicom_session(
        reference_fields=["EchoTime"],
        session_dir=str(dicom_dir),
        acquisition_fields=["ProtocolName"]
    )

    # Save the result as a JSON file
    json_path = tmp_path / "session_output.json"
    with open(json_path, "w") as json_file:
        json.dump(result, json_file, indent=4)

    # Use `read_json_session` to load the JSON
    acq_fields, series_fields, loaded_result, ref_models = read_json_session(str(json_path))

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

    # Validate models are built correctly
    print(ref_models)
    for series_entry in series:
        series_name = series_entry["name"]
        model = ref_models.get(("acq-t1", series_name))
        assert model is not None
        assert "EchoTime" in model.model_fields


# Test for empty DICOM directory
def test_read_dicom_session_empty_directory(tmp_path):
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="No DICOM data found to process."):
        read_dicom_session(
            reference_fields=["PatientName"],
            session_dir=str(empty_dir),
        )
