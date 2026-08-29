"""Tests for parameterized validation rules (params / ctx.params injection)."""

import pandas as pd
import pytest

from dicompare import create_validation_model_from_rules, resolve_rule_params
from dicompare.interface.schema_tools import run_rule_test_case


ECHO_IMPL = """
n = value["EchoTime"].dropna().nunique()
if n < params["min_echoes"]:
    raise ValidationError(f"Only {n} echoes; need >= {params['min_echoes']}")
if params.get("warn_below") and n < params["warn_below"]:
    raise ValidationWarning(f"Found {n} echoes; {params['warn_below']}+ recommended")
"""

ECHO_RULE = {
    "id": "echo_count",
    "name": "Echo Count",
    "fields": ["EchoTime"],
    "implementation": ECHO_IMPL,
    "parameterDefinitions": [
        {"name": "min_echoes", "type": "number", "default": 3},
        {"name": "warn_below", "type": "number", "default": None},
    ],
}


def _df(n_echoes):
    return pd.DataFrame({
        "Acquisition": ["a"] * n_echoes,
        "EchoTime": list(range(1, n_echoes + 1)),
    })


class TestResolveRuleParams:
    def test_dict_passthrough(self):
        assert resolve_rule_params({"x": 1}) == {"x": 1}

    def test_declaration_defaults(self):
        decls = [{"name": "x", "type": "number", "default": 5}, {"name": "y", "type": "string"}]
        assert resolve_rule_params(decls) == {"x": 5, "y": None}

    def test_null_and_garbage(self):
        assert resolve_rule_params(None) == {}
        assert resolve_rule_params("nope") == {}
        assert resolve_rule_params([{"no_name": 1}]) == {}


class TestParamsInjection:
    def test_declaration_defaults_used(self):
        model = create_validation_model_from_rules("a", [ECHO_RULE])
        ok, errors, warnings, passes = model.validate(_df(4))
        assert ok and not errors

    def test_configured_value_overrides_default(self):
        rule = dict(ECHO_RULE, parameters={"min_echoes": 8})
        model = create_validation_model_from_rules("a", [rule])
        ok, errors, warnings, passes = model.validate(_df(4))
        assert not ok
        assert "need >= 8" in errors[0]["message"]

    def test_ctx_params(self):
        impl = """
n = len(set(ctx.get("EchoTime")))
if n < ctx.params["min_echoes"]:
    ctx.error(f"Only {n} echoes")
"""
        rule = {"id": "r", "name": "r", "fields": ["EchoTime"],
                "implementation": impl, "parameters": {"min_echoes": 8}}
        model = create_validation_model_from_rules("a", [rule])
        ok, errors, warnings, passes = model.validate(_df(4))
        assert not ok

    def test_rule_without_params_unaffected(self):
        rule = {"id": "x", "name": "x", "fields": ["EchoTime"],
                "implementation": 'n = value["EchoTime"].nunique()\n'
                                  'if n < 2: raise ValidationError("nope")'}
        model = create_validation_model_from_rules("a", [rule])
        ok, errors, warnings, passes = model.validate(_df(2))
        assert ok


class TestRunRuleTestCaseParams:
    def test_configured_params_apply(self):
        rule = dict(ECHO_RULE, parameters={"min_echoes": 8})
        result = run_rule_test_case(rule, {"EchoTime": [1, 2, 3, 4]})
        assert result["result"] == "fail"

    def test_per_test_case_override(self):
        rule = dict(ECHO_RULE, parameters={"min_echoes": 8})
        result = run_rule_test_case(rule, {"EchoTime": [1, 2, 3, 4]},
                                    params={"min_echoes": 4})
        assert result["result"] == "pass"

    def test_override_can_trigger_warning(self):
        rule = dict(ECHO_RULE, parameters={"min_echoes": 8})
        result = run_rule_test_case(rule, {"EchoTime": [1, 2, 3, 4]},
                                    params={"min_echoes": 4, "warn_below": 6})
        assert result["result"] == "warning"
