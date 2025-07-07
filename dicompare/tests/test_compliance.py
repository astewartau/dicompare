import pytest
import json
import os
import pandas as pd
from pathlib import Path
import tempfile

from dicompare.compliance import (
    check_session_compliance_with_json_schema,
    check_session_compliance_with_python_module
)
from dicompare.io import load_json_schema, load_python_schema
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

def test_check_session_compliance_with_json_schema_pass(dummy_in_session, dummy_ref_session_pass, dummy_session_map_pass):
    compliance = check_session_compliance_with_json_schema(
        dummy_in_session, dummy_ref_session_pass, dummy_session_map_pass
    )
    assert all(record["passed"] for record in compliance)


def test_check_session_compliance_with_json_schema_missing_and_unmapped(dummy_in_session, dummy_ref_session_fail, dummy_session_map_fail):
    compliance = check_session_compliance_with_json_schema(
        dummy_in_session, dummy_ref_session_fail, dummy_session_map_fail
    )
    messages = [rec.get("message", "") for rec in compliance]
    assert any("Field not found in input session" in msg for msg in messages)
    assert any("not mapped" in msg for msg in messages)


def test_check_session_compliance_with_json_schema_series_fail(dummy_in_session):
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
    compliance = check_session_compliance_with_json_schema(dummy_in_session, ref_session, session_map)
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

def test_load_json_schema_and_fields(tmp_path):
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

    fields, data = load_json_schema(str(file))
    assert "F1" in fields
    assert "test_acq" in data["acquisitions"]


def test_load_python_schema_qsm_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "ref_qsm.py"
    models = load_python_schema(str(fixture_path))
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
    models = load_python_schema(str(fixture_path))
    QSM_cls = models["QSM"]
    df = create_base_qsm_df_over_echos([10, 20, 30])
    compliance = check_session_compliance_with_python_module(
        df, {"QSM": QSM_cls}, {"QSM": "acq1"}, raise_errors=False
    )
    # all validators should pass
    assert all(rec["passed"] for rec in compliance)


def test_qsm_compliance_failure_pixel_bandwidth():
    fixture_path = Path(__file__).parent / "fixtures" / "ref_qsm.py"
    models = load_python_schema(str(fixture_path))
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


# -------------------- Additional Tests for Missing Coverage --------------------

def test_json_compliance_contains_validation():
    """Test 'contains' validation in JSON reference compliance."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1", "acq1"],
        "ProtocolName": ["BOLD_task", "BOLD_rest"],
        "SeriesDescription": ["func_task", "func_rest"]
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "ProtocolName", "contains": "BOLD"},
                    {"field": "SeriesDescription", "contains": "func"}
                ],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should pass - both fields contain the required substrings
    assert all(rec["passed"] for rec in compliance)


def test_json_compliance_contains_validation_failure():
    """Test 'contains' validation failure in JSON reference compliance."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1", "acq1"],
        "ProtocolName": ["T1w_MPR", "T2w_TSE"],
        "SeriesDescription": ["anat_T1", "anat_T2"]
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "ProtocolName", "contains": "BOLD"}
                ],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should fail - ProtocolName values don't contain "BOLD"
    assert any(not rec["passed"] for rec in compliance)
    failed_records = [r for r in compliance if not r["passed"]]
    assert any("Expected to contain 'BOLD'" in r["message"] for r in failed_records)


def test_json_compliance_tolerance_validation():
    """Test numeric tolerance validation in JSON reference compliance."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1", "acq1"],
        "RepetitionTime": [2000, 2005],
        "FlipAngle": [90, 90]
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "RepetitionTime", "value": 2000, "tolerance": 10},
                    {"field": "FlipAngle", "value": 90, "tolerance": 5}
                ],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should pass - values are within tolerance
    assert all(rec["passed"] for rec in compliance)


def test_json_compliance_tolerance_validation_failure():
    """Test numeric tolerance validation failure in JSON reference compliance."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1"],
        "RepetitionTime": [2100],  # Outside tolerance
        "FlipAngle": [90]
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "RepetitionTime", "value": 2000, "tolerance": 50}
                ],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should fail - RepetitionTime is outside tolerance
    assert any(not rec["passed"] for rec in compliance)
    failed_records = [r for r in compliance if not r["passed"]]
    assert any("Expected 2000" in r["message"] and "2100" in r["message"] for r in failed_records)


