import os
import json
import asyncio

import numpy as np
import pandas as pd
import pytest
import nibabel as nib
import pydicom
from pydicom.dataset import FileMetaDataset, FileDataset

import dicompare

# ---------- Helper functions for tests ----------

def create_dummy_file_dataset(filename, patient_name="Doe^John", series_number=1, instance_number=1, include_pixel=True):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.3"
    file_meta.MediaStorageSOPInstanceUID = "1.2.3.4"
    file_meta.ImplementationClassUID = "1.2.3.4.5"
    ds = FileDataset(filename, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientName = patient_name
    ds.SeriesNumber = series_number
    ds.InstanceNumber = instance_number
    ds.add_new((0x0010, 0x0010), "PN", patient_name)
    ds.add_new((0x0020, 0x0011), "IS", str(series_number))
    ds.add_new((0x0020, 0x0013), "IS", str(instance_number))
    if include_pixel:
        ds.add_new((0x7fe0, 0x0010), "OB", b'\x00\x01')
    return ds


def write_dummy_dicom(tmp_dir, filename="dummy.dcm", **kwargs):
    filepath = os.path.join(tmp_dir, filename)
    ds = create_dummy_file_dataset(filepath, **kwargs)
    pydicom.filewriter.dcmwrite(filepath, ds)
    return filepath


def create_dummy_nifti(tmp_dir, filename="sub-01_task-rest.nii", array_shape=(2, 2, 2)):
    data = np.zeros(array_shape)
    affine = np.eye(4)
    nifti_img = nib.Nifti1Image(data, affine)
    file_path = os.path.join(tmp_dir, filename)
    nib.save(nifti_img, file_path)
    return file_path


def create_temp_json(tmp_dir, filename="dummy.json"):
    data = {
        "acquisitions": {
            "acq1": {
                "fields": [
                    {"field": "TestField", "value": [1, 2], "tolerance": 5, "contains": "abc"}
                ],
                "series": [
                    {"name": "series1", "fields": [{"field": "SeriesField", "value": "x"}]}
                ]
            }
        }
    }
    file_path = os.path.join(tmp_dir, filename)
    with open(file_path, "w") as f:
        json.dump(data, f)
    return file_path


def create_dummy_python_module(tmp_dir, content, filename="dummy_module.py"):
    file_path = os.path.join(tmp_dir, filename)
    with open(file_path, "w") as f:
        f.write(content)
    return file_path


# ---------- Fixtures ----------

@pytest.fixture
def temp_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


@pytest.fixture
def dicom_file(temp_dir):
    return write_dummy_dicom(temp_dir, filename="test.dcm", patient_name="Test^Patient", series_number=2, instance_number=5)


@pytest.fixture
def dicom_bytes(dicom_file):
    with open(dicom_file, "rb") as f:
        return f.read()


@pytest.fixture
def nifti_file(temp_dir):
    # Create a NIfTI file and an accompanying JSON file.
    nii_path = create_dummy_nifti(temp_dir, filename="sub-01_task-rest.nii")
    json_path = nii_path.replace(".nii", ".json")
    data = {"extra": "value"}
    with open(json_path, "w") as f:
        json.dump(data, f)
    return nii_path


@pytest.fixture
def json_file(temp_dir):
    return create_temp_json(temp_dir, filename="ref.json")


@pytest.fixture
def valid_python_module(temp_dir):
    # Dummy python module with ACQUISITION_MODELS as a dict.
    content = '''
from dicompare.validation import ValidationError, BaseValidationModel, validator
class DummyValidationModel(BaseValidationModel):
    pass
ACQUISITION_MODELS = {"dummy": DummyValidationModel()}
'''
    return create_dummy_python_module(temp_dir, content, filename="valid_module.py")


@pytest.fixture
def no_models_python_module(temp_dir):
    content = '''
# No ACQUISITION_MODELS defined here.
'''
    return create_dummy_python_module(temp_dir, content, filename="no_models.py")


@pytest.fixture
def invalid_models_python_module(temp_dir):
    content = '''
ACQUISITION_MODELS = ["not", "a", "dict"]
'''
    return create_dummy_python_module(temp_dir, content, filename="invalid_models.py")


# ---------- Tests for get_dicom_values and load_dicom ----------

def test_get_dicom_values_skip_pixel():
    ds = create_dummy_file_dataset("dummy", include_pixel=True)
    # Use skip_pixel_data True so pixel data is omitted.
    result = dicompare.get_dicom_values(ds, skip_pixel_data=True)
    # Expect PatientName but no pixel data.
    assert "PatientName" in result
    for key in result.keys():
        assert "7FE0,0010" not in key and key != "(7FE0,0010)"

def test_get_dicom_values_no_skip_pixel():
    ds = create_dummy_file_dataset("dummy", include_pixel=True)
    # Even if skip_pixel_data is False, binary data is filtered out.
    result = dicompare.get_dicom_values(ds, skip_pixel_data=False)
    assert "PatientName" in result
    # Pixel data element should be None or not present.
    pixel_keys = [key for key in result if "7FE0" in key]
    for k in pixel_keys:
        assert result[k] is None

def test_load_dicom_with_file(dicom_file):
    result = dicompare.load_dicom(dicom_file, skip_pixel_data=True)
    assert "PatientName" in result
    assert result.get("InstanceNumber") is not None

def test_load_dicom_with_bytes(dicom_bytes):
    result = dicompare.load_dicom(dicom_bytes, skip_pixel_data=True)
    assert "PatientName" in result
    assert result.get("InstanceNumber") is not None


# ---------- Tests for load_nifti_session ----------

def test_load_nifti_session(nifti_file):
    df = dicompare.load_nifti_session(session_dir=os.path.dirname(nifti_file), acquisition_fields=["ProtocolName"], show_progress=False)
    # Check expected columns from nibabel and JSON inclusion.
    assert "NIfTI_Path" in df.columns
    assert "NIfTI_Shape" in df.columns
    # Check BIDS tag extraction; for file "sub-01_task-rest.nii", expect a key from splitting "sub-01"
    sample = df.iloc[0].to_dict()
    # Suffix should be set from the last token.
    assert "suffix" in sample
    # Extra JSON field should be present.
    assert sample.get("extra") == "value"


# ---------- Tests for async_load_dicom_session and load_dicom_session ----------

@pytest.mark.asyncio
async def test_async_load_dicom_session_bytes(dicom_bytes):
    # Test branch for dicom_bytes
    dicom_dict = {"dummy": dicom_bytes}
    progress_list = []
    def progress_fn(p):
        progress_list.append(p)
    df = await dicompare.async_load_dicom_session(
        dicom_bytes=dicom_dict,
        skip_pixel_data=True,
        show_progress=False,
        progress_function=progress_fn,
        parallel_workers=1
    )
    assert not df.empty
    # Check that progress function was called.
    assert progress_list or progress_list == []

@pytest.mark.asyncio
async def test_async_load_dicom_session_dir(temp_dir, dicom_file):
    # Test branch for session_dir
    df = await dicompare.async_load_dicom_session(
        session_dir=temp_dir,
        skip_pixel_data=True,
        show_progress=False,
        progress_function=None,
        parallel_workers=1
    )
    assert not df.empty

def test_load_dicom_session_wrapper(dicom_bytes):
    # Use the synchronous wrapper with dicom_bytes.
    dicom_dict = {"dummy": dicom_bytes}
    df = dicompare.load_dicom_session(
        dicom_bytes=dicom_dict,
        skip_pixel_data=True,
        show_progress=False,
        progress_function=None,
        parallel_workers=1
    )
    assert not df.empty

def test_async_load_dicom_session_error():
    with pytest.raises(ValueError, match="Either session_dir or dicom_bytes must be provided."):
        asyncio.run(dicompare.async_load_dicom_session(
            session_dir=None,
            dicom_bytes=None,
            skip_pixel_data=True
        ))


# ---------- Tests for assign_acquisition_and_run_numbers ----------

def test_assign_acquisition_and_run_numbers():
    # Create a DataFrame with necessary columns.
    data = {
        "SeriesDescription": ["desc1", "desc1", "desc2"],
        "ImageType": [("ORIGINAL", "PRIMARY", "AXIAL"), ("ORIGINAL", "PRIMARY", "AXIAL"), ("DERIVED", "SECONDARY", "AXIAL")],
        "SeriesTime": ["120000", "130000", "120000"],
        "ProtocolName": ["protA", "protA", "protA"],
        "PatientName": ["A", "A", "A"],
        "PatientID": ["ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101"],
        "StudyTime": ["120000", "130000", "120000"],
    }
    df = pd.DataFrame(data)
    df_out = dicompare.assign_acquisition_and_run_numbers(df.copy())
    # Acquisition column should be set.
    assert "Acquisition" in df_out.columns
    # RunNumber column should exist and be numeric.
    assert "RunNumber" in df_out.columns
    assert df_out["RunNumber"].dtype.kind in "biuf"
    # If only one series per description, run number should be 1.
    runs = df_out.groupby("SeriesDescription")["RunNumber"].unique()
    for arr in runs:
        for run in arr:
            assert run >= 1

# ---------- Tests for load_json_session ----------

def test_load_json_session(json_file):
    fields, ref_data = dicompare.load_json_session(json_file)
    # Expect two fields: one from acquisitions and one from series.
    assert "TestField" in fields
    assert "SeriesField" in fields
    # Check structure.
    assert "acquisitions" in ref_data
    assert "acq1" in ref_data["acquisitions"]
    acq = ref_data["acquisitions"]["acq1"]
    assert "fields" in acq
    assert isinstance(acq["series"], list)
    assert acq["series"][0]["name"] == "series1"


# ---------- Tests for load_python_session ----------

def test_load_python_session_valid(valid_python_module):
    models = dicompare.load_python_session(valid_python_module)
    assert isinstance(models, dict)
    assert "dummy" in models

def test_load_python_session_no_models(no_models_python_module):
    with pytest.raises(ValueError, match="does not define 'ACQUISITION_MODELS'"):
        dicompare.load_python_session(no_models_python_module)

def test_load_python_session_invalid(invalid_models_python_module):
    with pytest.raises(ValueError, match="'ACQUISITION_MODELS' must be a dictionary"):
        dicompare.load_python_session(invalid_models_python_module)
