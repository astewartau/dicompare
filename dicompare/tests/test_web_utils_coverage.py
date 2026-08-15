"""
Additional coverage tests for dicompare.interface.web_utils.

These exercise the plain-Python (non-Pyodide) surface of the web interface
layer: protocol loading, UI acquisition formatting, direct validation,
schema (re)building, dictionary search, and JSON serialization edge cases.

Pyodide-only branches (JSProxy conversion, ``pyodide.ffi.to_js`` progress
callbacks) are intentionally not forced here.
"""

import json
import os
import tempfile
import unittest.mock as mock

import numpy as np
import pandas as pd
import pytest

from dicompare.interface.web_utils import (
    analyze_dicom_files_for_ui,
    validate_acquisition_direct,
    load_protocol_for_ui,
    load_gradient_file_for_ui,
    search_dicom_dictionary,
    build_schema_from_ui_acquisitions,
    attach_gradient_files_to_acquisitions,
    make_json_serializable,
    _gradient_file_kind,
    _gradient_base_name,
    _acq_field_value,
    _is_diffusion_acquisition,
    _merge_descriptor_fields,
)
from dicompare.tests.test_dicom_factory import (
    create_test_dicom_series,
    create_multi_echo_series,
)


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PRO_DIR = os.path.join(FIXTURES, "pro_files")
GRAD_DIR = os.path.join(FIXTURES, "gradients")
PRINTPROT_DIR = os.path.join(FIXTURES, "printprot")


# ---------------------------------------------------------------------------
# make_json_serializable
# ---------------------------------------------------------------------------

class TestMakeJsonSerializable:
    def test_numpy_scalars_and_arrays(self):
        data = {
            "arr": np.array([1, 2, 3]),
            "int": np.int64(42),
            "float": np.float64(3.5),
        }
        out = make_json_serializable(data)
        assert out == {"arr": [1, 2, 3], "int": 42, "float": 3.5}
        # Result must be JSON-encodable
        json.dumps(out)

    def test_nan_inf_and_none_become_none(self):
        out = make_json_serializable(
            {"a": np.nan, "b": np.float64("inf"), "c": None, "d": float("nan")}
        )
        assert out == {"a": None, "b": None, "c": None, "d": None}

    def test_pandas_series_and_dataframe(self):
        series = pd.Series([1, 2, 3])
        df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
        assert make_json_serializable(series) == [1, 2, 3]
        assert make_json_serializable(df) == [
            {"x": 1, "y": 3},
            {"x": 2, "y": 4},
        ]

    def test_nested_and_tuple_and_numpy_bool(self):
        data = {"nested": [(np.int32(1), np.bool_(True)), {"k": np.array([5])}]}
        out = make_json_serializable(data)
        assert out == {"nested": [[1, True], {"k": [5]}]}
        json.dumps(out)

    def test_plain_python_passthrough(self):
        assert make_json_serializable("hello") == "hello"
        assert make_json_serializable(7) == 7


# ---------------------------------------------------------------------------
# load_protocol_for_ui
# ---------------------------------------------------------------------------

def _read(path, binary=True):
    with open(path, "rb" if binary else "r") as f:
        return f.read()


def _assert_ui_acquisition_shape(acq):
    for key in (
        "id",
        "protocolName",
        "seriesDescription",
        "totalFiles",
        "acquisitionFields",
        "seriesFields",
        "series",
        "metadata",
    ):
        assert key in acq, f"missing key {key}"
    # Every acquisition field carries the UI contract fields.
    for field in acq["acquisitionFields"]:
        for k in ("tag", "name", "keyword", "value", "vr", "level", "dataType", "fieldType"):
            assert k in field
        assert field["level"] == "acquisition"
    # Must be JSON serializable.
    json.dumps(acq)


