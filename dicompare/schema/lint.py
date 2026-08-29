"""
Schema linting.

Machine checks for dicompare validation schemas, mirroring (and extending) the
web schema editor's lint. Used by the CLI (``dicompare lint``) and by the
schema-submission CI gate in dicompare-web, so problems like console display
strings, raw vendor codes, self-failing rules, and duplicate ids are caught at
submission time instead of during a human review.

Severities:
    error   — the schema is structurally broken or demonstrably wrong
              (fails metaschema, duplicate ids, rules reading undeclared
              fields, rule test cases that do not produce their expected
              result). CI fails on these.
    warning — the constraint will likely not match real data or falls short
              of best practice (out-of-vocabulary values, display strings,
              exact matches on continuous fields, missing test coverage).
              CI reports these without failing.
"""

import ast
import json

from dataclasses import dataclass
from typing import Any, Dict, List

from ..fields import check_value, get_field

__all__ = ["LintFinding", "lint_schema", "format_findings"]


@dataclass
class LintFinding:
    severity: str   # "error" | "warning"
    code: str       # machine-readable check name
    location: str   # human-readable path within the schema
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"severity": self.severity, "code": self.code,
                "location": self.location, "message": self.message}


# Constraint keys that make a field definition something other than an exact
# match (mirrors the metaschema's constraint types).
_NON_EXACT_KEYS = ("tolerance", "min", "max", "contains", "contains_any", "contains_all")

def _fields_read_by(impl: str):
    """
    AST-parse a rule implementation and return the set of field names it reads
    via value["Field"] subscripts (ignoring comments and strings), or a
    SyntaxError if the code does not parse.
    """
    try:
        tree = ast.parse(impl)
    except SyntaxError as e:
        return None, e
    read = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "value"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            read.add(node.slice.value)
    return read, None


def _parse_cell(cell: Any) -> Any:
    """
    Parse one test-case cell the way the web editor does (testCaseCells.ts):
    "[0, 1000]" -> [0, 1000], "5" -> 5, other strings kept verbatim.
    """
    if not isinstance(cell, str):
        return cell
    s = cell.strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return cell
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return cell


def _lint_metaschema(schema: Dict[str, Any], findings: List[LintFinding]) -> None:
    try:
        from ..io.json import validate_schema
        validate_schema(schema)
    except Exception as e:  # jsonschema.ValidationError or load issues
        findings.append(LintFinding(
            "error", "metaschema", "schema",
            f"Schema does not validate against the dicompare metaschema: {e}"))


def _lint_field(fdef: Dict[str, Any], location: str, findings: List[LintFinding]) -> None:
    keyword = fdef.get("field", "")
    value = fdef.get("value")

    # Registry checks: vocabulary and console display strings.
    if value is not None:
        for problem in check_value(keyword, value):
            code = "display-string" if "display string" in problem else "vocabulary"
            findings.append(LintFinding("warning", code, location, problem))

    # Exact match on a continuous physical parameter is brittle — but only as
    # a requirement. A warning-severity constraint is a reference annotation
    # ("this is what the reference used"), where an exact value is honest.
    reg = get_field(keyword)
    is_exact = value is not None and not any(k in fdef for k in _NON_EXACT_KEYS)
    is_requirement = fdef.get("severity") != "warning"
    if reg is not None and reg.continuous and is_exact and is_requirement:
        findings.append(LintFinding(
            "warning", "exact-continuous", location,
            f"Exact match on continuous field {keyword} is brittle — real "
            f"scans vary slightly. Consider a ± tolerance, or mark the "
            f"constraint severity 'warning' if it is reference information."))


