"""
Targeted unit tests to top up coverage of several smaller dicompare modules.

Covers edge cases / error paths in:
  - dicompare/io/dicom_generator.py
  - dicompare/schema/tags.py
  - dicompare/io/printprot.py
  - dicompare/validation/compliance.py
  - dicompare/io/special_fields.py
  - dicompare/io/gradients.py
  - dicompare/validation/helpers.py
  - dicompare/schemas/__init__.py
  - dicompare/schema/build_schema.py
"""

import io
import json
import zipfile

import pandas as pd
import pydicom
import pytest


# ---------------------------------------------------------------------------
# dicompare/io/dicom_generator.py
# ---------------------------------------------------------------------------
from dicompare.io import generate_test_dicoms_from_schema


def _read_first_dicom(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = sorted(zf.namelist())
        return [pydicom.dcmread(io.BytesIO(zf.read(n))) for n in names]


def test_dicom_generator_invalid_tag_is_skipped(capsys):
    """A malformed tag string is skipped (hits the except branch)."""
    test_data = [{"BadField": 5, "RepetitionTime": 2000}]
    field_definitions = [
        {"name": "BadField", "tag": "notahex,zz", "vr": "DS"},
        {"name": "RepetitionTime", "tag": "0018,0080", "vr": "DS"},
    ]
    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)
    ds = _read_first_dicom(zip_bytes)[0]
    assert str(ds.RepetitionTime) == "2000.0"
    out = capsys.readouterr().out
    assert "Skipping invalid tag" in out


def test_dicom_generator_series_grouping_shares_uid():
    """Rows with the same _seriesIndex share a SeriesInstanceUID and series name."""
    test_data = [
        {"_seriesIndex": 0, "_seriesName": "SeriesA", "RepetitionTime": 2000},
        {"_seriesIndex": 0, "_seriesName": "SeriesA", "RepetitionTime": 2000},
        {"_seriesIndex": 1, "_seriesName": "SeriesB", "RepetitionTime": 3000},
    ]
    field_definitions = [{"name": "RepetitionTime", "tag": "0018,0080", "vr": "DS"}]
    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)
    dss = _read_first_dicom(zip_bytes)
    assert dss[0].SeriesInstanceUID == dss[1].SeriesInstanceUID
    assert dss[0].SeriesInstanceUID != dss[2].SeriesInstanceUID
    assert dss[0].SeriesDescription == "SeriesA"
    assert dss[2].SeriesDescription == "SeriesB"


def test_dicom_generator_vr_numeric_variants():
    """Exercise DS/IS/FL/FD/US single-value and list conversions across VR types."""
    test_data = [
        {
            "InstanceNumber": 7,                              # IS single
            "ImageOrientationPatient": [1, 0, 0, 0, 1, 0],   # DS list of ints
            "AcquisitionMatrix": [64, 64],                   # US list -> integers
            "AcquisitionNumber": [1, 2],                     # IS list -> string list
            "TableHeight": 155.5,                            # DS single
        }
    ]
    field_definitions = [
        {"name": "InstanceNumber", "tag": "0020,0013", "vr": "IS"},
        {"name": "ImageOrientationPatient", "tag": "0020,0037", "vr": "DS"},
        {"name": "AcquisitionMatrix", "tag": "0018,1310", "vr": "US"},
        {"name": "AcquisitionNumber", "tag": "0020,0012", "vr": "IS"},
        {"name": "TableHeight", "tag": "0018,1130", "vr": "DS"},
    ]
    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)
    ds = _read_first_dicom(zip_bytes)[0]
    assert list(ds.AcquisitionMatrix) == [64, 64]
    assert int(ds.InstanceNumber) == 7
    assert len(ds.ImageOrientationPatient) == 6


def test_dicom_generator_float_vr_single_and_list():
    """FL/FD VR types keep numeric single values and lists (lines 229, 243)."""
    test_data = [
        {
            "DiffusionBValue": 1000.0,                       # FD single -> float
            "DiffusionGradientOrientation": [1.0, 0.0, 0.0],  # FD list -> floats
        }
    ]
    field_definitions = [
        {"name": "DiffusionBValue", "tag": "0018,9087", "vr": "FD"},
        {"name": "DiffusionGradientOrientation", "tag": "0018,9089", "vr": "FD"},
    ]
    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)
    ds = _read_first_dicom(zip_bytes)[0]
    assert float(ds.DiffusionBValue) == 1000.0
    assert list(ds.DiffusionGradientOrientation) == [1.0, 0.0, 0.0]


