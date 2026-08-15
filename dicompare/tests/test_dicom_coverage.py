"""
Coverage-focused unit tests for dicompare/io/dicom.py.

These tests exercise the DICOM field/value extraction helpers, the various
metadata-manipulation helpers, the enhanced/regular DICOM processing paths,
CSA / ASCCONV extraction, ASL inference branches, and the session-loading
entry points. Tests assert real behaviour and use tmp_path for file IO.
"""

import os
import asyncio

import numpy as np
import pandas as pd
import pydicom
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import UID, ExplicitVRLittleEndian
from pydicom.valuerep import DT

import dicompare.io.dicom as dio
from dicompare.io.dicom import (
    _extract_inferred_metadata,
    _extract_csa_metadata,
    _extract_ascconv,
    _get_ascconv_value,
    _process_dicom_element,
    _extract_shared_functional_groups,
    _process_enhanced_dicom,
    _process_regular_dicom,
    get_dicom_values,
    _update_metadata,
    _get_metadata_value,
    _set_metadata_value,
    _key_in_metadata,
    load_dicom,
    load_nifti_session,
    async_load_dicom_session,
    load_dicom_session,
    _load_one_dicom_path,
    _load_one_dicom_bytes,
)


# --------------------------------------------------------------------------
# Helpers to build DICOM datasets
# --------------------------------------------------------------------------

def _make_base_dataset(**extra):
    ds = Dataset()
    ds.PatientName = "Test^Patient"
    ds.PatientID = "123"
    ds.StudyInstanceUID = "1.2.3.4.5"
    ds.SeriesInstanceUID = "1.2.3.4.6"
    ds.SOPInstanceUID = "1.2.3.4.7"
    ds.Modality = "MR"
    ds.SeriesNumber = "1"
    ds.InstanceNumber = "1"

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = UID("1.2.840.10008.5.1.4.1.1.4")
    fm.MediaStorageSOPInstanceUID = UID("1.2.3")
    fm.ImplementationClassUID = UID("1.2.3.4")
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta = fm

    for k, v in extra.items():
        setattr(ds, k, v)
    return ds


def _write_dataset(ds, path):
    ds.save_as(str(path), write_like_original=False)
    return str(path)


# --------------------------------------------------------------------------
# _extract_inferred_metadata
# --------------------------------------------------------------------------

def test_inferred_metadata_from_image_comments():
    ds = _make_base_dataset()
    ds.ImageComments = "Unaliased MB3/PE3 SENSE1"
    meta = _extract_inferred_metadata(ds)
    assert meta["MultibandFactor"] == 3
    assert meta["MultibandAccelerationFactor"] == 3
    assert meta["ParallelReductionFactorOutOfPlane"] == 3


def test_inferred_metadata_from_protocol_name():
    ds = _make_base_dataset()
    ds.ProtocolName = "rest_mb4_bold"
    meta = _extract_inferred_metadata(ds)
    assert meta["MultibandFactor"] == 4


def test_inferred_metadata_image_comments_takes_priority():
    ds = _make_base_dataset()
    ds.ImageComments = "Unaliased MB2/PE3"
    ds.ProtocolName = "task_mb8_run"
    meta = _extract_inferred_metadata(ds)
    # ImageComments (MB2) wins over ProtocolName (mb8)
    assert meta["MultibandFactor"] == 2


def test_inferred_metadata_none_found():
    ds = _make_base_dataset()
    ds.ImageComments = "no multiband here"
    ds.ProtocolName = "plain_t1"
    assert _extract_inferred_metadata(ds) == {}


# --------------------------------------------------------------------------
# _extract_csa_metadata (via monkeypatched get_csa_header)
# --------------------------------------------------------------------------

def test_csa_metadata_none(monkeypatch):
    monkeypatch.setattr(dio, "get_csa_header", lambda ds, kind: None)
    assert _extract_csa_metadata(_make_base_dataset()) == {}


def test_csa_metadata_no_tags_key(monkeypatch):
    monkeypatch.setattr(dio, "get_csa_header", lambda ds, kind: {"something": 1})
    assert _extract_csa_metadata(_make_base_dataset()) == {}


def test_csa_metadata_scalar_list_and_fallbacks(monkeypatch):
    csa = {
        "tags": {
            "B_value": {"items": ["1000"]},
            "DiffusionGradientDirection": {"items": ["1.0", "0.0", "0.0"]},
            "SliceMeasurementDuration": {"items": []},          # empty -> None
            "GradientMode": {"items": ["Fast"]},                 # non-float scalar -> str
            "B_matrix": {"items": ["1.5", "notnum"]},            # mixed list
        }
    }
    monkeypatch.setattr(dio, "get_csa_header", lambda ds, kind: csa)
    meta = _extract_csa_metadata(_make_base_dataset())
    assert meta["DiffusionBValue"] == 1000.0
    assert meta["DiffusionGradientOrientation"] == [1.0, 0.0, 0.0]
    assert meta["SliceMeasurementDuration"] is None
    assert meta["GradientMode"] == "Fast"
    assert meta["B_matrix"] == [1.5, "notnum"]
    # A tag not present at all resolves to None
    assert meta["TotalReadoutTime"] is None


# --------------------------------------------------------------------------
# _extract_ascconv
# --------------------------------------------------------------------------

def _csa_series_bytes(ascconv_body):
    return (
        b"junk header bytes "
        + b"### ASCCONV BEGIN ###\n"
        + ascconv_body.encode("latin-1")
        + b"\n### ASCCONV END ###"
        + b" trailing"
    )


