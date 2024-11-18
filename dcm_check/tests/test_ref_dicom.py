#!/usr/bin/env python

import numpy as np
import pytest

from pydantic import ValidationError
from pydicom.dataset import Dataset

from dcm_check import load_dicom, is_compliant, get_compliance_summary, load_ref_dicom, get_dicom_values
from dcm_check.tests.utils import create_empty_dicom

@pytest.fixture
def t1() -> Dataset:
    """Create a DICOM object with T1-weighted MRI metadata for testing."""

    ref_dicom = create_empty_dicom()
    
    # Set example attributes for T1-weighted MRI
    ref_dicom.SeriesDescription = "T1-weighted"
    ref_dicom.ProtocolName = "T1"
    ref_dicom.ScanningSequence = "GR"
    ref_dicom.SequenceVariant = "SP"
    ref_dicom.ScanOptions = "FS"
    ref_dicom.MRAcquisitionType = "3D"
    ref_dicom.RepetitionTime = "8.0"
    ref_dicom.EchoTime = "3.0"
    ref_dicom.InversionTime = "400.0"
    ref_dicom.FlipAngle = "15"
    ref_dicom.SAR = "0.1"
    ref_dicom.SliceThickness = "1.0"
    ref_dicom.SpacingBetweenSlices = "1.0"
    ref_dicom.PixelSpacing = ["0.5", "0.5"]
    ref_dicom.Rows = 256
    ref_dicom.Columns = 256
    ref_dicom.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    ref_dicom.ImagePositionPatient = ["-128", "-128", "0"]
    ref_dicom.Laterality = "R"
    ref_dicom.PatientPosition = "HFS"
    ref_dicom.BodyPartExamined = "BRAIN"
    ref_dicom.PatientOrientation = ["A", "P", "R", "L"]
    ref_dicom.AcquisitionMatrix = [256, 0, 0, 256]
    ref_dicom.InPlanePhaseEncodingDirection = "ROW"
    ref_dicom.EchoTrainLength = 1
    ref_dicom.PercentPhaseFieldOfView = "100"
    ref_dicom.AcquisitionContrast = "UNKNOWN"
    ref_dicom.PixelBandwidth = "200"
    ref_dicom.DeviceSerialNumber = "12345"
    ref_dicom.ImageType = ["ORIGINAL", "PRIMARY", "M", "ND"]

    # Set PixelData to a 10x10 array of random integers
    ref_dicom.Rows = 10
    ref_dicom.Columns = 10
    ref_dicom.BitsAllocated = 16
    ref_dicom.BitsStored = 16
    ref_dicom.HighBit = 15
    ref_dicom.PixelRepresentation = 0
    ref_dicom.PixelData = np.random.randint(0, 2**16, (10, 10)).astype(np.uint16).tobytes()

    return ref_dicom

def test_load_dicom(tmp_path, t1):
    dicom_path = tmp_path / "ref_dicom.dcm"
    t1.save_as(dicom_path, enforce_file_format=True)
    dicom_values = load_dicom(dicom_path)
    assert dicom_values["SeriesDescription"] == "T1-weighted"

def test_dicom_compliance_identity(t1):
    t1_values = get_dicom_values(t1)
    reference = load_ref_dicom(t1_values, fields=None)
    assert is_compliant(reference_model=reference, dicom_values=t1_values)
    assert len(get_compliance_summary(reference_model=reference, dicom_values=t1_values)) == 0

def test_dicom_compliance_specific_fields_compliant(t1):
    t1_values = get_dicom_values(t1)
    reference = load_ref_dicom(t1_values, fields=["RepetitionTime", "EchoTime", "InversionTime"])
    t1_values["SliceThickness"] = 2.0
    assert is_compliant(reference_model=reference, dicom_values=t1_values)
    assert len(get_compliance_summary(reference_model=reference, dicom_values=t1_values)) == 0

def test_dicom_compliance_specific_fields_non_compliant(t1):
    t1_values = get_dicom_values(t1)
    reference = load_ref_dicom(t1_values, fields=["RepetitionTime", "EchoTime", "InversionTime"])
    t1_values["RepetitionTime"] = 8.1

    assert not is_compliant(reference_model=reference, dicom_values=t1_values)

    compliance_summary = get_compliance_summary(reference_model=reference, dicom_values=t1_values)
    assert len(compliance_summary) == 1
    assert compliance_summary[0]["Parameter"] == "RepetitionTime"
    assert compliance_summary[0]["Expected"] == "8.0"
    assert compliance_summary[0]["Value"] == 8.1

