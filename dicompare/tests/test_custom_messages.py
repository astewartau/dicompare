"""Tests for custom warning/error messages on field constraints.

A field may carry ``warningMessage`` / ``errorMessage``; when the field produces
that outcome the custom text (with ``%V`` filled in) replaces the auto-generated
message. This works for legacy, graded, and series fields, across all types.
"""

import pandas as pd

from dicompare.validation.helpers import (
    apply_message_template,
    custom_message_for_status,
)
from dicompare.tests.test_helpers import check_session_compliance


class TestApplyMessageTemplate:
    def test_substitutes_value_placeholder(self):
        assert apply_message_template("%V T is too high", [3]) == "3 T is too high"

    def test_joins_multiple_values(self):
        assert apply_message_template("got %V", [1, 2, 3]) == "got 1, 2, 3"

    def test_escaped_percent_is_literal(self):
        assert apply_message_template("%V%% off", [50]) == "50% off"

    def test_no_placeholder_is_unchanged(self):
        assert apply_message_template("plain text", [9]) == "plain text"

    def test_empty_template_passthrough(self):
        assert apply_message_template("", [1]) == ""


class TestCustomMessageForStatus:
    fdef = {"errorMessage": "bad %V", "warningMessage": "hmm %V"}

    def test_error_selects_error_message(self):
        assert custom_message_for_status(self.fdef, "error", [5]) == "bad 5"

    def test_warning_selects_warning_message(self):
        assert custom_message_for_status(self.fdef, "warning", [5]) == "hmm 5"

    def test_missing_message_returns_none(self):
        assert custom_message_for_status({"errorMessage": "x"}, "warning", [1]) is None
        assert custom_message_for_status({}, "error", [1]) is None

    def test_ok_status_never_has_custom_message(self):
        assert custom_message_for_status(self.fdef, "ok", [1]) is None


def _acq(field_defs, df):
    schema = {"acquisitions": {"A": {"fields": field_defs}}}
    return check_session_compliance(in_session=df, schema_data=schema, session_map={"A": "A"})


class TestAcquisitionFieldMessages:
    def test_error_message_on_legacy_fail(self):
        df = pd.DataFrame({"Acquisition": ["A"], "MagneticFieldStrength": [7]})
        res = _acq([{"field": "MagneticFieldStrength", "value": 3,
                     "errorMessage": "%V T is not the required 3 T"}], df)
        r = next(x for x in res if x["field"] == "MagneticFieldStrength")
        assert r["status"] == "error"
        assert r["message"] == "7 T is not the required 3 T"

    def test_warning_message_on_advisory_fail(self):
        df = pd.DataFrame({"Acquisition": ["A"], "MagneticFieldStrength": [7]})
        res = _acq([{"field": "MagneticFieldStrength", "value": 3, "severity": "warning",
                     "warningMessage": "reference used 3 T, got %V T"}], df)
        r = next(x for x in res if x["field"] == "MagneticFieldStrength")
        assert r["status"] == "warning"
        assert r["message"] == "reference used 3 T, got 7 T"

    def test_graded_warn_and_error_messages(self):
        fdef = {"field": "FlipAngle", "min": 3, "max": 5, "errorMin": 2, "errorMax": 6,
                "warningMessage": "%V is a bit off", "errorMessage": "%V is way off"}
        # Warn band (5 < v <= 6).
        warn = _acq([fdef], pd.DataFrame({"Acquisition": ["A"], "FlipAngle": [5.5]}))[0]
        assert warn["status"] == "warning" and warn["message"] == "5.5 is a bit off"
        # Fail zone (v > 6).
        err = _acq([fdef], pd.DataFrame({"Acquisition": ["A"], "FlipAngle": [9]}))[0]
        assert err["status"] == "error" and err["message"] == "9 is way off"

    def test_pass_keeps_default_message(self):
        df = pd.DataFrame({"Acquisition": ["A"], "MagneticFieldStrength": [3]})
        r = _acq([{"field": "MagneticFieldStrength", "value": 3,
                   "errorMessage": "should not appear"}], df)[0]
        assert r["status"] == "ok"
        assert r["message"] != "should not appear"


class TestSeriesFieldMessages:
    def test_series_miss_uses_custom_error_message(self):
        schema = {"acquisitions": {"A": {"series": [
            {"name": "s1", "fields": [
                {"field": "EchoTime", "value": 10, "tolerance": 0.1,
                 "errorMessage": "no echo near 10 ms (saw %V)"}
            ]}
        ]}}}
        df = pd.DataFrame({"Acquisition": ["A", "A"], "EchoTime": [20, 30]})
        res = check_session_compliance(in_session=df, schema_data=schema, session_map={"A": "A"})
        miss = next(r for r in res if r["status"] == "error")
        assert "no echo near 10 ms" in miss["message"]
        assert "20" in miss["message"] and "30" in miss["message"]
