#!/usr/bin/env python

import pytest

from pydicom.dataset import Dataset

from dicompare import load_dicom, get_dicom_values
from .fixtures.fixtures import t1

def test_load_dicom(tmp_path, t1):
    dicom_path = tmp_path / "ref_dicom.dcm"
    t1.save_as(dicom_path, write_like_original=True)
    dicom_values = load_dicom(dicom_path)
    assert dicom_values["SeriesDescription"] == "T1-weighted"

if __name__ == "__main__":
    pytest.main(["-v", __file__])
    
