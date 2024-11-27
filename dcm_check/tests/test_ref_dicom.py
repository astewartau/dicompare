#!/usr/bin/env python

import numpy as np
import pytest

from pydantic import ValidationError
from pydicom.dataset import Dataset

from dcm_check import load_dicom, is_dicom_compliant, check_dicom_compliance, get_dicom_values
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
    