def test_ascconv_extract_vseries_tag():
    ds = _make_base_dataset()
    body = "ucCoilCombineMode = 1\nsPat.lAccelFactPE = 2\nlRepetitions = 17"
    ds.add_new((0x0029, 0x1020), "OB", _csa_series_bytes(body))
    parsed = _extract_ascconv(ds)
    assert parsed["ucCoilCombineMode"] == 1
    assert parsed["sPat"]["lAccelFactPE"] == 2
    assert parsed["lRepetitions"] == 17


def test_ascconv_extract_xa_tag():
    ds = _make_base_dataset()
    body = "ucCoilCombineMode = 2"
    ds.add_new((0x0021, 0x1019), "OB", _csa_series_bytes(body))
    parsed = _extract_ascconv(ds)
    assert parsed["ucCoilCombineMode"] == 2


def test_ascconv_no_csa_tag():
    ds = _make_base_dataset()
    assert _extract_ascconv(ds) == {}


def test_ascconv_no_markers():
    ds = _make_base_dataset()
    ds.add_new((0x0029, 0x1020), "OB", b"some bytes without ascconv markers")
    assert _extract_ascconv(ds) == {}


def test_ascconv_empty_bytes_skipped():
    ds = _make_base_dataset()
    ds.add_new((0x0029, 0x1020), "OB", b"")
    assert _extract_ascconv(ds) == {}


def test_ascconv_parse_failure(monkeypatch):
    ds = _make_base_dataset()
    ds.add_new((0x0029, 0x1020), "OB", _csa_series_bytes("ucCoilCombineMode = 1"))
    import twixtools.twixprot as tp
    monkeypatch.setattr(tp, "parse_buffer", lambda text: (_ for _ in ()).throw(RuntimeError("boom")))
    assert _extract_ascconv(ds) == {}


# --------------------------------------------------------------------------
# _get_ascconv_value
# --------------------------------------------------------------------------

def test_get_ascconv_value_direct_and_default():
    d = {"a": 5}
    assert _get_ascconv_value(d, "a") == 5
    assert _get_ascconv_value(d, "missing", default="x") == "x"


def test_get_ascconv_value_nested_dict():
    d = {"sPat": {"lAccelFactPE": 3}}
    assert _get_ascconv_value(d, "sPat.lAccelFactPE") == 3


def test_get_ascconv_value_nested_missing():
    d = {"sPat": {"lAccelFactPE": 3}}
    assert _get_ascconv_value(d, "sPat.nope", default="dflt") == "dflt"
    assert _get_ascconv_value(d, "missing.child", default="dflt") == "dflt"


def test_get_ascconv_value_array_index():
    d = {"arr": [10, 20, 30]}
    assert _get_ascconv_value(d, "arr.1") == 20
    # Out of range index -> default
    assert _get_ascconv_value(d, "arr.9", default=None) is None


def test_get_ascconv_value_none_in_path():
    d = {"a": None}
    assert _get_ascconv_value(d, "a.b", default="d") == "d"


def test_get_ascconv_value_returns_default_when_value_none():
    d = {"a": {"b": None}}
    assert _get_ascconv_value(d, "a.b", default="d") == "d"


# --------------------------------------------------------------------------
# _process_dicom_element
# --------------------------------------------------------------------------

def test_process_element_skips_pixel_data():
    ds = _make_base_dataset()
    ds.add_new((0x7FE0, 0x0010), "OB", b"\x00\x01")
    elem = ds[(0x7FE0, 0x0010)]
    assert _process_dicom_element(elem, skip_pixel_data=True) is None


def test_process_element_bytes_returns_none():
    ds = _make_base_dataset()
    ds.add_new((0x0009, 0x0010), "OB", b"\x01\x02")
    elem = ds[(0x0009, 0x0010)]
    assert _process_dicom_element(elem) is None


def test_process_element_multivalue_and_scalars():
    ds = _make_base_dataset()
    ds.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    elem = ds["ImageOrientationPatient"]
    result = _process_dicom_element(elem)
    assert isinstance(result, tuple)
    assert result == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def test_process_element_empty_string_returns_none():
    ds = _make_base_dataset()
    ds.SeriesDescription = ""
    elem = ds["SeriesDescription"]
    assert _process_dicom_element(elem) is None


def test_process_element_string_value():
    ds = _make_base_dataset()
    ds.SeriesDescription = "T1w"
    elem = ds["SeriesDescription"]
    assert _process_dicom_element(elem) == "T1w"


def test_process_element_datetime():
    ds = _make_base_dataset()
    ds.add_new((0x0008, 0x002A), "DT", DT("20240101120000.000000"))
    elem = ds[(0x0008, 0x002A)]
    result = _process_dicom_element(elem)
    assert result == "2024-01-01 12:00:00"


def test_process_element_nested_dataset():
    inner = Dataset()
    inner.EchoTime = "3.0"
    outer = Dataset()
    seq = Sequence([inner])
    outer.add_new((0x0018, 0x9114), "SQ", seq)  # MREchoSequence
    elem = outer[(0x0018, 0x9114)]
    result = _process_dicom_element(elem)
    # sequences -> tuple of converted dicts
    assert isinstance(result, tuple)
    assert result[0]["EchoTime"] == 3.0


def test_process_element_unconvertible_returns_none():
    # A value that is not str/int/float/DT/list and whose str conversion is
    # empty -> None (line 358 fallback path).
    ds = _make_base_dataset()
    ds.add_new((0x0009, 0x0011), "SH", "")  # empty short string
    elem = ds[(0x0009, 0x0011)]
    assert _process_dicom_element(elem) is None


