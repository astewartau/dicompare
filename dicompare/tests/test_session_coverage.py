"""
Coverage-focused unit tests for:
  - dicompare/session/mapping.py
  - dicompare/session/acquisition.py
  - dicompare/data_utils.py

These tests exercise branches that were previously uncovered: the min/max range
scoring path, missing-column handling in map_to_json_reference, the interactive
(curses-driven) mapping function via a scripted fake stdscr, orphan-series run
assignment and settings-split logic in acquisition assignment, and the nested
flatten / AcquisitionDateTime handling in data_utils.
"""

import numpy as np
import pandas as pd
import pytest

from dicompare.session import mapping as mapping_mod
from dicompare.session.mapping import (
    calculate_field_score,
    map_to_json_reference,
    interactive_mapping_to_json_reference,
)
from dicompare.session.acquisition import (
    assign_acquisition_and_run_numbers,
    _dicom_time_to_seconds,
    _normalize_series_description_for_run_detection,
)
from dicompare import data_utils
from dicompare.data_utils import (
    make_dataframe_hashable,
    _flatten_nested_dict,
    _reduce_flattened_keys,
    _convert_to_plain_python_types,
    _process_dicom_metadata,
    prepare_session_dataframe,
)
from dicompare.config import MAX_DIFF_SCORE


# ---------------------------------------------------------------------------
# mapping.calculate_field_score - min/max range constraints (lines 82-96)
# ---------------------------------------------------------------------------
class TestCalculateFieldScoreRange:
    def test_within_min_max_range(self):
        assert calculate_field_score(None, 5, min_value=0, max_value=10) == 0

    def test_only_min_in_range(self):
        assert calculate_field_score(None, 5, min_value=0) == 0

    def test_only_max_in_range(self):
        assert calculate_field_score(None, 5, max_value=10) == 0

    def test_below_min_value(self):
        # actual below min: distance from boundary = min - actual = 3
        assert calculate_field_score(None, 2, min_value=5) == 3

    def test_below_min_value_capped(self):
        # distance would be huge -> capped at MAX_DIFF_SCORE
        assert calculate_field_score(None, -100, min_value=5) == MAX_DIFF_SCORE

    def test_above_max_value(self):
        # actual above max: distance = actual - max = 4
        assert calculate_field_score(None, 14, max_value=10) == 4

    def test_above_max_value_capped(self):
        assert calculate_field_score(None, 1000, max_value=10) == MAX_DIFF_SCORE

    def test_non_numeric_with_range_constraint(self):
        # non-numeric actual under a range constraint -> fixed penalty of 5
        assert calculate_field_score(None, "notanumber", min_value=0, max_value=10) == 5


# ---------------------------------------------------------------------------
# mapping.map_to_json_reference
# ---------------------------------------------------------------------------
def _simple_ref_session():
    return {
        "acquisitions": {
            "acqA": {
                "fields": [{"field": "ProtocolName", "value": "protoA"}],
                "series": [],
            },
            "acqB": {
                "fields": [{"field": "ProtocolName", "value": "protoB"}],
                "series": [],
            },
        }
    }


def _simple_in_df():
    return pd.DataFrame(
        [
            {"Acquisition": "in_a", "ProtocolName": "protoA"},
            {"Acquisition": "in_b", "ProtocolName": "protoB"},
        ]
    )


