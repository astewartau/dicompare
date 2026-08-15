"""
Additional coverage tests for dicompare/io/examcard.py.

These tests exercise:
  * The real Philips ExamCard fixtures (DUAL_ECHO_EPI, SSdense) through the
    public loaders in both flat and schema formats.
  * The XML navigation helpers with small synthetic SOAP documents.
  * The binary parameter parsing helpers with hand-built byte buffers that hit
    every parameter type (float/int/string/enum) and each validation branch.
  * The derived-field / mapping / schema-format branches that the existing
    test_examcard.py does not reach.

Only this file is added; source is not modified.
"""

import base64
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dicompare.io import examcard as ec
from dicompare.io.examcard import (
    load_examcard_file,
    load_examcard_file_schema_format,
    apply_examcard_to_dicom_mapping,
    _parse_examcard,
    _parse_examcard_all_scans,
    _parse_parameter_data,
    _get_a_param,
    _get_param_value,
    _calculate_derived_fields,
    _clean_tag,
    _get_attrib_value,
    _get_nodes_by_tag,
    _get_node_by_attrib_value,
    _get_child_by_tag,
    _get_child_thru_ref,
    _get_child_name,
    _get_item_content,
    _get_info_for_node,
    _extract_series_parameters,
    _generate_series_combinations,
    _convert_to_schema_format,
    _sort_output_fields,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DUAL_ECHO = REPO_ROOT / "DUAL_ECHO_EPI.ExamCard"
SSDENSE = REPO_ROOT / "SSdense_July2024.ExamCard"


# ---------------------------------------------------------------------------
# Helpers for building synthetic binary parameter blocks
# ---------------------------------------------------------------------------

_HEADER = b"\x00" * 32  # pos0 offset used by _get_a_param


def _make_param(name, typ, num, off1_rel, off2_rel):
    """Build a single 50-byte parameter entry matching the parser's layout."""
    nb = name.encode("utf-8")
    block = nb + b"\x00" * (34 - len(nb))
    block += struct.pack("<I", typ)       # bytes 34-37: type
    block += struct.pack("<I", num)       # bytes 38-41: count
    block += struct.pack("<I", off1_rel)  # bytes 42-45: off1 (relative)
    block += struct.pack("<I", off2_rel)  # bytes 46-49: off2 (relative)
    assert len(block) == 50
    return block


class _TextNode:
    """Minimal stand-in for an XML node carrying base64 text."""

    def __init__(self, text):
        self.text = text


# ===========================================================================
# Real fixture tests through the public loaders
# ===========================================================================

class TestRealFixturesFlat:
    def test_dual_echo_flat(self):
        result = load_examcard_file(str(DUAL_ECHO))
        assert result["Manufacturer"] == "Philips"
        assert result["ProtocolName"] == "GE-SE EPI 2Sh 1Sl"
        assert result["ScanningSequence"] == "SE"
        # Dual echo -> list of two echo times
        assert result["EchoTime"] == [30.0, 70.0]
        assert result["ExamCard_FileName"] == "DUAL_ECHO_EPI.ExamCard"
        assert result["ExamCard_Path"] == str(DUAL_ECHO)
        # A whitelisted Philips-specific parameter should be surfaced.
        assert result["Philips_ACQ_echoes"] == 2

    def test_ssdense_flat(self):
        result = load_examcard_file(str(SSDENSE))
        assert result["Manufacturer"] == "Philips"
        assert result["ProtocolName"]  # first non-General scan
        assert result["ExamCard_FileName"] == "SSdense_July2024.ExamCard"

    def test_copy_into_tmp_path(self, tmp_path):
        dest = tmp_path / "copy.ExamCard"
        shutil.copy(DUAL_ECHO, dest)
        result = load_examcard_file(str(dest))
        assert result["Manufacturer"] == "Philips"


class TestRealFixturesSchema:
    def test_dual_echo_schema(self):
        scans = load_examcard_file_schema_format(str(DUAL_ECHO))
        assert len(scans) == 2
        first = scans[0]
        assert set(first.keys()) == {"acquisition_info", "fields", "series"}
        info = first["acquisition_info"]
        assert info["source_type"] == "examcard"
        assert info["protocol_name"] == "GE-SE EPI 2Sh 1Sl"
        assert info["examcard_filename"] == "DUAL_ECHO_EPI.ExamCard"
        # Series are generated from the two echo times.
        assert len(first["series"]) == 2
        assert first["series"][0]["fields"][0]["field"] == "EchoTime"
        echo_values = [s["fields"][0]["value"] for s in first["series"]]
        assert echo_values == [30.0, 70.0]
        # EchoTime is series-varying so it must NOT be an acquisition-level field.
        acq_field_names = {f["field"] for f in first["fields"]}
        assert "EchoTime" not in acq_field_names
        assert "Manufacturer" in acq_field_names

    def test_ssdense_schema(self):
        scans = load_examcard_file_schema_format(str(SSDENSE))
        assert len(scans) == 14
        names = [s["acquisition_info"]["protocol_name"] for s in scans]
        assert "AnatBrain_T1W3D" in names
        # Single-echo scans produce no series entries.
        for s in scans:
            for f in s["fields"]:
                assert f["value"] not in (None, "")


class TestFileErrors:
    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_examcard_file("/no/such/file.ExamCard")

    def test_load_schema_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_examcard_file_schema_format("/no/such/file.ExamCard")

    def test_parse_all_scans_missing_file(self):
        with pytest.raises(FileNotFoundError):
            _parse_examcard_all_scans("/no/such/file.ExamCard")

    def test_parse_malformed_xml_raises(self, tmp_path):
        bad = tmp_path / "bad.ExamCard"
        bad.write_text("<SOAP-ENV:Envelope><unclosed>")
        with pytest.raises(RuntimeError):
            _parse_examcard_all_scans(str(bad))

    def test_parse_examcard_no_scans_returns_empty(self, tmp_path):
        # Valid XML with no ExecutionStep / ExamCard nodes -> {} from
        # _parse_examcard (line: "return {}").
        f = tmp_path / "empty.ExamCard"
        f.write_text("<root><child/></root>")
        assert _parse_examcard(str(f)) == {}

    def test_trailing_garbage_after_envelope(self, tmp_path):
        # Exercise the closing-tag truncation path with well-formed content.
        f = tmp_path / "trail.ExamCard"
        f.write_text(
            "<SOAP-ENV:Envelope xmlns:SOAP-ENV='urn:x'>"
            "<body/></SOAP-ENV:Envelope>GARBAGE_AFTER_TAG\x00\x01"
        )
        result = _parse_examcard_all_scans(str(f))
        assert result == {}  # no ExamCard/ExecutionStep nodes


# ===========================================================================
# XML helper functions
# ===========================================================================

class TestXmlHelpers:
    def test_clean_tag(self):
        assert _clean_tag("{urn:ns}ExamCard") == "ExamCard"
        assert _clean_tag("plain") == "plain"

    def test_get_attrib_value(self):
        node = ET.fromstring('<n xmlns:x="urn:x" x:href="#abc" other="1"/>')
        assert _get_attrib_value(node, "href") == "#abc"
        assert _get_attrib_value(node, "missing") is None

    def test_get_nodes_by_tag(self):
        root = ET.fromstring("<a><b/><c><b/></c></a>")
        assert len(_get_nodes_by_tag(root, "b")) == 2

    def test_get_node_by_attrib_value(self):
        root = ET.fromstring('<a><b id="x1"/><c id="x2"/></a>')
        found = _get_node_by_attrib_value(root, "id", "x2")
        assert found is not None and _clean_tag(found.tag) == "c"
        # No match -> None
        assert _get_node_by_attrib_value(root, "id", "nope") is None

    def test_get_child_by_tag(self):
        parent = ET.fromstring("<p><a/><b/></p>")
        assert _clean_tag(_get_child_by_tag(parent, "b").tag) == "b"
        assert _get_child_by_tag(parent, "z") is None

    def test_get_child_thru_ref_missing_child(self):
        parent = ET.fromstring("<p><a/></p>")
        assert _get_child_thru_ref(parent, parent, "missing") is None

    def test_get_child_thru_ref_no_href_returns_child(self):
        parent = ET.fromstring("<p><target>value</target></p>")
        child = _get_child_thru_ref(parent, parent, "target")
        assert child is not None
        assert child.text == "value"

    def test_get_child_thru_ref_follows_href(self):
        root = ET.fromstring(
            '<root xmlns:x="urn:x">'
            '<parent><target x:href="#ref1"/></parent>'
            '<data id="ref1"><v>42</v></data>'
            "</root>"
        )
        parent = _get_child_by_tag(root, "parent")
        resolved = _get_child_thru_ref(root, parent, "target")
        assert resolved is not None
        assert _clean_tag(resolved.tag) == "data"

    def test_get_child_name(self):
        node = ET.fromstring("<n><name>  Hello  </name></n>")
        assert _get_child_name(node) == "Hello"
        assert _get_child_name(ET.fromstring("<n/>")) == ""

    def test_get_item_content(self):
        node = ET.fromstring("<n><a> x </a><b/><c>y</c></n>")
        assert _get_item_content(node) == {"a": "x", "c": "y"}

    def test_get_info_for_node_text_and_ref(self):
        root = ET.fromstring(
            '<root xmlns:x="urn:x">'
            '<node><plain> hi </plain><reffed x:href="#r"/></node>'
            '<blob id="r"><k>v</k></blob>'
            "</root>"
        )
        node = _get_child_by_tag(root, "node")
        info = _get_info_for_node(node, root)
        assert info["plain"] == "hi"
        assert info["reffed"] == {"k": "v"}

    def test_get_info_for_node_dangling_ref(self):
        # href that resolves to nothing -> key omitted.
        root = ET.fromstring(
            '<root xmlns:x="urn:x"><node><reffed x:href="#missing"/></node></root>'
        )
        node = _get_child_by_tag(root, "node")
        assert _get_info_for_node(node, root) == {}


# ===========================================================================
# Binary parameter parsing
# ===========================================================================

class TestParamValue:
    def test_float_multi(self):
        data = struct.pack("<f", 1.5) + struct.pack("<f", 2.5)
        val, enum = _get_param_value(0, 2, 0, 0, data)
        assert val == [1.5, 2.5]
        assert enum is None

    def test_int_single(self):
        data = struct.pack("<i", 7)
        val, _ = _get_param_value(1, 1, 0, 0, data)
        assert val == 7

    def test_string(self):
        data = b"\x00" * 40 + b"HELLO\x00" + b"\x00" * 100
        val, _ = _get_param_value(2, 1, 0, 40, data)
        assert val == "HELLO"

    def test_enum(self):
        data = b"A,B,C\x00" + struct.pack("<i", 2)
        val, enum = _get_param_value(4, 1, 0, 6, data)
        assert val == 2
        assert enum == ("A,B,C", ["A", "B", "C"])

    def test_no_values_returns_none(self):
        val, enum = _get_param_value(0, 1, 0, 0, b"")
        assert val is None and enum is None

    def test_exception_path_swallowed(self):
        # off2 = None triggers a TypeError inside the try/except -> returns None.
        val, enum = _get_param_value(0, 1, 0, None, b"\x00\x00\x00\x00")
        assert val is None and enum is None


class TestGetAParam:
    def test_int_param(self):
        data = _HEADER + _make_param("EX_ACQ_flip_angle", 1, 1, 0, 4) + struct.pack("<i", 45)
        name, val, enum = _get_a_param(data, 0)
        assert name == "EX_ACQ_flip_angle"
        assert val == 45
        assert enum is None

    def test_enum_param_with_map(self):
        data = (
            _HEADER
            + _make_param("EX_ACQ_scan_mode", 4, 1, 8, 13)
            + b"AA,BB,CC\x00"
            + struct.pack("<i", 1)
        )
        name, val, enum = _get_a_param(data, 0)
        assert name == "EX_ACQ_scan_mode"
        assert val == 1
        assert enum[1] == ["AA", "BB", "CC"]

    def test_end_beyond_buffer(self):
        assert _get_a_param(b"\x00" * 32, 0) == (None, None, None)

    def test_name_too_short(self):
        data = _HEADER + _make_param("EX", 1, 1, 0, 0)
        assert _get_a_param(data, 0) == (None, None, None)

    def test_name_without_underscore(self):
        data = _HEADER + _make_param("ABCDEF", 1, 1, 0, 0)
        assert _get_a_param(data, 0) == (None, None, None)

    def test_type_out_of_range(self):
        data = _HEADER + _make_param("EX_ACQ_x", 9, 1, 0, 0)
        assert _get_a_param(data, 0) == (None, None, None)


class TestParseParameterData:
    def test_none_node(self):
        assert _parse_parameter_data(None) == ({}, {})

    def test_none_text(self):
        assert _parse_parameter_data(_TextNode(None)) == ({}, {})

    def test_invalid_base64(self):
        assert _parse_parameter_data(_TextNode("!!!not base64!!!")) == ({}, {})

    def test_roundtrip_int_and_enum(self):
        data = (
            _HEADER
            + _make_param("EX_ACQ_scan_mode", 4, 1, 8, 13)
            + b"AA,BB,CC\x00"
            + struct.pack("<i", 2)
        )
        node = _TextNode(base64.b64encode(data).decode())
        params, enum_map = _parse_parameter_data(node)
        assert params["EX_ACQ_scan_mode"] == 2
        assert enum_map["EX_ACQ_scan_mode"] == ["AA", "BB", "CC"]

    def test_stops_at_first_invalid(self):
        # A valid param followed by junk stops iteration at the junk.
        good = _make_param("EX_ACQ_flip_angle", 1, 1, 0, 4)
        data = _HEADER + good + struct.pack("<i", 12)
        node = _TextNode(base64.b64encode(data).decode())
        params, _ = _parse_parameter_data(node)
        assert params == {"EX_ACQ_flip_angle": 12}


# ===========================================================================
# Mapping / derived-field branches not covered by test_examcard.py
# ===========================================================================

class TestMappingBranches:
    def test_gex_and_if_name_cleaning(self):
        # USEFUL_PHILIPS_PARAMETERS is a whitelist, so add temp entries to
        # exercise the GEX_/IF_ prefix-stripping branches, then restore.
        added = {"GEX_custom_thing", "IF_custom_thing"}
        original = set(ec.USEFUL_PHILIPS_PARAMETERS)
        ec.USEFUL_PHILIPS_PARAMETERS.update(added)
        try:
            scan_data = {
                "name": "T",
                "parameters": {"GEX_custom_thing": 5, "IF_custom_thing": 9},
                "enum_map": {},
            }
            result = apply_examcard_to_dicom_mapping(scan_data)
            assert result["Philips_custom_thing"] in (5, 9)
            # Both cleaned to the same key; last write wins but both branches ran.
            assert "Philips_custom_thing" in result
        finally:
            ec.USEFUL_PHILIPS_PARAMETERS.clear()
            ec.USEFUL_PHILIPS_PARAMETERS.update(original)

    def test_whitelisted_enum_translation(self):
        # Unmapped-but-whitelisted param that is an int + has enum_map entry.
        scan_data = {
            "name": "T",
            "parameters": {"EX_ACQ_gradient_mode": 1},
            "enum_map": {"EX_ACQ_gradient_mode": ["DEFAULT", "FAST"]},
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        assert result["Philips_ACQ_gradient_mode"] == "FAST"

    def test_reconstruction_diameter(self):
        scan_data = {
            "name": "T",
            "parameters": {
                "EX_PROC_recon_resolution": 256,
                "EX_PROC_recon_voxel_size_m": 1.0,
                "EX_PROC_recon_voxel_size_p": 1.0,
            },
            "enum_map": {},
        }
        result = apply_examcard_to_dicom_mapping(scan_data)
        assert result["ReconstructionDiameter"] == 256.0

    def test_tr_te_from_combined_string_when_missing(self):
        dicom_fields = {}
        params = {"IF_act_rep_time_echo_time": "9.8 / 4.6"}
        _calculate_derived_fields(dicom_fields, params)
        assert dicom_fields["RepetitionTime"] == 9.8
        assert dicom_fields["EchoTime"] == 4.6

    def test_te_only_from_combined_string(self):
        # RepetitionTime already present -> only TE branch parses.
        dicom_fields = {"RepetitionTime": 100.0}
        params = {"IF_act_rep_time_echo_time": "100.0 / 3.2"}
        _calculate_derived_fields(dicom_fields, params)
        assert dicom_fields["RepetitionTime"] == 100.0
        assert dicom_fields["EchoTime"] == 3.2

    def test_te_combined_string_bad_second_part(self):
        dicom_fields = {"RepetitionTime": 100.0}
        params = {"IF_act_rep_time_echo_time": "100.0 / notanumber"}
        _calculate_derived_fields(dicom_fields, params)
        assert "EchoTime" not in dicom_fields

    def test_acquisition_duration_value_error(self):
        dicom_fields = {}
        params = {"IF_str_total_scan_time": "bad:xx"}
        _calculate_derived_fields(dicom_fields, params)
        assert "AcquisitionDuration" not in dicom_fields

    def test_number_of_slices_float(self):
        dicom_fields = {}
        params = {"EX_GEO_stacks_slices": 30.0}
        _calculate_derived_fields(dicom_fields, params)
        assert dicom_fields["NumberOfSlices"] == 30

    def test_tr_combined_string_bad_first_part(self):
        # RepetitionTime missing and first part not parsable -> ValueError swallowed.
        dicom_fields = {}
        params = {"IF_act_rep_time_echo_time": "notanumber / 4.6"}
        _calculate_derived_fields(dicom_fields, params)
        assert "RepetitionTime" not in dicom_fields

    def test_sort_output_other_dicom_field(self):
        # A non-Philips DICOM field that is not in DICOM_FIELD_ORDER falls into
        # the "other_dicom" bucket (sorted alphabetically after ordered fields).
        fields = {
            "SeriesDescription": "T",   # in DICOM_FIELD_ORDER
            "ZCustomTag": 1,            # not in order, not Philips_
            "ACustomTag": 2,            # not in order, not Philips_
            "Philips_z": 3,
        }
        result = _sort_output_fields(fields)
        keys = list(result.keys())
        assert keys.index("SeriesDescription") < keys.index("ACustomTag")
        assert keys.index("ACustomTag") < keys.index("ZCustomTag")  # alphabetical
        assert keys.index("ZCustomTag") < keys.index("Philips_z")


# ===========================================================================
# Schema-format helpers
# ===========================================================================

class TestSchemaHelpers:
    def test_extract_series_parameters_dual_echo(self):
        raw = {"parameters": {"EX_ACQ_first_echo_time": 10.0, "EX_ACQ_second_echo_time": 20.0}}
        series = _extract_series_parameters({}, raw)
        assert series == {"EchoTime": [10.0, 20.0]}

    def test_extract_series_parameters_single_echo(self):
        raw = {"parameters": {"EX_ACQ_first_echo_time": 10.0, "EX_ACQ_second_echo_time": 0}}
        assert _extract_series_parameters({}, raw) == {}

    def test_generate_series_combinations_empty(self):
        assert _generate_series_combinations({}) == []

    def test_generate_series_combinations(self):
        series = _generate_series_combinations({"EchoTime": [5.0, 10.0]})
        assert len(series) == 2
        assert series[0] == {"name": "Series 01", "fields": [{"field": "EchoTime", "value": 5.0}]}

    def test_convert_to_schema_skips_metadata_and_empty(self):
        dicom_fields = {
            "Manufacturer": "Philips",
            "ExamCard_Path": "x",
            "ExamCard_FileName": "x",
            "ScanName": "skip-me",
            "EmptyField": "",
            "NoneField": None,
            "EchoTime": [10.0, 20.0],
        }
        raw = {"parameters": {"EX_ACQ_first_echo_time": 10.0, "EX_ACQ_second_echo_time": 20.0}}
        schema = _convert_to_schema_format(dicom_fields, raw, "MyScan", "/tmp/my.ExamCard")
        field_names = {f["field"] for f in schema["fields"]}
        assert "Manufacturer" in field_names
        # Metadata / empty / series-varying fields excluded from acquisition fields.
        for excluded in ["ExamCard_Path", "ExamCard_FileName", "ScanName",
                         "EmptyField", "NoneField", "EchoTime"]:
            assert excluded not in field_names
        # EchoTime becomes a series-varying param.
        assert len(schema["series"]) == 2
        assert schema["acquisition_info"]["protocol_name"] == "MyScan"


# ===========================================================================
# _parse_examcard_all_scans branch coverage via synthetic SOAP document
# ===========================================================================

def _build_soap(scan_xml):
    return (
        "<SOAP-ENV:Envelope xmlns:SOAP-ENV='urn:soap' xmlns:x='urn:x'>"
        "<ExamCard><methodDescription>General card</methodDescription></ExamCard>"
        f"{scan_xml}"
        "</SOAP-ENV:Envelope>"
    )


class TestParseAllScansSynthetic:
    def test_step_missing_single_scan_skipped(self, tmp_path):
        # ExecutionStep whose singleScan cannot be resolved -> continue.
        soap = _build_soap("<ExecutionStep><nothing/></ExecutionStep>")
        f = tmp_path / "s.ExamCard"
        f.write_text(soap)
        result = _parse_examcard_all_scans(str(f))
        assert "General" in result
        # Only General should be present (scan was skipped).
        assert list(result.keys()) == ["General"]

    def test_step_missing_scan_procedure_skipped(self, tmp_path):
        soap = _build_soap(
            "<ExecutionStep><singleScan><name>S1</name></singleScan></ExecutionStep>"
        )
        f = tmp_path / "s.ExamCard"
        f.write_text(soap)
        result = _parse_examcard_all_scans(str(f))
        assert list(result.keys()) == ["General"]

    def test_scan_name_fallback_to_index(self, tmp_path):
        # singleScan + scanProcedure present but no name anywhere -> Scan_1.
        soap = _build_soap(
            "<ExecutionStep><singleScan>"
            "<scanProcedure><parameterData></parameterData></scanProcedure>"
            "</singleScan></ExecutionStep>"
        )
        f = tmp_path / "s.ExamCard"
        f.write_text(soap)
        result = _parse_examcard_all_scans(str(f))
        assert "Scan_1" in result
        assert result["Scan_1"]["name"] == "Scan_1"

    def test_scan_name_from_scan_procedure(self, tmp_path):
        # No name on singleScan, name present on scanProcedure.
        soap = _build_soap(
            "<ExecutionStep><singleScan>"
            "<scanProcedure><name>ProcName</name>"
            "<parameterData></parameterData></scanProcedure>"
            "</singleScan></ExecutionStep>"
        )
        f = tmp_path / "s.ExamCard"
        f.write_text(soap)
        result = _parse_examcard_all_scans(str(f))
        assert "ProcName" in result

    def test_scan_loop_exception_skipped(self, tmp_path, monkeypatch):
        # Force an exception while processing a scan; the loop should swallow it
        # (lines 461-463 "except Exception: continue") and still return General.
        soap = _build_soap(
            "<ExecutionStep><singleScan><name>S1</name>"
            "<scanProcedure><parameterData></parameterData></scanProcedure>"
            "</singleScan></ExecutionStep>"
        )
        f = tmp_path / "s.ExamCard"
        f.write_text(soap)

        def boom(node):
            raise RuntimeError("boom")

        monkeypatch.setattr(ec, "_parse_parameter_data", boom)
        result = _parse_examcard_all_scans(str(f))
        assert list(result.keys()) == ["General"]

    def test_scan_properties_merged(self, tmp_path):
        soap = _build_soap(
            "<ExecutionStep><singleScan><name>S1</name>"
            "<scanProcedure><parameterData></parameterData></scanProcedure>"
            "<scanProperties><foo>bar</foo></scanProperties>"
            "</singleScan></ExecutionStep>"
        )
        f = tmp_path / "s.ExamCard"
        f.write_text(soap)
        result = _parse_examcard_all_scans(str(f))
        assert result["S1"]["foo"] == "bar"
