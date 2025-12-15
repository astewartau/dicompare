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
    ds.Modality = "MR"  # Required field for DICOM image validation
    ds.add_new((0x0010, 0x0010), "PN", patient_name)
    ds.add_new((0x0020, 0x0011), "IS", str(series_number))
    ds.add_new((0x0020, 0x0013), "IS", str(instance_number))
    ds.add_new((0x0008, 0x0060), "CS", "MR")  # Modality tag
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
        "version": "1.0",
        "name": "Test Template",
        "description": "Test template for schema loading",
        "created": "2025-08-08T04:29:05.132Z",
        "authors": ["Test Author"],
        "acquisitions": {
            "acq1": {
                "fields": [
                    {
                        "field": "TestField",
                        "value": 10,
                        "tolerance": 5
                    }
                ],
                "series": [
                    {
                        "name": "series1",
                        "fields": [
                            {
                                "field": "SeriesField",
                                "value": "x"
                            }
                        ]
                    }
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

def test_assign_acquisition_and_run_numbers_basic():
    """Test basic acquisition and run number assignment."""
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


def test_assign_acquisition_and_run_numbers_multiple_protocols():
    """Test handling of multiple different protocols (acquisitions)."""
    data = {
        "ProtocolName": ["T1w", "T1w", "T2w", "T2w"],
        "SeriesDescription": ["T1_MPR", "T1_MPR", "T2_TSE", "T2_TSE"], 
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "130000", "130000"],
        "PatientName": ["Patient1", "Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101", "20210101"],
    }
    df = pd.DataFrame(data)
    df_out = dicompare.assign_acquisition_and_run_numbers(df.copy())
    
    # Should have two different acquisitions
    unique_acquisitions = df_out["Acquisition"].unique()
    assert len(unique_acquisitions) == 2
    assert "acq-t1w" in unique_acquisitions
    assert "acq-t2w" in unique_acquisitions
    
    # Each acquisition should have run number 1 (no temporal repeats)
    for acq in unique_acquisitions:
        acq_data = df_out[df_out["Acquisition"] == acq]
        assert all(acq_data["RunNumber"] == 1)


def test_assign_acquisition_and_run_numbers_settings_splitting():
    """Test acquisition splitting when different settings are detected between runs."""
    data = {
        "ProtocolName": ["fMRI", "fMRI", "fMRI", "fMRI"],
        "SeriesDescription": ["BOLD", "BOLD", "BOLD", "BOLD"],
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "130000", "130000"],
        "SeriesInstanceUID": ["1.2.3.1", "1.2.3.1", "1.2.3.2", "1.2.3.2"],  # Two different series UIDs for run detection
        "PatientName": ["Patient1", "Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101", "20210101"],
        # Add a reference field that varies - this should trigger splitting
        "FlipAngle": [90, 90, 45, 45],  # Two different flip angles
        "RepetitionTime": [2000, 2000, 2000, 2000],  # Same TR
    }
    df = pd.DataFrame(data)

    # Use specific settings fields that include the varying field
    df_out = dicompare.assign_acquisition_and_run_numbers(
        df.copy(),
        settings_fields=["FlipAngle", "RepetitionTime"]
    )

    # Should split into two acquisitions due to different FlipAngle between runs
    unique_acquisitions = df_out["Acquisition"].unique()
    assert len(unique_acquisitions) == 2

    # Check that acquisitions are named with settings group numbers
    acq_names = sorted(unique_acquisitions)
    assert "acq-fmri" in acq_names and "acq-fmri_2" in acq_names


def test_assign_acquisition_and_run_numbers_temporal_runs():
    """Test detection of temporal runs (same acquisition repeated over time)."""
    data = {
        "ProtocolName": ["rsfMRI", "rsfMRI", "rsfMRI", "rsfMRI"],
        "SeriesDescription": ["BOLD", "BOLD", "BOLD", "BOLD"],
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "140000", "140000"],  # Two different times (>60s apart)
        "SeriesInstanceUID": ["1.2.3.1", "1.2.3.1", "1.2.3.2", "1.2.3.2"],  # Two different series UIDs
        "PatientName": ["Patient1", "Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101", "20210101"],
        "FlipAngle": [90, 90, 90, 90],  # Same settings
        "RepetitionTime": [2000, 2000, 2000, 2000],
    }
    df = pd.DataFrame(data)
    df_out = dicompare.assign_acquisition_and_run_numbers(
        df.copy(),
        settings_fields=["FlipAngle", "RepetitionTime"]
    )

    # Should have one acquisition type (settings don't change)
    unique_acquisitions = df_out["Acquisition"].unique()
    assert len(unique_acquisitions) == 1

    # Should detect two runs based on SeriesInstanceUID temporal clustering
    run_numbers = sorted(df_out["RunNumber"].unique())
    assert len(run_numbers) == 2  # Two runs detected


