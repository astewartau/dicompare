"""
Coverage-focused unit tests for the dicompare CLI.

Targets dicompare/cli/main.py and dicompare/cli/match.py:
    - the argparse ``main()`` dispatcher (build / check / match / no-command / errors)
    - the ``check_command`` output branches (mapping summary confidence levels,
      unmapped acquisitions, verbose vs. summary output, compliant sessions)
    - the ``match_command`` / ``load_schemas_from_paths`` edge cases
      (directories, invalid schemas, non-json paths, no schemas, long names,
      scoring exceptions).

These tests only exercise the CLI; they do not modify source or other tests.
"""

import json
import sys

import pytest
from argparse import Namespace

import dicompare.cli.main as cli_main
from dicompare.cli.main import main, check_command
from dicompare.cli import match as cli_match
from dicompare.cli.match import match_command, load_schemas_from_paths
from dicompare.tests.test_dicom_factory import create_test_dicom_series


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

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
def self_schema(tmp_path, dicom_dir):
    """A schema built from ``dicom_dir`` so it matches exactly."""
    schema_path = tmp_path / "schema.json"
    _run(["build", str(dicom_dir), str(schema_path)])
    return schema_path


def _run(argv, monkeypatch=None):
    """Invoke ``main()`` with a given argv (sys.argv[1:])."""
    full = ["dicompare"] + argv
    if monkeypatch is not None:
        monkeypatch.setattr(sys, "argv", full)
        return main()
    # fall back to direct patching when no monkeypatch is supplied
    old = sys.argv
    sys.argv = full
    try:
        return main()
    finally:
        sys.argv = old


# --------------------------------------------------------------------------- #
# main() dispatcher: argument parsing & errors                                #
# --------------------------------------------------------------------------- #