def test_dicom_generator_string_field_and_none():
    """String VR fields and a None value take the string branches."""
    test_data = [{"SequenceName": "epfid2d1_64", "PatientPosition": None}]
    field_definitions = [
        {"name": "SequenceName", "tag": "0018,0024", "vr": "SH"},
        {"name": "PatientPosition", "tag": "0018,5100", "vr": "CS"},
    ]
    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)
    ds = _read_first_dicom(zip_bytes)[0]
    assert ds.SequenceName == "epfid2d1_64"


def test_dicom_generator_uncastable_value_is_caught(capsys):
    """A value that cannot be cast for its VR is caught and skipped (except branch)."""
    # RepetitionTime is DS; a non-numeric string triggers float() failure inside the
    # try block -> caught, warning printed, generation still succeeds.
    test_data = [{"RepetitionTime": ["not_a_number"], "EchoTime": 2.46}]
    field_definitions = [
        {"name": "RepetitionTime", "tag": "0018,0080", "vr": "DS"},
        {"name": "EchoTime", "tag": "0018,0081", "vr": "DS"},
    ]
    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)
    ds = _read_first_dicom(zip_bytes)[0]
    assert str(ds.EchoTime) == "2.46"
    assert "Could not set RepetitionTime" in capsys.readouterr().out


def test_dicom_generator_special_multiband_field():
    """A handled special field (MultibandFactor) is encoded and sets Manufacturer."""
    test_data = [{"MultibandFactor": 3, "RepetitionTime": 2000}]
    field_definitions = [
        {"name": "MultibandFactor", "tag": ""},
        {"name": "RepetitionTime", "tag": "0018,0080", "vr": "DS"},
    ]
    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)
    ds = _read_first_dicom(zip_bytes)[0]
    assert ds.ImageComments == "Unaliased MB3/PE2"
    assert ds.Manufacturer == "SIEMENS"


def test_dicom_generator_unknown_tag_frontend_vr_fallback():
    """A valid-format tag unknown to pydicom falls back to the frontend VR (except branch)."""
    test_data = [{"MyPrivate": 5}]
    # (0011,1010) is not a standard keyword -> dictionary_VR raises KeyError and
    # actual_vr falls back to the frontend VR ('US'); generation still succeeds.
    field_definitions = [{"name": "MyPrivate", "tag": "0011,1010", "vr": "US"}]
    zip_bytes = generate_test_dicoms_from_schema(test_data, field_definitions)
    dss = _read_first_dicom(zip_bytes)
    assert len(dss) == 1  # DICOM generated without error


# ---------------------------------------------------------------------------
# dicompare/io/special_fields.py
# ---------------------------------------------------------------------------
from dicompare.io.special_fields import (
    categorize_field,
    apply_special_field_encoding,
    encode_multiband_in_image_comments,
)


def test_categorize_field_valid_format_unknown_tag_is_standard():
    """A valid-format tag (even one pydicom cannot name) is categorized as standard."""
    category, _desc = categorize_field("SomeField", "0011,1010")
    assert category == "standard"


def test_categorize_field_invalid_tag_falls_through():
    """A tag with a comma but non-hex parts hits the ValueError branch and falls through."""
    # Not a handled special field and not a valid tag -> unhandled.
    category, desc = categorize_field("WeirdField", "zz,zz")
    assert category == "unhandled"


def test_apply_special_field_encoding_leak_block():
    """LeakBlock=True appends /LB to the ImageComments encoding."""
    ds = pydicom.Dataset()
    apply_special_field_encoding(ds, {"MultibandFactor": 4, "PhaseEncodingShift": 3, "LeakBlock": True})
    assert ds.ImageComments == "Unaliased MB4/PE3/LB"


def test_encode_multiband_singleband_reference():
    """MB factor <= 1 yields a single-band reference string."""
    assert encode_multiband_in_image_comments(1) == "Single-band reference SENSE1"