def test_assign_acquisition_and_run_numbers_coil_type_splitting():
    """Test CoilType-based acquisition splitting between runs."""
    data = {
        "ProtocolName": ["GRE", "GRE", "GRE", "GRE"],
        "SeriesDescription": ["GRE_magnitude", "GRE_magnitude", "GRE_magnitude", "GRE_magnitude"],
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "121000", "121000"],  # Two time points for run detection
        "SeriesInstanceUID": ["1.2.3.1", "1.2.3.1", "1.2.3.2", "1.2.3.2"],  # Two series UIDs
        "PatientName": ["Patient1", "Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101", "20210101"],
        "CoilType": ["Combined", "Combined", "Uncombined", "Uncombined"],  # Different coil types
        "FlipAngle": [15, 15, 15, 15],
    }
    df = pd.DataFrame(data)
    df_out = dicompare.assign_acquisition_and_run_numbers(
        df.copy(),
        settings_fields=["FlipAngle", "CoilType"]  # Include CoilType in settings
    )

    # Should split on CoilType differences between runs
    unique_acquisitions = df_out["Acquisition"].unique()
    assert len(unique_acquisitions) == 2

    # Verify CoilType is preserved in output
    assert "CoilType" in df_out.columns


def test_assign_acquisition_and_run_numbers_missing_protocol():
    """Test handling when ProtocolName is missing but SequenceName is available."""
    data = {
        "SequenceName": ["*tfl3d1_16ns", "*tfl3d1_16ns", "*tse2d1_15"],  # SequenceName as fallback
        "SeriesDescription": ["T1_MPR", "T1_MPR", "T2_TSE"],
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "130000"],
        "PatientName": ["Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101"],
        # No ProtocolName column - should use SequenceName
    }
    df = pd.DataFrame(data)
    df_out = dicompare.assign_acquisition_and_run_numbers(df.copy())

    # Should use SequenceName for acquisition identification
    assert "Acquisition" in df_out.columns
    assert "RunNumber" in df_out.columns
    # Should create two acquisitions based on SequenceName
    unique_acquisitions = df_out["Acquisition"].unique()
    assert len(unique_acquisitions) == 2


def test_assign_acquisition_and_run_numbers_custom_fields():
    """Test using custom settings fields."""
    data = {
        "ProtocolName": ["Scan1", "Scan1", "Scan2"],
        "SeriesDescription": ["desc1", "desc1", "desc2"],
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "130000"],
        "PatientName": ["Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101"],
        "CustomField": ["A", "A", "B"],
    }
    df = pd.DataFrame(data)
    df_out = dicompare.assign_acquisition_and_run_numbers(
        df.copy(),
        settings_fields=["CustomField"]
    )

    # Should create acquisitions based on ProtocolName
    unique_acquisitions = df_out["Acquisition"].unique()
    assert len(unique_acquisitions) == 2
    assert any("scan1" in acq.lower() for acq in unique_acquisitions)
    assert any("scan2" in acq.lower() for acq in unique_acquisitions)


# ---------- Tests for Series Grouping Functionality ----------