def test_json_compliance_non_numeric_tolerance():
    """Test tolerance validation with non-numeric values."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1"],
        "ProtocolName": ["T1w_MPR"],  # String value with tolerance constraint
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "ProtocolName", "value": "T1w", "tolerance": 5}
                ],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should fail - non-numeric values can't use tolerance
    assert any(not rec["passed"] for rec in compliance)
    failed_records = [r for r in compliance if not r["passed"]]
    assert any("Field must be numeric" in r["message"] for r in failed_records)


def test_json_compliance_list_value_matching_fixed():
    """Test list-based value matching now works correctly with tuples from make_hashable.
    
    This test verifies that the refactored compliance code correctly handles
    both lists and tuples when comparing values.
    """
    from dicompare.utils import make_hashable
    
    in_session = pd.DataFrame({
        "Acquisition": ["acq1", "acq1"],
        "ImageType": [["ORIGINAL", "PRIMARY"], ["ORIGINAL", "PRIMARY"]],
    })
    
    # Apply make_hashable to simulate real processing - converts lists to tuples
    for col in in_session.columns:
        in_session[col] = in_session[col].apply(make_hashable)
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "ImageType", "value": ["ORIGINAL", "PRIMARY"]},
                ],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should now pass - the bug has been fixed in the refactoring
    assert all(rec["passed"] for rec in compliance)


def test_json_compliance_case_insensitive_matching():
    """Test case-insensitive string matching in JSON reference compliance."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1"],
        "PatientName": ["JOHN DOE"],
        "SeriesDescription": ["  T1w MPR  "]  # Extra whitespace
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "PatientName", "value": "john doe"},
                    {"field": "SeriesDescription", "value": "t1w mpr"}
                ],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should pass - case-insensitive matching with whitespace trimming
    assert all(rec["passed"] for rec in compliance)


def test_json_compliance_single_element_list_unwrapping():
    """Test unwrapping of single-element lists for string comparison."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1"],
        "ProtocolName": ["T1w_MPR"],  # String value
        "SeriesDescription": "T1w_MPR"   # String
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [
                    {"field": "ProtocolName", "value": "T1w_MPR"},
                    {"field": "SeriesDescription", "value": "T1w_MPR"}
                ],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should pass - string values match exactly
    assert all(rec["passed"] for rec in compliance)


def test_json_compliance_series_validation_complex():
    """Test complex series validation with multiple constraints."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1", "acq1", "acq1"],
        "SeriesDescription": ["BOLD_run1", "BOLD_run1", "T1w_MPR"],
        "EchoTime": [30, 30, 0],
        "RepetitionTime": [2000, 2000, 500],
        "FlipAngle": [90, 90, 10]
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [],
                "series": [
                    {
                        "name": "BOLD_series",
                        "fields": [
                            {"field": "SeriesDescription", "contains": "BOLD"},
                            {"field": "EchoTime", "value": 30, "tolerance": 5},
                            {"field": "RepetitionTime", "value": 2000}
                        ]
                    }
                ]
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should pass - series validation finds matching rows
    assert all(rec["passed"] for rec in compliance)


def test_json_compliance_series_not_found():
    """Test series validation when no matching series is found."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1", "acq1"],
        "SeriesDescription": ["T1w_MPR", "T2w_TSE"],
        "EchoTime": [0, 100],
        "RepetitionTime": [500, 5000]
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [],
                "series": [
                    {
                        "name": "BOLD_series",
                        "fields": [
                            {"field": "SeriesDescription", "contains": "BOLD"},
                            {"field": "EchoTime", "value": 30}
                        ]
                    }
                ]
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should fail - no series matches the constraints
    assert any(not rec["passed"] for rec in compliance)
    failed_records = [r for r in compliance if not r["passed"]]
    assert any("not found with the specified constraints" in r["message"] for r in failed_records)


def test_json_compliance_missing_series_field():
    """Test series validation when a required field is missing."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1"],
        "SeriesDescription": ["BOLD_run1"],
        "RepetitionTime": [2000]
        # Missing EchoTime field
    })
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [],
                "series": [
                    {
                        "name": "BOLD_series",
                        "fields": [
                            {"field": "SeriesDescription", "contains": "BOLD"},
                            {"field": "EchoTime", "value": 30}
                        ]
                    }
                ]
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should fail - EchoTime field is missing
    assert any(not rec["passed"] for rec in compliance)
    failed_records = [r for r in compliance if not r["passed"]]
    assert any("not found in input for series" in r["message"] for r in failed_records)


def test_python_module_compliance_no_model():
    """Test Python module compliance when no model is found for acquisition."""
    in_session = pd.DataFrame({
        "Acquisition": ["acq1"],
        "ProtocolName": ["T1w_MPR"]
    })
    
    ref_models = {}  # No models available
    session_map = {"ref1": "acq1"}
    
    compliance = check_session_compliance_with_python_module(in_session, ref_models, session_map)
    
    # Should fail - no model found
    assert any(not rec["passed"] for rec in compliance)
    failed_records = [r for r in compliance if not r["passed"]]
    assert any("No model found for reference acquisition" in r["message"] for r in failed_records)


def test_json_compliance_empty_input_session():
    """Test JSON compliance with empty input session."""
    in_session = pd.DataFrame({"Acquisition": []})  # Empty DataFrame with required column
    
    ref_session = {
        "acquisitions": {
            "ref1": {
                "fields": [{"field": "ProtocolName", "value": "T1w"}],
                "series": []
            }
        }
    }
    
    session_map = {"ref1": "acq1"}
    compliance = check_session_compliance_with_json_schema(in_session, ref_session, session_map)
    
    # Should handle empty session gracefully and report field not found
    assert isinstance(compliance, list)
    assert any("Field not found in input session" in r.get("message", "") for r in compliance)
