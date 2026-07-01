"""
Diffusion gradient encoding: parse gradient files and derive protocol descriptors.

Diffusion MRI protocols are only fully described by their gradient encoding. A
scalar b-value in a scanner protocol under-describes the acquisition because, in
Siemens "Free" diffusion mode, the effective b-value of each volume is modulated
by the magnitude of the gradient vector in the ``.dvs`` file. A protocol that
looks single-shell can encode several shells.

This module parses the vendor-neutral **bvec/bval** representation (FSL layout)
and the Siemens **.dvs** vector file, converts a ``.dvs`` to bvec/bval, and
derives the validation-relevant descriptors:

- number of shells, the b-values, and the number of directions per shell,
- number of b0 volumes and total volumes,
- whether the directions cover a hemisphere or the full sphere.

Conversion (Siemens ``.dvs`` with ``Normalisation = none``): the console
b-value is ``b_max`` (the b at unit gradient), and for each raw vector ``g_i``::

    bval_i = b_max * |g_i|^2       # depends only on magnitude (convention-free)
    bvec_i = g_i / |g_i|           # unit direction (0,0,0 for b0)

The b-value shells therefore fall out of ``|g|^2`` with no coordinate/sign
ambiguity; only the *direction* convention (axis flips/handedness for an
FSL-style bvec) is vendor/tool-dependent.

The raw gradient files are consumed to derive descriptors and are not retained:
a dicompare schema stores the descriptors (validation requirements), not files.
"""

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vector = Tuple[float, float, float]

# A volume is a b0 when its b-value is at or below this (s/mm^2).
B0_THRESHOLD = 50.0


# ============================================================================
# Parsing
# ============================================================================

def parse_dvs(text: str) -> Dict[str, Any]:
    """
    Parse a Siemens diffusion vector (.dvs) file.

    Returns:
        {
            "directions": int | None,        # declared count from the header
            "coordinate_system": str | None,  # e.g. "xyz"
            "normalisation": str | None,      # e.g. "none"
            "vectors": [(x, y, z), ...],       # raw vectors, magnitudes preserved
        }
    """
    directions = None
    m = re.search(r"\[\s*directions\s*=\s*(\d+)\s*\]", text, re.IGNORECASE)
    if m:
        directions = int(m.group(1))

    def _header(key: str) -> Optional[str]:
        mm = re.search(rf"{key}\s*=\s*([^\n\r\[]+)", text, re.IGNORECASE)
        return mm.group(1).strip() if mm else None

    vectors: List[Vector] = []
    for x, y, z in re.findall(
        r"Vector\[\s*\d+\s*\]\s*=\s*\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)",
        text,
    ):
        vectors.append((float(x), float(y), float(z)))

    return {
        "directions": directions,
        "coordinate_system": _header("CoordinateSystem"),
        "normalisation": _header("Normalisation"),
        "vectors": vectors,
    }


def parse_bval(text: str) -> List[float]:
    """Parse an FSL .bval file (whitespace-separated b-values)."""
    return [float(tok) for tok in text.split()]


def parse_bvec(text: str) -> List[Vector]:
    """
    Parse an FSL .bvec file (three whitespace-separated rows: x, y, z) into a
    list of (x, y, z) direction vectors.
    """
    rows = [
        [float(tok) for tok in line.split()]
        for line in text.splitlines()
        if line.strip() != ""
    ]
    if len(rows) != 3:
        raise ValueError(f"Expected 3 rows in bvec file, found {len(rows)}")
    n = len(rows[0])
    if not all(len(r) == n for r in rows):
        raise ValueError("bvec rows have inconsistent lengths")
    return [(rows[0][i], rows[1][i], rows[2][i]) for i in range(n)]


# ============================================================================
# Conversion
# ============================================================================

def _norm(v: Vector) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def dvs_to_bvec_bval(
    vectors: Sequence[Vector], b_max: float, eps: float = 1e-6
) -> Tuple[List[Vector], List[float]]:
    """
    Convert raw .dvs vectors to (bvecs, bvals) given the protocol's max b-value.

    bval_i = b_max * |g_i|^2 ; bvec_i = g_i / |g_i| (unit), or (0,0,0) for b0.
    """
    bvecs: List[Vector] = []
    bvals: List[float] = []
    for v in vectors:
        n = _norm(v)
        if n < eps:
            bvecs.append((0.0, 0.0, 0.0))
            bvals.append(0.0)
        else:
            bvecs.append((v[0] / n, v[1] / n, v[2] / n))
            bvals.append(b_max * n * n)
    return bvecs, bvals


# ============================================================================
# Descriptor derivation
# ============================================================================

