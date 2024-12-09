#!/usr/bin/env python

import pytest

from pydicom.dataset import Dataset

from dicompare import load_dicom, get_dicom_values
from .fixtures.fixtures import t1

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
    
