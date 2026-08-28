"""Tests for schema linting (dicompare/schema/lint.py)."""

import pytest

from dicompare.schema.lint import lint_schema, format_findings, _parse_cell


def _schema(acquisitions):
    return {
        "name": "Test Schema",
        "version": "1.0",
        "authors": ["Tester"],
        "acquisitions": acquisitions,
    }


def _acq(**overrides):
    acq = {
        "description": "Test acquisition",
        "detailed_description": "A test acquisition.",
        "fields": [{"field": "MRAcquisitionType", "tag": "0018,0023", "value": "2D"}],
        "series": [],
        "rules": [],
    }
    acq.update(overrides)
    return acq


def _codes(findings, severity=None):
    return [f.code for f in findings if severity is None or f.severity == severity]


class TestFieldChecks:
    def test_clean_schema_no_errors(self):
        findings = lint_schema(_schema({"A": _acq()}))
        assert _codes(findings, "error") == []

    def test_display_string_flagged(self):
        acq = _acq(fields=[{"field": "InPlanePhaseEncodingDirection",
                            "tag": "0018,1312", "value": "A >> P"}])
        findings = lint_schema(_schema({"A": acq}))
        assert "display-string" in _codes(findings, "warning")
        assert "vocabulary" in _codes(findings, "warning")

    def test_raw_vendor_code_flagged(self):
        acq = _acq(fields=[{"field": "CoilCombinationMethod",
                            "tag": "derived", "value": 2}])
        findings = lint_schema(_schema({"A": acq}))
        assert "vocabulary" in _codes(findings, "warning")

    def test_exact_continuous_flagged(self):
        acq = _acq(fields=[{"field": "EchoTime", "tag": "0018,0081", "value": 66}])
        findings = lint_schema(_schema({"A": acq}))
        assert "exact-continuous" in _codes(findings, "warning")

    def test_tolerance_not_flagged(self):
        acq = _acq(fields=[{"field": "EchoTime", "tag": "0018,0081",
                            "value": 66, "tolerance": 5}])
        findings = lint_schema(_schema({"A": acq}))
        assert "exact-continuous" not in _codes(findings)

    def test_series_fields_linted(self):
        acq = _acq(series=[{"name": "S1", "fields": [
            {"field": "InPlanePhaseEncodingDirection", "value": "A >> P"}]}])
        findings = lint_schema(_schema({"A": acq}))
        assert "display-string" in _codes(findings, "warning")

    def test_empty_detailed_description_flagged(self):
        acq = _acq(detailed_description="")
        findings = lint_schema(_schema({"A": acq}))
        assert "empty-description" in _codes(findings, "warning")


def _rule(impl, fields, test_cases=None, rule_id="r1"):
    return {
        "id": rule_id,
        "name": "Test rule",
        "description": "",
        "implementation": impl,
        "fields": fields,
        "testCases": test_cases or [],
    }


