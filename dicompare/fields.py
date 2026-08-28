"""
Canonical field registry.

Single source of truth for per-field knowledge that was previously scattered
across the importers, the validation helpers, and the web schema editor:

- canonical keyword, DICOM tag (or derived), VR and value type
- canonical unit
- allowed value vocabulary (the values DICOM-derived data actually reports)
- whether the field is a continuous physical parameter (exact matches brittle)
- suggested tolerance for continuous fields
- vendor encodings: raw source codes -> canonical values (e.g. Siemens
  ``ucCoilCombineMode`` 2 -> "Adaptive Combine")

Importers translate *labels* to canonical keywords themselves (that mapping is
inherently per-source), but *values* should pass through :func:`decode` when a
vendor encoding exists, and importer output should be funnelled through
:func:`validate_fields` so out-of-vocabulary values (raw codes, console display
strings) are caught at import time instead of at validation-against-real-data
time.

The registry is exported as JSON (``python -m dicompare.fields``) and consumed
by the dicompare-web schema editor (``src/data/fieldRegistry.json``) so the
lint vocabularies there cannot drift from the importers.

Only fields with an actual consumer belong here; do not add metadata
speculatively.
"""

import json
import logging
from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "FieldDef",
    "FIELD_REGISTRY",
    "get_field",
    "decode",
    "check_value",
    "validate_fields",
    "registry_to_json",
]


@dataclass(frozen=True)
class FieldDef:
    """Canonical metadata for one field."""

    keyword: str
    tag: Optional[str] = None            # "GGGG,EEEE"; None for derived fields
    vr: Optional[str] = None
    value_type: str = "string"           # string | number | list_string | list_number
    unit: Optional[str] = None           # canonical unit for numeric fields
    vocabulary: Optional[Tuple[Any, ...]] = None
    continuous: bool = False             # exact matches are brittle
    suggested_tolerance: Optional[float] = None
    # source key -> {raw value -> canonical value}. A canonical value of None
    # means "this raw code carries no information; drop the field".
    encodings: Mapping[str, Mapping[Any, Any]] = _field(default_factory=dict)


def _continuous(keyword: str, tag: str, unit: str, vr: str = "DS",
                tolerance: Optional[float] = None) -> FieldDef:
    return FieldDef(keyword=keyword, tag=tag, vr=vr, value_type="number",
                    unit=unit, continuous=True, suggested_tolerance=tolerance)


