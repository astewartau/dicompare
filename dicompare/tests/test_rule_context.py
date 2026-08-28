"""Tests for the v2 rule API (RuleContext / ctx) in validation/core.py."""

import pandas as pd
import pytest

from dicompare.validation.core import (
    RuleContext,
    ValidationError,
    ValidationWarning,
    create_validation_model_from_rules,
)


def _run(implementation, data, fields=None):
    """Run one rule implementation against a one-acquisition DataFrame."""
    rule = {
        "id": "r1",
        "name": "Test rule",
        "fields": fields or list(data.keys()),
        "implementation": implementation,
    }
    rows = []
    n = max(len(v) for v in data.values())
    for i in range(n):
        row = {"Acquisition": "acq"}
        for k, v in data.items():
            row[k] = v[i]
        rows.append(row)
    model = create_validation_model_from_rules("acq", [rule])
    return model.validate(pd.DataFrame(rows))


class TestSeverities:
    def test_ctx_error_fails(self):
        _ok, errors, warnings, _p = _run(
            'ctx.error("bad value")', {"EchoTime": [66]})
        assert len(errors) == 1 and "bad value" in errors[0]["message"]
        assert not warnings

    def test_ctx_warn_warns(self):
        _ok, errors, warnings, _p = _run(
            'ctx.warn("could be better")', {"EchoTime": [66]})
        assert not errors
        assert len(warnings) == 1 and "could be better" in warnings[0]["message"]

    def test_errors_include_warnings_for_context(self):
        _ok, errors, warnings, _p = _run(
            'ctx.error("bad")\nctx.warn("also meh")', {"EchoTime": [66]})
        assert len(errors) == 1
        assert "bad" in errors[0]["message"]
        assert "also meh" in errors[0]["message"]
        assert not warnings

    def test_no_findings_passes(self):
        _ok, errors, warnings, passes = _run('pass', {"EchoTime": [66]})
        assert not errors and not warnings and len(passes) == 1

    def test_explicit_raise_still_works(self):
        _ok, errors, _w, _p = _run(
            'raise ValidationError("old style")', {"EchoTime": [66]})
        assert len(errors) == 1 and "old style" in errors[0]["message"]


class TestTypedAccess:
    def test_rows_convert_tuples_to_lists(self):
        _ok, errors, _w, _p = _run(
            'bvals = ctx.rows[0]["DiffusionBValues"]\n'
            'if not isinstance(bvals, list):\n'
            '    ctx.error("expected a list, got " + type(bvals).__name__)',
            {"DiffusionBValues": [(0, 1000)]})
        assert not errors

    def test_get_converts_tuples(self):
        _ok, errors, _w, _p = _run(
            'for bvals in ctx.get("DiffusionBValues"):\n'
            '    if 1000 not in bvals:\n'
            '        ctx.error("missing shell")',
            {"DiffusionBValues": [(0, 1000), (0, 1000, 3000)]})
        assert not errors

    def test_get_missing_field_raises_helpful_error(self):
        _ok, errors, _w, _p = _run(
            'ctx.get("NotDeclared")', {"EchoTime": [66]})
        assert len(errors) == 1
        assert "declare" in errors[0]["message"]

    def test_registry_number_coercion_from_string(self):
        # NumberOfB0Volumes is number-typed in the registry; a string cell
        # (hand-written test data) coerces to float.
        _ok, errors, _w, _p = _run(
            'n = ctx.rows[0]["NumberOfB0Volumes"]\n'
            'if not isinstance(n, float) or n != 5.0:\n'
            '    ctx.error("expected 5.0, got " + repr(n))',
            {"NumberOfB0Volumes": ["5"]})
        assert not errors

    def test_registry_list_coercion_from_string(self):
        # DiffusionBValues is list_number-typed; a string repr cell parses.
        _ok, errors, _w, _p = _run(
            'bvals = ctx.rows[0]["DiffusionBValues"]\n'
            'if bvals != [0, 1000]:\n'
            '    ctx.error("expected [0, 1000], got " + repr(bvals))',
            {"DiffusionBValues": ["[0, 1000]"]})
        assert not errors

    def test_legacy_value_dataframe_still_available(self):
        _ok, errors, _w, _p = _run(
            'if float(value["EchoTime"][0]) > 100:\n'
            '    raise ValidationError("too long")',
            {"EchoTime": [66]})
        assert not errors


class TestOptionalFields:
    def _run_rule(self, rule, data):
        rows = []
        n = max(len(v) for v in data.values())
        for i in range(n):
            row = {"Acquisition": "acq"}
            for k, v in data.items():
                row[k] = v[i]
            rows.append(row)
        model = create_validation_model_from_rules("acq", [rule])
        return model.validate(pd.DataFrame(rows))

    VENDOR_RULE = {
        "id": "r1",
        "name": "Vendor polarity",
        "fields": ["Manufacturer"],
        "optional_fields": ["PhaseEncodingDirectionPositive",
                            "RectilinearPhaseEncodeReordering"],
        "implementation": (
            'm = str(value["Manufacturer"][0]).upper()\n'
            'if "SIEMENS" in m:\n'
            '    if "PhaseEncodingDirectionPositive" in value.columns:\n'
            '        if int(value["PhaseEncodingDirectionPositive"][0]) != 0:\n'
            '            raise ValidationError("wrong polarity")\n'
            '    else:\n'
            '        raise ValidationWarning("polarity unknown")\n'),
    }

    def test_absent_optional_field_is_not_an_error(self):
        # A Siemens session has no GE column; the rule must still run.
        _ok, errors, warnings, _p = self._run_rule(self.VENDOR_RULE, {
            "Manufacturer": ["SIEMENS"],
            "PhaseEncodingDirectionPositive": [0],
        })
        assert not errors and not warnings

    def test_all_optional_fields_absent_rule_still_runs(self):
        _ok, errors, warnings, _p = self._run_rule(self.VENDOR_RULE, {
            "Manufacturer": ["SIEMENS"],
        })
        assert not errors
        assert len(warnings) == 1 and "polarity unknown" in warnings[0]["message"]

    def test_missing_required_field_still_errors(self):
        _ok, errors, _w, _p = self._run_rule(self.VENDOR_RULE, {
            "PhaseEncodingDirectionPositive": [0],
        })
        assert len(errors) == 1 and "Missing fields" in errors[0]["message"]
        assert "Manufacturer" in errors[0]["message"]


class TestFinish:
    def test_finish_raises_error_over_warning(self):
        ctx = RuleContext(pd.DataFrame({"A": [1]}))
        ctx.warn("w")
        ctx.error("e")
        with pytest.raises(ValidationError):
            ctx.finish()

    def test_finish_raises_warning_alone(self):
        ctx = RuleContext(pd.DataFrame({"A": [1]}))
        ctx.warn("w")
        with pytest.raises(ValidationWarning):
            ctx.finish()

    def test_finish_noop_when_clean(self):
        RuleContext(pd.DataFrame({"A": [1]})).finish()