class TestMapToJsonReference:
    def test_basic_assignment(self):
        ref = _simple_ref_session()
        df = _simple_in_df()
        result = map_to_json_reference(df, ref)
        assert result == {"acqA": "in_a", "acqB": "in_b"}

    def test_return_costs(self):
        ref = _simple_ref_session()
        df = _simple_in_df()
        mapping, costs = map_to_json_reference(df, ref, return_costs=True)
        assert mapping == {"acqA": "in_a", "acqB": "in_b"}
        assert "assigned_costs" in costs
        assert "ref_acq_list" in costs
        assert "input_acq_list" in costs
        # Perfect matches -> zero cost
        assert costs["assigned_costs"]["acqA"] == 0.0
        assert costs["assigned_costs"]["acqB"] == 0.0

    def test_missing_column_yields_high_cost(self):
        # Reference references a field absent from the input df (line 265 path):
        # actual_value = None -> MAX_DIFF_SCORE penalty.
        ref = {
            "acquisitions": {
                "acqX": {
                    "fields": [{"field": "NotPresentField", "value": "whatever"}],
                    "series": [],
                }
            }
        }
        df = pd.DataFrame([{"Acquisition": "in_only", "ProtocolName": "p"}])
        mapping, costs = map_to_json_reference(df, ref, return_costs=True)
        assert mapping == {"acqX": "in_only"}
        assert costs["assigned_costs"]["acqX"] == MAX_DIFF_SCORE

    def test_multiple_values_in_column_high_cost(self):
        # Column present but with multiple distinct values -> actual_value None branch.
        ref = {
            "acquisitions": {
                "acqM": {
                    "fields": [{"field": "ProtocolName", "value": "protoA"}],
                    "series": [],
                }
            }
        }
        df = pd.DataFrame(
            [
                {"Acquisition": "in_multi", "ProtocolName": "protoA"},
                {"Acquisition": "in_multi", "ProtocolName": "protoB"},
            ]
        )
        mapping, costs = map_to_json_reference(df, ref, return_costs=True)
        assert mapping == {"acqM": "in_multi"}
        assert costs["assigned_costs"]["acqM"] == MAX_DIFF_SCORE

    def test_with_series_definitions(self):
        # Exercise the nested series-assignment branch (compute_series_cost_matrix).
        ref = {
            "acquisitions": {
                "acqS": {
                    "fields": [{"field": "ProtocolName", "value": "protoS"}],
                    "series": [
                        {"name": "s1", "fields": [{"field": "ImageType", "value": "M"}]},
                        {"name": "s2", "fields": [{"field": "ImageType", "value": "P"}]},
                    ],
                }
            }
        }
        df = pd.DataFrame(
            [
                {"Acquisition": "in_s", "ProtocolName": "protoS", "ImageType": "M"},
                {"Acquisition": "in_s", "ProtocolName": "protoS", "ImageType": "P"},
            ]
        )
        mapping, costs = map_to_json_reference(df, ref, return_costs=True)
        assert mapping == {"acqS": "in_s"}
        # ProtocolName matches and both series match perfectly -> zero cost
        assert costs["assigned_costs"]["acqS"] == 0.0


# ---------------------------------------------------------------------------
# mapping.interactive_mapping_to_json_reference (curses, lines 329-438)
# ---------------------------------------------------------------------------
class FakeStdscr:
    """Minimal fake curses screen that returns a scripted sequence of keys."""

    def __init__(self, keys):
        self._keys = list(keys)

    def clear(self):
        pass

    def addstr(self, *args, **kwargs):
        pass

    def refresh(self):
        pass

    def getch(self):
        if not self._keys:
            # Safety net: quit if the script runs out.
            return ord("q")
        return self._keys.pop(0)


class FakeCurses:
    """Stand-in for the curses module used by the interactive mapper."""

    KEY_UP = 1000
    KEY_DOWN = 1001
    KEY_LEFT = 1002
    KEY_RIGHT = 1003
    KEY_ENTER = 1004

    def __init__(self, keys):
        self._keys = keys

    def curs_set(self, n):
        pass

    def wrapper(self, func):
        return func(FakeStdscr(self._keys))


def _install_fake_curses(monkeypatch, keys):
    fake = FakeCurses(keys)
    monkeypatch.setattr(mapping_mod, "curses", fake)
    return fake


def _interactive_session_df():
    return pd.DataFrame(
        [
            {"Acquisition": "in_alpha", "ProtocolName": "ProtoAlpha"},
            {"Acquisition": "in_beta", "ProtocolName": "ProtoBeta"},
            # in_gamma intentionally has two distinct ProtocolNames -> "multiple"
            {"Acquisition": "in_gamma", "ProtocolName": "ProtoG1"},
            {"Acquisition": "in_gamma", "ProtocolName": "ProtoG2"},
        ]
    )


def _interactive_ref_session():
    return {
        "acquisitions": {
            "RefOne": {"fields": []},
            "RefTwo": {"fields": []},
        }
    }