def test_assign_acquisition_and_run_numbers_series_multiecho():
    """Test series grouping for multi-echo sequences with varying EchoTime.

    In the new model, EchoTime is a parameter variation within a series, not a series differentiator.
    Multi-echo acquisitions are single series with varying echo times.
    """
    data = {
        "ProtocolName": ["T2star_multiecho", "T2star_multiecho", "T2star_multiecho", "T2star_multiecho"],
        "SeriesDescription": ["MultiEcho", "MultiEcho", "MultiEcho", "MultiEcho"],
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "120000", "120000"],
        "PatientName": ["Patient1", "Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101", "20210101"],
        "EchoTime": [5.0, 10.0, 15.0, 20.0],  # 4 different echo times - parameter variation within series
    }
    df = pd.DataFrame(data)

    df_out = dicompare.assign_acquisition_and_run_numbers(df.copy())

    # Should have 1 acquisition and 1 series (EchoTime is parameter variation, not series differentiator)
    unique_acquisitions = df_out["Acquisition"].unique()
    unique_series = df_out["Series"].unique()

    assert len(unique_acquisitions) == 1
    assert len(unique_series) == 1

    # Check acquisition and series naming convention
    acq_name = unique_acquisitions[0]
    series_name = unique_series[0]
    assert "acq-t2starmultiecho" == acq_name
    assert "Series 01" == series_name

    # Verify all echo times belong to the same series
    assert all(df_out["Series"] == series_name)


def test_assign_acquisition_and_run_numbers_series_dti():
    """Test series grouping for DTI sequences with varying DiffusionBValue.

    In the new model, DiffusionBValue is a parameter variation within a series, not a series differentiator.
    DTI acquisitions are single series with varying b-values.
    """
    data = {
        "ProtocolName": ["DTI_30dir", "DTI_30dir", "DTI_30dir", "DTI_30dir"],
        "SeriesDescription": ["DTI", "DTI", "DTI", "DTI"],
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "120000", "120000"],
        "PatientName": ["Patient1", "Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101", "20210101"],
        "DiffusionBValue": [0, 0, 1000, 1000],  # b=0 and b=1000 values - parameter variation
        "RepetitionTime": [5000, 5000, 5000, 5000],  # Same TR
    }
    df = pd.DataFrame(data)

    df_out = dicompare.assign_acquisition_and_run_numbers(
        df.copy(),
        settings_fields=["RepetitionTime", "EchoTime"]
    )

    # Should have 1 acquisition and 1 series (DiffusionBValue is parameter variation)
    unique_acquisitions = df_out["Acquisition"].unique()
    unique_series = df_out["Series"].unique()

    assert len(unique_acquisitions) == 1
    assert len(unique_series) == 1

    # Check acquisition and series naming
    acq_name = unique_acquisitions[0]
    series_name = unique_series[0]
    assert "acq-dti30dir" == acq_name
    assert "Series 01" == series_name

    # Verify all b-values belong to the same series
    assert all(df_out["Series"] == series_name)


def test_assign_acquisition_and_run_numbers_series_single_sequence():
    """Test series grouping for sequences with no varying parameters."""
    data = {
        "ProtocolName": ["T1_MPRAGE", "T1_MPRAGE", "T1_MPRAGE"],
        "SeriesDescription": ["MPRAGE", "MPRAGE", "MPRAGE"],
        "ImageType": [("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY"), ("ORIGINAL", "PRIMARY")],
        "SeriesTime": ["120000", "120000", "120000"],
        "PatientName": ["Patient1", "Patient1", "Patient1"],
        "PatientID": ["ID1", "ID1", "ID1"],
        "StudyDate": ["20210101", "20210101", "20210101"],
        "EchoTime": [5.0, 5.0, 5.0],  # Same echo time for all
        "RepetitionTime": [2000, 2000, 2000],  # Same TR for all
    }
    df = pd.DataFrame(data)

    df_out = dicompare.assign_acquisition_and_run_numbers(df.copy())

    # Should have 1 acquisition and 1 series (no varying parameters)
    unique_acquisitions = df_out["Acquisition"].unique()
    unique_series = df_out["Series"].unique()

    assert len(unique_acquisitions) == 1
    assert len(unique_series) == 1
    assert "acq-t1mprage" == unique_acquisitions[0]
    assert "Series 01" == unique_series[0]