class TestLoadProtocolForUi:
    def test_pro_file(self):
        content = _read(os.path.join(PRO_DIR, "PRODUCT__ep2d_bold__p2_sms1.pro"))
        result = load_protocol_for_ui(content, "bold.pro", "pro")
        assert isinstance(result, list)
        assert len(result) == 1
        acq = result[0]
        _assert_ui_acquisition_shape(acq)
        assert acq["protocolName"] == "PRODUCT__ep2d_bold__p2_sms1"
        assert acq["totalFiles"] == 1
        assert acq["metadata"]["source"] == "siemens_protocol"
        assert acq["metadata"]["originalFileName"] == "bold.pro"
        assert len(acq["acquisitionFields"]) > 0

    def test_pro_diffusion_file_has_list_values(self):
        content = _read(os.path.join(PRO_DIR, "PRODUCT__ep2d_diff__p3_sms1.pro"))
        result = load_protocol_for_ui(content, "diff.pro", "pro")
        acq = result[0]
        _assert_ui_acquisition_shape(acq)
        # DiffusionBValue is a multi-element list -> list dataType.
        bval = _acq_field_value(acq, "DiffusionBValue")
        assert isinstance(bval, list)

    def test_examcard_file(self):
        content = _read(os.path.join(REPO_ROOT, "DUAL_ECHO_EPI.ExamCard"))
        result = load_protocol_for_ui(content, "DUAL_ECHO_EPI.ExamCard", "examcard")
        assert isinstance(result, list)
        assert len(result) >= 1
        for acq in result:
            _assert_ui_acquisition_shape(acq)
            assert acq["metadata"]["source"] == "philips_examcard"
        # At least one exam-card scan should carry series with fields.
        assert any(len(a["series"]) > 0 for a in result)

    def test_examcard_second_fixture(self):
        content = _read(os.path.join(REPO_ROOT, "SSdense_July2024.ExamCard"))
        result = load_protocol_for_ui(content, "SSdense_July2024.ExamCard", "examcard")
        assert isinstance(result, list)
        assert len(result) >= 1
        for acq in result:
            _assert_ui_acquisition_shape(acq)

    def test_printprot_file(self):
        content = _read(os.path.join(PRINTPROT_DIR, "AxonDiameterProtocol.txt"))
        result = load_protocol_for_ui(content, "AxonDiameterProtocol.txt", "printprot")
        assert isinstance(result, list)
        assert len(result) >= 1
        for acq in result:
            _assert_ui_acquisition_shape(acq)
            assert acq["metadata"]["source"] == "siemens_printprot"

    def test_lxprotocol_file(self):
        from dicompare.tests.test_lxprotocol import SAMPLE_LXPROTOCOL

        result = load_protocol_for_ui(
            SAMPLE_LXPROTOCOL.encode("utf-8"), "LxProtocol", "lxprotocol"
        )
        assert isinstance(result, list)
        assert len(result) >= 1
        for acq in result:
            _assert_ui_acquisition_shape(acq)
            assert acq["metadata"]["source"] == "ge_lxprotocol"

    def test_exar1_file(self):
        from dicompare.tests.test_pro_coverage import (
            _build_exar,
            PROTO_TEXT_MULTIECHO,
        )

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.exar1")
            _build_exar(path, [PROTO_TEXT_MULTIECHO])
            with open(path, "rb") as fh:
                content = fh.read()
        result = load_protocol_for_ui(content, "test.exar1", "exar1")
        assert isinstance(result, list)
        assert len(result) >= 1
        for acq in result:
            _assert_ui_acquisition_shape(acq)
            assert acq["metadata"]["source"] == "siemens_exar"
        # Multi-echo protocol should expand into series.
        assert any(len(a["series"]) > 0 for a in result)

    def test_unknown_file_type_raises(self):
        with pytest.raises(ValueError, match="Unknown file type"):
            load_protocol_for_ui(b"whatever", "x.bin", "not_a_type")

    def test_single_element_lists_and_empty_list_data_types(self):
        # Exercise the single-element-array normalization and empty-list data
        # type branches via a mocked pro loader.
        fake = {
            "acquisition_info": {"protocol_name": "MockProt"},
            "fields": [
                {"field": "EchoTime", "value": [5.0]},        # single numeric
                {"field": "ProtocolName", "value": ["abc"]},  # single string
                {"field": "ImageType", "value": []},          # empty list
                {"field": "FlipAngle", "value": 9.0},         # scalar number
                {"field": "ScanOptions", "value": ["A", "B"]},  # multi string list
            ],
            "series": [],
        }
        with mock.patch(
            "dicompare.io.load_pro_file_schema_format", return_value=fake
        ):
            result = load_protocol_for_ui(b"x", "mock.pro", "pro")
        acq = result[0]
        by_name = {f["name"]: f for f in acq["acquisitionFields"]}
        assert by_name["EchoTime"]["value"] == 5.0
        assert by_name["EchoTime"]["dataType"] == "number"
        assert by_name["ProtocolName"]["value"] == "abc"
        assert by_name["ProtocolName"]["dataType"] == "string"
        assert by_name["ImageType"]["value"] == []
        assert by_name["ImageType"]["dataType"] == "list_string"
        assert by_name["ScanOptions"]["dataType"] == "list_string"

    def test_vr_lookup_exception_falls_back_to_LO(self):
        fake = {
            "acquisition_info": {"protocol_name": "MockProt"},
            "fields": [{"field": "EchoTime", "value": 5.0}],
            "series": [
                {"name": "S1", "fields": [{"field": "FlipAngle", "value": 9}]},
            ],
        }
        with mock.patch(
            "dicompare.io.load_pro_file_schema_format", return_value=fake
        ), mock.patch(
            "pydicom.datadict.dictionary_VR", side_effect=KeyError("boom")
        ):
            result = load_protocol_for_ui(b"x", "mock.pro", "pro")
        acq = result[0]
        assert acq["acquisitionFields"][0]["vr"] == "LO"

    def test_series_fields_present_for_multi_series_protocol(self):
        # The dual-echo exam card expands into series; verify seriesFields carry
        # a 'values' array and 'series' carries 'fields' arrays.
        content = _read(os.path.join(REPO_ROOT, "DUAL_ECHO_EPI.ExamCard"))
        result = load_protocol_for_ui(content, "DUAL_ECHO_EPI.ExamCard", "examcard")
        multi = [a for a in result if a["series"]]
        assert multi, "expected at least one acquisition with series"
        acq = multi[0]
        for sf in acq["seriesFields"]:
            assert "values" in sf and isinstance(sf["values"], list)
            assert sf["level"] == "series"
        for series in acq["series"]:
            assert "name" in series
            assert isinstance(series["fields"], list)


# ---------------------------------------------------------------------------
# load_gradient_file_for_ui
# ---------------------------------------------------------------------------