# --------------------------------------------------------------------------
# _extract_shared_functional_groups
# --------------------------------------------------------------------------

def test_shared_functional_groups_combined():
    coil = Dataset()
    coil.ReceiveCoilName = "HeadNeck_20"
    coil.ReceiveCoilType = "MULTICOIL"
    e1 = Dataset(); e1.MultiCoilElementName = "H1"
    e2 = Dataset(); e2.MultiCoilElementName = "H2"
    coil.MultiCoilDefinitionSequence = Sequence([e1, e2])
    tx = Dataset(); tx.TransmitCoilName = "Body"
    shared = Dataset()
    shared.MRReceiveCoilSequence = Sequence([coil])
    shared.MRTransmitCoilSequence = Sequence([tx])

    result = _extract_shared_functional_groups(shared)
    assert result["ReceiveCoilName"] == "HeadNeck_20"
    assert result["ReceiveCoilType"] == "MULTICOIL"
    assert result["MultiCoilElementCount"] == 2
    assert result["MultiCoilElementNames"] == ["H1", "H2"]
    assert result["TransmitCoilName"] == "Body"


def test_shared_functional_groups_empty():
    shared = Dataset()
    assert _extract_shared_functional_groups(shared) == {}


# --------------------------------------------------------------------------
# Enhanced / regular DICOM processing + get_dicom_values
# --------------------------------------------------------------------------

def _make_enhanced_dataset():
    ds = _make_base_dataset()
    ds.SeriesDescription = "Enhanced"

    # Shared functional groups with coil info
    coil = Dataset()
    coil.ReceiveCoilName = "Head_32"
    e1 = Dataset(); e1.MultiCoilElementName = "H1"
    e2 = Dataset(); e2.MultiCoilElementName = "H2"
    coil.MultiCoilDefinitionSequence = Sequence([e1, e2])
    shared = Dataset()
    shared.MRReceiveCoilSequence = Sequence([coil])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])

    # Two per-frame groups: one with a single-item sequence, one with multi-item
    frame1 = Dataset()
    echo = Dataset(); echo.EffectiveEchoTime = 3.0
    frame1.MREchoSequence = Sequence([echo])
    frame1.InstanceNumber = "1"

    frame2 = Dataset()
    m1 = Dataset(); m1.EffectiveEchoTime = 3.0
    m2 = Dataset(); m2.EffectiveEchoTime = 6.0
    frame2.MREchoSequence = Sequence([m1, m2])  # multi-item sequence branch
    frame2.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]  # MultiValue branch
    frame2.InstanceNumber = "2"

    ds.PerFrameFunctionalGroupsSequence = Sequence([frame1, frame2])
    return ds


def test_get_dicom_values_enhanced():
    ds = _make_enhanced_dataset()
    rows = get_dicom_values(ds, skip_pixel_data=True)
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert rows[0]["FrameIndex"] == 0
    assert rows[1]["FrameIndex"] == 1
    # Shared coil metadata merged into every frame
    assert rows[0]["MultiCoilElementCount"] == 2


def test_get_dicom_values_regular():
    ds = _make_base_dataset()
    ds.SeriesDescription = "T1w"
    result = get_dicom_values(ds, skip_pixel_data=True)
    assert isinstance(result, dict)
    assert result["SeriesDescription"] == "T1w"


def test_process_enhanced_dicom_skip_pixel():
    ds = _make_enhanced_dataset()
    ds.add_new((0x7FE0, 0x0010), "OB", b"\x00\x01")
    rows = _process_enhanced_dicom(ds, skip_pixel_data=True)
    assert all("PixelData" not in r for r in rows)


def test_process_regular_dicom_direct():
    ds = _make_base_dataset()
    ds.SeriesDescription = "reg"
    result = _process_regular_dicom(ds)
    assert result["SeriesDescription"] == "reg"


# --------------------------------------------------------------------------
# metadata helper functions (dict + list variants)
# --------------------------------------------------------------------------

def test_update_metadata_dict_and_list():
    d = {"a": 1}
    _update_metadata(d, {"b": 2})
    assert d == {"a": 1, "b": 2}

    lst = [{"a": 1}, {"a": 2}]
    _update_metadata(lst, {"c": 9})
    assert all(item["c"] == 9 for item in lst)


def test_get_metadata_value_dict_and_list():
    assert _get_metadata_value({"a": 5}, "a") == 5
    assert _get_metadata_value({"a": 5}, "b", default="d") == "d"

    lst = [{"a": None}, {"a": 7}]
    assert _get_metadata_value(lst, "a") == 7
    assert _get_metadata_value([{"x": 1}], "a", default="d") == "d"


def test_set_metadata_value_dict_and_list():
    d = {}
    _set_metadata_value(d, "k", 3)
    assert d["k"] == 3

    lst = [{}, {}]
    _set_metadata_value(lst, "k", 4)
    assert all(item["k"] == 4 for item in lst)


def test_key_in_metadata_dict_and_list():
    assert _key_in_metadata({"a": 1}, "a")
    assert not _key_in_metadata({"a": 1}, "b")
    assert _key_in_metadata([{"a": 1}, {"b": 2}], "b")
    assert not _key_in_metadata([{"a": 1}], "z")


# --------------------------------------------------------------------------
# load_dicom - core behaviour and branch coverage
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_csa_no_ascconv(monkeypatch):
    """Default: no CSA header and no ASCCONV so non-Siemens tests are clean.

    Individual tests override these as needed.
    """
    monkeypatch.setattr(dio, "get_csa_header", lambda ds, kind: None)
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {})