def _lint_rule(rule: Dict[str, Any], location: str, findings: List[LintFinding]) -> None:
    impl = rule.get("implementation", "") or ""
    declared = set(rule.get("fields", []) or []) | set(rule.get("optional_fields", []) or [])

    # Fields the implementation reads but does not declare: at runtime the
    # rule receives ONLY declared columns, so this is a guaranteed failure.
    read, syntax_error = _fields_read_by(impl)
    if syntax_error is not None:
        findings.append(LintFinding(
            "error", "syntax-error", location,
            f"Implementation does not parse as Python: {syntax_error}"))
        return
    # "Count" is a synthetic column the validation harness always injects
    # (slice/file count per unique value combination) — reading it is fine.
    for missing in sorted(read - declared - {"Count"}):
        findings.append(LintFinding(
            "error", "undeclared-field", location,
            f"Implementation reads value[\"{missing}\"] but the rule's "
            f"'fields' list does not declare it — the rule will fail on "
            f"every dataset."))

    # Test coverage.
    test_cases = rule.get("testCases", []) or []
    if not test_cases:
        findings.append(LintFinding(
            "warning", "no-test-cases", location,
            "Rule has no test cases. Add at least one passing and one "
            "failing case (the schema's own example values make a good "
            "passing case)."))
        return
    expectations = {tc.get("expectedResult") for tc in test_cases}
    if "pass" not in expectations:
        findings.append(LintFinding(
            "warning", "no-passing-test", location,
            "Rule has no passing test case, so nothing verifies that "
            "conforming data is accepted."))

    # Execute every test case through the production validation path.
    from ..interface.web_utils import run_rule_test_case
    for tc in test_cases:
        tc_name = tc.get("name") or tc.get("id") or "unnamed"
        tc_loc = f"{location}.testCases[{tc_name}]"
        data = {
            field: [_parse_cell(cell) for cell in cells] if isinstance(cells, list)
            else [_parse_cell(cells)]
            for field, cells in (tc.get("data") or {}).items()
        }
        try:
            outcome = run_rule_test_case(rule, data, params=tc.get("params"))
        except Exception as e:
            findings.append(LintFinding(
                "error", "test-error", tc_loc,
                f"Test case could not be executed: {e}"))
            continue
        expected = tc.get("expectedResult")
        if expected and outcome.get("result") != expected:
            findings.append(LintFinding(
                "error", "test-failed", tc_loc,
                f"Expected '{expected}' but got '{outcome.get('result')}'"
                f" ({outcome.get('message') or 'no message'})"))


def lint_schema(schema: Dict[str, Any]) -> List[LintFinding]:
    """Lint a schema dict. Returns findings (possibly empty)."""
    findings: List[LintFinding] = []

    _lint_metaschema(schema, findings)

    for acq_name, acq in (schema.get("acquisitions") or {}).items():
        if not isinstance(acq, dict):
            continue
        base = f"acquisitions[{acq_name}]"

        if not (acq.get("detailed_description") or "").strip():
            findings.append(LintFinding(
                "warning", "empty-description", base,
                "Acquisition has no detailed description."))

        for fdef in acq.get("fields", []) or []:
            _lint_field(fdef, f"{base}.fields[{fdef.get('field', '?')}]", findings)
        for series in acq.get("series", []) or []:
            for fdef in series.get("fields", []) or []:
                _lint_field(
                    fdef,
                    f"{base}.series[{series.get('name', '?')}].fields[{fdef.get('field', '?')}]",
                    findings)

        # Ids only need to be unique within their container: rules are scoped
        # to an acquisition (a within-acquisition collision silently drops a
        # rule when the validation model is built) and test cases to a rule.
        # Reuse across acquisitions is meaningless and harmless — there is no
        # shared-rule mechanism — so it is not flagged at all.
        seen_rule_ids: Dict[str, str] = {}
        for rule in acq.get("rules", []) or []:
            rid = rule.get("id", "?")
            loc = f"{base}.rules[{rid}]"
            if rid in seen_rule_ids:
                findings.append(LintFinding(
                    "error", "duplicate-id", loc,
                    f"Rule id '{rid}' is used twice in this acquisition — "
                    f"one of the rules will be silently dropped."))
            else:
                seen_rule_ids[rid] = loc
            seen_test_ids: Dict[str, str] = {}
            for tc in rule.get("testCases", []) or []:
                tid = tc.get("id", "?")
                if tid in seen_test_ids:
                    findings.append(LintFinding(
                        "error", "duplicate-id", f"{loc}.testCases[{tid}]",
                        f"Test case id '{tid}' is used twice in this rule."))
                else:
                    seen_test_ids[tid] = loc
            _lint_rule(rule, loc, findings)

    return findings


def format_findings(findings: List[LintFinding], fmt: str = "text") -> str:
    """Render findings as 'text', 'json', or 'markdown'."""
    if fmt == "json":
        return json.dumps([f.to_dict() for f in findings], indent=2)

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if fmt == "markdown":
        if not findings:
            return "**Schema lint:** no issues found."
        lines = [f"**Schema lint:** {len(errors)} error(s), {len(warnings)} warning(s)", ""]
        for label, group in (("Errors", errors), ("Warnings", warnings)):
            if group:
                lines.append(f"### {label}")
                for f in group:
                    lines.append(f"- `{f.location}` ({f.code}): {f.message}")
                lines.append("")
        return "\n".join(lines).rstrip()

    if not findings:
        return "No issues found."
    lines = []
    for f in findings:
        lines.append(f"{f.severity.upper():7} {f.code:18} {f.location}: {f.message}")
    lines.append(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return "\n".join(lines)