def test_dicom_compliance_small_change(t1):
    t1_values = get_dicom_values(t1)
    reference = load_ref_dicom(t1_values, fields=None)

    t1_values["RepetitionTime"] = 8.1

    assert not is_compliant(reference_model=reference, dicom_values=t1_values)

    compliance_summary = get_compliance_summary(reference_model=reference, dicom_values=t1_values)
    assert len(compliance_summary) == 1
    assert compliance_summary[0]["Parameter"] == "RepetitionTime"
    assert compliance_summary[0]["Expected"] == "8.0"
    assert compliance_summary[0]["Value"] == 8.1

def test_dicom_compliance_num_errors(t1):
    t1_values = get_dicom_values(t1)
    reference = load_ref_dicom(t1_values, fields=None)

    t1_values["RepetitionTime"] = 8.1
    t1_values["EchoTime"] = 3.1
    t1_values["InversionTime"] = 400.1

    assert len(get_compliance_summary(reference_model=reference, dicom_values=t1_values)) == 3

def test_dicom_compliance_error_message(t1):
    t1_values = get_dicom_values(t1)
    reference = load_ref_dicom(t1_values, fields=None)

    t1_values["RepetitionTime"] = 8.1
    t1_values["EchoTime"] = 3.1
    t1_values["InversionTime"] = 400.1

    errors = get_compliance_summary(reference_model=reference, dicom_values=t1_values)

    assert errors[0]["Parameter"] == "RepetitionTime"
    assert errors[1]["Parameter"] == "EchoTime"
    assert errors[2]["Parameter"] == "InversionTime"
    assert errors[0]["Expected"] == "8.0"
    assert errors[1]["Expected"] == "3.0"
    assert errors[2]["Expected"] == "400.0"
    assert errors[0]["Value"] == 8.1
    assert errors[1]["Value"] == 3.1
    assert errors[2]["Value"] == 400.1

def test_dicom_compliance_error_message_missing_field(t1):
    t1_values = get_dicom_values(t1)
    reference = load_ref_dicom(t1_values, fields=None)

    del t1_values["RepetitionTime"]

    errors = get_compliance_summary(reference_model=reference, dicom_values=t1_values)
    compliant = is_compliant(reference_model=reference, dicom_values=t1_values)

    assert not compliant
    assert len(errors) == 1
    assert errors[0]["Parameter"] == "RepetitionTime"
    assert errors[0]["Expected"] == "Field required"
    assert errors[0]["Value"] == "N/A"

def test_dicom_compliance_error_raise(t1):
    t1_values = get_dicom_values(t1)
    reference = load_ref_dicom(t1_values, fields=None)

    t1_values["RepetitionTime"] = 8.1

    with pytest.raises(ValidationError):
        get_compliance_summary(reference_model=reference, dicom_values=t1_values, raise_errors=True)

def test_get_dicom_values_sequence(t1):
    t1.SequenceOfUltrasoundRegions = [Dataset(), Dataset()]
    t1.SequenceOfUltrasoundRegions[0].RegionLocationMinX0 = 0
    t1.SequenceOfUltrasoundRegions[0].RegionLocationMinY0 = 0
    t1.SequenceOfUltrasoundRegions[0].PhysicalUnitsXDirection = 1
    t1.SequenceOfUltrasoundRegions[0].PhysicalUnitsYDirection = 1
    t1.SequenceOfUltrasoundRegions[1].RegionLocationMinX0 = 0
    t1.SequenceOfUltrasoundRegions[1].RegionLocationMinY0 = 0
    t1.SequenceOfUltrasoundRegions[1].PhysicalUnitsXDirection = 1
    t1.SequenceOfUltrasoundRegions[1].PhysicalUnitsYDirection = 1

    dicom_values = get_dicom_values(t1)
    assert dicom_values["SequenceOfUltrasoundRegions"][0]["RegionLocationMinX0"] == 0
    assert dicom_values["SequenceOfUltrasoundRegions"][1]["RegionLocationMinY0"] == 0
    assert dicom_values["SequenceOfUltrasoundRegions"][0]["PhysicalUnitsXDirection"] == 1
    assert dicom_values["SequenceOfUltrasoundRegions"][1]["PhysicalUnitsYDirection"] == 1
    

if __name__ == "__main__":
    pytest.main(["-v", __file__])
    