def test_load_dicom_from_path(tmp_path):
    ds = _make_base_dataset()
    ds.SeriesDescription = "T1w"
    path = _write_dataset(ds, tmp_path / "a.dcm")
    result = load_dicom(path)
    assert result["SeriesDescription"] == "T1w"
    assert result["PatientName"] == "Test^Patient"


def test_load_dicom_from_bytes(tmp_path):
    ds = _make_base_dataset()
    path = _write_dataset(ds, tmp_path / "a.dcm")
    with open(path, "rb") as f:
        content = f.read()
    result = load_dicom(content)
    assert result["PatientName"] == "Test^Patient"


def test_load_dicom_missing_file_raises(tmp_path):
    with pytest.raises(Exception):
        load_dicom(str(tmp_path / "does_not_exist.dcm"))


def test_load_dicom_acquisition_plane_axial(tmp_path):
    ds = _make_base_dataset()
    ds.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    path = _write_dataset(ds, tmp_path / "ax.dcm")
    result = load_dicom(path)
    assert result["AcquisitionPlane"] == "axial"


def test_load_dicom_acquisition_plane_sagittal(tmp_path):
    ds = _make_base_dataset()
    ds.ImageOrientationPatient = ["0", "1", "0", "0", "0", "1"]
    path = _write_dataset(ds, tmp_path / "sag.dcm")
    result = load_dicom(path)
    assert result["AcquisitionPlane"] == "sagittal"


def test_load_dicom_acquisition_plane_coronal(tmp_path):
    ds = _make_base_dataset()
    ds.ImageOrientationPatient = ["1", "0", "0", "0", "0", "1"]
    path = _write_dataset(ds, tmp_path / "cor.dcm")
    result = load_dicom(path)
    assert result["AcquisitionPlane"] == "coronal"


def test_load_dicom_coil_combined_from_private_tag(tmp_path):
    ds = _make_base_dataset()
    ds.add_new((0x0051, 0x100F), "LO", "HC1-6")  # range -> combined
    path = _write_dataset(ds, tmp_path / "coil.dcm")
    result = load_dicom(path)
    assert result["CoilType"] == "Combined"


def test_load_dicom_coil_uncombined_from_private_tag(tmp_path):
    ds = _make_base_dataset()
    ds.add_new((0x0051, 0x100F), "LO", "H15")  # single element -> uncombined
    path = _write_dataset(ds, tmp_path / "coil2.dcm")
    result = load_dicom(path)
    assert result["CoilType"] == "Uncombined"


def test_load_dicom_coil_combined_semicolon(tmp_path):
    ds = _make_base_dataset()
    ds.add_new((0x0051, 0x100F), "LO", "HEA;HEP")
    path = _write_dataset(ds, tmp_path / "coil3.dcm")
    result = load_dicom(path)
    assert result["CoilType"] == "Combined"


def test_load_dicom_coil_combined_no_digits(tmp_path):
    ds = _make_base_dataset()
    ds.add_new((0x0051, 0x100F), "LO", "HEA")
    path = _write_dataset(ds, tmp_path / "coil4.dcm")
    result = load_dicom(path)
    assert result["CoilType"] == "Combined"


def test_load_dicom_coil_from_element_count(tmp_path, monkeypatch):
    # Enhanced DICOM path: MultiCoilElementCount drives CoilType when no private tag.
    ds = _make_enhanced_dataset()
    path = _write_dataset(ds, tmp_path / "enh.dcm")
    result = load_dicom(path)
    # result is a list of frame dicts; count of 2 -> Combined
    assert isinstance(result, list)
    assert all(r["CoilType"] == "Combined" for r in result)


def test_load_dicom_ge_image_type_mapping(tmp_path):
    ds = _make_base_dataset()
    ds.ImageType = ["ORIGINAL", "PRIMARY"]
    ds.add_new((0x0043, 0x102F), "SS", 1)  # -> 'P'
    path = _write_dataset(ds, tmp_path / "ge.dcm")
    result = load_dicom(path)
    assert "P" in result["ImageType"]


def test_load_dicom_ge_image_type_no_existing(tmp_path):
    ds = _make_base_dataset()
    ds.add_new((0x0043, 0x102F), "SS", 0)  # -> 'M'
    # Remove ImageType if implicitly present
    path = _write_dataset(ds, tmp_path / "ge2.dcm")
    result = load_dicom(path)
    assert result["ImageType"] == ["M"]


def test_load_dicom_siemens_xa_phase_encoding(tmp_path):
    ds = _make_base_dataset()
    ds.add_new((0x0021, 0x111C), "IS", "1")
    path = _write_dataset(ds, tmp_path / "xa.dcm")
    result = load_dicom(path)
    assert result["PhaseEncodingDirectionPositive"] == 1


def test_load_dicom_philips_asl_trigger_delay(tmp_path):
    # 'TriggerDelayTime' is not a standard DICOM keyword; register a data
    # dictionary entry so the metadata dict exposes it (as Philips scanners do
    # via their private tag), which drives the Philips PostLabelDelay branch.
    from pydicom.datadict import add_dict_entry
    add_dict_entry(0x00181062, "DS", "TriggerDelayTime", "TriggerDelayTime")

    ds = _make_base_dataset()
    ds.Manufacturer = "Philips"
    ds.add_new(0x00181062, "DS", "1800.0")  # TriggerDelayTime
    path = _write_dataset(ds, tmp_path / "phil.dcm")
    result = load_dicom(path)
    assert result["PostLabelDelay"] == pytest.approx(1.8)