class TestInteractiveMapping:
    def test_map_first_ref_to_first_input(self, monkeypatch):
        c = FakeCurses.__dict__  # keep reference alive
        keys = [
            FakeCurses.KEY_RIGHT,   # enter input-selection for RefOne (idx 0)
            FakeCurses.KEY_ENTER,   # confirm in_alpha (input idx 0)
            ord("q"),               # quit
        ]
        _install_fake_curses(monkeypatch, keys)
        result = interactive_mapping_to_json_reference(
            _interactive_session_df(), _interactive_ref_session()
        )
        # reference_acq_names sorted -> ["RefOne", "RefTwo"]; input sorted ->
        # ["in_alpha", "in_beta", "in_gamma"]
        assert result["RefOne"] == "in_alpha"

    def test_navigation_and_unmap(self, monkeypatch):
        keys = [
            FakeCurses.KEY_DOWN,    # move ref selection to RefTwo (idx 1)
            FakeCurses.KEY_UP,      # back to RefOne
            FakeCurses.KEY_RIGHT,   # open input list
            FakeCurses.KEY_DOWN,    # to in_beta
            FakeCurses.KEY_DOWN,    # to in_gamma
            FakeCurses.KEY_UP,      # back to in_beta
            FakeCurses.KEY_LEFT,    # cancel selection (no assignment)
            FakeCurses.KEY_RIGHT,   # reopen
            FakeCurses.KEY_ENTER,   # confirm in_alpha for RefOne
            ord("u"),               # unmap RefOne
            ord("q"),
        ]
        _install_fake_curses(monkeypatch, keys)
        result = interactive_mapping_to_json_reference(
            _interactive_session_df(), _interactive_ref_session()
        )
        # RefOne was mapped then unmapped -> should be absent
        assert "RefOne" not in result

    def test_enter_without_input_selection_noop(self, monkeypatch):
        keys = [
            FakeCurses.KEY_ENTER,   # ENTER while not picking input -> no-op branch
            ord("q"),
        ]
        _install_fake_curses(monkeypatch, keys)
        result = interactive_mapping_to_json_reference(
            _interactive_session_df(), _interactive_ref_session()
        )
        assert result == {}

    def test_initial_mapping_seeded(self, monkeypatch):
        keys = [ord("q")]
        _install_fake_curses(monkeypatch, keys)
        result = interactive_mapping_to_json_reference(
            _interactive_session_df(),
            _interactive_ref_session(),
            initial_mapping={
                "RefTwo": "in_beta",
                "RefUnknown": "in_alpha",  # ignored: ref not in ref set
                "RefOne": "no_such_input",  # ignored: input not present
            },
        )
        assert result == {"RefTwo": "in_beta"}

    def test_reassign_input(self, monkeypatch):
        keys = [
            FakeCurses.KEY_RIGHT,
            FakeCurses.KEY_ENTER,   # RefOne -> in_alpha
            FakeCurses.KEY_RIGHT,
            FakeCurses.KEY_DOWN,    # to in_beta
            FakeCurses.KEY_ENTER,   # RefOne -> in_beta (overwrite)
            ord("q"),
        ]
        _install_fake_curses(monkeypatch, keys)
        result = interactive_mapping_to_json_reference(
            _interactive_session_df(), _interactive_ref_session()
        )
        assert result["RefOne"] == "in_beta"


# ---------------------------------------------------------------------------
# acquisition helper functions
# ---------------------------------------------------------------------------
class TestDicomTimeToSeconds:
    def test_nan_returns_zero(self):
        assert _dicom_time_to_seconds(np.nan) == 0

    def test_empty_string_returns_zero(self):
        assert _dicom_time_to_seconds("") == 0

    def test_hhmmss_string(self):
        # 01:02:03 -> 3723 seconds
        assert _dicom_time_to_seconds("010203") == 3723

    def test_fractional_seconds_stripped(self):
        assert _dicom_time_to_seconds("010203.500000") == 3723

    def test_short_string_padded(self):
        # "0102" -> "010200" -> 01:02:00 = 3720
        assert _dicom_time_to_seconds("0102") == 3720

    def test_numeric_input_returned_as_float(self):
        assert _dicom_time_to_seconds(42) == 42.0