class TestLoadGradientFileForUi:
    def test_dvs_produces_derived_fields(self):
        dvs = _read(
            os.path.join(GRAD_DIR, "DiffusionVectors_AxonDiameter_ERJV.dvs"),
            binary=False,
        )
        result = load_gradient_file_for_ui({"dvs": dvs}, b_max=1000.0)
        assert "fields" in result
        names = {f["name"] for f in result["fields"]}
        assert "NumberOfDiffusionShells" in names
        assert "DiffusionBValues" in names
        for f in result["fields"]:
            assert f["fieldType"] == "derived"
            assert f["level"] == "acquisition"
            assert "dataType" in f
        json.dumps(result)

    def test_dvs_requires_b_max(self):
        with pytest.raises(ValueError, match="b_max"):
            load_gradient_file_for_ui({"dvs": "irrelevant"})

    def test_bvec_bval_pair(self):
        # 3 directions: one b0 and two shells.
        bval = "0 1000 1000"
        bvec = "0 1 0\n0 0 1\n0 0 0"
        result = load_gradient_file_for_ui({"bvec": bvec, "bval": bval})
        assert "fields" in result
        names = {f["name"] for f in result["fields"]}
        assert "NumberOfDiffusionVolumes" in names

    def test_missing_inputs_raises(self):
        with pytest.raises(ValueError, match="Provide either"):
            load_gradient_file_for_ui({"foo": "bar"})

    def test_data_type_classification(self):
        # Force a descriptor dict with a mix of value types to exercise
        # the internal _data_type helper across number/list/string branches.
        fake = {
            "AScalar": 5,
            "AList": [1, 2, 3],
            "AStrList": ["a", "b"],
            "AString": "full-sphere",
        }
        with mock.patch(
            "dicompare.io.descriptors_from_dvs", return_value=fake
        ):
            result = load_gradient_file_for_ui({"dvs": "x"}, b_max=1.0)
        by_name = {f["name"]: f for f in result["fields"]}
        assert by_name["AScalar"]["dataType"] == "number"
        assert by_name["AList"]["dataType"] == "list_number"
        assert by_name["AStrList"]["dataType"] == "list_string"
        assert by_name["AString"]["dataType"] == "string"


# ---------------------------------------------------------------------------
# search_dicom_dictionary
# ---------------------------------------------------------------------------

class TestSearchDicomDictionary:
    # Exercises the real pydicom DicomDictionary (tag_int -> entry tuple).

    def test_search_by_keyword(self):
        results = search_dicom_dictionary("EchoTime", limit=50)
        match = [r for r in results if r["keyword"] == "EchoTime"]
        assert match, "EchoTime should be found"
        assert match[0]["tag"] == "0018,0081"
        assert "suggested_data_type" in match[0]
        json.dumps(results)  # results must be JSON-serializable

    def test_search_by_tag_string(self):
        results = search_dicom_dictionary("0018,0080", limit=10)
        assert any(r["keyword"] == "RepetitionTime" for r in results)

    def test_limit_is_respected(self):
        results = search_dicom_dictionary("0018", limit=2)
        assert len(results) == 2

    def test_no_match_returns_empty(self):
        results = search_dicom_dictionary("zzz_no_such_field_xyzzy", limit=10)
        assert results == []

    def test_multivalue_becomes_list_type(self):
        # AcquisitionMatrix has VM > 1 so its suggested type should be listified.
        results = search_dicom_dictionary("AcquisitionMatrix", limit=10)
        match = [r for r in results if r["keyword"] == "AcquisitionMatrix"]
        assert match
        assert match[0]["suggested_data_type"].startswith("list_") or \
            match[0]["suggested_data_type"] == "string"

    def test_dictionary_lookup_failure_falls_back(self):
        # If per-tag lookups raise, the except branch supplies UN/1/keyword.
        with mock.patch(
            "pydicom.datadict.dictionary_VR", side_effect=KeyError("boom")
        ):
            results = search_dicom_dictionary("EchoTime", limit=5)
        assert any(r["vr"] == "UN" for r in results)


# ---------------------------------------------------------------------------
# build_schema_from_ui_acquisitions
# ---------------------------------------------------------------------------

def _sample_ui_acquisition():
    return {
        "id": "t1",
        "protocolName": "T1_MPRAGE",
        "seriesDescription": "T1w anatomical",
        "detailedDescription": "detail",
        "tags": ["anatomical"],
        "acquisitionFields": [
            {
                "tag": "0018,0080",
                "name": "RepetitionTime",
                "keyword": "RepetitionTime",
                "value": 2300,
                "validationRule": {"type": "exact"},
            },
            {
                "tag": "0018,0081",
                "name": "EchoTime",
                "keyword": "EchoTime",
                "value": 2.98,
                "validationRule": {"type": "tolerance", "value": 3.0, "tolerance": 0.5},
            },
            {
                "tag": "0018,1314",
                "name": "FlipAngle",
                "keyword": "FlipAngle",
                "value": 9,
                "validationRule": {"type": "range", "min": 5, "max": 15},
            },
            {
                "tag": "0008,0008",
                "name": "ImageType",
                "keyword": "ImageType",
                "value": ["ORIGINAL", "PRIMARY"],
                "validationRule": {"type": "contains", "contains": "PRIMARY"},
            },
        ],
        "series": [
            {
                "name": "Series 01",
                "fields": [
                    {
                        "name": "EchoTime",
                        "tag": "0018,0081",
                        "value": 2.98,
                        "validationRule": {"type": "exact"},
                    }
                ],
            }
        ],
    }