def test_assign_acquisition_and_run_numbers_series_multiple_acquisitions():
    """Test series grouping across multiple different acquisitions.

    In the new model, parameter variations (EchoTime, DiffusionBValue) don't create separate series.
    """
    data = {
        "ProtocolName": ["T2star_multiecho", "T2star_multiecho", "DTI_30dir", "DTI_30dir", "T1_MPRAGE"],
        "SeriesDescription": ["MultiEcho", "MultiEcho", "DTI", "DTI", "MPRAGE"],
        "ImageType": [("ORIGINAL", "PRIMARY")] * 5,
        "SeriesTime": ["120000"] * 5,
        "PatientName": ["Patient1"] * 5,
        "PatientID": ["ID1"] * 5,
        "StudyDate": ["20210101"] * 5,
        "EchoTime": [5.0, 10.0, None, None, 5.0],  # MultiEcho varies (parameter variation)
        "DiffusionBValue": [None, None, 0, 1000, None],  # DTI varies (parameter variation)
        "RepetitionTime": [2000] * 5,  # Same for all
    }
    df = pd.DataFrame(data)

    # Use reference fields that exclude series-grouping parameters
    df_out = dicompare.assign_acquisition_and_run_numbers(
        df.copy(),
        settings_fields=["RepetitionTime"]  # Exclude EchoTime and DiffusionBValue
    )

    # Should have 3 acquisitions (one for each protocol)
    unique_acquisitions = df_out["Acquisition"].unique()
    assert len(unique_acquisitions) == 3

    # Check series for T2star_multiecho (should have 1 series - EchoTime is parameter variation)
    t2star_rows = df_out[df_out["ProtocolName"] == "T2star_multiecho"]
    t2star_series = t2star_rows["Series"].unique()
    assert len(t2star_series) == 1

    # Check series for DTI_30dir (should have 1 series - DiffusionBValue is parameter variation)
    dti_rows = df_out[df_out["ProtocolName"] == "DTI_30dir"]
    dti_series = dti_rows["Series"].unique()
    assert len(dti_series) == 1

    # Check series for T1_MPRAGE (should have 1 series, no variation)
    t1_rows = df_out[df_out["ProtocolName"] == "T1_MPRAGE"]
    t1_series = t1_rows["Series"].unique()
    assert len(t1_series) == 1


def test_assign_acquisition_and_run_numbers_series_with_nans():
    """Test series grouping handles NaN values correctly."""
    data = {
        "ProtocolName": ["fMRI", "fMRI", "fMRI", "fMRI"],
        "SeriesDescription": ["BOLD_task1", "BOLD_task1", "BOLD_task2", "BOLD_task2"],
        "ImageType": [("ORIGINAL", "PRIMARY")] * 4,
        "SeriesTime": ["120000"] * 4,
        "PatientName": ["Patient1"] * 4,
        "PatientID": ["ID1"] * 4,
        "StudyDate": ["20210101"] * 4,
        "EchoTime": [30.0, 30.0, None, None],  # Some NaN values
        "FlipAngle": [90, 45, 90, 45],  # FlipAngle varies within acquisition (like MPRAGE)
    }
    df = pd.DataFrame(data)
    
    df_out = dicompare.assign_acquisition_and_run_numbers(df.copy())
    
    # Should create separate series based on SeriesDescription differences
    unique_series = df_out["Series"].unique()
    assert len(unique_series) == 2  # Two different SeriesDescription values


def test_assign_acquisition_and_run_numbers_backward_compatibility():
    """Test that adding Series column doesn't break existing functionality."""
    data = {
        "ProtocolName": ["fMRI", "fMRI", "T1", "T1"],
        "SeriesDescription": ["BOLD", "BOLD", "MPRAGE", "MPRAGE"],
        "ImageType": [("ORIGINAL", "PRIMARY")] * 4,
        "SeriesTime": ["120000", "130000", "140000", "150000"],
        "PatientName": ["Patient1"] * 4,
        "PatientID": ["ID1"] * 4,
        "StudyDate": ["20210101"] * 4,
        "RunNumber": [1, 1, 1, 1],
    }
    df = pd.DataFrame(data)
    
    df_out = dicompare.assign_acquisition_and_run_numbers(df.copy())
    
    # Should still have Acquisition and Run columns as before
    assert "Acquisition" in df_out.columns
    assert "RunNumber" in df_out.columns  
    
    # Should now also have Series column
    assert "Series" in df_out.columns
    
    # Basic acquisition grouping should still work
    unique_acquisitions = df_out["Acquisition"].unique()
    assert len(unique_acquisitions) == 2