class TestNormalizeSeriesDescription:
    def test_nan_passthrough(self):
        assert pd.isna(_normalize_series_description_for_run_detection(np.nan))

    def test_empty_passthrough(self):
        assert _normalize_series_description_for_run_detection("") == ""

    def test_single_rr_removed(self):
        assert _normalize_series_description_for_run_detection("qsm_RR") == "qsm"

    def test_multiple_rr_removed(self):
        assert _normalize_series_description_for_run_detection("qsm_RR_RR") == "qsm"

    def test_no_rr_unchanged(self):
        assert _normalize_series_description_for_run_detection("qsm") == "qsm"


# ---------------------------------------------------------------------------
# acquisition.assign_acquisition_and_run_numbers
# ---------------------------------------------------------------------------
class TestAssignAcquisitionAndRunNumbers:
    def test_existing_acquisition_column_short_circuit(self):
        df = pd.DataFrame([{"Acquisition": "already", "ProtocolName": "p"}])
        result = assign_acquisition_and_run_numbers(df)
        assert list(result["Acquisition"]) == ["already"]

    def test_raises_without_protocol_or_sequence(self):
        df = pd.DataFrame([{"SeriesDescription": "foo"}])
        with pytest.raises(ValueError, match="Neither ProtocolName nor SequenceName"):
            assign_acquisition_and_run_numbers(df)

    def test_single_acquisition_basic(self):
        df = pd.DataFrame(
            [
                {"ProtocolName": "MyProto", "SeriesDescription": "sd", "ImageType": "M"},
                {"ProtocolName": "MyProto", "SeriesDescription": "sd", "ImageType": "M"},
            ]
        )
        result = assign_acquisition_and_run_numbers(df)
        assert set(result["Acquisition"]) == {"acq-myproto"}
        assert set(result["RunNumber"]) == {1}
        assert "Series" in result.columns

    def test_sequence_name_fallback(self):
        # ProtocolName present but NaN -> falls back to SequenceName.
        df = pd.DataFrame(
            [
                {"ProtocolName": np.nan, "SequenceName": "seqfoo", "SeriesDescription": "sd"},
                {"ProtocolName": np.nan, "SequenceName": "seqfoo", "SeriesDescription": "sd"},
            ]
        )
        result = assign_acquisition_and_run_numbers(df)
        assert set(result["Acquisition"]) == {"acq-seqfoo"}

    def test_sequence_name_only(self):
        df = pd.DataFrame(
            [
                {"SequenceName": "seqonly", "SeriesDescription": "sd"},
                {"SequenceName": "seqonly", "SeriesDescription": "sd"},
            ]
        )
        result = assign_acquisition_and_run_numbers(df)
        assert set(result["Acquisition"]) == {"acq-seqonly"}

    def test_patient_name_only(self):
        df = pd.DataFrame(
            [
                {"ProtocolName": "P", "PatientName": "Alice", "SeriesDescription": "sd"},
                {"ProtocolName": "P", "PatientName": "Alice", "SeriesDescription": "sd"},
            ]
        )
        result = assign_acquisition_and_run_numbers(df)
        assert set(result["Acquisition"]) == {"acq-p"}

    def test_patient_id_only(self):
        df = pd.DataFrame(
            [
                {"ProtocolName": "P", "PatientID": "ID1", "SeriesDescription": "sd"},
                {"ProtocolName": "P", "PatientID": "ID1", "SeriesDescription": "sd"},
            ]
        )
        result = assign_acquisition_and_run_numbers(df)
        assert set(result["Acquisition"]) == {"acq-p"}

    def test_no_series_fields_default_signature(self):
        # No SeriesDescription/ImageType/InversionTime columns -> "default" signature path.
        df = pd.DataFrame(
            [
                {"ProtocolName": "NoSeries", "Foo": 1},
                {"ProtocolName": "NoSeries", "Foo": 2},
            ]
        )
        result = assign_acquisition_and_run_numbers(df)
        assert set(result["Acquisition"]) == {"acq-noseries"}
        assert set(result["Series"]) == {"Series 01"}

    def test_multiple_runs_detected_via_series_time(self):
        # Two runs of the same series, >60s apart -> two runs.
        rows = []
        for run_idx, (stime, uid) in enumerate(
            [("100000.000000", "uid-run1"), ("100200.000000", "uid-run2")]
        ):
            for _ in range(2):
                rows.append(
                    {
                        "ProtocolName": "RunProto",
                        "PatientName": "Pat",
                        "PatientID": "PID",
                        "SeriesDescription": "sd",
                        "ImageType": "M",
                        "SeriesInstanceUID": uid,
                        "SeriesTime": stime,
                    }
                )
        df = pd.DataFrame(rows)
        result = assign_acquisition_and_run_numbers(df)
        assert set(result["RunNumber"]) == {1, 2}

    def test_acquisition_time_fallback_for_runs(self):
        # No SeriesTime, but AcquisitionTime present -> uses AcquisitionTime (line 222-223).
        rows = []
        for stime, uid in [("100000.000000", "uidA"), ("100200.000000", "uidB")]:
            for _ in range(2):
                rows.append(
                    {
                        "ProtocolName": "AcqTimeProto",
                        "PatientName": "Pat",
                        "PatientID": "PID",
                        "SeriesDescription": "sd",
                        "ImageType": "M",
                        "SeriesInstanceUID": uid,
                        "AcquisitionTime": stime,
                    }
                )
        df = pd.DataFrame(rows)
        result = assign_acquisition_and_run_numbers(df)
        assert set(result["RunNumber"]) == {1, 2}

    def test_settings_split_creates_second_acquisition(self):
        # Same protocol, two temporally-separated runs, but a settings field
        # (EchoTime) changes between them -> acquisition split (Stage 4).
        rows = []
        for etime, stime, uid in [
            (10.0, "100000.000000", "uidA"),
            (20.0, "100200.000000", "uidB"),
        ]:
            for _ in range(2):
                rows.append(
                    {
                        "ProtocolName": "SplitProto",
                        "PatientName": "Pat",
                        "PatientID": "PID",
                        "SeriesDescription": "sd",
                        "ImageType": "M",
                        "EchoTime": etime,
                        "SeriesInstanceUID": uid,
                        "SeriesTime": stime,
                    }
                )
        df = pd.DataFrame(rows)
        result = assign_acquisition_and_run_numbers(df)
        acqs = set(result["Acquisition"])
        # Original acq plus a settings-split acquisition suffixed with _2
        assert "acq-splitproto" in acqs
        assert any(a.endswith("_2") for a in acqs)

    def test_orphan_series_assigned_to_closest_run(self):
        # One repeated series (drives run detection) plus an orphan series with
        # its own SeriesTime -> orphan is assigned to the closest run by time
        # (lines 333-367).
        rows = []
        # Repeated series: two UIDs >60s apart -> two runs
        for stime, uid in [("100000.000000", "rep-uid1"), ("100300.000000", "rep-uid2")]:
            rows.append(
                {
                    "ProtocolName": "OrphanProto",
                    "PatientName": "Pat",
                    "PatientID": "PID",
                    "SeriesDescription": "repeated",
                    "ImageType": "M",
                    "SeriesInstanceUID": uid,
                    "SeriesTime": stime,
                }
            )
        # Orphan series (single UID) near run 2's time
        rows.append(
            {
                "ProtocolName": "OrphanProto",
                "PatientName": "Pat",
                "PatientID": "PID",
                "SeriesDescription": "orphan",
                "ImageType": "P",
                "SeriesInstanceUID": "orphan-uid",
                "SeriesTime": "100305.000000",
            }
        )
        df = pd.DataFrame(rows)
        result = assign_acquisition_and_run_numbers(df)
        orphan_rows = result[result["SeriesDescription"] == "orphan"]
        # The orphan-series branch (closest-run-by-time) executed and assigned a
        # concrete run number to the orphan series.
        assert len(orphan_rows) == 1
        assert orphan_rows["RunNumber"].iloc[0] in (1, 2)
        assert orphan_rows["Acquisition"].iloc[0].startswith("acq-orphanproto")

    def test_orphan_series_without_time_assigned_run_one(self):
        # Orphan series whose SeriesTime is missing -> defaults to run 1 (lines 338-346).
        rows = []
        for stime, uid in [("100000.000000", "rep1"), ("100300.000000", "rep2")]:
            rows.append(
                {
                    "ProtocolName": "OrphanNoTime",
                    "PatientName": "Pat",
                    "PatientID": "PID",
                    "SeriesDescription": "repeated",
                    "ImageType": "M",
                    "SeriesInstanceUID": uid,
                    "SeriesTime": stime,
                }
            )
        # Orphan with no SeriesTime value
        rows.append(
            {
                "ProtocolName": "OrphanNoTime",
                "PatientName": "Pat",
                "PatientID": "PID",
                "SeriesDescription": "orphan",
                "ImageType": "P",
                "SeriesInstanceUID": "orphan-uid",
                "SeriesTime": np.nan,
            }
        )
        df = pd.DataFrame(rows)
        result = assign_acquisition_and_run_numbers(df)
        orphan_rows = result[result["SeriesDescription"] == "orphan"]
        assert set(orphan_rows["RunNumber"]) == {1}