class TestRuleChecks:
    def test_undeclared_field_read_is_error(self):
        rule = _rule('x = value["EchoTime"][0]', fields=["RepetitionTime"])
        findings = lint_schema(_schema({"A": _acq(rules=[rule])}))
        assert "undeclared-field" in _codes(findings, "error")

    def test_count_column_read_not_flagged(self):
        # "Count" is a synthetic column the harness always injects.
        rule = _rule('n = value["Count"][0]', fields=["EchoTime"])
        findings = lint_schema(_schema({"A": _acq(rules=[rule])}))
        assert "undeclared-field" not in _codes(findings)

    def test_field_read_in_comment_not_flagged(self):
        # Regression: value["FieldName"] inside a comment is not a read.
        rule = _rule(
            '# Access field data with value["FieldName"]\n'
            'x = value["EchoTime"][0]',
            fields=["EchoTime"])
        findings = lint_schema(_schema({"A": _acq(rules=[rule])}))
        assert "undeclared-field" not in _codes(findings)

    def test_syntax_error_is_error(self):
        rule = _rule('def broken(:', fields=[])
        findings = lint_schema(_schema({"A": _acq(rules=[rule])}))
        assert "syntax-error" in _codes(findings, "error")

    def test_no_test_cases_is_warning(self):
        rule = _rule('pass', fields=["EchoTime"])
        findings = lint_schema(_schema({"A": _acq(rules=[rule])}))
        assert "no-test-cases" in _codes(findings, "warning")

    def test_duplicate_rule_ids_across_acquisitions_not_flagged(self):
        # Rules are scoped to an acquisition; there is no shared-rule
        # mechanism, so id reuse across acquisitions is meaningless noise.
        r = _rule('pass', fields=["EchoTime"])
        findings = lint_schema(_schema({
            "A": _acq(rules=[dict(r)]),
            "B": _acq(rules=[dict(r)]),
        }))
        assert "duplicate-id" not in _codes(findings)

    def test_duplicate_rule_ids_within_acquisition_is_error(self):
        # Within one acquisition a collision silently drops a rule.
        findings = lint_schema(_schema({
            "A": _acq(rules=[_rule('pass', fields=["EchoTime"]),
                             _rule('pass', fields=["EchoTime"])]),
        }))
        assert "duplicate-id" in _codes(findings, "error")

    def test_passing_and_failing_cases_executed(self):
        rule = _rule(
            'if float(value["EchoTime"][0]) > 100:\n'
            '    raise ValidationError("TE too long")',
            fields=["EchoTime"],
            test_cases=[
                {"id": "t1", "name": "ok", "data": {"EchoTime": ["66"]},
                 "expectedResult": "pass"},
                {"id": "t2", "name": "too long", "data": {"EchoTime": ["150"]},
                 "expectedResult": "fail"},
            ])
        findings = lint_schema(_schema({"A": _acq(rules=[rule])}))
        assert "test-failed" not in _codes(findings)
        assert "test-error" not in _codes(findings)

    def test_wrong_expectation_is_error(self):
        rule = _rule(
            'raise ValidationError("always fails")',
            fields=["EchoTime"],
            test_cases=[{"id": "t1", "name": "expected pass",
                         "data": {"EchoTime": ["66"]},
                         "expectedResult": "pass"}])
        findings = lint_schema(_schema({"A": _acq(rules=[rule])}))
        assert "test-failed" in _codes(findings, "error")

    def test_list_cells_arrive_as_tuples(self):
        # Production-faithful: "[0, 1000]" string cells become tuples, so a
        # rule using as_list() passes and one using ast.literal_eval fails.
        rule = _rule(
            'bvals = as_list(value["DiffusionBValues"][0])\n'
            'if 1000 not in bvals:\n'
            '    raise ValidationError("missing b=1000")',
            fields=["DiffusionBValues"],
            test_cases=[{"id": "t1", "name": "has shell",
                         "data": {"DiffusionBValues": ["[0, 1000]"]},
                         "expectedResult": "pass"}])
        findings = lint_schema(_schema({"A": _acq(rules=[rule])}))
        assert "test-failed" not in _codes(findings)


class TestStructural:
    def test_metaschema_violation_is_error(self):
        findings = lint_schema({"description": "no name or acquisitions"})
        assert "metaschema" in _codes(findings, "error")


class TestHelpers:
    def test_parse_cell(self):
        assert _parse_cell("[0, 1000]") == [0, 1000]
        assert _parse_cell("5") == 5
        assert _parse_cell("2.5") == 2.5
        assert _parse_cell("full-sphere") == "full-sphere"
        assert _parse_cell(7) == 7

    def test_format_markdown(self):
        findings = lint_schema(_schema({"A": _acq(fields=[
            {"field": "CoilCombinationMethod", "value": 2}])}))
        md = format_findings(findings, "markdown")
        assert "Warnings" in md
        assert "CoilCombinationMethod" in md

    def test_format_no_findings(self):
        assert "no issues" in format_findings([], "markdown").lower()