_DEFS: List[FieldDef] = [
    # ------------------------------------------------------------------
    # Enumerated fields (vocabulary = what DICOM-derived data reports)
    # ------------------------------------------------------------------
    FieldDef(
        keyword="InPlanePhaseEncodingDirection", tag="0018,1312", vr="CS",
        vocabulary=("ROW", "COL"),
        encodings={
            # Siemens .pro sSpecPara.lPhaseEncodingType
            "siemens.pro.lPhaseEncodingType": {1: "ROW", 2: "COL"},
        },
    ),
    FieldDef(
        # Derived: Siemens CSA / XA private polarity flag; ROW/COL cannot
        # express it. 1 = positive (A>>P), 0 = negative (P>>A).
        keyword="PhaseEncodingDirectionPositive", value_type="number",
        vocabulary=(0, 1),
    ),
    FieldDef(
        keyword="MRAcquisitionType", tag="0018,0023", vr="CS",
        vocabulary=("2D", "3D"),
        encodings={
            # Philips ExamCard EX_ACQ_scan_mode: MS (multi-slice) and M2D
            # (multiple 2D) are 2D acquisitions in DICOM terms.
            "philips.EX_ACQ_scan_mode": {0: "2D", 1: "3D", 2: "2D", 3: "2D"},
            # GE LxProtocol IMODE
            "ge.IMODE": {"2D": "2D", "3D": "3D", "3DE": "3D"},
        },
    ),
    FieldDef(
        keyword="CoilCombinationMethod", value_type="string",
        vocabulary=("Sum of Squares", "Adaptive Combine"),
        encodings={
            # Siemens ASCCONV ucCoilCombineMode
            "siemens.ucCoilCombineMode": {1: "Sum of Squares", 2: "Adaptive Combine"},
        },
    ),
    FieldDef(
        keyword="ComplexImageComponent", value_type="string",
        vocabulary=("MAGNITUDE", "PHASE", "REAL", "IMAGINARY", "MIXED"),
    ),
    FieldDef(
        keyword="PhotometricInterpretation", tag="0028,0004", vr="CS",
        vocabulary=("MONOCHROME1", "MONOCHROME2", "PALETTE COLOR", "RGB",
                    "YBR_FULL", "YBR_FULL_422", "YBR_PARTIAL_422",
                    "YBR_ICT", "YBR_RCT"),
    ),
    FieldDef(
        keyword="PatientPosition", tag="0018,5100", vr="CS",
        vocabulary=("HFS", "HFP", "FFS", "FFP", "HFDR", "HFDL", "FFDR", "FFDL",
                    "LFP", "LFS", "RFP", "RFS", "AFDR", "AFDL", "PFDR", "PFDL"),
        encodings={
            "philips.EX_GEO_patient_body_position": {0: "HFS", 1: "FFS"},
            "philips.EX_GEO_patient_body_orientation": {
                0: "HFS", 1: "HFP", 2: "HFDL", 3: "HFDR"},
        },
    ),
    FieldDef(
        keyword="ImagedNucleus", tag="0018,0085", vr="SH",
        vocabulary=("1H", "31P", "13C", "23NA", "19F", "129XE", "2H", "7LI"),
        encodings={
            "philips.EX_ACQ_nucleus": {0: "1H", 1: "31P", 2: "13C", 3: "23NA", 4: "19F"},
        },
    ),
    FieldDef(
        # Vendor-practical vocabulary; DICOM's own defined terms (PILS, SENSE,
        # SMASH) are rarely what vendors write.
        keyword="ParallelAcquisitionTechnique", tag="0018,9078", vr="CS",
        vocabulary=("GRAPPA", "SENSE", "mSENSE", "SMASH", "PILS", "ASSET", "ARC"),
        encodings={
            # Siemens .pro sPat.ucPATMode — enum PATSelMode in the IDEA
            # SeqDefines.h (via FreeSurfer read_meas_prot.m): 0x01 none,
            # 0x02 GRAPPA, 0x04 (m)SENSE, 0x08 2D-PAT. Product SMS-framework
            # sequences use 0x20 (slice-acceleration mode) even with MB=1.
            # 0x01 and 0x20 map to None (drop): real DICOM omits the field on
            # unaccelerated scans, dcm2niix likewise emits no technique for
            # 0x20, and the quantitative info lives in
            # ParallelReductionFactorInPlane / MultibandFactor anyway.
            # (Previous behaviour labelled both 1 and 32 as "SENSE".)
            # 0x08 is deliberately unmapped until we know what DICOM reports
            # for it — decode() keeps the raw value and logs a warning.
            "siemens.pro.ucPATMode": {1: None, 2: "GRAPPA", 4: "mSENSE", 32: None},
        },
    ),
    FieldDef(
        keyword="DiffusionHemisphereCoverage", value_type="string",
        vocabulary=("full-sphere", "half-sphere", "unknown"),
    ),

    # ------------------------------------------------------------------
    # Continuous physical parameters (canonical units; exact match brittle)
    # ------------------------------------------------------------------
    _continuous("RepetitionTime", "0018,0080", "ms", tolerance=10.0),
    _continuous("EchoTime", "0018,0081", "ms", tolerance=1.0),
    _continuous("InversionTime", "0018,0082", "ms", tolerance=10.0),
    _continuous("SliceThickness", "0018,0050", "mm", tolerance=0.1),
    _continuous("SpacingBetweenSlices", "0018,0088", "mm", tolerance=0.1),
    _continuous("PixelBandwidth", "0018,0095", "Hz/pixel", tolerance=50.0),
    _continuous("FlipAngle", "0018,1314", "deg", tolerance=2.0),
    _continuous("ImagingFrequency", "0018,0084", "MHz", tolerance=1.0),
    _continuous("MagneticFieldStrength", "0018,0087", "T", tolerance=0.3),
    _continuous("EchoSpacing", None, "ms", tolerance=0.05),
    _continuous("SAR", "0018,1316", "W/kg"),
    _continuous("dBdt", "0018,1318", "T/s"),
    _continuous("PercentPhaseFieldOfView", "0018,0094", "%", tolerance=10.0),
    _continuous("PercentSampling", "0018,0093", "%", tolerance=10.0),
    FieldDef(keyword="PixelSpacing", tag="0028,0030", vr="DS",
             value_type="list_number", unit="mm", continuous=True,
             suggested_tolerance=0.1),

    # ------------------------------------------------------------------
    # Derived diffusion summary fields (rule-facing; see io/gradients.py)
    # ------------------------------------------------------------------
    FieldDef(keyword="NumberOfDiffusionShells", value_type="number"),
    FieldDef(keyword="DiffusionBValues", value_type="list_number", unit="s/mm2"),
    FieldDef(keyword="DirectionsPerShell", value_type="list_number"),
    FieldDef(keyword="NumberOfDiffusionVolumes", value_type="number"),
    FieldDef(keyword="NumberOfB0Volumes", value_type="number"),
]

