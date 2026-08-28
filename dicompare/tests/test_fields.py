"""Tests for the canonical field registry (dicompare/fields.py)."""

import pytest

from dicompare.fields import (
    FIELD_REGISTRY,
    check_value,
    decode,
    get_field,
    registry_to_json,
    validate_fields,
)


class TestDecode:
    def test_siemens_coil_combine_code(self):
        assert decode("CoilCombinationMethod", "siemens.ucCoilCombineMode", 2) == "Adaptive Combine"
        assert decode("CoilCombinationMethod", "siemens.ucCoilCombineMode", 1) == "Sum of Squares"

    def test_unknown_code_kept_raw(self):
        assert decode("CoilCombinationMethod", "siemens.ucCoilCombineMode", 99) == 99

    def test_unregistered_source_passthrough(self):
        assert decode("CoilCombinationMethod", "no.such.source", 2) == 2

    def test_unregistered_field_passthrough(self):
        assert decode("NoSuchField", "siemens.ucCoilCombineMode", 2) == 2

    def test_philips_scan_mode_multislice_is_2d(self):
        # Philips MS (multi-slice) and M2D are 2D acquisitions in DICOM terms.
        assert decode("MRAcquisitionType", "philips.EX_ACQ_scan_mode", 2) == "2D"
        assert decode("MRAcquisitionType", "philips.EX_ACQ_scan_mode", 3) == "2D"
        assert decode("MRAcquisitionType", "philips.EX_ACQ_scan_mode", 1) == "3D"

    def test_ge_imode_3de(self):
        assert decode("MRAcquisitionType", "ge.IMODE", "3DE") == "3D"

    def test_siemens_phase_encoding_type(self):
        assert decode("InPlanePhaseEncodingDirection", "siemens.pro.lPhaseEncodingType", 1) == "ROW"
        assert decode("InPlanePhaseEncodingDirection", "siemens.pro.lPhaseEncodingType", 2) == "COL"


class TestCheckValue:
    def test_canonical_value_ok(self):
        assert check_value("InPlanePhaseEncodingDirection", "ROW") == []
        assert check_value("CoilCombinationMethod", "Adaptive Combine") == []

    def test_case_insensitive_ok(self):
        assert check_value("InPlanePhaseEncodingDirection", "row") == []

    def test_raw_code_flagged(self):
        problems = check_value("CoilCombinationMethod", 2)
        assert len(problems) == 1
        assert "vocabulary" in problems[0]

    def test_display_string_flagged(self):
        problems = check_value("InPlanePhaseEncodingDirection", "A >> P")
        # Both a display string and out-of-vocabulary.
        assert any("display string" in p for p in problems)
        assert any("vocabulary" in p for p in problems)

    def test_display_string_flagged_even_for_unregistered_field(self):
        problems = check_value("SomeRandomField", "A >> P")
        assert any("display string" in p for p in problems)

    def test_unregistered_field_ok(self):
        assert check_value("SomeRandomField", "anything") == []

    def test_list_values_checked_elementwise(self):
        assert check_value("PatientPosition", ["HFS", "FFS"]) == []
        assert len(check_value("PatientPosition", ["HFS", "BAD"])) == 1

    def test_none_ok(self):
        assert check_value("CoilCombinationMethod", None) == []


class TestValidateFields:
    def test_clean_fields(self):
        problems = validate_fields({
            "RepetitionTime": 3500,
            "InPlanePhaseEncodingDirection": "COL",
            "UnregisteredThing": "whatever",
        })
        assert problems == []

    def test_problems_collected(self):
        problems = validate_fields({
            "InPlanePhaseEncodingDirection": "A >> P",
            "CoilCombinationMethod": 2,
        }, context="test-import")
        assert len(problems) == 3  # display + vocab for PE, vocab for coil


class TestRegistryExport:
    def test_json_shape(self):
        out = registry_to_json()
        pe = out["InPlanePhaseEncodingDirection"]
        assert pe["vocabulary"] == ["ROW", "COL"]
        assert pe["tag"] == "0018,1312"
        assert "encodings" not in pe  # importer-internal

    def test_continuous_fields_exported(self):
        out = registry_to_json()
        assert out["EchoTime"]["continuous"] is True
        assert out["EchoTime"]["unit"] == "ms"
        assert out["MagneticFieldStrength"]["suggestedTolerance"] == 0.3

    def test_every_field_has_type(self):
        for keyword, entry in registry_to_json().items():
            assert entry["valueType"] in (
                "string", "number", "list_string", "list_number"), keyword

    def test_registry_keys_match_keywords(self):
        for keyword, fdef in FIELD_REGISTRY.items():
            assert fdef.keyword == keyword
