import pytest
import json
import os
import pandas as pd
from pathlib import Path
import tempfile

from dicompare.compliance import (
    check_session_compliance_with_json_reference,
    check_session_compliance_with_python_module
)
from dicompare.io import load_json_session, load_python_session
from dicompare.validation import BaseValidationModel

# -------------------- Dummy Model for Python Module Compliance --------------------
class DummyValidationModel(BaseValidationModel):
    def validate(self, data: pd.DataFrame):
        if "fail" in data.columns and data["fail"].iloc[0]:
            return (
                False,
                [{'field': 'fail', 'value': data['fail'].iloc[0], 'expected': False, 'message': 'should be False', 'rule_name': 'dummy_rule'}],
                []
            )
        return (
            True,
            [],
            [{'field': 'dummy', 'value': 'ok', 'expected': 'ok', 'message': 'passed', 'rule_name': 'dummy_rule'}]
        )

# -------------------- Fixtures --------------------
@pytest.fixture
def dummy_in_session():
    data = {
        "Acquisition": ["acq1", "acq1", "acq2"],
        "Age": [30, 30, 25],
        "Name": ["John Doe", "John Doe", "Jane Smith"],
        "SeriesDescription": ["SeriesA", "SeriesA", "SeriesB"],
        "SeriesNumber": [1, 1, 2],
    }
    return pd.DataFrame(data)

@pytest.fixture
def dummy_ref_session_pass():
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "Age", "value": 30, "tolerance": 5},
                    {"field": "Name", "value": "John Doe"}
                ],
                "series": [
                    {"name": "SeriesA", "fields": [{"field": "Name", "value": "John Doe"}]}
                ]
            }
        }
    }
    return ref_session

@pytest.fixture
def dummy_ref_session_fail():
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "Weight", "value": 70}
                ],
                "series": [
                    {"name": "SeriesA", "fields": [{"field": "Name", "value": "John Doe"}]}
                ]
            },
            "ref2": {
                "fields": [
                    {"field": "Age", "value": 40, "tolerance": 2}
                ],
                "series": [
                    {"name": "SeriesB", "fields": [{"field": "Name", "value": "Jane Smith"}]}
                ]
            }
        }
    }
    return ref_session

@pytest.fixture
def dummy_session_map_pass():
    return {"ref1": "acq1"}

@pytest.fixture
def dummy_session_map_fail():
    return {"ref1": "acq1"}

@pytest.fixture
def dummy_ref_models():
    return {"ref1": DummyValidationModel, "ref2": DummyValidationModel}

# -------------------- Tests for JSON Reference Compliance --------------------

def test_check_session_compliance_with_json_reference_pass(dummy_in_session, dummy_ref_session_pass, dummy_session_map_pass):
    compliance = check_session_compliance_with_json_reference(
        dummy_in_session, dummy_ref_session_pass, dummy_session_map_pass
    )
    assert all(record["passed"] for record in compliance)


def test_check_session_compliance_with_json_reference_missing_and_unmapped(dummy_in_session, dummy_ref_session_fail, dummy_session_map_fail):
    compliance = check_session_compliance_with_json_reference(
        dummy_in_session, dummy_ref_session_fail, dummy_session_map_fail
    )
    messages = [rec.get("message", "") for rec in compliance]
    assert any("Field not found in input session" in msg for msg in messages)
    assert any("not mapped" in msg for msg in messages)


def test_check_session_compliance_with_json_reference_series_fail(dummy_in_session):
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [],
                "series": [
                    {"name": "SeriesA", "fields": [{"field": "Name", "value": "Nonexistent"}]}]
            }
        }
    }
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_reference(dummy_in_session, ref_session, session_map)
    assert any(rec.get("series") is not None and "not found" in rec.get("message", "") for rec in compliance)

# -------------------- Tests for Python Module Compliance --------------------

def test_check_session_compliance_with_python_module_pass(dummy_in_session, dummy_ref_models):
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_python_module(
        dummy_in_session, dummy_ref_models, session_map, raise_errors=False
    )
    assert any(r["passed"] for r in compliance)