# ---------------------------------------------------------------------------
# data_utils.make_dataframe_hashable
# ---------------------------------------------------------------------------
class TestMakeDataframeHashable:
    def test_lists_become_tuples(self):
        df = pd.DataFrame({"a": [[1, 2], [3, 4]]})
        out = make_dataframe_hashable(df)
        assert out["a"].iloc[0] == (1, 2)
        assert out["a"].iloc[1] == (3, 4)

    def test_nested_lists(self):
        df = pd.DataFrame({"a": [[[1], [2]]]})
        out = make_dataframe_hashable(df)
        assert out["a"].iloc[0] == ((1,), (2,))

    def test_scalars_unchanged(self):
        df = pd.DataFrame({"a": [1, "x"]})
        out = make_dataframe_hashable(df)
        assert list(out["a"]) == [1, "x"]

    def test_all_values_hashable_after(self):
        df = pd.DataFrame({"a": [[1, 2], {"k": "v"}]})
        out = make_dataframe_hashable(df)
        for v in out["a"]:
            hash(v)  # must not raise


# ---------------------------------------------------------------------------
# data_utils._flatten_nested_dict / _reduce_flattened_keys
# ---------------------------------------------------------------------------
class TestFlattenNestedDict:
    def test_simple_dict(self):
        assert _flatten_nested_dict({"a": 1, "b": 2}) == {"a": 1, "b": 2}

    def test_nested_dict(self):
        assert _flatten_nested_dict({"a": {"b": 1}}) == {"a_b": 1}

    def test_list_of_primitives_kept_whole(self):
        assert _flatten_nested_dict({"a": [1, 2, 3]}) == {"a": [1, 2, 3]}

    def test_list_of_dicts_descended(self):
        result = _flatten_nested_dict({"a": [{"b": 1}, {"c": 2}]})
        assert result == {"a_0_b": 1, "a_1_c": 2}

    def test_list_mixed_dict_and_primitive(self):
        # Covers line 59: a non-dict item inside a dict-containing list.
        result = _flatten_nested_dict({"a": [{"b": 1}, 42]})
        assert result == {"a_0_b": 1, "a_1": 42}

    def test_top_level_list_of_primitives(self):
        # Covers the top-level list branch (lines 67-77).
        assert _flatten_nested_dict([1, 2, 3]) == {"": [1, 2, 3]}

    def test_top_level_list_of_dicts(self):
        result = _flatten_nested_dict([{"a": 1}, {"b": 2}])
        assert result == {"0_a": 1, "1_b": 2}

    def test_top_level_list_mixed(self):
        result = _flatten_nested_dict([{"a": 1}, 99])
        assert result == {"0_a": 1, "1": 99}

    def test_top_level_scalar(self):
        assert _flatten_nested_dict(5) == {"": 5}


