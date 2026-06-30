"""
Tests for Siemens "MR print protocol" (XML/TXT) loading.

Covers the label->DICOM mapping, value/unit parsing, format auto-detection, and
end-to-end schema-format loading against real Connectom axon-diameter protocols.
"""

from pathlib import Path

import pytest

from dicompare.io.printprot import (
    load_printprot_file,
    load_printprot_file_schema_format,
    apply_printprot_to_dicom_mapping,
    _split_value_unit,
    _detect_format,
    _parse_header_title,
)

FIXTURES = Path(__file__).parent / "fixtures" / "printprot"
XML_FILE = FIXTURES / "axcal_forJelle.xml"
TXT_FILE = FIXTURES / "AxonDiameterProtocol.txt"


# ---------------------------------------------------------------------------
# Value/unit parsing
# ---------------------------------------------------------------------------

class TestSplitValueUnit:
    def test_number_with_unit(self):
        assert _split_value_unit("3900 ms") == (3900.0, "ms")

    def test_percent(self):
        assert _split_value_unit("100.0 %") == (100.0, "%")

    def test_compound_unit(self):
        assert _split_value_unit("2272 Hz/Px") == (2272.0, "Hz/Px")

    def test_bare_number(self):
        assert _split_value_unit("256") == (256.0, None)

    def test_on_off_kept_as_string(self):
        assert _split_value_unit("On") == ("On", None)

    def test_descriptive_string_kept(self):
        assert _split_value_unit("A >> P") == ("A >> P", None)

    def test_position_string_not_a_scalar(self):
        # Multiple numbers -> not a simple scalar, keep as string.
        assert _split_value_unit("L2.4 P2.0 H0.0 mm") == ("L2.4 P2.0 H0.0 mm", None)

    def test_empty(self):
        assert _split_value_unit("") == ("", None)


class TestHeaderTitle:
    def test_connectom_header(self):
        fields = _parse_header_title("SIEMENS MAGNETOM ConnectomA syngo MR D11")
        assert fields["Manufacturer"] == "SIEMENS"
        assert fields["ManufacturerModelName"] == "MAGNETOM ConnectomA"
        assert fields["SoftwareVersions"] == "syngo MR D11"


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

class TestApplyMapping:
    def _protocol(self, params):
        return {"name": "Test", "title": "SIEMENS MAGNETOM ConnectomA syngo MR D11", "params": params}

    def test_basic_dicom_fields(self):
        proto = self._protocol({
            ("Routine", "TR"): "3500 ms",
            ("Routine", "TE"): "66.0 ms",
            ("Routine", "Averages"): "1",
            ("Routine", "Slice thickness"): "2.5 mm",
        })
        result = apply_printprot_to_dicom_mapping(proto)
        assert result["RepetitionTime"] == 3500
        assert result["EchoTime"] == 66
        assert result["NumberOfAverages"] == 1
        assert result["SliceThickness"] == 2.5
        assert result["Manufacturer"] == "SIEMENS"

    def test_derived_diffusion_fields(self):
        proto = self._protocol({
            ("Sequence", "Small delta"): "15 ms",
            ("Sequence", "Big Delta"): "30 ms",
            ("Sequence", "Directions"): "Jones31",
            ("BOLD", "Diffusion mode"): "Free",
        })
        result = apply_printprot_to_dicom_mapping(proto)
        assert result["SmallDelta"] == 15
        assert result["BigDelta"] == 30
        assert result["DiffusionDirectionSet"] == "Jones31"
        assert result["DiffusionMode"] == "Free"

    def test_single_bvalue_is_acquisition_level(self):
        proto = self._protocol({("BOLD", "b-value"): "30450 s/mm²"})
        result = apply_printprot_to_dicom_mapping(proto)
        assert result["DiffusionBValue"] == 30450

    def test_pixel_spacing_derived(self):
        proto = self._protocol({
            ("Routine", "Base resolution"): "110",
            ("Routine", "FoV read"): "220 mm",
        })
        result = apply_printprot_to_dicom_mapping(proto)
        assert result["Rows"] == 110
        assert result["Columns"] == 110
        assert result["PixelSpacing"] == [2.0, 2.0]

    def test_unmapped_labels_dropped(self):
        proto = self._protocol({("Properties", "Inline movie"): "Off"})
        result = apply_printprot_to_dicom_mapping(proto)
        assert "Inline movie" not in result
        assert "InlineMovie" not in result


class TestDetectFormat:
    def test_xml(self):
        assert _detect_format('<?xml version="1.0"?>\n<PrintOut>') == "xml"

    def test_txt(self):
        assert _detect_format("\n\n   SIEMENS MAGNETOM ConnectomA\n") == "txt"


# ---------------------------------------------------------------------------
# Integration: real fixtures
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not XML_FILE.exists(), reason="XML fixture missing")
class TestXmlIntegration:
    def test_ten_acquisitions(self):
        schemas = load_printprot_file_schema_format(str(XML_FILE))
        assert len(schemas) == 10
        names = [s["acquisition_info"]["protocol_name"] for s in schemas]
        assert "AX_delta30" in names
        assert "localizer" in names

    def test_diffusion_time_sweep(self):
        schemas = load_printprot_file_schema_format(str(XML_FILE))
        by_name = {s["acquisition_info"]["protocol_name"]: s for s in schemas}
        expected = {"AX_delta17p3": 18, "AX_delta30": 30, "AX_delta42": 42, "AX_delta55": 55}
        for name, big_delta in expected.items():
            fields = {f["field"]: f["value"] for f in by_name[name]["fields"]}
            assert fields["BigDelta"] == big_delta, name

    def test_acquisition_info_source(self):
        schemas = load_printprot_file_schema_format(str(XML_FILE))
        assert schemas[0]["acquisition_info"]["source_type"] == "printprot"

    def test_raw_loader(self):
        protocols = load_printprot_file(str(XML_FILE))
        assert len(protocols) == 10
        assert all("protocol_name" in p and "fields" in p for p in protocols)


@pytest.mark.skipif(not TXT_FILE.exists(), reason="TXT fixture missing")
class TestTxtIntegration:
    def test_seven_acquisitions(self):
        schemas = load_printprot_file_schema_format(str(TXT_FILE))
        assert len(schemas) == 7
        names = [s["acquisition_info"]["protocol_name"] for s in schemas]
        assert "Axon Diameter" in names
        assert "fast DKI" in names

    def test_axon_diameter_high_bvalue(self):
        schemas = load_printprot_file_schema_format(str(TXT_FILE))
        by_name = {s["acquisition_info"]["protocol_name"]: s for s in schemas}
        fields = {f["field"]: f["value"] for f in by_name["Axon Diameter"]["fields"]}
        assert fields["DiffusionBValue"] == 30450
        assert fields["BigDelta"] == 30
        assert fields["SmallDelta"] == 15

    def test_header_parsed_for_all(self):
        schemas = load_printprot_file_schema_format(str(TXT_FILE))
        for s in schemas:
            fields = {f["field"]: f["value"] for f in s["fields"]}
            assert fields.get("Manufacturer") == "SIEMENS"