# ---------------------------------------------------------------------------
# dicompare/schema/tags.py
# ---------------------------------------------------------------------------
from dicompare.schema.tags import get_tag_info, determine_field_type_from_values


def test_get_tag_info_known_tag_format_infers_type():
    """A known standard tag in (gggg,eeee) format returns its inferred type + name."""
    info = get_tag_info("(0018,0080)")  # RepetitionTime, DS -> number
    assert info["tag"] == "(0018,0080)"
    assert info["type"] == "number"
    assert info["fieldType"] == "standard"
    assert info["name"]  # description present


def test_get_tag_info_field_with_underscores():
    """A keyword with underscores resolves via the underscore-stripping fallback."""
    info = get_tag_info("Repetition_Time")
    assert info["tag"] == "(0018,0080)"
    assert info["fieldType"] == "standard"


def test_get_tag_info_field_with_spaces():
    """A keyword with spaces resolves via the space-stripping fallback."""
    info = get_tag_info("Flip Angle")
    assert info["tag"] == "(0018,1314)"
    assert info["fieldType"] == "standard"


def test_determine_field_type_from_plain_list_input():
    """A plain (non-pandas) list of multi-valued items becomes list_*."""
    result = determine_field_type_from_values("PatientName", [["A", "B"], None])
    assert result == "list_string"


def test_determine_field_type_from_tuple_values():
    """Tuple values are detected as multi-valued."""
    result = determine_field_type_from_values("PixelSpacing", [(0.5, 0.5), (0.6, 0.6)])
    assert result == "list_number"


def test_determine_field_type_backslash_string_scalar_field():
    """A scalar-typed field with backslash-joined string values becomes list_string."""
    # SeriesDescription is VR=LO, VM=1 -> base type 'string'; backslash promotes it.
    result = determine_field_type_from_values("SeriesDescription", ["a\\b", "c\\d"])
    assert result == "list_string"


# ---------------------------------------------------------------------------
# dicompare/io/gradients.py
# ---------------------------------------------------------------------------
from dicompare.io.gradients import (
    parse_bvec,
    descriptors_from_dvs,
    descriptors_from_bvec_bval,
    _hemisphere_coverage,
)


def test_parse_bvec_inconsistent_row_lengths():
    with pytest.raises(ValueError, match="inconsistent"):
        parse_bvec("1 0\n0 1 0\n0 0 1")


def test_descriptors_from_dvs_no_vectors():
    with pytest.raises(ValueError, match="No vectors"):
        descriptors_from_dvs("[directions=0]\nNormalisation = none\n", b_max=1000)


def test_descriptors_from_bvec_bval_length_mismatch():
    bvec = "0 1\n0 0\n0 0"  # 2 dirs
    bval = "0 1000 1000"     # 3 bvals
    with pytest.raises(ValueError, match="length mismatch"):
        descriptors_from_bvec_bval(bvec, bval)


def test_hemisphere_coverage_too_few_directions():
    """Fewer than 2 non-b0 directions returns 'unknown'."""
    result = _hemisphere_coverage([(1.0, 0.0, 0.0)], [1000.0])
    assert result == "unknown"


# ---------------------------------------------------------------------------
# dicompare/validation/helpers.py
# ---------------------------------------------------------------------------
from dicompare.validation.helpers import check_equality, validate_constraint, validate_field_values


def test_check_equality_nested_list_numeric_and_string_normalization():
    """List inputs recurse: numeric strings convert, non-numeric strings normalize."""
    # Both are lists so we bypass the str-branch and hit normalize_for_comparison.
    assert check_equality(["42"], [42]) is True          # numeric conversion (line 85)
    assert check_equality(["Abc"], ["abc"]) is True       # string normalization (line 89)


def test_validate_constraint_list_expected_non_list_actual():
    """Expected is a list but actual is scalar -> constraint fails."""
    assert validate_constraint(5, expected_value=[5, 6]) is False


def test_validate_field_values_whole_list_mismatch():
    """Multi-element actual_values compared against an expected list that differs."""
    passed, invalid, message = validate_field_values(
        "ImageType", ["ORIGINAL", "PRIMARY"], expected_value=["ORIGINAL", "SECONDARY"]
    )
    assert passed is False
    assert "Expected" in message


