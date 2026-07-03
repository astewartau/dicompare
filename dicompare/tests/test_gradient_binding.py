"""
Tests for attach_gradient_files_to_acquisitions: matching gradient files to
acquisitions and merging derived descriptors (the shared binder used by the web
app and the embed).
"""

from pathlib import Path

import pytest

from dicompare.interface import attach_gradient_files_to_acquisitions

FIXTURES = Path(__file__).parent / "fixtures" / "gradients"
DVS_FILE = FIXTURES / "DiffusionVectors_AxonDiameter_ERJV.dvs"


def _acq(protocol_name, **fields):
    """Build a minimal UI-acquisition dict."""
    return {
        "id": protocol_name,
        "protocolName": protocol_name,
        "acquisitionFields": [
            {"keyword": k, "name": k, "value": v} for k, v in fields.items()
        ],
    }


def _field(acq, name):
    for f in acq["acquisitionFields"]:
        if (f.get("keyword") or f.get("name")) == name:
            return f["value"]
    return None


class TestBinding:
    def test_bvec_bval_bind_to_sole_diffusion(self):
        acqs = [
            _acq("localizer"),
            _acq("dwi", DiffusionBValue=1000),
        ]
        bvec = "1 0 0\n0 1 0\n0 0 1"
        bval = "1000 1000 1000"
        result = attach_gradient_files_to_acquisitions(
            acqs,
            [{"name": "sub-01_dwi.bvec", "content": bvec},
             {"name": "sub-01_dwi.bval", "content": bval}],
        )
        assert result["unmatched"] == []
        assert len(result["bound"]) == 1
        assert result["bound"][0]["protocolName"] == "dwi"
        dwi = next(a for a in result["acquisitions"] if a["protocolName"] == "dwi")
        assert _field(dwi, "NumberOfDiffusionShells") == 1

    def test_no_match_reported_unmatched(self):
        # No diffusion acquisition to bind to.
        acqs = [_acq("t1w"), _acq("t2w")]
        result = attach_gradient_files_to_acquisitions(
            acqs,
            [{"name": "x.bvec", "content": "1\n0\n0"},
             {"name": "x.bval", "content": "1000"}],
        )
        assert result["bound"] == []
        assert result["unmatched"] == ["x"]

    def test_incomplete_pair_unmatched(self):
        acqs = [_acq("dwi", DiffusionBValue=1000)]
        result = attach_gradient_files_to_acquisitions(
            acqs, [{"name": "x.bval", "content": "0 1000"}]
        )
        assert result["bound"] == []
        assert result["unmatched"] == ["x"]

    def test_dvs_missing_bvalue_unmatched(self):
        # dvs needs a DiffusionBValue on the target to interpret magnitudes.
        acqs = [_acq("dwi", DiffusionDirectionSet="Scheme")]
        result = attach_gradient_files_to_acquisitions(
            acqs, [{"name": "Scheme.dvs", "content": "[directions=1]\nVector[0] = ( 1.0, 0.0, 0.0 )"}]
        )
        assert result["bound"] == []
        assert "Scheme" in result["unmatched"]


@pytest.mark.skipif(not DVS_FILE.exists(), reason="dvs fixture missing")
class TestDvsIntegration:
    def test_dvs_binds_by_direction_set_name(self):
        acqs = [
            _acq("Axon Diameter",
                 DiffusionBValue=30450,
                 DiffusionDirectionSet="DiffusionVectors_AxonDiameter_ERJV"),
            _acq("Axon Diameter - repetition",
                 DiffusionBValue=30450,
                 DiffusionDirectionSet="DiffusionVectors_AxonDiameter_ERJV"),
            _acq("t1w"),
        ]
        result = attach_gradient_files_to_acquisitions(
            acqs,
            [{"name": "DiffusionVectors_AxonDiameter_ERJV.dvs", "content": DVS_FILE.read_text()}],
        )
        assert result["unmatched"] == []
        # Both "Axon Diameter" scans (which name the dvs) get descriptors.
        bound_names = {b["protocolName"] for b in result["bound"]}
        assert bound_names == {"Axon Diameter", "Axon Diameter - repetition"}
        axon = next(a for a in result["acquisitions"] if a["protocolName"] == "Axon Diameter")
        assert _field(axon, "NumberOfDiffusionShells") == 2
        assert _field(axon, "DiffusionBValues") == [0, 5990, 30450]
        # t1w untouched
        t1 = next(a for a in result["acquisitions"] if a["protocolName"] == "t1w")
        assert _field(t1, "NumberOfDiffusionShells") is None
