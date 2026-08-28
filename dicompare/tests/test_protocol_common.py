"""Tests for shared importer post-processing (dicompare/io/protocol_common.py)."""

from dicompare.io.protocol_common import (
    convert_to_schema_format,
    generate_series_combinations,
    sort_output_fields,
)


class TestSortOutputFields:
    def test_known_other_last_ordering(self):
        fields = {
            "Vendor_thing": 1,
            "ZZUnknown": 2,
            "EchoTime": 3,
            "RepetitionTime": 4,
            "AAUnknown": 5,
        }
        ordered = list(sort_output_fields(
            fields, ["RepetitionTime", "EchoTime"],
            is_last_group=lambda k: k.startswith("Vendor_")).keys())
        assert ordered == ["RepetitionTime", "EchoTime", "AAUnknown", "ZZUnknown", "Vendor_thing"]

    def test_no_last_group(self):
        ordered = list(sort_output_fields(
            {"B": 1, "A": 2, "EchoTime": 3}, ["EchoTime"]).keys())
        assert ordered == ["EchoTime", "A", "B"]


class TestGenerateSeriesCombinations:
    def test_empty(self):
        assert generate_series_combinations({}) == []

    def test_single_param(self):
        series = generate_series_combinations({"EchoTime": [5.0, 10.0]})
        assert [s["name"] for s in series] == ["Series 01", "Series 02"]
        assert series[0]["fields"] == [{"field": "EchoTime", "value": 5.0}]

    def test_cartesian_product_with_priority(self):
        series = generate_series_combinations(
            {"ImageType": ["M", "P"], "EchoTime": [5.0, 10.0]},
            priority=("EchoTime",))
        assert len(series) == 4
        # EchoTime expands outermost because of priority.
        assert series[0]["fields"][0] == {"field": "EchoTime", "value": 5.0}
        assert series[1]["fields"] == [
            {"field": "EchoTime", "value": 5.0},
            {"field": "ImageType", "value": "P"},
        ]


class TestConvertToSchemaFormat:
    def test_provenance_keys_follow_source_type(self):
        schema = convert_to_schema_format(
            {"EchoTime": 5.0}, "MyScan", "examcard", "/tmp/x.ExamCard")
        info = schema["acquisition_info"]
        assert info["source_type"] == "examcard"
        assert info["examcard_path"] == "/tmp/x.ExamCard"
        assert info["examcard_filename"] == "x.ExamCard"
        assert info["protocol_name"] == "MyScan"

    def test_series_varying_and_skip_fields_excluded(self):
        schema = convert_to_schema_format(
            {"EchoTime": 5.0, "RepetitionTime": 2000, "ScanName": "x", "Empty": ""},
            "S", "printprot", "/tmp/p.txt",
            series_params={"EchoTime": [5.0, 10.0]},
            skip_fields=("ScanName",))
        names = [f["field"] for f in schema["fields"]]
        assert names == ["RepetitionTime"]
        assert len(schema["series"]) == 2