class TestBuildSchemaFromUiAcquisitions:
    def test_basic_structure_and_validation_rules(self):
        acq = _sample_ui_acquisition()
        schema = build_schema_from_ui_acquisitions(
            [acq], {"name": "My Schema", "version": "2.0", "authors": ["Ada"]}
        )
        assert schema["name"] == "My Schema"
        assert schema["version"] == "2.0"
        assert schema["authors"] == ["Ada"]
        assert "T1_MPRAGE" in schema["acquisitions"]
        entry = schema["acquisitions"]["T1_MPRAGE"]
        assert entry["description"] == "T1w anatomical"
        assert entry["detailed_description"] == "detail"
        assert entry["tags"] == ["anatomical"]

        fields_by_name = {f["field"]: f for f in entry["fields"]}
        # exact -> value
        assert fields_by_name["RepetitionTime"]["value"] == 2300
        # tolerance -> value + tolerance
        assert fields_by_name["EchoTime"]["value"] == 3.0
        assert fields_by_name["EchoTime"]["tolerance"] == 0.5
        # range -> min/max, no value
        assert fields_by_name["FlipAngle"]["min"] == 5
        assert fields_by_name["FlipAngle"]["max"] == 15
        assert "value" not in fields_by_name["FlipAngle"]
        # contains
        assert fields_by_name["ImageType"]["contains"] == "PRIMARY"
        # Series present
        assert len(entry["series"]) == 1
        json.dumps(schema)

    def test_contains_any_all_and_missing_rule_data(self):
        acq = {
            "protocolName": "Test",
            "acquisitionFields": [
                {
                    "keyword": "A",
                    "value": [1, 2],
                    "validationRule": {"type": "contains_any", "contains_any": [1]},
                },
                {
                    "keyword": "B",
                    "value": [1, 2],
                    "validationRule": {"type": "contains_all", "contains_all": [1, 2]},
                },
                # tolerance rule missing tolerance -> falls back to value
                {
                    "keyword": "C",
                    "value": 5,
                    "validationRule": {"type": "tolerance"},
                },
                # contains rule missing contains -> falls back to value
                {
                    "keyword": "D",
                    "value": "x",
                    "validationRule": {"type": "contains"},
                },
            ],
            "series": [],
        }
        schema = build_schema_from_ui_acquisitions([acq], {})
        fields = {f["field"]: f for f in schema["acquisitions"]["Test"]["fields"]}
        assert fields["A"]["contains_any"] == [1]
        assert fields["B"]["contains_all"] == [1, 2]
        assert fields["C"]["value"] == 5
        assert fields["D"]["value"] == "x"

    def test_defaults_when_metadata_empty(self):
        acq = {"protocolName": "P", "acquisitionFields": [], "series": []}
        schema = build_schema_from_ui_acquisitions([acq], {})
        assert schema["name"] == "Generated Schema"
        assert schema["version"] == "1.0"
        assert schema["authors"] == []

    def test_series_object_format_and_images(self):
        acq = {
            "protocolName": "P",
            "acquisitionFields": [],
            "images": ["img_acq"],
            "series": [
                {
                    "name": "S1",
                    "images": ["img1"],
                    # object-format fields (dict, not array)
                    "fields": {
                        "EchoTime": {"value": 5, "validationRule": {"type": "exact"}},
                    },
                }
            ],
        }
        schema = build_schema_from_ui_acquisitions([acq], {})
        entry = schema["acquisitions"]["P"]
        assert entry["images"] == ["img_acq"]
        assert len(entry["series"]) == 1
        assert entry["series"][0]["images"] == ["img1"]
        assert entry["series"][0]["fields"][0]["field"] == "EchoTime"

    def test_validation_functions_become_rules(self):
        acq = {
            "protocolName": "Rules Acq",
            "acquisitionFields": [],
            "series": [],
            "validationFunctions": [
                {
                    "name": "check_thing",
                    "description": "desc",
                    "implementation": "pass",
                    "parameters": {"p": 1},
                    "fields": ["EchoTime"],
                    "testCases": [],
                }
            ],
        }
        schema = build_schema_from_ui_acquisitions([acq], {})
        rules = schema["acquisitions"]["Rules Acq"]["rules"]
        assert len(rules) == 1
        assert rules[0]["name"] == "check_thing"
        assert rules[0]["fields"] == ["EchoTime"]
        assert "id" in rules[0]

    def test_uses_id_when_protocol_name_absent(self):
        acq = {"id": "fallback_id", "acquisitionFields": [], "series": []}
        schema = build_schema_from_ui_acquisitions([acq], {})
        assert "fallback_id" in schema["acquisitions"]

    def test_series_field_rule_types(self):
        # Exercise every rule branch on series fields (tolerance/range/contains/
        # contains_any/contains_all and their fall-back-to-value forms).
        acq = {
            "protocolName": "P",
            "acquisitionFields": [],
            "series": [
                {
                    "name": "S1",
                    "fields": [
                        {"name": "Tol", "value": 5,
                         "validationRule": {"type": "tolerance", "value": 5.0, "tolerance": 0.1}},
                        {"name": "TolFallback", "value": 6,
                         "validationRule": {"type": "tolerance"}},
                        {"name": "Rng", "value": 5,
                         "validationRule": {"type": "range", "min": 1, "max": 10}},
                        {"name": "Con", "value": ["a"],
                         "validationRule": {"type": "contains", "contains": "a"}},
                        {"name": "ConFallback", "value": ["a"],
                         "validationRule": {"type": "contains"}},
                        {"name": "Any", "value": [1],
                         "validationRule": {"type": "contains_any", "contains_any": [1]}},
                        {"name": "AnyFallback", "value": [1],
                         "validationRule": {"type": "contains_any"}},
                        {"name": "All", "value": [1, 2],
                         "validationRule": {"type": "contains_all", "contains_all": [1, 2]}},
                        {"name": "AllFallback", "value": [1, 2],
                         "validationRule": {"type": "contains_all"}},
                    ],
                }
            ],
        }
        schema = build_schema_from_ui_acquisitions([acq], {})
        series = schema["acquisitions"]["P"]["series"][0]
        fields = {f["field"]: f for f in series["fields"]}
        assert fields["Tol"]["tolerance"] == 0.1
        assert fields["TolFallback"]["value"] == 6
        assert fields["Rng"]["min"] == 1 and fields["Rng"]["max"] == 10
        assert fields["Con"]["contains"] == "a"
        assert fields["ConFallback"]["value"] == ["a"]
        # Series fields carrying only contains_any/contains_all constraints (and
        # no 'value') are filtered out by the constraint check, but their
        # fallback-to-value forms survive.
        assert "Any" not in fields
        assert "All" not in fields
        assert fields["AnyFallback"]["value"] == [1]
        assert fields["AllFallback"]["value"] == [1, 2]

    def test_acq_contains_any_all_fallback_to_value(self):
        acq = {
            "protocolName": "P",
            "acquisitionFields": [
                {"keyword": "A", "value": [1],
                 "validationRule": {"type": "contains_any"}},
                {"keyword": "B", "value": [1, 2],
                 "validationRule": {"type": "contains_all"}},
            ],
            "series": [],
        }
        schema = build_schema_from_ui_acquisitions([acq], {})
        fields = {f["field"]: f for f in schema["acquisitions"]["P"]["fields"]}
        assert fields["A"]["value"] == [1]
        assert fields["B"]["value"] == [1, 2]

    def test_complex_value_object_is_unwrapped(self):
        # A field whose 'value' is itself a dict carrying validationRule/dataType
        # is unwrapped: the nested validationRule is read, then the scalar value
        # is extracted from the dict.
        acq = {
            "protocolName": "P",
            "acquisitionFields": [
                {"keyword": "EchoTime",
                 "value": {"value": 42, "dataType": "number",
                           "validationRule": {"type": "exact"}}},
            ],
            "series": [],
        }
        schema = build_schema_from_ui_acquisitions([acq], {})
        fields = {f["field"]: f for f in schema["acquisitions"]["P"]["fields"]}
        assert fields["EchoTime"]["value"] == 42

    def test_series_field_without_constraint_is_dropped(self):
        # A series field whose rule yields no constraint keys is omitted, and a
        # series with no remaining fields is not added.
        acq = {
            "protocolName": "P",
            "acquisitionFields": [],
            "series": [
                {
                    "name": "S1",
                    "fields": [
                        {"name": "X", "validationRule": {"type": "range"}},
                    ],
                }
            ],
        }
        schema = build_schema_from_ui_acquisitions([acq], {})
        assert schema["acquisitions"]["P"]["series"] == []