def test_load_dicom_asl_type_from_protocol_name(tmp_path):
    ds = _make_base_dataset()
    ds.ImageType = ["ORIGINAL", "PRIMARY", "ASL"]
    ds.ProtocolName = "my_pcasl_scan"
    path = _write_dataset(ds, tmp_path / "asl.dcm")
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PCASL"


def test_load_dicom_asl_type_pasl_name(tmp_path):
    ds = _make_base_dataset()
    ds.SeriesDescription = "ep2d_pasl_run"
    path = _write_dataset(ds, tmp_path / "pasl.dcm")
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PASL"


def test_load_dicom_asl_type_casl_name(tmp_path):
    ds = _make_base_dataset()
    ds.SeriesDescription = "some_casl_thing"
    path = _write_dataset(ds, tmp_path / "casl.dcm")
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "CASL"


def test_load_dicom_labeling_duration_from_tag_duration(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "ld.dcm")
    # Inject TagDuration via CSA metadata
    monkeypatch.setattr(dio, "_extract_csa_metadata", lambda ds: {"TagDuration": 1.5})
    result = load_dicom(path)
    assert result["LabelingDuration"] == 1.5


def test_load_dicom_labeling_duration_from_rf_blocks(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "ld2.dcm")
    monkeypatch.setattr(dio, "_extract_csa_metadata", lambda ds: {"NumRFBlocks": 20, "RFGap": 0.001})
    result = load_dicom(path)
    assert result["LabelingDuration"] == pytest.approx(0.02)


def test_load_dicom_pasl_bolus_labeling_duration(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    ds.SeriesDescription = "pasl_scan"
    path = _write_dataset(ds, tmp_path / "pasl2.dcm")
    monkeypatch.setattr(dio, "_extract_csa_metadata", lambda ds: {"BolusDuration": 0.7, "InversionTime": 1.8})
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PASL"
    assert result["LabelingDuration"] == 0.7


# --------------------------------------------------------------------------
# load_dicom - Siemens ASCCONV branches
# --------------------------------------------------------------------------

def test_load_dicom_ascconv_coil_and_accel(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "scan.dcm")
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {
        "ucCoilCombineMode": 2,
        "sPat": {"lAccelFactPE": 3},
    })
    result = load_dicom(path)
    assert result["CoilCombinationMethod"] == "Adaptive Combine"
    assert result["AccelerationFactorPE"] == 3


def test_load_dicom_ascconv_coil_unknown_mode(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "sie2.dcm")
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {"ucCoilCombineMode": 9})
    result = load_dicom(path)
    assert result["CoilCombinationMethod"] == "Unknown (9)"


def test_load_dicom_ascconv_product_pcasl(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "pcasl.dcm")
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {
        "sAsl": {"ulMode": 1},
        "tSequenceFileName": "%SiemensSeq%\\ep2d_pcasl",
        "sWipMemBlock": {"adFree": [0.0, 60.0, 1800000.0]},
    })
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PCASL"
    assert result["LabelOffset"] == 60.0
    assert result["PostLabelDelay"] == pytest.approx(1.8)
    assert result["PulseSequenceDetails"] == "%SiemensSeq%\\ep2d_pcasl"


def test_load_dicom_ascconv_pasl(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "asclpasl.dcm")
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {
        "sAsl": {"ulMode": 2},
        "tSequenceFileName": "%SiemensSeq%\\ep2d_pasl",
        "alTI": [700000.0, 0.0, 1800000.0],
    })
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PASL"
    assert result["BolusDuration"] == pytest.approx(0.7)
    assert result["InversionTime"] == pytest.approx(1.8)


def test_load_dicom_ascconv_vessel_encoded_2d(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "vepcasl.dcm")
    alFree = [0] * 32
    alFree[4] = 25.0        # flip angle
    alFree[5] = 500.0       # duration us
    alFree[6] = 100.0       # separation us
    alFree[10] = 4000.0     # t1opt ms
    alFree[11] = 1000.0     # PLD ms
    alFree[12] = 1500.0     # PLD ms
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {
        "sAsl": {"ulMode": 2},
        "tSequenceFileName": "%CustomerSeq%\\to_ep2d_VEPCASL",
        "sWipMemBlock": {"alFree": alFree},
    })
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PCASL"
    assert result["TagRFFlipAngle"] == 25.0
    assert result["TagRFDuration"] == pytest.approx(0.0005)
    assert result["TagRFSeparation"] == pytest.approx(0.0001)
    assert result["MaximumT1Opt"] == pytest.approx(4.0)
    assert result["InitialPostLabelDelay"] == pytest.approx([1.0, 1.5])


def test_load_dicom_ascconv_vessel_encoded_3d(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "vepcasl3d.dcm")
    alFree = [0] * 40
    alFree[6] = 30.0
    alFree[7] = 600.0
    alFree[8] = 120.0
    alFree[9] = 3500.0
    alFree[30] = 900.0
    alFree[31] = 1400.0
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {
        "tSequenceFileName": "%CustomerSeq%\\jw_tgse_VEPCASL",
        "sWipMemBlock": {"alFree": alFree},
    })
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PCASL"
    assert result["TagRFFlipAngle"] == 30.0
    assert result["InitialPostLabelDelay"] == pytest.approx([0.9, 1.4])


