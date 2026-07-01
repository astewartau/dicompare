"""
Tests for diffusion gradient encoding: .dvs / bvec / bval parsing, dvs->bvec/bval
conversion, and descriptor derivation.
"""

import math
from pathlib import Path

import pytest

from dicompare.io.gradients import (
    parse_dvs,
    parse_bval,
    parse_bvec,
    dvs_to_bvec_bval,
    derive_diffusion_descriptors,
    descriptors_from_dvs,
    descriptors_from_bvec_bval,
)

FIXTURES = Path(__file__).parent / "fixtures" / "gradients"
DVS_FILE = FIXTURES / "DiffusionVectors_AxonDiameter_ERJV.dvs"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class TestParseDvs:
    def test_header_and_vectors(self):
        text = (
            "[directions=3]\n"
            "CoordinateSystem = xyz\n"
            "Normalisation = none\n"
            "Vector[0] = ( 0.000000, 0.000000, 0.000000 )\n"
            "Vector[1] = ( 1.000000, 0.000000, 0.000000 )\n"
            "Vector[2] = ( 0.443532, 0.443532, 0.443532 )\n"
        )
        p = parse_dvs(text)
        assert p["directions"] == 3
        assert p["coordinate_system"] == "xyz"
        assert p["normalisation"] == "none"
        assert len(p["vectors"]) == 3
        assert p["vectors"][1] == (1.0, 0.0, 0.0)


class TestParseBvecBval:
    def test_bval(self):
        assert parse_bval("0 1000 2000 0") == [0.0, 1000.0, 2000.0, 0.0]

    def test_bvec(self):
        text = "0 1 0\n0 0 1\n0 0 0"
        vecs = parse_bvec(text)
        assert vecs == [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]

    def test_bvec_wrong_rows(self):
        with pytest.raises(ValueError):
            parse_bvec("0 1\n0 0")


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

class TestConversion:
    def test_bval_from_magnitude(self):
        # |g|=1 -> b_max ; |g|=0.5 -> b_max*0.25 ; |g|=0 -> 0
        vectors = [(1.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.0, 0.0)]
        bvecs, bvals = dvs_to_bvec_bval(vectors, b_max=30000)
        assert bvals[0] == pytest.approx(30000)
        assert bvals[1] == pytest.approx(7500)
        assert bvals[2] == 0.0
        # unit direction preserved / b0 zeroed
        assert bvecs[0] == pytest.approx((1.0, 0.0, 0.0))
        assert bvecs[2] == (0.0, 0.0, 0.0)

    def test_bvec_is_unit(self):
        vectors = [(0.3, 0.4, 0.0)]  # |g| = 0.5
        bvecs, _ = dvs_to_bvec_bval(vectors, b_max=1000)
        assert math.isclose(math.hypot(*bvecs[0][:2]), 1.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------

class TestDescriptors:
    def test_two_shell(self):
        # 1 b0, 2 dirs at b=1000, 3 dirs at b=2000
        bvals = [0, 1000, 1010, 2000, 1990, 2005]
        bvecs = [(0, 0, 0)] + [(1, 0, 0)] * 5
        d = derive_diffusion_descriptors(bvecs, bvals)
        assert d["NumberOfDiffusionShells"] == 2
        assert d["DiffusionBValues"] == [0, 1000, 2000]
        assert d["DirectionsPerShell"] == [1, 2, 3]
        assert d["NumberOfB0Volumes"] == 1
        assert d["NumberOfDiffusionVolumes"] == 6


# ---------------------------------------------------------------------------
# Integration: real ERJV axon-diameter vector file
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not DVS_FILE.exists(), reason="dvs fixture missing")
class TestErjvIntegration:
    B_MAX = 30450

    def test_hidden_two_shell(self):
        d = descriptors_from_dvs(DVS_FILE.read_text(), b_max=self.B_MAX)
        assert d["NumberOfDiffusionVolumes"] == 190
        assert d["NumberOfB0Volumes"] == 10
        assert d["NumberOfDiffusionShells"] == 2
        assert d["DiffusionBValues"] == [0, 5990, 30450]
        assert d["DirectionsPerShell"] == [10, 60, 120]

    def test_dvs_bvecbval_roundtrip_matches(self):
        text = DVS_FILE.read_text()
        p = parse_dvs(text)
        bvecs, bvals = dvs_to_bvec_bval(p["vectors"], self.B_MAX)
        bval_text = " ".join(str(round(b)) for b in bvals)
        bvec_text = "\n".join(
            " ".join(f"{bvecs[i][ax]:.6f}" for i in range(len(bvecs))) for ax in range(3)
        )
        via_pair = descriptors_from_bvec_bval(bvec_text, bval_text)
        via_dvs = descriptors_from_dvs(text, b_max=self.B_MAX)
        assert via_pair["DiffusionBValues"] == via_dvs["DiffusionBValues"]
        assert via_pair["DirectionsPerShell"] == via_dvs["DirectionsPerShell"]
