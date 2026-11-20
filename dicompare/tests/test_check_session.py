"""
Tests for ``dicompare.check_session`` and the exit status of ``dicompare check``.
"""

import copy
import json
import sys

import pandas as pd
import pytest

from dicompare import (
    build_schema, check_session, load_dicom_session, load_schema, map_session, save_report, save_schema,
)
from dicompare.check import mapping_confidence
from dicompare.examples import write_multisite_example
from dicompare.cli.main import main
from dicompare.tests.test_dicom_factory import create_test_dicom_series


@pytest.fixture
def dicom_dir(tmp_path):
    """A directory with a single simple DICOM acquisition."""
    d = tmp_path / "dicoms"
    d.mkdir()
    create_test_dicom_series(
        str(d),
        acquisition_name="T1_MPRAGE",
        num_slices=3,
        metadata_base={
            'ProtocolName': 'T1_MPRAGE',
            'RepetitionTime': 2000.0,
            'EchoTime': 3.0,
            'FlipAngle': 9.0,
            'SliceThickness': 1.0,
        },
    )
    return d


@pytest.fixture
def self_schema(tmp_path, dicom_dir, monkeypatch):
    """A schema built from ``dicom_dir`` so it matches exactly."""
    schema_path = tmp_path / "schema.json"
    _run(["build", str(dicom_dir), str(schema_path)], monkeypatch)
    return schema_path


