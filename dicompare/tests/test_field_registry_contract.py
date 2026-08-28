"""
Contract test: every importer's output must satisfy the canonical field
registry.

This is the enforcement layer for dicompare/fields.py — it runs each protocol
importer over its real fixtures and asserts that every emitted value is within
the field's declared vocabulary and free of console display strings. A new
importer (or a change to an existing one) that leaks a raw vendor code or a
display value fails here instead of failing silently against real data later.
"""

from pathlib import Path

import pytest

from dicompare.fields import check_value

FIXTURES = Path(__file__).parent / "fixtures"

PRINTPROT_FILES = sorted((FIXTURES / "printprot").glob("*"))
PRO_FILES = sorted((FIXTURES / "pro_files").glob("*.pro"))


def _assert_fields_canonical(fields, context):
    problems = []
    for keyword, value in fields.items():
        problems.extend(f"{context}: {p}" for p in check_value(keyword, value))
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", PRINTPROT_FILES, ids=lambda p: p.name)
def test_printprot_output_is_canonical(path):
    from dicompare.io.printprot import load_printprot_file

    protocols = load_printprot_file(str(path))
    assert protocols, f"no protocols parsed from {path.name}"
    for proto in protocols:
        _assert_fields_canonical(proto["fields"], f"{path.name}:{proto['protocol_name']}")


@pytest.mark.parametrize("path", PRO_FILES, ids=lambda p: p.name)
def test_pro_output_is_canonical(path):
    from dicompare.io.pro import load_pro_file

    fields = load_pro_file(str(path))
    assert fields, f"no fields parsed from {path.name}"
    _assert_fields_canonical(fields, path.name)


def test_dicom_output_is_canonical():
    from dicompare.io.dicom import load_dicom

    ref = FIXTURES / "ref_dicom.dcm"
    if not ref.exists():
        pytest.skip("reference DICOM fixture missing")
    fields = load_dicom(str(ref))
    _assert_fields_canonical(fields, ref.name)


def test_cross_importer_vocabulary_consistency():
    """
    The same field emitted by different importers must use the same
    vocabulary. Phase encoding is the canary: printprot converts console
    display values, pro converts Siemens codes — both must land on ROW/COL.
    """
    from dicompare.io.printprot import load_printprot_file
    from dicompare.io.pro import load_pro_file

    seen = set()
    for path in PRINTPROT_FILES:
        for proto in load_printprot_file(str(path)):
            v = proto["fields"].get("InPlanePhaseEncodingDirection")
            if v is not None:
                seen.add(v)
    for path in PRO_FILES:
        v = load_pro_file(str(path)).get("InPlanePhaseEncodingDirection")
        if v is not None:
            seen.add(v)

    assert seen, "no phase-encoding values emitted by any importer"
    assert seen <= {"ROW", "COL"}, f"non-canonical phase encoding values: {seen}"