# ---------------------------------------------------------------------------
# dicompare/validation/compliance.py
# ---------------------------------------------------------------------------
from dicompare.validation.compliance import check_acquisition_compliance, _find_column_match


def test_find_column_match_normalizations():
    cols = ["FlipAngle", "EchoTime", "FooBar"]
    assert _find_column_match("Flip Angle", cols) == "FlipAngle"   # no-space
    assert _find_column_match("Foo_Bar", cols) == "FooBar"         # no-underscore (line 40)
    assert _find_column_match("echotime", cols) == "EchoTime"      # case-insensitive
    assert _find_column_match("flip_angle", cols) == "FlipAngle"   # normalized
    assert _find_column_match("Missing", cols) is None


def test_check_acquisition_compliance_requires_acquisition_column():
    df = pd.DataFrame({"EchoTime": [1.0]})
    with pytest.raises(ValueError, match="Acquisition"):
        check_acquisition_compliance(df, {"fields": []}, acquisition_name="T1")


def test_check_acquisition_compliance_no_name_uses_full_session():
    """With no acquisition_name the whole session is used (else branch)."""
    df = pd.DataFrame({"EchoTime": [2.46, 2.46]})
    schema = {"fields": [{"field": "EchoTime", "value": 2.46}]}
    results = check_acquisition_compliance(df, schema)
    assert any(r["field"] == "EchoTime" for r in results)


def test_check_acquisition_compliance_series_empty_fields_skipped():
    """A series definition with no fields is skipped (continue branch)."""
    df = pd.DataFrame({"Acquisition": ["A"], "EchoTime": [2.46]})
    schema = {"series": [{"name": "S1", "fields": []}]}
    results = check_acquisition_compliance(df, schema, acquisition_name="A")
    # No series record produced for the empty-field series.
    assert all(r.get("series") != "S1" for r in results)


def test_check_acquisition_compliance_series_minmax_constraint_message():
    """Series not matching a min/max constraint produces a descriptive message."""
    df = pd.DataFrame({"Acquisition": ["A", "A"], "EchoTime": [2.0, 3.0]})
    schema = {
        "series": [
            {"name": "S1", "fields": [{"field": "EchoTime", "min": 10, "max": 20}]},
        ]
    }
    results = check_acquisition_compliance(df, schema, acquisition_name="A")
    s1 = [r for r in results if r.get("series") == "S1"][0]
    assert "in [10, 20]" in s1["message"]


def test_check_acquisition_compliance_series_min_only_and_contains_any():
    """Cover 'field >= min' and contains_any/contains_all constraint descriptions."""
    df = pd.DataFrame({"Acquisition": ["A"], "EchoTime": [2.0], "ImageType": [["M"]]})
    schema = {
        "series": [
            {"name": "MinOnly", "fields": [{"field": "EchoTime", "min": 100}]},
            {"name": "MaxOnly", "fields": [{"field": "EchoTime", "max": -1}]},
            {"name": "AnyS", "fields": [{"field": "ImageType", "contains_any": ["FOO", "BAR"]}]},
            {"name": "AllOf", "fields": [{"field": "ImageType", "contains_all": ["FOO", "BAR"]}]},
        ]
    }
    results = check_acquisition_compliance(df, schema, acquisition_name="A")
    msgs = {r.get("series"): r["message"] for r in results if r.get("series")}
    assert ">= 100" in msgs["MinOnly"]
    assert "<= -1" in msgs["MaxOnly"]
    assert "contains any of" in msgs["AnyS"]
    assert "contains all of" in msgs["AllOf"]


def test_check_acquisition_compliance_validation_model_class_instantiated():
    """A model passed as a class (not instance) is instantiated (line 302-303)."""
    from dicompare.validation.core import BaseValidationModel, validator

    class MyModel(BaseValidationModel):
        @validator(["EchoTime"], rule_name="echo", rule_message="Echo present")
        def check_echo(cls, value):
            return value

    df = pd.DataFrame({"Acquisition": ["A"], "EchoTime": [2.46]})
    results = check_acquisition_compliance(
        df, {"fields": []}, acquisition_name="A", validation_model=MyModel
    )
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# dicompare/io/printprot.py
# ---------------------------------------------------------------------------
from dicompare.io.printprot import (
    _split_value_unit,
    _parse_header_title,
    apply_printprot_to_dicom_mapping,
    _extract_series_parameters,
    _generate_series_combinations,
    _read_content,
    load_printprot_file,
    load_printprot_file_schema_format,
)