def _cluster_bvalues(bvals: Sequence[float], rel_tol: float) -> List[Dict[str, Any]]:
    """
    Cluster b-values into shells. b0 volumes (<= B0_THRESHOLD) form one cluster;
    non-zero values are grouped when within ``rel_tol`` of a running cluster mean.
    Returns clusters sorted by mean, each {"mean": float, "count": int}.
    """
    zeros = [b for b in bvals if b <= B0_THRESHOLD]
    nonzero = sorted(b for b in bvals if b > B0_THRESHOLD)

    clusters: List[Dict[str, Any]] = []
    if zeros:
        clusters.append({"mean": 0.0, "_vals": list(zeros)})

    for b in nonzero:
        placed = False
        for c in clusters:
            if c["mean"] > B0_THRESHOLD and abs(b - c["mean"]) / c["mean"] <= rel_tol:
                c["_vals"].append(b)
                c["mean"] = sum(c["_vals"]) / len(c["_vals"])
                placed = True
                break
        if not placed:
            clusters.append({"mean": b, "_vals": [b]})

    clusters.sort(key=lambda c: c["mean"])
    return [{"mean": c["mean"], "count": len(c["_vals"])} for c in clusters]


def _hemisphere_coverage(
    bvecs: Sequence[Vector], bvals: Sequence[float], cos_tol: float = -0.98
) -> str:
    """
    Classify direction sampling as "half-sphere" or "full-sphere".

    Full-sphere schemes contain antipodal pairs (a direction and, roughly, its
    negative). If a meaningful fraction of non-b0 directions have an antipode in
    the set, call it full-sphere; otherwise half-sphere.
    """
    dirs = [
        bv for bv, b in zip(bvecs, bvals)
        if b > B0_THRESHOLD and _norm(bv) > 1e-6
    ]
    if len(dirs) < 2:
        return "unknown"

    with_antipode = 0
    for i, a in enumerate(dirs):
        for j, b in enumerate(dirs):
            if i == j:
                continue
            dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]  # unit vectors
            if dot <= cos_tol:
                with_antipode += 1
                break
    return "full-sphere" if with_antipode >= 0.5 * len(dirs) else "half-sphere"


def derive_diffusion_descriptors(
    bvecs: Sequence[Vector], bvals: Sequence[float], rel_tol: float = 0.05
) -> Dict[str, Any]:
    """
    Derive validation descriptors from a (bvecs, bvals) scheme.

    Returns a plain dict of descriptor name -> value:
        NumberOfDiffusionShells   : non-zero shells (int)
        DiffusionBValues          : [0, b1, b2, ...] cluster b-values (list, incl. b0 if present)
        DirectionsPerShell        : volume count per entry of DiffusionBValues (list)
        NumberOfDiffusionVolumes  : total volumes (int)
        NumberOfB0Volumes         : b0 volume count (int)
        DiffusionHemisphereCoverage: "half-sphere" | "full-sphere" | "unknown"
    """
    clusters = _cluster_bvalues(bvals, rel_tol)
    has_b0 = bool(clusters) and clusters[0]["mean"] <= B0_THRESHOLD

    bvalues = [int(round(c["mean"] / 10.0) * 10) for c in clusters]
    per_shell = [c["count"] for c in clusters]
    n_b0 = clusters[0]["count"] if has_b0 else 0
    n_shells = len(clusters) - (1 if has_b0 else 0)

    return {
        "NumberOfDiffusionShells": n_shells,
        "DiffusionBValues": bvalues,
        "DirectionsPerShell": per_shell,
        "NumberOfDiffusionVolumes": len(bvals),
        "NumberOfB0Volumes": n_b0,
        "DiffusionHemisphereCoverage": _hemisphere_coverage(bvecs, bvals),
    }


# ============================================================================
# High-level entry
# ============================================================================

def descriptors_from_dvs(text: str, b_max: float, rel_tol: float = 0.05) -> Dict[str, Any]:
    """Parse a .dvs, convert with b_max, and derive descriptors."""
    parsed = parse_dvs(text)
    if not parsed["vectors"]:
        raise ValueError("No vectors found in .dvs file")
    bvecs, bvals = dvs_to_bvec_bval(parsed["vectors"], b_max)
    return derive_diffusion_descriptors(bvecs, bvals, rel_tol)


def descriptors_from_bvec_bval(
    bvec_text: str, bval_text: str, rel_tol: float = 0.05
) -> Dict[str, Any]:
    """Parse an FSL bvec/bval pair and derive descriptors."""
    bvals = parse_bval(bval_text)
    bvecs = parse_bvec(bvec_text)
    if len(bvecs) != len(bvals):
        raise ValueError(
            f"bvec/bval length mismatch: {len(bvecs)} directions vs {len(bvals)} b-values"
        )
    return derive_diffusion_descriptors(bvecs, bvals, rel_tol)