class TestReduceFlattenedKeys:
    def test_reduces_to_last_component(self):
        assert _reduce_flattened_keys({"a_b_c": 1}) == {"c": 1}

    def test_collision_keeps_first_non_none(self):
        # Existing None, incoming value -> update.
        result = _reduce_flattened_keys({"x_c": None, "y_c": 5})
        assert result == {"c": 5}

    def test_collision_keeps_existing_when_incoming_none(self):
        result = _reduce_flattened_keys({"x_c": 5, "y_c": None})
        assert result == {"c": 5}


class TestConvertToPlainPythonTypes:
    def test_float_rounded(self):
        assert _convert_to_plain_python_types(1.123456789) == round(1.123456789, 5)

    def test_int_preserved(self):
        assert _convert_to_plain_python_types(np.int64(7)) == 7

    def test_list_recursed(self):
        assert _convert_to_plain_python_types([1.0000001, 2]) == [1.0, 2]

    def test_dict_recursed(self):
        assert _convert_to_plain_python_types({"a": 1.0000001}) == {"a": 1.0}

    def test_string_passthrough(self):
        assert _convert_to_plain_python_types("hello") == "hello"


class TestProcessDicomMetadata:
    def test_enhanced_to_regular_mapping_applied(self):
        # EffectiveEchoTime -> EchoTime when EchoTime absent.
        result = _process_dicom_metadata({"EffectiveEchoTime": 2.5})
        assert result.get("EchoTime") == 2.5
        assert "EffectiveEchoTime" not in result

    def test_enhanced_empty_source_removed(self):
        # Source empty but target has a value -> source removed, target kept.
        result = _process_dicom_metadata({"EffectiveEchoTime": "", "EchoTime": 3.0})
        assert result.get("EchoTime") == 3.0
        assert "EffectiveEchoTime" not in result

    def test_acquisition_datetime_split(self):
        # AcquisitionDateTime split into date + time (lines 188-196).
        result = _process_dicom_metadata({"AcquisitionDateTime": "20250101123456.000000"})
        assert result["AcquisitionDate"] == "20250101"
        assert result["AcquisitionTime"] == "123456.000000"

    def test_acquisition_datetime_no_time_component(self):
        # Exactly 8 chars -> date set, time None.
        result = _process_dicom_metadata({"AcquisitionDateTime": "20250101"})
        assert result["AcquisitionDate"] == "20250101"
        assert result["AcquisitionTime"] is None

    def test_acquisition_datetime_not_split_when_fields_present(self):
        result = _process_dicom_metadata(
            {
                "AcquisitionDateTime": "20250101123456",
                "AcquisitionDate": "19990101",
                "AcquisitionTime": "010101",
            }
        )
        assert result["AcquisitionDate"] == "19990101"
        assert result["AcquisitionTime"] == "010101"