def test_load_dicom_ascconv_lrepetitions(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "reps.dcm")
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {"lRepetitions": 17})
    result = load_dicom(path)
    assert result["NumberOfTemporalPositions"] == 18


def test_load_dicom_ge_image_type_scalar(tmp_path):
    # ImageType present as a scalar string exercises the non-list concat branch.
    ds = _make_base_dataset()
    ds.ImageType = "DERIVED"
    ds.add_new((0x0043, 0x102F), "SS", 2)  # -> 'REAL'
    path = _write_dataset(ds, tmp_path / "ge_scalar.dcm")
    result = load_dicom(path)
    assert result["ImageType"] == ["DERIVED", "REAL"]


def test_load_dicom_xa_pe_non_numeric(tmp_path):
    # Non-integer XA PE value hits the ValueError/TypeError branch and does not
    # set PhaseEncodingDirectionPositive.
    ds = _make_base_dataset()
    ds.add_new((0x0021, 0x111C), "SH", "notanumber")
    path = _write_dataset(ds, tmp_path / "xa_bad.dcm")
    result = load_dicom(path)
    assert "PhaseEncodingDirectionPositive" not in result


def test_load_dicom_image_type_scalar_perfusion(tmp_path):
    # Single-valued ImageType is a scalar string; exercises the scalar
    # image_type_str branch and ASL scan inference.
    ds = _make_base_dataset()
    ds.ImageType = "PERFUSION"
    path = _write_dataset(ds, tmp_path / "perf.dcm")
    result = load_dicom(path)
    assert result["ImageType"] == "PERFUSION"


def test_load_dicom_asl_pcasl_params_and_asl_scan(tmp_path, monkeypatch):
    # has_pcasl_params True + ASL scan -> PCASL (no name hints).
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    ds.ImageType = ["ORIGINAL", "ASL"]
    path = _write_dataset(ds, tmp_path / "pcasl_param.dcm")
    monkeypatch.setattr(dio, "_extract_csa_metadata", lambda ds: {"RFGap": 0.001})
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PCASL"


def test_load_dicom_asl_pasl_params_and_asl_scan(tmp_path, monkeypatch):
    # has_pasl_params True + ASL scan -> PASL (no name hints).
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    ds.ImageType = ["ORIGINAL", "PERFUSION"]
    path = _write_dataset(ds, tmp_path / "pasl_param.dcm")
    monkeypatch.setattr(dio, "_extract_csa_metadata",
                        lambda ds: {"BolusDuration": 0.7, "InversionTime": 1.8})
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PASL"


def test_load_dicom_iop_wrong_length(tmp_path):
    # ImageOrientationPatient with unexpected length -> AcquisitionPlane Unknown.
    ds = _make_base_dataset()
    ds.add_new((0x0020, 0x0037), "DS", ["1", "0", "0"])  # only 3 values
    path = _write_dataset(ds, tmp_path / "iop_bad.dcm")
    result = load_dicom(path)
    assert result["AcquisitionPlane"] == "Unknown"


def test_load_dicom_element_count_uncombined_enhanced(tmp_path):
    # Enhanced DICOM with a single coil element -> Uncombined via element count.
    ds = _make_base_dataset()
    ds.SeriesDescription = "Enhanced"
    coil = Dataset()
    coil.ReceiveCoilName = "H"
    e1 = Dataset(); e1.MultiCoilElementName = "H1"
    coil.MultiCoilDefinitionSequence = Sequence([e1])
    shared = Dataset()
    shared.MRReceiveCoilSequence = Sequence([coil])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])
    frame = Dataset()
    frame.InstanceNumber = "1"
    ds.PerFrameFunctionalGroupsSequence = Sequence([frame])
    path = _write_dataset(ds, tmp_path / "enh_single.dcm")
    result = load_dicom(path)
    assert all(r["CoilType"] == "Uncombined" for r in result)


def test_load_dicom_element_count_zero_no_cointype(tmp_path):
    # Enhanced DICOM whose coil definition sequence is empty gives an element
    # count of 0 -> is_combined_coil_from_element_count returns None -> no
    # CoilType is set (line 709).
    ds = _make_base_dataset()
    ds.SeriesDescription = "Enhanced"
    coil = Dataset()
    coil.ReceiveCoilName = "H"
    coil.MultiCoilDefinitionSequence = Sequence([])  # zero elements
    shared = Dataset()
    shared.MRReceiveCoilSequence = Sequence([coil])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])
    frame = Dataset()
    frame.InstanceNumber = "1"
    ds.PerFrameFunctionalGroupsSequence = Sequence([frame])
    path = _write_dataset(ds, tmp_path / "enh_zero.dcm")
    result = load_dicom(path)
    assert all("CoilType" not in r for r in result)


def test_load_dicom_philips_trigger_non_numeric(tmp_path):
    # Non-numeric TriggerDelayTime hits the Philips ValueError/TypeError branch.
    ds = _make_base_dataset()
    ds.Manufacturer = "Philips"
    path = _write_dataset(ds, tmp_path / "phil_bad.dcm")

    real = dio._get_metadata_value

    def fake(metadata, key, default=None):
        if key == "TriggerDelayTime":
            return "notnum"
        return real(metadata, key, default)

    dio._get_metadata_value = fake
    try:
        result = load_dicom(path)
    finally:
        dio._get_metadata_value = real
    assert "PostLabelDelay" not in result