def test_check_session_compliance_with_python_module_fail(dummy_in_session, dummy_ref_models):
    df = dummy_in_session.copy()
    df.loc[df["Acquisition"] == "acq1", "fail"] = True
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_python_module(df, dummy_ref_models, session_map, raise_errors=False)
    assert any(not r["passed"] for r in compliance)


def test_check_session_compliance_with_python_module_empty_acquisition(dummy_in_session, dummy_ref_models):
    session_map = {"ref1": "nonexistent"}
    compliance = check_session_compliance_with_python_module(
        dummy_in_session, dummy_ref_models, session_map, raise_errors=False
    )
    assert any("Acquisition-Level Error" in str(r.get("field", "")) for r in compliance)


def test_check_session_compliance_with_python_module_raise_error(dummy_in_session, dummy_ref_models):
    df = dummy_in_session.copy()
    df.loc[df["Acquisition"] == "acq1", "fail"] = True
    session_map = {"ref1": "acq1"}
    with pytest.raises(ValueError, match="Validation failed for acquisition 'acq1'"):
        check_session_compliance_with_python_module(df, dummy_ref_models, session_map, raise_errors=True)

# -------------------- Tests for JSON and Python Session Loaders --------------------

def test_load_json_session_and_fields(tmp_path):
    ref = {
        "acquisitions": {
            "test_acq": {
                "fields": [
                    {"field": "F1", "value": [1,2], "tolerance": 0.5}
                ],
                "series": [
                    {"name": "S1", "fields": [{"field": "F1", "value": 1}]}
                ]
            }
        }
    }
    file = tmp_path / "ref.json"
    file.write_text(json.dumps(ref))

    fields, data = load_json_session(str(file))
    assert "F1" in fields
    assert "test_acq" in data["acquisitions"]


def test_load_python_session_qsm_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "ref_qsm.py"
    models = load_python_session(str(fixture_path))
    assert "QSM" in models
    assert issubclass(models["QSM"], BaseValidationModel)

# -------------------- Tests for QSM Compliance --------------------

def create_base_qsm_df_over_echos(echos, count=5, mra_type="3D", tr=700, b0=3.0, flip=55, pix_sp=(0.5,0.5), slice_th=0.5, bw=200):
    rows = []
    for te in echos:
        for img in ("M", "P"):
            rows.append({
                "Acquisition": "acq1",
                "EchoTime": te,
                "ImageType": img,
                "Count": count,
                "MRAcquisitionType": mra_type,
                "RepetitionTime": tr,
                "MagneticFieldStrength": b0,
                "FlipAngle": flip,
                "PixelSpacing": pix_sp,
                "SliceThickness": slice_th,
                "PixelBandwidth": bw
            })
    return pd.DataFrame(rows)


def test_qsm_compliance_pass():
    fixture_path = Path(__file__).parent / "fixtures" / "ref_qsm.py"
    models = load_python_session(str(fixture_path))
    QSM_cls = models["QSM"]
    df = create_base_qsm_df_over_echos([10, 20, 30])
    compliance = check_session_compliance_with_python_module(
        df, {"QSM": QSM_cls}, {"QSM": "acq1"}, raise_errors=False
    )
    # all validators should pass
    assert all(rec["passed"] for rec in compliance)


def test_qsm_compliance_failure_pixel_bandwidth():
    fixture_path = Path(__file__).parent / "fixtures" / "ref_qsm.py"
    models = load_python_session(str(fixture_path))
    QSM_cls = models["QSM"]
    # set bandwidth above acceptable threshold for 3T
    df = create_base_qsm_df_over_echos([10, 20, 30], bw=300)
    compliance = check_session_compliance_with_python_module(
        df, {"QSM": QSM_cls}, {"QSM": "acq1"}, raise_errors=False
    )
    # at least one validator should fail
    assert any(not rec["passed"] for rec in compliance)
    # confirm PixelBandwidth validator triggered via message content
    assert any(
        "PixelBandwidth" in str(rec.get("message", ""))
        or (isinstance(rec.get("expected"), str) and "PixelBandwidth" in rec.get("expected"))
        for rec in compliance
    )