def test_split_value_unit_multi_number_treated_as_string():
    """A leading number followed by more digits is kept as a string (unit has digits)."""
    val, unit = _split_value_unit("2 x 2")
    assert val == "2 x 2"
    assert unit is None


def test_split_value_unit_plain_string():
    val, unit = _split_value_unit("A >> P")
    assert val == "A >> P"
    assert unit is None


def test_parse_header_title_empty():
    assert _parse_header_title("") == {}


def test_apply_mapping_multiple_bvalues_creates_series():
    """Multiple distinct b-values become a list and generate series combinations."""
    protocol = {
        "name": "diff",
        "title": "SIEMENS MAGNETOM ConnectomA syngo MR D11",
        "params": {
            ("Diff", "b-value 1"): "1000",
            ("Diff", "b-value 2"): "2000",
            ("Diff", "FoV read"): "220 mm",  # exercises other-field path in sort
        },
    }
    fields = apply_printprot_to_dicom_mapping(protocol)
    assert fields["DiffusionBValue"] == [1000, 2000]

    series_params = _extract_series_parameters(fields)
    assert series_params["DiffusionBValue"] == [1000, 2000]
    series = _generate_series_combinations(series_params)
    assert len(series) == 2
    assert series[0]["name"] == "Series 01"
    assert series[0]["fields"][0]["field"] == "DiffusionBValue"


def test_generate_series_combinations_empty():
    assert _generate_series_combinations({}) == []


def test_sort_output_fields_orders_known_other_derived():
    """A field not in DICOM_FIELD_ORDER and not derived goes to the 'other' bucket."""
    from dicompare.io.printprot import _sort_output_fields

    fields = {
        "SomeCustomField": 1,     # other (line 405)
        "RepetitionTime": 3900,    # known ordered
        "MultibandFactor": 2,      # derived (last)
    }
    ordered = list(_sort_output_fields(fields).keys())
    assert ordered.index("RepetitionTime") < ordered.index("SomeCustomField")
    assert ordered.index("SomeCustomField") < ordered.index("MultibandFactor")


def test_convert_to_schema_format_skips_series_and_empty():
    """Fields that are series-varying or None/empty are excluded from acquisition fields."""
    from dicompare.io.printprot import _convert_to_schema_format

    dicom_fields = {
        "RepetitionTime": 3900,
        "EchoTime": None,               # skipped (line 458)
        "ProtocolName": "",             # skipped (line 458)
        "DiffusionBValue": [1000, 2000],  # series-varying -> skipped (line 456)
    }
    schema = _convert_to_schema_format(dicom_fields, "prot", "/tmp/x.txt")
    field_names = {f["field"] for f in schema["fields"]}
    assert field_names == {"RepetitionTime"}
    assert len(schema["series"]) == 2


def test_read_content_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        _read_content(tmp_path / "nope.txt")


def test_read_content_latin1_fallback(tmp_path):
    """Non-UTF-8 bytes are decoded with latin-1."""
    p = tmp_path / "prot.txt"
    p.write_bytes(b"Voxel 0.5\xd7\xd7 mm")  # 0xd7 invalid as UTF-8 start byte here
    text = _read_content(p)
    assert "Voxel" in text


def test_load_printprot_txt_fixture():
    """Load the real TXT fixture end-to-end."""
    import dicompare.tests.fixtures as fx_pkg
    from pathlib import Path

    base = Path(fx_pkg.__file__).parent / "printprot"
    results = load_printprot_file(base / "AxonDiameterProtocol.txt")
    assert isinstance(results, list) and len(results) > 0
    assert all("protocol_name" in r and "fields" in r for r in results)


