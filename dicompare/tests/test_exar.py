"""
Tests for Siemens .exar1 archive loading.

The fixture is the spine-generic XA61 protocol export, which mixes 3D
(MP2RAGE-style T1w, T2w, 3D GRE) and 2D (localizer, 2D multi-echo GRE, DWI)
acquisitions in one archive — the combination that exposed the slice
thickness regression.
"""

import pytest
from pathlib import Path

from dicompare import load_exar_file_schema_format


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "exar"
XA61_FIXTURE = FIXTURES_DIR / "spine-generic_CimaX_XA61_ZOOMit.exar1"


def _fields_by_protocol():
    """Map protocol name -> {field: value} for every protocol in the fixture."""
    protocols = load_exar_file_schema_format(str(XA61_FIXTURE))
    return {
        p["acquisition_info"]["protocol_name"]: {
            f["field"]: f.get("value") for f in p["fields"]
        }
        for p in protocols
    }


class TestLoadExarFileSchemaFormat:
    """Tests for load_exar_file_schema_format."""

    def test_fixture_exists(self):
        assert XA61_FIXTURE.exists(), f"Test file not found: {XA61_FIXTURE}"

    def test_loads_every_protocol(self):
        protocols = load_exar_file_schema_format(str(XA61_FIXTURE))

        assert len(protocols) == 8
        for p in protocols:
            assert set(p) == {"acquisition_info", "fields", "series"}
            assert p["acquisition_info"]["source_type"] == "exar1"
            assert p["acquisition_info"]["exar_filename"] == XA61_FIXTURE.name
            assert len(p["fields"]) > 0

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_exar_file_schema_format(str(FIXTURES_DIR / "does_not_exist.exar1"))


class TestExarSliceThickness:
    """2D and 3D protocols in one archive must each get the right thickness.

    Before sKSpace.ucDimension was consulted, the 2D protocols here were
    treated as 3D and their thickness divided by the slice count: the 5 mm
    DWI came out at 0.078125 mm and the 5 mm 2D GRE at 0.15625 mm.
    """

    # protocol name -> (slice thickness in mm, acquisition type)
    EXPECTED = {
        "Localizer": (6.0, "2D"),
        "GRE-ME": (5.0, "2D"),
        "DWI_ES192_TE72_SPAIRweak": (5.0, "2D"),
        "GRE-MT0": (5.0, "3D"),
        "GRE-MT1": (5.0, "3D"),
        "GRE-T1w": (5.0, "3D"),
        "T1w": (1.0, "3D"),
        "T2w": (0.8, "3D"),
    }

    @pytest.fixture(scope="class")
    def protocols(self):
        return _fields_by_protocol()

    @pytest.mark.parametrize("protocol_name", sorted(EXPECTED))
    def test_slice_thickness_and_acquisition_type(self, protocols, protocol_name):
        expected_thickness, expected_type = self.EXPECTED[protocol_name]
        fields = protocols[protocol_name]

        assert fields["SliceThickness"] == pytest.approx(expected_thickness)
        assert fields["MRAcquisitionType"] == expected_type

    def test_slab_thickness_only_on_3d(self, protocols):
        for protocol_name, (_, expected_type) in self.EXPECTED.items():
            fields = protocols[protocol_name]
            if expected_type == "3D":
                assert fields["SlabThickness"] > fields["SliceThickness"]
            else:
                assert "SlabThickness" not in fields


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