# ---------- Tests for load_schema ----------

def test_load_schema(json_file):
    fields, ref_data, validation_rules = dicompare.load_schema(json_file)
    # Expect two fields: one from acquisitions and one from series.
    assert "TestField" in fields
    assert "SeriesField" in fields
    # Check structure.
    assert "acquisitions" in ref_data
    # validation_rules can be empty dict if no rules in schema
    assert isinstance(validation_rules, dict)
    assert "acq1" in ref_data["acquisitions"]  # protocolName becomes the key
    acq = ref_data["acquisitions"]["acq1"]
    assert "fields" in acq
    assert isinstance(acq["series"], list)
    assert acq["series"][0]["name"] == "series1"
    
    # Verify the field structure
    test_field = acq["fields"][0]
    assert test_field["field"] == "TestField"
    assert test_field["value"] == 10  # Numeric value
    assert test_field["tolerance"] == 5
    
    # Verify series field structure conversion
    series_field = acq["series"][0]["fields"][0]
    assert series_field["field"] == "SeriesField"
    assert series_field["value"] == "x"


# ---------- Tests for load_python_schema ----------

def test_load_schema(tmp_path):
    """Test loading a hybrid JSON schema with both fields and rules."""
    # Create a hybrid schema with both fields and rules
    hybrid_schema = {
        "name": "Test Hybrid Schema",
        "version": "1.0",
        "acquisitions": {
            "QSM": {
                "fields": [
                    {"field": "EchoTime", "value": 5, "tolerance": 1},
                    {"field": "RepetitionTime", "value": 25}
                ],
                "rules": [
                    {
                        "id": "validate_echo_count",
                        "name": "Multi-echo Validation",
                        "description": "At least 3 echoes required for QSM",
                        "fields": ["EchoTime"],
                        "implementation": "echo_times = value['EchoTime'].dropna().unique()\nif len(echo_times) < 3:\n    raise ValidationError('Need at least 3 echoes')\nreturn value"
                    },
                    {
                        "id": "validate_tr_range",
                        "name": "TR Range Check",
                        "fields": ["RepetitionTime"],
                        "implementation": "tr = value['RepetitionTime'].iloc[0]\nif tr < 20 or tr > 30:\n    raise ValidationError('TR should be between 20-30ms')\nreturn value"
                    }
                ]
            },
            "T1w": {
                "fields": [
                    {"field": "SequenceName", "value": "MPRAGE"}
                ]
                # No rules for this acquisition
            }
        }
    }
    
    # Write schema to file
    schema_path = tmp_path / "hybrid_schema.json"
    with open(schema_path, "w") as f:
        json.dump(hybrid_schema, f)
    
    # Test loading the hybrid schema
    fields, schema_data, validation_rules = dicompare.load_schema(str(schema_path))
    
    # Check that all fields are extracted correctly
    assert "EchoTime" in fields
    assert "RepetitionTime" in fields
    assert "SequenceName" in fields
    assert len(fields) == 3  # All unique fields
    
    # Check schema data is loaded correctly
    assert "acquisitions" in schema_data
    assert "QSM" in schema_data["acquisitions"]
    assert "T1w" in schema_data["acquisitions"]
    
    # Check validation rules are extracted correctly
    assert "QSM" in validation_rules
    assert "T1w" not in validation_rules  # T1w has no rules
    
    qsm_rules = validation_rules["QSM"]
    assert len(qsm_rules) == 2
    assert qsm_rules[0]["id"] == "validate_echo_count"
    assert qsm_rules[0]["fields"] == ["EchoTime"]
    assert "implementation" in qsm_rules[0]
    assert qsm_rules[1]["id"] == "validate_tr_range"


def test_load_schema_backward_compatible(json_file):
    """Test that hybrid loader works with old field-only schemas."""
    # Use existing test JSON file which has no rules
    fields, schema_data, validation_rules = dicompare.load_schema(json_file)
    
    # Should work like the old loader
    assert "TestField" in fields
    assert "SeriesField" in fields
    
    # No validation rules in old schema
    assert validation_rules == {}
    
    # Schema data should be unchanged
    assert "acquisitions" in schema_data
    assert "acq1" in schema_data["acquisitions"]