def test_load_dicom_iop_non_numeric_values(tmp_path):
    # ImageOrientationPatient with 6 non-numeric values raises inside the
    # AcquisitionPlane calculation -> Unknown (lines 1054-1056).
    ds = _make_base_dataset()
    ds.add_new((0x0020, 0x0037), "DS", ["1", "0", "0", "0", "1", "0"])
    path = _write_dataset(ds, tmp_path / "iop_ok.dcm")

    # Patch _get_metadata_value used inside load_dicom so IOP returns junk that
    # cannot be converted to float, exercising the except branch.
    real = dio._get_metadata_value

    def fake(metadata, key, default=None):
        if key == "ImageOrientationPatient":
            return ("a", "b", "c", "d", "e", "f")
        return real(metadata, key, default)

    orig = dio._get_metadata_value
    dio._get_metadata_value = fake
    try:
        result = load_dicom(path)
    finally:
        dio._get_metadata_value = orig
    assert result["AcquisitionPlane"] == "Unknown"


def test_load_dicom_ascconv_pcasl_bad_adfree(tmp_path, monkeypatch):
    # Non-numeric adFree values exercise the ValueError/TypeError except branches.
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "pcasl_bad.dcm")
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {
        "sAsl": {"ulMode": 1},
        "tSequenceFileName": "%SiemensSeq%\\ep2d_pcasl",
        "sWipMemBlock": {"adFree": ["x", "y", "z"]},
    })
    result = load_dicom(path)
    # ASL type still set; bad values silently skipped
    assert result["ArterialSpinLabelingType"] == "PCASL"
    assert "LabelOffset" not in result


def test_load_dicom_ascconv_pasl_bad_alti(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "pasl_bad.dcm")
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {
        "sAsl": {"ulMode": 2},
        "tSequenceFileName": "%SiemensSeq%\\ep2d_pasl",
        "alTI": ["bad", 0.0, "worse"],
    })
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PASL"
    assert "BolusDuration" not in result


def test_load_dicom_ascconv_vepcasl_bad_values(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "vep_bad.dcm")
    alFree = ["a"] * 32  # all non-numeric
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {
        "tSequenceFileName": "%CustomerSeq%\\to_ep2d_VEPCASL",
        "sWipMemBlock": {"alFree": alFree},
    })
    result = load_dicom(path)
    assert result["ArterialSpinLabelingType"] == "PCASL"
    assert "TagRFFlipAngle" not in result


def test_load_dicom_ascconv_lrepetitions_bad(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "reps_bad.dcm")
    monkeypatch.setattr(dio, "_extract_ascconv", lambda ds: {"lRepetitions": "notint"})
    result = load_dicom(path)
    assert "NumberOfTemporalPositions" not in result


def test_load_dicom_labeling_duration_bad_rf(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "ld_bad.dcm")
    monkeypatch.setattr(dio, "_extract_csa_metadata",
                        lambda ds: {"NumRFBlocks": "x", "RFGap": "y"})
    result = load_dicom(path)
    assert "LabelingDuration" not in result


# --------------------------------------------------------------------------
# _load_one_dicom_path / _load_one_dicom_bytes
# --------------------------------------------------------------------------

def test_load_one_dicom_path(tmp_path):
    ds = _make_base_dataset()
    ds.InstanceNumber = "5"
    path = _write_dataset(ds, tmp_path / "one.dcm")
    result = _load_one_dicom_path(path, skip_pixel_data=True)
    assert result["DICOM_Path"] == path
    assert result["InstanceNumber"] == 5


def test_load_one_dicom_path_missing_modality(tmp_path):
    ds = _make_base_dataset()
    del ds.Modality
    path = _write_dataset(ds, tmp_path / "nomod.dcm")
    with pytest.raises(ValueError, match="Modality"):
        _load_one_dicom_path(path, skip_pixel_data=True)


def test_load_one_dicom_bytes(tmp_path):
    ds = _make_base_dataset()
    ds.InstanceNumber = "9"
    path = _write_dataset(ds, tmp_path / "b.dcm")
    with open(path, "rb") as f:
        content = f.read()
    result = _load_one_dicom_bytes("key1", content, skip_pixel_data=True)
    assert result["DICOM_Path"] == "key1"
    assert result["InstanceNumber"] == 9


def test_load_one_dicom_bytes_missing_modality(tmp_path):
    ds = _make_base_dataset()
    del ds.Modality
    path = _write_dataset(ds, tmp_path / "nomodb.dcm")
    with open(path, "rb") as f:
        content = f.read()
    with pytest.raises(ValueError, match="Modality"):
        _load_one_dicom_bytes("k", content, skip_pixel_data=True)


def test_load_one_dicom_path_enhanced(tmp_path):
    ds = _make_enhanced_dataset()
    path = _write_dataset(ds, tmp_path / "enh_path.dcm")
    result = _load_one_dicom_path(path, skip_pixel_data=True)
    assert isinstance(result, list)
    for item in result:
        assert item["DICOM_Path"] == path


def test_load_one_dicom_bytes_enhanced(tmp_path):
    ds = _make_enhanced_dataset()
    path = _write_dataset(ds, tmp_path / "enh_bytes.dcm")
    with open(path, "rb") as f:
        content = f.read()
    result = _load_one_dicom_bytes("ek", content, skip_pixel_data=True)
    assert isinstance(result, list)
    for item in result:
        assert item["DICOM_Path"] == "ek"


def test_load_dicom_csa_non_dict_warns(tmp_path, monkeypatch):
    # CSA metadata returned as a non-dict truthy value triggers a warning and is
    # not merged (line 645).
    ds = _make_base_dataset()
    ds.Manufacturer = "SIEMENS"
    path = _write_dataset(ds, tmp_path / "csa_bad.dcm")
    monkeypatch.setattr(dio, "_extract_csa_metadata", lambda ds: ["not", "a", "dict"])
    result = load_dicom(path)
    assert result["PatientName"] == "Test^Patient"