def test_main_no_command_prints_help_and_exits(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run([], monkeypatch)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_main_help_flag(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(["--help"], monkeypatch)
    # argparse exits 0 on --help
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "build" in out and "check" in out and "match" in out


def test_main_unknown_command_errors(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(["frobnicate"], monkeypatch)
    assert exc.value.code == 2  # argparse invalid choice


def test_build_missing_args_errors(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(["build"], monkeypatch)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "required" in err.lower()


def test_check_missing_args_errors(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(["check", "onlydicoms"], monkeypatch)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "required" in err.lower()


def test_match_missing_dicoms_errors(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(["match", "--library"], monkeypatch)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "required" in err.lower()


def test_match_requires_schemas_or_library(monkeypatch, capsys, dicom_dir):
    with pytest.raises(SystemExit) as exc:
        _run(["match", str(dicom_dir)], monkeypatch)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "schemas" in err.lower() or "library" in err.lower()


# --------------------------------------------------------------------------- #
# main() -> build_command                                                     #
# --------------------------------------------------------------------------- #

def test_main_build_positional(monkeypatch, capsys, dicom_dir, tmp_path):
    schema_path = tmp_path / "out_schema.json"
    _run(["build", str(dicom_dir), str(schema_path)], monkeypatch)
    out = capsys.readouterr().out
    assert "JSON schema saved to" in out
    assert schema_path.exists()
    data = json.loads(schema_path.read_text())
    assert "acquisitions" in data


def test_main_build_named_args(monkeypatch, capsys, dicom_dir, tmp_path):
    schema_path = tmp_path / "named_schema.json"
    _run(
        ["build", "--dicoms", str(dicom_dir), "--schema", str(schema_path)],
        monkeypatch,
    )
    assert schema_path.exists()


# --------------------------------------------------------------------------- #
# main() -> check_command                                                     #
# --------------------------------------------------------------------------- #

def test_main_check_compliant_verbose(monkeypatch, capsys, dicom_dir, self_schema, tmp_path):
    report = tmp_path / "report.json"
    _run(
        ["check", str(dicom_dir), str(self_schema), str(report),
         "--auto-yes", "--verbose"],
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert "Acquisition Mapping:" in out
    # exact match -> confidence "exact" and PASS lines shown in verbose mode
    assert "exact" in out
    assert "[PASS]" in out
    assert "Compliance report saved to" in out
    assert report.exists()
    results = json.loads(report.read_text())
    assert all(r.get("status") == "ok" for r in results)


def test_main_check_named_args_summary(monkeypatch, capsys, dicom_dir, self_schema):
    # non-verbose path -> summary line, no PASS lines printed
    _run(
        ["check", "--dicoms", str(dicom_dir), "--schema", str(self_schema),
         "--auto-yes"],
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert "passed" in out.lower()
    assert "[PASS]" not in out  # passes hidden in non-verbose mode


def test_check_command_confidence_and_failures(capsys, dicom_dir, self_schema, tmp_path):
    """Drive check_command with a schema that mismatches -> FAIL/expected/got."""
    schema = json.loads(self_schema.read_text())
    # Force a mismatch by changing EchoTime to a value the DICOMs don't have.
    for acq in schema["acquisitions"].values():
        for f in acq["fields"]:
            if f["field"] == "EchoTime":
                f["value"] = 999.0
    schema_path = tmp_path / "mismatch.json"
    schema_path.write_text(json.dumps(schema))
    report = tmp_path / "rep.json"

    args = Namespace(
        dicoms=str(dicom_dir),
        schema=str(schema_path),
        report=str(report),
        auto_yes=True,
        verbose=False,
    )
    check_command(args)
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "expected:" in out
    assert "got:" in out
    assert "--verbose" in out  # summary suggests --verbose when there are failures
    assert report.exists()


def test_check_command_unmapped_acquisition(capsys, dicom_dir, self_schema, tmp_path):
    """A schema with an extra acquisition that has no input to map to."""
    schema = json.loads(self_schema.read_text())
    acqs = schema["acquisitions"]
    (first_name, first_acq), = list(acqs.items())
    # Duplicate the acquisition under a second name so there are two reference
    # acquisitions but only one input acquisition -> one stays unmapped.
    import copy
    acqs["ExtraUnmappedAcq"] = copy.deepcopy(first_acq)
    schema_path = tmp_path / "extra.json"
    schema_path.write_text(json.dumps(schema))

    args = Namespace(
        dicoms=str(dicom_dir),
        schema=str(schema_path),
        report=None,  # no report -> exercise the "no report" branch
        auto_yes=True,
        verbose=False,
    )
    check_command(args)
    out = capsys.readouterr().out
    # Unmapped reference acquisition appears in mapping summary and/or WARN line
    assert "unmapped" in out.lower()


def test_check_command_no_verbose_attr(capsys, dicom_dir, self_schema, tmp_path):
    """Namespace without 'verbose' -> getattr default False path."""
    args = Namespace(
        dicoms=str(dicom_dir),
        schema=str(self_schema),
        report=None,
        auto_yes=True,
    )
    check_command(args)
    out = capsys.readouterr().out
    assert "passed" in out.lower()


def test_check_command_interactive_skipped_when_not_tty(monkeypatch, capsys, dicom_dir, self_schema):
    """With auto_yes False but stdin not a tty, interactive mapping is skipped."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    args = Namespace(
        dicoms=str(dicom_dir),
        schema=str(self_schema),
        report=None,
        auto_yes=False,
        verbose=False,
    )
    check_command(args)  # should not hang / prompt
    out = capsys.readouterr().out
    assert "Acquisition Mapping:" in out


def test_check_command_fully_compliant_no_fields(capsys, dicom_dir, self_schema, tmp_path):
    """Schema acquisition with no fields -> empty results -> 'fully compliant' path."""
    schema = json.loads(self_schema.read_text())
    (name, acq), = list(schema["acquisitions"].items())
    acq["fields"] = []
    acq["series"] = []
    schema_path = tmp_path / "nofields.json"
    schema_path.write_text(json.dumps(schema))
    args = Namespace(
        dicoms=str(dicom_dir),
        schema=str(schema_path),
        report=None,
        auto_yes=True,
        verbose=False,
    )
    check_command(args)
    out = capsys.readouterr().out
    assert "fully compliant" in out.lower()


@pytest.mark.parametrize("cost,label", [(2.0, "high"), (10.0, "medium"), (42.0, "low")])
def test_check_command_confidence_levels(monkeypatch, capsys, dicom_dir, self_schema, cost, label):
    """Patch cost_details so the 'high'/'medium'/'low' confidence branches run."""
    real_map = cli_main.map_to_json_reference

    def fake_map(in_session, json_schema, return_costs=False):
        session_map, cost_details = real_map(in_session, json_schema, return_costs=True)
        for ref in cost_details.get("assigned_costs", {}):
            cost_details["assigned_costs"][ref] = cost
        if return_costs:
            return session_map, cost_details
        return session_map

    monkeypatch.setattr(cli_main, "map_to_json_reference", fake_map)
    args = Namespace(
        dicoms=str(dicom_dir),
        schema=str(self_schema),
        report=None,
        auto_yes=True,
        verbose=False,
    )
    check_command(args)
    out = capsys.readouterr().out
    assert label in out


def test_check_command_interactive_mapping_invoked(monkeypatch, capsys, dicom_dir, self_schema):
    """auto_yes False + tty True -> interactive_mapping_to_json_reference is called."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    called = {}

    def fake_interactive(in_session, json_schema, initial_mapping=None):
        called["yes"] = True
        return initial_mapping

    monkeypatch.setattr(cli_main, "interactive_mapping_to_json_reference", fake_interactive)
    args = Namespace(
        dicoms=str(dicom_dir),
        schema=str(self_schema),
        report=None,
        auto_yes=False,
        verbose=False,
    )
    check_command(args)
    assert called.get("yes") is True


def test_check_command_series_and_rule_name_printing(monkeypatch, capsys, dicom_dir, self_schema):
    """Patch compliance results to exercise series/rule_name/verbose-PASS print branches."""
    crafted = [
        {"status": "error", "field": "EchoTime", "series": "s1",
         "value": 5.0, "expected": 3.0, "message": "mismatch"},
        {"status": "warning", "field": "FlipAngle", "rule_name": "MyRule",
         "value": 10.0, "expected": 9.0, "message": "warn"},
        {"status": "ok", "field": "RepetitionTime", "value": 2000.0,
         "message": "Passed."},
        {"status": "na", "field": "Unknown", "message": "OK"},
    ]
    monkeypatch.setattr(cli_main, "check_acquisition_compliance",
                        lambda *a, **k: list(crafted))
    args = Namespace(
        dicoms=str(dicom_dir),
        schema=str(self_schema),
        report=None,
        auto_yes=True,
        verbose=True,  # verbose so the OK-with-value line prints too
    )
    check_command(args)
    out = capsys.readouterr().out
    assert "[FAIL] EchoTime [s1]" in out          # series branch (line ~148)
    assert "MyRule: FlipAngle" in out             # rule_name branch (line ~150)
    assert "[PASS] RepetitionTime (2000.0)" in out  # verbose ok-with-value branch
    assert "[N/A]" in out
    assert "1 passed" in out and "1 failed" in out and "1 warnings" in out


# --------------------------------------------------------------------------- #
# main() -> match_command                                                     #
# --------------------------------------------------------------------------- #

def test_main_match_library(monkeypatch, capsys, dicom_dir, tmp_path):
    report = tmp_path / "match.json"
    _run(
        ["match", str(dicom_dir), "--library", "--report", str(report), "--top", "2"],
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert "Loading DICOM session" in out
    assert "Loaded" in out
    assert "Match report saved to" in out
    assert report.exists()
    data = json.loads(report.read_text())
    for acq, matches in data.items():
        assert len(matches) <= 2


def test_main_match_named_dicoms(monkeypatch, capsys, dicom_dir, self_schema):
    _run(
        ["match", "--dicoms", str(dicom_dir), "--schemas", str(self_schema)],
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert "=== " in out  # per-acquisition header printed


# --------------------------------------------------------------------------- #
# match.py: load_schemas_from_paths edge cases                                #
# --------------------------------------------------------------------------- #

def test_load_schemas_non_json_path_skipped(tmp_path, caplog):
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    result = load_schemas_from_paths([str(txt)])
    assert result == {}


def test_load_schemas_nonexistent_path_skipped(tmp_path):
    result = load_schemas_from_paths([str(tmp_path / "does_not_exist")])
    assert result == {}


def test_load_schemas_invalid_json_file_skipped(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json")
    result = load_schemas_from_paths([str(bad)])
    assert result == {}


def test_load_schemas_from_directory_with_index(tmp_path):
    good = {
        "name": "Dir Schema",
        "acquisitions": {
            "Acq": {"fields": [{"field": "EchoTime", "value": 30.0, "tag": "0018,0081"}], "series": []}
        },
    }
    (tmp_path / "a.json").write_text(json.dumps(good))
    (tmp_path / "index.json").write_text(json.dumps(["a.json"]))
    (tmp_path / "bad.json").write_text("nope")
    result = load_schemas_from_paths([str(tmp_path)])
    assert len(result) == 1
    assert not any("index.json" in k for k in result)


# --------------------------------------------------------------------------- #
# match.py: match_command branches                                            #
# --------------------------------------------------------------------------- #

def test_match_command_no_schemas_loaded(capsys, dicom_dir):
    """schemas point to nothing loadable -> 'No schemas loaded' path, early return."""
    args = Namespace(
        dicoms=str(dicom_dir),
        schemas=["/nonexistent/path.json"],
        library=False,
        report=None,
        top=5,
    )
    match_command(args)
    out = capsys.readouterr().out
    assert "No schemas loaded" in out


def test_match_command_long_name_truncation(capsys, dicom_dir, tmp_path):
    """A very long schema name is truncated with '...' in the table output."""
    long_name = "X" * 60
    schema = {
        "name": long_name,
        "acquisitions": {
            "Acq": {
                "fields": [{"field": "RepetitionTime", "value": 2000.0, "tag": "0018,0080"}],
                "series": [],
            }
        },
    }
    schema_path = tmp_path / "long.json"
    schema_path.write_text(json.dumps(schema))
    args = Namespace(
        dicoms=str(dicom_dir),
        schemas=[str(schema_path)],
        library=False,
        report=None,
        top=5,
    )
    match_command(args)
    out = capsys.readouterr().out
    assert "..." in out
    assert ("X" * 25) in out  # truncated prefix present


def test_match_command_scoring_exception_skips(monkeypatch, capsys, dicom_dir, tmp_path):
    """If scoring raises, that candidate is skipped and no matches are produced."""
    schema = {
        "name": "Boom",
        "acquisitions": {
            "Acq": {"fields": [{"field": "EchoTime", "value": 3.0, "tag": "0018,0081"}], "series": []}
        },
    }
    schema_path = tmp_path / "boom.json"
    schema_path.write_text(json.dumps(schema))

    def _raise(*a, **k):
        raise RuntimeError("scoring blew up")

    monkeypatch.setattr(cli_match, "compute_compliance_score", _raise)

    args = Namespace(
        dicoms=str(dicom_dir),
        schemas=[str(schema_path)],
        library=False,
        report=None,
        top=5,
    )
    match_command(args)
    out = capsys.readouterr().out
    assert "No matching schemas found." in out