# ---------------------------------------------------------------------------
# validate_acquisition_direct
# ---------------------------------------------------------------------------

class TestValidateAcquisitionDirect:
    def _schema_content(self, acq):
        schema = build_schema_from_ui_acquisitions(
            [acq], {"name": "S", "version": "1.0", "authors": ["a"]}
        )
        return json.dumps(schema)

    def test_pass_results(self):
        acq = _sample_ui_acquisition()
        content = self._schema_content(acq)
        results = validate_acquisition_direct(acq, content, 0)
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            for k in ("fieldPath", "fieldName", "status", "message", "validationType"):
                assert k in r
        by_field = {r["fieldName"]: r for r in results if r["validationType"] == "field"}
        assert by_field["RepetitionTime"]["status"] == "pass"
        json.dumps(results)

    def test_fail_on_mismatch(self):
        acq = _sample_ui_acquisition()
        content = self._schema_content(acq)
        # Mutate the actual data so RepetitionTime disagrees with schema.
        bad = json.loads(json.dumps(acq))
        for f in bad["acquisitionFields"]:
            if f["keyword"] == "RepetitionTime":
                f["value"] = 9999
        results = validate_acquisition_direct(bad, content, 0)
        rt = [r for r in results if r["fieldName"] == "RepetitionTime"]
        assert rt and rt[0]["status"] == "fail"

    def test_no_series_uses_base_row(self):
        acq = {
            "protocolName": "NoSeries",
            "acquisitionFields": [
                {
                    "keyword": "RepetitionTime",
                    "tag": "0018,0080",
                    "value": 100,
                    "validationRule": {"type": "exact"},
                }
            ],
            "series": [],
        }
        content = self._schema_content(acq)
        results = validate_acquisition_direct(acq, content, 0)
        assert len(results) >= 1

    def test_single_acquisition_no_index(self):
        acq = _sample_ui_acquisition()
        content = self._schema_content(acq)
        # index None with a single-acquisition schema is allowed.
        results = validate_acquisition_direct(acq, content, None)
        assert len(results) > 0

    def test_empty_schema_raises(self):
        content = json.dumps({"name": "S", "version": "1.0", "authors": [], "acquisitions": {}})
        with pytest.raises(ValueError, match="no acquisitions"):
            validate_acquisition_direct(_sample_ui_acquisition(), content, 0)

    def test_invalid_index_raises(self):
        acq = _sample_ui_acquisition()
        content = self._schema_content(acq)
        with pytest.raises(ValueError, match="Invalid acquisition index"):
            validate_acquisition_direct(acq, content, 5)

    def test_multiple_acquisitions_without_index_raises(self):
        acq1 = _sample_ui_acquisition()
        acq2 = _sample_ui_acquisition()
        acq2["protocolName"] = "Second"
        schema = build_schema_from_ui_acquisitions(
            [acq1, acq2], {"name": "S", "version": "1.0", "authors": ["a"]}
        )
        content = json.dumps(schema)
        with pytest.raises(ValueError, match="Multiple acquisitions"):
            validate_acquisition_direct(acq1, content, None)

    def test_list_values_are_made_hashable(self):
        acq = {
            "protocolName": "ListAcq",
            "sliceCount": 3,
            "acquisitionFields": [
                {
                    "keyword": "ImageType",
                    "tag": "0008,0008",
                    "value": ["ORIGINAL", "PRIMARY"],
                    "validationRule": {"type": "exact"},
                }
            ],
            "series": [],
        }
        content = self._schema_content(acq)
        # Should not raise despite list-valued field.
        results = validate_acquisition_direct(acq, content, 0)
        assert isinstance(results, list)

    def test_temp_schema_file_is_cleaned_up(self):
        acq = _sample_ui_acquisition()
        content = self._schema_content(acq)
        before = set(os.listdir(tempfile.gettempdir()))
        validate_acquisition_direct(acq, content, 0)
        after = set(os.listdir(tempfile.gettempdir()))
        leaked = [p for p in (after - before) if p.endswith(".json")]
        assert not leaked

    def test_status_and_type_branches_via_mock(self):
        # Craft compliance results that exercise the na / warning / rule /
        # series status and validation-type branches.
        acq = _sample_ui_acquisition()
        content = self._schema_content(acq)
        fake_results = [
            {"field": "F1", "status": "na", "message": "not applicable"},
            {"field": "F2", "status": "warning", "message": "warn", "expected": 1, "value": [2]},
            {"field": "F3", "status": "ok", "message": "ok"},
            {"field": "F4", "status": "error", "message": "err"},
            # Unknown status -> falls back to 'passed' boolean (False -> fail).
            {"field": "F5", "message": "weird", "passed": False},
            {"field": "F6", "message": "boolpass", "passed": True},
            # Series-level result.
            {"field": "F7", "status": "pass", "series": "Series 01", "message": "s"},
            # Rule result.
            {"field": "F8", "rule_name": "MyRule", "passed": True, "expected": "yes", "message": "r"},
        ]
        with mock.patch(
            "dicompare.validation.check_acquisition_compliance",
            return_value=fake_results,
        ):
            results = validate_acquisition_direct(acq, content, 0)
        by_field = {r["fieldName"]: r for r in results}
        assert by_field["F1"]["status"] == "na"
        assert by_field["F2"]["status"] == "warning"
        assert by_field["F2"]["actualValue"] == 2  # extracted from list
        assert by_field["F3"]["status"] == "pass"
        assert by_field["F4"]["status"] == "fail"
        assert by_field["F5"]["status"] == "fail"
        assert by_field["F6"]["status"] == "pass"
        assert by_field["F7"]["validationType"] == "series"
        assert by_field["F7"]["seriesName"] == "Series 01"
        assert by_field["F8"]["validationType"] == "rule"
        assert by_field["F8"]["rule_name"] == "MyRule"
        assert by_field["F8"]["expectedValue"] == "yes"