def test_load_dicom_inferred_non_dict_warns(tmp_path, monkeypatch):
    ds = _make_base_dataset()
    path = _write_dataset(ds, tmp_path / "inf_bad.dcm")
    monkeypatch.setattr(dio, "_extract_inferred_metadata", lambda ds: ["bad"])
    result = load_dicom(path)
    assert result["PatientName"] == "Test^Patient"


# --------------------------------------------------------------------------
# Session loaders
# --------------------------------------------------------------------------

def test_load_dicom_session_from_dir(tmp_path):
    for i in range(3):
        ds = _make_base_dataset()
        ds.InstanceNumber = str(i + 1)
        ds.SeriesDescription = "T1w"
        _write_dataset(ds, tmp_path / f"f{i}.dcm")
    df = load_dicom_session(session_dir=str(tmp_path))
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3


def test_load_dicom_session_from_bytes(tmp_path):
    ds = _make_base_dataset()
    ds.SeriesDescription = "T1w"
    path = _write_dataset(ds, tmp_path / "x.dcm")
    with open(path, "rb") as f:
        content = f.read()
    df = load_dicom_session(dicom_bytes={"x.dcm": content})
    assert len(df) == 1


def test_async_load_dicom_session_parallel(tmp_path):
    for i in range(2):
        ds = _make_base_dataset()
        ds.InstanceNumber = str(i + 1)
        _write_dataset(ds, tmp_path / f"p{i}.dcm")
    df = asyncio.run(async_load_dicom_session(session_dir=str(tmp_path), parallel_workers=2))
    assert len(df) == 2


def test_async_load_dicom_session_requires_source():
    with pytest.raises(ValueError, match="Either session_dir or dicom_bytes"):
        asyncio.run(async_load_dicom_session())


def test_load_dicom_session_enhanced_flatten(tmp_path):
    # Enhanced DICOM files return lists of frame dicts, which the session loader
    # must flatten into individual rows (line 1272).
    ds = _make_enhanced_dataset()
    _write_dataset(ds, tmp_path / "enh_session.dcm")
    df = load_dicom_session(session_dir=str(tmp_path))
    # Two frames -> two rows
    assert len(df) == 2


def test_load_dicom_session_show_progress(tmp_path):
    ds = _make_base_dataset()
    _write_dataset(ds, tmp_path / "prog.dcm")
    df = load_dicom_session(session_dir=str(tmp_path), show_progress=True)
    assert len(df) == 1


# --------------------------------------------------------------------------
# load_nifti_session
# --------------------------------------------------------------------------

def _write_nifti(path, shape=(2, 2, 2)):
    import nibabel as nib
    data = np.zeros(shape, dtype=np.int16)
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(path))


def test_load_nifti_session_basic(tmp_path):
    nii = tmp_path / "sub-01_task-rest_bold.nii"
    _write_nifti(nii)
    df = load_nifti_session(session_dir=str(tmp_path), acquisition_fields=None)
    assert "NIfTI_Path" in df.columns
    # BIDS tag extraction
    vals = df.reset_index(drop=True).iloc[0].to_dict()
    assert vals["sub"] == "01"
    assert vals["suffix"] == "bold"


def test_load_nifti_session_with_json(tmp_path):
    nii = tmp_path / "sub-02_T1w.nii"
    _write_nifti(nii)
    json_path = tmp_path / "sub-02_T1w.json"
    json_path.write_text('{"EchoTime": 0.003}')
    df = load_nifti_session(session_dir=str(tmp_path), acquisition_fields=None)
    row = df.reset_index(drop=True).iloc[0].to_dict()
    assert row["EchoTime"] == 0.003
    assert row["JSON_Path"] == str(json_path)


def test_load_nifti_session_4d(tmp_path):
    nii = tmp_path / "sub-03_bold.nii"
    _write_nifti(nii, shape=(2, 2, 2, 3))
    df = load_nifti_session(session_dir=str(tmp_path), acquisition_fields=None)
    # 4D -> one row per volume
    assert len(df) == 3
    vol_indices = sorted(df["Volume_Index"].tolist())
    assert vol_indices == [0, 1, 2]


def test_load_nifti_session_no_files_raises(tmp_path):
    with pytest.raises(ValueError, match="No NIfTI files found"):
        load_nifti_session(session_dir=str(tmp_path))


def test_load_nifti_session_unavailable_acq_field(tmp_path):
    nii = tmp_path / "plain.nii"
    _write_nifti(nii)
    # acquisition field doesn't exist as a column -> no grouping, no error
    df = load_nifti_session(session_dir=str(tmp_path), acquisition_fields=["NotAColumn"])
    assert len(df) == 1


def test_load_nifti_session_groupby(tmp_path):
    # Two files with a shared BIDS 'sub' key exercise the groupby branch.
    _write_nifti(tmp_path / "sub-01_T1w.nii")
    _write_nifti(tmp_path / "sub-02_T1w.nii")
    df = load_nifti_session(session_dir=str(tmp_path), acquisition_fields=["sub"])
    assert len(df) == 2


def test_load_nifti_session_show_progress(tmp_path):
    _write_nifti(tmp_path / "sub-01_T1w.nii")
    df = load_nifti_session(session_dir=str(tmp_path), acquisition_fields=None,
                            show_progress=True)
    assert len(df) == 1