FIELD_REGISTRY: Dict[str, FieldDef] = {d.keyword: d for d in _DEFS}

# Console/UI display strings never stored in DICOM (e.g. "A >> P").
_DISPLAY_STRING_MARKERS = (">>", "<<", "->", "<-", "→", "←")


def get_field(keyword: str) -> Optional[FieldDef]:
    """Return the FieldDef for a canonical keyword, or None if unregistered."""
    return FIELD_REGISTRY.get(keyword)


def decode(keyword: str, source: str, raw: Any) -> Any:
    """
    Translate a raw vendor value to its canonical form.

    Args:
        keyword: canonical field keyword (e.g. "CoilCombinationMethod").
        source: encoding key (e.g. "siemens.ucCoilCombineMode").
        raw: the raw source value.

    Returns:
        The canonical value; None when the encoding maps the code to "no
        information"; the raw value unchanged when the field or source has no
        registered encoding or the code is unknown (unknown codes are logged).
    """
    fdef = FIELD_REGISTRY.get(keyword)
    if fdef is None or source not in fdef.encodings:
        return raw
    mapping = fdef.encodings[source]
    if raw in mapping:
        return mapping[raw]
    logger.warning("Unknown %s code %r for %s; keeping raw value", source, raw, keyword)
    return raw


def check_value(keyword: str, value: Any) -> List[str]:
    """
    Check one value against the registry. Returns a list of human-readable
    problems (empty when the value is fine or the field is unregistered).
    """
    problems: List[str] = []

    if isinstance(value, str) and any(m in value for m in _DISPLAY_STRING_MARKERS):
        problems.append(
            f"{keyword}={value!r} looks like a console display string, "
            f"which DICOM does not store"
        )

    fdef = FIELD_REGISTRY.get(keyword)
    if fdef is None or fdef.vocabulary is None or value is None:
        return problems

    vocab = fdef.vocabulary
    values = value if isinstance(value, (list, tuple)) else [value]
    lowered = {str(v).strip().lower(): v for v in vocab}
    for v in values:
        if v in vocab:
            continue
        if str(v).strip().lower() in lowered:
            continue  # case-insensitive match is acceptable
        problems.append(
            f"{keyword}={v!r} is not in the canonical vocabulary "
            f"{list(vocab)} (raw vendor code or display value?)"
        )
    return problems


def validate_fields(fields: Mapping[str, Any], context: str = "") -> List[str]:
    """
    Boundary check for importer output: validate every field value against the
    registry, log problems, and return them. Intended to be called by each
    protocol importer on its final field dict.
    """
    problems: List[str] = []
    for keyword, value in fields.items():
        problems.extend(check_value(keyword, value))
    for p in problems:
        logger.warning("%s%s", f"{context}: " if context else "", p)
    return problems


def registry_to_json() -> Dict[str, Dict[str, Any]]:
    """
    Export the registry (minus encodings, which are importer-internal) for
    consumption by the web schema editor.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for keyword, d in sorted(FIELD_REGISTRY.items()):
        entry: Dict[str, Any] = {"valueType": d.value_type}
        if d.tag:
            entry["tag"] = d.tag
        if d.vr:
            entry["vr"] = d.vr
        if d.unit:
            entry["unit"] = d.unit
        if d.vocabulary is not None:
            entry["vocabulary"] = list(d.vocabulary)
        if d.continuous:
            entry["continuous"] = True
        if d.suggested_tolerance is not None:
            entry["suggestedTolerance"] = d.suggested_tolerance
        out[keyword] = entry
    return out


if __name__ == "__main__":
    print(json.dumps(registry_to_json(), indent=2))