# ---------------------------------------------------------------------------
# analyze_dicom_files_for_ui
# ---------------------------------------------------------------------------

class TestAnalyzeDicomFilesForUi:
    @pytest.mark.asyncio
    async def test_single_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, dicom_bytes = create_test_dicom_series(
                base_dir=tmp,
                acquisition_name="T1_MPRAGE",
                num_slices=3,
                metadata_base={
                    "RepetitionTime": 2300.0,
                    "EchoTime": 2.98,
                    "FlipAngle": 9.0,
                    "SeriesDescription": "T1w",
                },
            )
            result = await analyze_dicom_files_for_ui(dicom_bytes)
        assert isinstance(result, list)
        assert len(result) == 1
        acq = result[0]
        for key in (
            "id",
            "protocolName",
            "seriesDescription",
            "totalFiles",
            "sliceCount",
            "acquisitionFields",
            "seriesFields",
            "series",
            "seriesFileMapping",
            "metadata",
        ):
            assert key in acq
        assert acq["totalFiles"] == 3
        assert acq["sliceCount"] == 3
        assert len(acq["acquisitionFields"]) > 0
        assert acq["metadata"]["source"] == "dicom_analysis"
        json.dumps(result)

    @pytest.mark.asyncio
    async def test_multi_echo_produces_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, dicom_bytes = create_multi_echo_series(
                base_dir=tmp,
                acquisition_name="MEGRE",
                echo_times=[0.01, 0.02, 0.03],
                num_slices_per_echo=2,
            )
            result = await analyze_dicom_files_for_ui(dicom_bytes)
        assert len(result) == 1
        acq = result[0]
        # Varying EchoTime -> series fields with values and a file mapping.
        assert len(acq["series"]) >= 2
        assert len(acq["seriesFields"]) > 0
        assert len(acq["seriesFileMapping"]) >= 2
        for sf in acq["seriesFields"]:
            assert isinstance(sf["values"], list)
            assert sf["level"] == "series"

    @pytest.mark.asyncio
    async def test_error_raises_runtime_error(self):
        # Empty input -> underlying analysis returns an error status, which the
        # UI wrapper surfaces as RuntimeError.
        with pytest.raises(RuntimeError):
            await analyze_dicom_files_for_ui({})


