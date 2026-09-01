"""Tests for graded (three-way pass/warn/fail) field validation.

Graded validation is opt-in: a field only takes the new path when it carries an
error-edge key (errorMin / errorMax / errorTolerance). Fields without them keep the
legacy pass/fail behaviour, so existing schemas are unaffected — that invariant is
pinned here too.
"""

import pytest
from dicompare.validation.helpers import field_has_graded_edges, validate_field_graded


def status(fdef, value):
    st, _, _ = validate_field_graded("F", [value], fdef)
    return st


class TestHasGradedEdges:
    def test_opt_in_by_error_keys(self):
        assert field_has_graded_edges({"errorMin": 2}) is True
        assert field_has_graded_edges({"errorMax": 6}) is True
        assert field_has_graded_edges({"errorTolerance": 1}) is True

    def test_legacy_fields_are_not_graded(self):
        assert field_has_graded_edges({"value": 3}) is False
        assert field_has_graded_edges({"min": 3, "max": 5}) is False
        assert field_has_graded_edges({"value": 3, "tolerance": 0.1}) is False
        assert field_has_graded_edges({"value": 3, "severity": "warning"}) is False


class TestGradedRange:
    fdef = {"min": 3, "max": 5, "errorMin": 2, "errorMax": 6}

    def test_pass_inside_target(self):
        assert status(self.fdef, 4) == "ok"
        assert status(self.fdef, 3) == "ok"
        assert status(self.fdef, 5) == "ok"

    def test_warn_between_target_and_error(self):
        assert status(self.fdef, 2.5) == "warning"
        assert status(self.fdef, 5.5) == "warning"

    def test_fail_beyond_error(self):
        assert status(self.fdef, 1) == "error"
        assert status(self.fdef, 7) == "error"

    def test_asymmetric_open_side_warns_forever(self):
        # errorMax only: below the target has no error edge, so it only ever warns
        fdef = {"min": 3, "max": 5, "errorMax": 6}
        assert status(fdef, 4) == "ok"
        assert status(fdef, 0) == "warning"   # far below, but no lower fail edge
        assert status(fdef, 5.5) == "warning"
        assert status(fdef, 7) == "error"     # above errorMax


class TestGradedExact:
    fdef = {"value": 3, "errorMin": 2, "errorMax": 4}

    def test_pass_only_at_value(self):
        assert status(self.fdef, 3) == "ok"

    def test_warn_within_error(self):
        assert status(self.fdef, 2.5) == "warning"
        assert status(self.fdef, 3.5) == "warning"

    def test_fail_beyond_error(self):
        assert status(self.fdef, 1) == "error"
        assert status(self.fdef, 5) == "error"


class TestGradedTolerance:
    fdef = {"value": 3, "tolerance": 0.5, "errorTolerance": 1.0}

    def test_pass_within_tolerance(self):
        assert status(self.fdef, 3) == "ok"
        assert status(self.fdef, 2.6) == "ok"

    def test_warn_within_error_tolerance(self):
        assert status(self.fdef, 2.3) == "warning"
        assert status(self.fdef, 3.7) == "warning"

    def test_fail_beyond_error_tolerance(self):
        assert status(self.fdef, 1.5) == "error"
        assert status(self.fdef, 4.5) == "error"

    def test_list_number_per_element(self):
        # tolerance/errorTolerance apply per element for list_number fields
        fdef = {"value": 3, "tolerance": 0.5, "errorTolerance": 1.0}
        st, _, _ = validate_field_graded("F", [(3.0, 2.6)], fdef)
        assert st == "ok"
        st, _, _ = validate_field_graded("F", [(3.0, 2.2)], fdef)   # one element in warn band
        assert st == "warning"
        st, _, _ = validate_field_graded("F", [(3.0, 4.5)], fdef)   # one element past error
        assert st == "error"