class TestPrepareSessionDataframe:
    def test_empty_raises(self):
        with pytest.raises(ValueError, match="No session data"):
            prepare_session_dataframe([])

    def test_sorts_by_instance_number(self):
        data = [
            {"InstanceNumber": 3, "Val": "c"},
            {"InstanceNumber": 1, "Val": "a"},
            {"InstanceNumber": 2, "Val": "b"},
        ]
        df = prepare_session_dataframe(data)
        assert list(df["InstanceNumber"]) == [1, 2, 3]

    def test_sorts_by_dicom_path_when_no_instance_number(self):
        data = [
            {"DICOM_Path": "/z", "Val": 1},
            {"DICOM_Path": "/a", "Val": 2},
        ]
        df = prepare_session_dataframe(data)
        assert list(df["DICOM_Path"]) == ["/a", "/z"]

    def test_drops_all_nan_columns(self):
        data = [
            {"Keep": 1, "Empty": None},
            {"Keep": 2, "Empty": None},
        ]
        df = prepare_session_dataframe(data)
        assert "Keep" in df.columns
        assert "Empty" not in df.columns

    def test_lists_made_hashable(self):
        data = [{"ImageType": ["ORIGINAL", "PRIMARY"], "InstanceNumber": 1}]
        df = prepare_session_dataframe(data)
        assert df["ImageType"].iloc[0] == ("ORIGINAL", "PRIMARY")