class TestAnalyzeDicomFilesForWebProgress:
    """Exercise the progress-callback path of analyze_dicom_files_for_web.

    The real code imports ``pyodide.ffi.to_js`` which only exists in a browser;
    we inject a stub ``pyodide`` module so the progress branches run under
    CPython. This covers the callback-wrapping and to_js progress reporting
    blocks that are otherwise Pyodide-only.
    """

    @pytest.fixture
    def fake_pyodide(self):
        import sys
        import types

        fake_ffi = types.ModuleType("pyodide.ffi")
        fake_ffi.to_js = lambda obj, **kw: obj
        fake_pyodide = types.ModuleType("pyodide")
        fake_pyodide.ffi = fake_ffi
        saved = {k: sys.modules.get(k) for k in ("pyodide", "pyodide.ffi")}
        sys.modules["pyodide"] = fake_pyodide
        sys.modules["pyodide.ffi"] = fake_ffi
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    @pytest.mark.asyncio
    async def test_progress_callback_invoked(self, fake_pyodide):
        from dicompare.interface.web_utils import analyze_dicom_files_for_web

        calls = []

        def callback(obj):
            calls.append(obj)

        with tempfile.TemporaryDirectory() as tmp:
            _, dicom_bytes = create_test_dicom_series(
                base_dir=tmp,
                acquisition_name="T1_MPRAGE",
                num_slices=2,
                metadata_base={"RepetitionTime": 2300.0, "EchoTime": 2.98},
            )
            result = await analyze_dicom_files_for_web(
                dicom_bytes, ["RepetitionTime", "EchoTime"], callback
            )

        assert result["status"] == "success"
        # The callback receives multiple progress objects (test ping + stages).
        assert len(calls) >= 2
        percentages = [c.get("percentage") for c in calls if isinstance(c, dict)]
        assert 80 in percentages  # "Organizing acquisitions" stage

    @pytest.mark.asyncio
    async def test_field_type_none_duplicate_id_and_slice_count_branches(self):
        # Feed a crafted web result + cached session to exercise the branches
        # that fill in missing fieldType/tag, dedupe acquisition ids, build the
        # series/file mapping, and compute sliceCount from a Siemens mosaic.
        web_result = {
            "status": "success",
            "acquisitions": {
                "Dup Acq": {
                    "fields": [
                        # Missing fieldType and tag -> get_tag_info fallback.
                        {"field": "EchoTime", "value": 5},
                    ],
                    "series": [
                        {
                            "name": "Series 01",
                            "fields": [{"field": "FlipAngle", "value": 9}],
                        },
                        {
                            "name": "Series 02",
                            "fields": [{"field": "FlipAngle", "value": 12}],
                        },
                    ],
                },
                # Same base id after normalization -> triggers dedupe counter.
                "Dup-Acq": {
                    "fields": [{"field": "RepetitionTime", "value": 2000}],
                    "series": [],
                },
                # Third collision -> forces the dedupe while-loop to increment.
                "Dup/Acq": {
                    "fields": [{"field": "RepetitionTime", "value": 2500}],
                    "series": [],
                },
            },
        }

        session_df = pd.DataFrame(
            {
                "Acquisition": ["Dup Acq", "Dup Acq", "Dup-Acq", "Dup/Acq"],
                "SeriesDescription": ["desc1", "desc1", "desc2", "desc3"],
                "FlipAngle": [9, 12, 9, 9],
                "DICOM_Path": ["/a/1.dcm", "/a/2.dcm", "/b/1.dcm", "/c/1.dcm"],
                "NumberOfImagesInMosaic": [40, 40, np.nan, np.nan],
            }
        )
        metadata = {"available_fields": ["FlipAngle"]}

        async def fake_core(*args, **kwargs):
            return web_result, session_df, metadata

        # Patch dictionary_VR to raise so the VR-lookup exception fallback
        # (lines 357-359) is also exercised.
        with mock.patch(
            "dicompare.interface.web_utils._analyze_dicom_session_core",
            side_effect=fake_core,
        ), mock.patch(
            "pydicom.datadict.dictionary_VR", side_effect=KeyError("boom")
        ):
            result = await analyze_dicom_files_for_ui({"x.dcm": b"x"})

        assert len(result) == 3
        ids = [a["id"] for a in result]
        # Deduplicated ids (base, base_2, base_3).
        assert len(set(ids)) == 3
        assert any(i.endswith("_2") for i in ids)
        assert any(i.endswith("_3") for i in ids)
        # VR fell back to 'LO' due to the raising dictionary_VR.
        assert result[0]["acquisitionFields"][0]["vr"] == "LO"
        first = result[0]
        # fieldType filled in by get_tag_info fallback.
        assert first["acquisitionFields"][0]["fieldType"] is not None
        # Mosaic slice count picked up.
        assert first["sliceCount"] == 40
        # File mapping built from varying FlipAngle field.
        assert len(first["seriesFileMapping"]) == 2
        # seriesDescription derived from the DataFrame.
        assert first["seriesDescription"] == "desc1"

    @pytest.mark.asyncio
    async def test_slice_count_from_unique_slice_location_and_no_varying(self):
        web_result = {
            "status": "success",
            "acquisitions": {
                "Acq": {
                    "fields": [{"field": "EchoTime", "value": 5}],
                    "series": [
                        {"name": "Series 01", "fields": [{"field": "EchoTime", "value": 5}]},
                    ],
                },
            },
        }
        session_df = pd.DataFrame(
            {
                "Acquisition": ["Acq", "Acq", "Acq"],
                "SliceLocation": [0.0, 5.0, 10.0],
                "DICOM_Path": ["/a/1.dcm", "/a/2.dcm", "/a/3.dcm"],
                # EchoTime constant -> no varying fields -> single "Series 01".
                "EchoTime": [5, 5, 5],
            }
        )
        metadata = {"available_fields": ["EchoTime"]}

        async def fake_core(*args, **kwargs):
            return web_result, session_df, metadata

        with mock.patch(
            "dicompare.interface.web_utils._analyze_dicom_session_core",
            side_effect=fake_core,
        ):
            result = await analyze_dicom_files_for_ui({"x.dcm": b"x"})

        acq = result[0]
        # Unique SliceLocation count.
        assert acq["sliceCount"] == 3
        # No varying fields -> all files in one series.
        assert list(acq["seriesFileMapping"].keys()) == ["Series 01"]


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_gradient_file_kind(self):
        assert _gradient_file_kind("a/b/Foo.dvs") == "dvs"
        assert _gradient_file_kind("Foo.BVEC") == "bvec"
        assert _gradient_file_kind("Foo.bval") == "bval"
        assert _gradient_file_kind("Foo.txt") is None

    def test_gradient_base_name(self):
        assert _gradient_base_name("a/b/Foo.dvs") == "Foo"
        assert _gradient_base_name("Bar.bvec") == "Bar"
        assert _gradient_base_name("NoExt") == "NoExt"
        assert _gradient_base_name("windows\\path\\Baz.dvs") == "Baz"

    def test_acq_field_value(self):
        acq = {
            "acquisitionFields": [
                {"keyword": "DiffusionBValue", "value": 1000},
                {"name": "OnlyName", "value": 7},
            ]
        }
        assert _acq_field_value(acq, "DiffusionBValue") == 1000
        assert _acq_field_value(acq, "OnlyName") == 7
        assert _acq_field_value(acq, "Missing") is None
        assert _acq_field_value({}, "X") is None

    def test_is_diffusion_acquisition(self):
        assert _is_diffusion_acquisition(
            {"acquisitionFields": [{"keyword": "DiffusionBValue", "value": 1000}]}
        )
        assert _is_diffusion_acquisition(
            {"acquisitionFields": [{"keyword": "DiffusionDirectionSet", "value": "set"}]}
        )
        assert not _is_diffusion_acquisition(
            {"acquisitionFields": [{"keyword": "EchoTime", "value": 5}]}
        )

    def test_merge_descriptor_fields_replaces_by_name(self):
        existing = [
            {"keyword": "A", "value": 1},
            {"keyword": "B", "value": 2},
        ]
        incoming = [{"keyword": "B", "value": 99}, {"keyword": "C", "value": 3}]
        merged = _merge_descriptor_fields(existing, incoming)
        by_name = {f["keyword"]: f["value"] for f in merged}
        assert by_name == {"A": 1, "B": 99, "C": 3}

    def test_merge_descriptor_fields_handles_none_existing(self):
        merged = _merge_descriptor_fields(None, [{"keyword": "A", "value": 1}])
        assert merged == [{"keyword": "A", "value": 1}]