def test_load_printprot_xml_fixture_schema_format():
    """Load the real XML fixture into schema format."""
    import dicompare.tests.fixtures as fx_pkg
    from pathlib import Path

    base = Path(fx_pkg.__file__).parent / "printprot"
    results = load_printprot_file_schema_format(base / "axcal_forJelle.xml")
    assert isinstance(results, list) and len(results) > 0
    for r in results:
        assert "acquisition_info" in r
        assert r["acquisition_info"]["source_type"] == "printprot"


def test_parse_printprot_xml_name_fallback_to_title():
    """When no HeaderProtPath is present, the protocol name falls back to the title."""
    from dicompare.io.printprot import _parse_printprot_xml

    xml = (
        "<PrintOut><PrintProtocol><Protocol>"
        "<HeaderTitle>SIEMENS MAGNETOM ConnectomA syngo MR D11</HeaderTitle>"
        "<Card name='Routine'>"
        "<ProtParameter><Label>TR</Label><ValueAndUnit>3900 ms</ValueAndUnit></ProtParameter>"
        "</Card>"
        "</Protocol></PrintProtocol></PrintOut>"
    )
    protos = _parse_printprot_xml(xml)
    assert protos[0]["name"] == "SIEMENS MAGNETOM ConnectomA syngo MR D11"


# ---------------------------------------------------------------------------
# dicompare/schemas/__init__.py
# ---------------------------------------------------------------------------
import dicompare.schemas as schemas_pkg


def test_list_bundled_schemas_glob_fallback(monkeypatch, tmp_path):
    """When index.json is absent, list_bundled_schemas globs *.json."""
    (tmp_path / "a_schema.json").write_text("{}")
    (tmp_path / "b_schema.json").write_text("{}")
    monkeypatch.setattr(schemas_pkg, "_SCHEMAS_DIR", tmp_path)
    result = schemas_pkg.list_bundled_schemas()
    assert result == ["a_schema.json", "b_schema.json"]


def test_load_all_bundled_schemas_handles_load_error(monkeypatch, tmp_path):
    """A schema that fails to load is skipped with a warning, not raised."""
    (tmp_path / "broken.json").write_text("{ not valid json")
    monkeypatch.setattr(schemas_pkg, "_SCHEMAS_DIR", tmp_path)
    result = schemas_pkg.load_all_bundled_schemas()
    assert "broken.json" not in result


# ---------------------------------------------------------------------------
# dicompare/schema/build_schema.py
# ---------------------------------------------------------------------------
from dicompare.schema.build_schema import build_schema


def test_build_schema_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        build_schema(pd.DataFrame())


def test_build_schema_multi_field_nested_tuple_unwrap():
    """Multi-field series where a value is a single-element tuple of a tuple is unwrapped."""
    df = pd.DataFrame(
        {
            "Acquisition": ["A", "A"],
            "PatientName": ["p", "p"],
            "EchoTime": [1.0, 2.0],
            # A value that is a 1-element tuple wrapping another tuple.
            "ImageType": [((1, 2),), ((3, 4),)],
        }
    )
    schema = build_schema(
        df, reference_fields=["PatientName", "EchoTime", "ImageType"]
    )
    (acq,) = schema["acquisitions"].values()
    # Two varying fields (EchoTime, ImageType) -> two series.
    assert len(acq["series"]) == 2
    # The nested-tuple value should be unwrapped to the inner tuple.
    all_values = [f["value"] for s in acq["series"] for f in s["fields"] if f["field"] == "ImageType"]
    assert (1, 2) in all_values or [1, 2] in [list(v) if isinstance(v, tuple) else v for v in all_values]


def test_build_schema_single_varying_tuple_value_unwrap():
    """A single varying field whose values are tuples exercises the tuple-unwrap path."""
    df = pd.DataFrame(
        {
            "Acquisition": ["A", "A"],
            "PatientName": ["p", "p"],
            "ImageType": [("ORIGINAL", "PRIMARY"), ("DERIVED", "SECONDARY")],
        }
    )
    schema = build_schema(df, reference_fields=["PatientName", "ImageType"])
    acqs = schema["acquisitions"]
    assert len(acqs) == 1
    (acq,) = acqs.values()
    # ImageType varies -> becomes series; PatientName constant -> acquisition field.
    assert len(acq["series"]) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