def _run(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dicompare"] + argv)
    return main()


def _write_schema(tmp_path, schema, name):
    path = tmp_path / name
    path.write_text(json.dumps(schema))
    return path


def _mismatched_schema(self_schema):
    schema = json.loads(self_schema.read_text())
    for acq in schema["acquisitions"].values():
        for f in acq["fields"]:
            if f["field"] == "EchoTime":
                f["value"] = 999.0
    return schema


def _schema_with_extra_acquisition(self_schema):
    schema = json.loads(self_schema.read_text())
    (first_acq,) = schema["acquisitions"].values()
    schema["acquisitions"]["ExtraUnmappedAcq"] = copy.deepcopy(first_acq)
    return schema


# --------------------------------------------------------------------------- #
# check_session                                                               #
# --------------------------------------------------------------------------- #

def test_check_session_paths_compliant(dicom_dir, self_schema):
    results = check_session(dicom_dir, self_schema)

    assert isinstance(results, pd.DataFrame)
    assert len(results) > 0
    assert list(results.columns[:4]) == [
        "reference_acquisition", "input_acquisition", "mapping_cost", "mapping_confidence",
    ]
    assert (results["status"] == "ok").all()
    assert results["passed"].tolist() == [True] * len(results)
    assert (results["mapping_cost"] == 0).all()
    assert (results["mapping_confidence"] == "exact").all()
    (ref_name,) = json.loads(self_schema.read_text())["acquisitions"]
    assert (results["reference_acquisition"] == ref_name).all()
    assert results["input_acquisition"].notna().all()


def test_check_session_dataframe_and_dict(dicom_dir, self_schema):
    session_df = load_dicom_session(session_dir=str(dicom_dir))
    schema = json.loads(self_schema.read_text())

    from_objects = check_session(session_df, schema)
    from_paths = check_session(str(dicom_dir), str(self_schema))

    assert len(from_objects) == len(from_paths)
    assert (from_objects["status"] == "ok").all()


def test_check_session_reports_failures(dicom_dir, self_schema):
    results = check_session(dicom_dir, _mismatched_schema(self_schema))

    failed = results[results["status"] == "error"]
    assert list(failed["field"]) == ["EchoTime"]
    assert failed["passed"].tolist() == [False]
    # passed is a bool column, so ~ selects everything that did not pass
    assert results[~results["passed"]].equals(failed)
    # The mismatch also makes the mapping less certain
    assert (results["mapping_cost"] > 0).all()
    assert (results["mapping_confidence"] != "exact").all()


def test_check_session_unmapped_reference_row(dicom_dir, self_schema):
    results = check_session(dicom_dir, _schema_with_extra_acquisition(self_schema))

    unmapped = results[results["status"] == "unmapped"]
    assert len(unmapped) == 1
    row = unmapped.iloc[0]
    assert row["input_acquisition"] is None
    assert row["mapping_cost"] is None
    assert row["mapping_confidence"] is None
    assert not row["passed"]
    # The other reference acquisition is still checked
    assert (results.loc[results["status"] != "unmapped", "status"] == "ok").all()


def test_check_session_explicit_mapping(dicom_dir, self_schema):
    schema = _schema_with_extra_acquisition(self_schema)
    session_df = load_dicom_session(session_dir=str(dicom_dir))
    auto = check_session(session_df, schema)
    auto_ref = auto.loc[auto["status"] != "unmapped", "reference_acquisition"].iloc[0]
    input_acq = auto.loc[auto["status"] != "unmapped", "input_acquisition"].iloc[0]
    other_ref = next(name for name in schema["acquisitions"] if name != auto_ref)

    # Swap the input acquisition onto the other reference acquisition
    results = check_session(session_df, schema, mapping={other_ref: input_acq})
    assert set(results.loc[results["status"] == "unmapped", "reference_acquisition"]) == {auto_ref}
    mapped = results[results["status"] != "unmapped"]
    assert (mapped["reference_acquisition"] == other_ref).all()
    assert (mapped["input_acquisition"] == input_acq).all()

    # An empty mapping leaves everything unmapped
    empty = check_session(session_df, schema, mapping={})
    assert (empty["status"] == "unmapped").all()
    assert len(empty) == len(schema["acquisitions"])


def test_check_session_rejects_unknown_mapping_names(dicom_dir, self_schema):
    schema = json.loads(self_schema.read_text())
    (ref_name,) = schema["acquisitions"]
    with pytest.raises(ValueError, match="not in the schema"):
        check_session(dicom_dir, schema, mapping={"NoSuchRef": "anything"})
    with pytest.raises(ValueError, match="not in the session"):
        check_session(dicom_dir, schema, mapping={ref_name: "NoSuchInput"})


@pytest.mark.parametrize("cost,label", [
    (0.0, "exact"), (2.0, "high"), (5.0, "medium"), (19.9, "medium"), (20.0, "low"),
])
def test_mapping_confidence(cost, label):
    assert mapping_confidence(cost) == label


# --------------------------------------------------------------------------- #
# map_session, save_report, save_schema                                       #
# --------------------------------------------------------------------------- #

def test_map_session_matches_check_session(dicom_dir, self_schema):
    schema = _schema_with_extra_acquisition(self_schema)
    mapping = map_session(dicom_dir, schema)

    assert list(mapping.columns) == [
        "reference_acquisition", "input_acquisition", "mapping_cost", "mapping_confidence",
    ]
    assert list(mapping["reference_acquisition"]) == list(schema["acquisitions"])
    assert mapping["input_acquisition"].isna().sum() == 1
    mapped = mapping.dropna(subset=["input_acquisition"])
    assert list(mapped["mapping_confidence"]) == ["exact"]

    results = check_session(dicom_dir, schema)
    from_results = (results[["reference_acquisition", "input_acquisition"]]
                    .drop_duplicates().set_index("reference_acquisition")["input_acquisition"])
    assert mapping.set_index("reference_acquisition")["input_acquisition"].equals(from_results)


def test_map_session_with_explicit_mapping(dicom_dir, self_schema):
    schema = json.loads(self_schema.read_text())
    assert map_session(dicom_dir, schema, mapping={})["input_acquisition"].isna().all()


def test_save_report_writes_records(tmp_path, dicom_dir, self_schema):
    results = check_session(dicom_dir, _schema_with_extra_acquisition(self_schema))
    path = tmp_path / "report.json"
    save_report(results, path)

    records = json.loads(path.read_text())
    assert len(records) == len(results)
    assert records[0]["reference_acquisition"] == results.iloc[0]["reference_acquisition"]
    assert sum(r["status"] == "unmapped" for r in records) == 1


def test_save_schema_round_trip(tmp_path, dicom_dir):
    schema = build_schema(load_dicom_session(session_dir=str(dicom_dir)))
    path = tmp_path / "schema.json"
    save_schema(schema, str(path))

    _, loaded, _ = load_schema(str(path))  # also validates against the metaschema
    assert list(loaded["acquisitions"]) == list(schema["acquisitions"])
    assert (check_session(dicom_dir, path)["status"] == "ok").all()


# --------------------------------------------------------------------------- #
# write_multisite_example                                                     #
# --------------------------------------------------------------------------- #

def test_multisite_example_has_the_documented_deviations(tmp_path):
    sites = write_multisite_example(tmp_path / "data")
    assert set(sites) == {"site_A", "site_B"}

    schema = build_schema(load_dicom_session(session_dir=str(sites["site_A"])))
    assert (check_session(sites["site_A"], schema)["status"] == "ok").all()

    mapping = map_session(sites["site_B"], schema).set_index("reference_acquisition")
    assert mapping.loc["acq-t1wmpr", "input_acquisition"] == "acq-t1mpragesag"
    assert mapping.loc["acq-qsmmegre", "input_acquisition"] == "acq-greqsm5echo"
    assert mapping.loc["acq-t2wflair", "input_acquisition"] is None

    results = check_session(sites["site_B"], schema)
    failed = results[results["status"] == "error"]
    assert sorted(zip(failed["reference_acquisition"], failed["field"])) == [
        ("acq-qsmmegre", "SliceThickness"),
        ("acq-t1wmpr", "EchoTime"),
        ("acq-t1wmpr", "RepetitionTime"),
        ("acq-t1wmpr", "SliceThickness"),
    ]
    assert list(results.loc[results["status"] == "unmapped", "reference_acquisition"]) == ["acq-t2wflair"]

    # Writing again gives the same files
    before = sorted(p.read_bytes() for p in (tmp_path / "data").rglob("*.dcm"))
    write_multisite_example(tmp_path / "data")
    assert sorted(p.read_bytes() for p in (tmp_path / "data").rglob("*.dcm")) == before


# --------------------------------------------------------------------------- #
# dicompare check: exit status and report                                     #
# --------------------------------------------------------------------------- #

def test_cli_check_exits_zero_when_compliant(monkeypatch, capsys, dicom_dir, self_schema):
    # main() returns normally (status 0) when everything passes
    _run(["check", str(dicom_dir), str(self_schema), "--auto-yes"], monkeypatch)
    assert "All checks passed." in capsys.readouterr().out


def test_cli_check_exits_one_on_failure(monkeypatch, capsys, tmp_path, dicom_dir, self_schema):
    schema_path = _write_schema(tmp_path, _mismatched_schema(self_schema), "mismatch.json")
    with pytest.raises(SystemExit) as exc:
        _run(["check", str(dicom_dir), str(schema_path), "--auto-yes"], monkeypatch)
    assert exc.value.code == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_cli_check_exits_one_when_unmapped(monkeypatch, capsys, tmp_path, dicom_dir, self_schema):
    schema_path = _write_schema(tmp_path, _schema_with_extra_acquisition(self_schema), "extra.json")
    report = tmp_path / "report.json"
    with pytest.raises(SystemExit) as exc:
        _run(["check", str(dicom_dir), str(schema_path), str(report), "--auto-yes"], monkeypatch)
    assert exc.value.code == 1

    # The two reference acquisitions are identical, so either may be left unmapped
    records = json.loads(report.read_text())
    unmapped = [r for r in records if r["status"] == "unmapped"]
    assert len(unmapped) == 1
    assert f"Acquisition unmapped: '{unmapped[0]['reference_acquisition']}'" in capsys.readouterr().out
    assert unmapped[0]["input_acquisition"] is None
    checked = [r for r in records if r["status"] != "unmapped"]
    assert checked
    for r in checked:
        assert r["input_acquisition"]
        assert r["mapping_cost"] == 0
        assert r["mapping_confidence"] == "exact"


def test_cli_check_help_mentions_exit_status(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _run(["check", "--help"], monkeypatch)
    assert "Exit status" in capsys.readouterr().out