# ---------------------------------------------------------------------------
# attach_gradient_files_to_acquisitions (branches not covered elsewhere)
# ---------------------------------------------------------------------------

class TestAttachGradientBranches:
    def _dvs(self):
        return _read(
            os.path.join(GRAD_DIR, "DiffusionVectors_AxonDiameter_ERJV.dvs"),
            binary=False,
        )

    def _diffusion_acq(self, name="DWI", b_value=1000):
        return {
            "id": name,
            "protocolName": name,
            "acquisitionFields": [
                {"keyword": "DiffusionBValue", "value": b_value},
            ],
        }

    def test_unknown_kind_file_is_ignored_and_dvs_falls_back(self):
        # A non-gradient file is skipped; the .dvs then binds to the single
        # diffusion acquisition via the fallback path.
        acq = self._diffusion_acq()
        files = [
            {"name": "readme.txt", "content": "ignore me"},
            {"name": "Foo.dvs", "content": self._dvs()},
        ]
        result = attach_gradient_files_to_acquisitions([acq], files)
        assert [b["protocolName"] for b in result["bound"]] == ["DWI"]
        assert result["unmatched"] == []
        # Descriptors merged into the acquisition.
        names = {f["keyword"] for f in acq["acquisitionFields"]}
        assert "NumberOfDiffusionShells" in names

    def test_bad_dvs_content_reported_unmatched(self):
        acq = self._diffusion_acq()
        result = attach_gradient_files_to_acquisitions(
            [acq], [{"name": "Bar.dvs", "content": "garbage without vectors"}]
        )
        assert result["bound"] == []
        assert result["unmatched"] == ["Bar"]

    def test_non_numeric_bvalue_reported_unmatched(self):
        acq = self._diffusion_acq(b_value="not-a-number")
        result = attach_gradient_files_to_acquisitions(
            [acq], [{"name": "Baz.dvs", "content": self._dvs()}]
        )
        assert result["bound"] == []
        assert "Baz" in result["unmatched"]
