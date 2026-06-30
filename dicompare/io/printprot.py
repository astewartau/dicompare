"""
Siemens "MR print protocol" Parser with DICOM Mapping

Parses the human-readable protocol export produced by the Siemens scanner
console ("MR print protocol") and extracts protocol information in both raw
and DICOM-compatible (schema) formats.

Two serialisations of the same content are supported and auto-detected:

- **XML** (``<PrintOut><PrintProtocol><Protocol>...``): each ``<Protocol>``
  holds ``<Card name="...">`` sections, each a list of
  ``<ProtParameter><Label>/<ValueAndUnit>`` pairs.
- **TXT**: the same content rendered as a column layout. Protocols are
  delimited by a ``\\\\USER\\...\\<name>`` path line; card names sit at column
  0; parameters are ``<indent>Label<2+ spaces>Value``.

This is distinct from the Siemens ``.pro`` parser (``pro.py``), which reads the
raw binary MrPhoenixProtocol. The print protocol is a rendered text/XML dump,
typically the only protocol artefact available when raw files and DICOM/JSON
sidecars were not retained.

This module follows the same pattern as the Philips ExamCard parser
(``examcard.py``): it produces a list of schema-format dictionaries, one per
protocol, each with ``acquisition_info``, ``fields`` and ``series``.
"""

import re
import itertools
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


# ============================================================================
# Label -> DICOM field mapping
# ============================================================================

# Siemens console label -> standard DICOM keyword. Labels are matched after
# stripping surrounding whitespace. Values are run through _split_value_unit so
# that e.g. "3900 ms" becomes the number 3900.0.
PRINTPROT_TO_DICOM_MAPPING: Dict[str, str] = {
    "TR": "RepetitionTime",
    "TE": "EchoTime",
    "TI": "InversionTime",
    "Flip angle": "FlipAngle",
    "Averages": "NumberOfAverages",
    "Slice thickness": "SliceThickness",
    "Base resolution": "Rows",  # also used to derive Columns / PixelSpacing
    "Bandwidth": "PixelBandwidth",
    "EPI factor": "EchoTrainLength",
    "Phase enc. dir.": "InPlanePhaseEncodingDirection",
    "Slices": "NumberOfSlices",
    "Coil elements": "ReceiveCoilName",
}

# Siemens console label -> dicompare derived field (no standard DICOM tag).
# These surface in the UI as derived/custom fields and are rule-able. The
# diffusion timing/scheme fields here are exactly what axon-diameter and
# fast-DKI modelling depend on, and have no DICOM equivalent.
PRINTPROT_TO_DERIVED_MAPPING: Dict[str, str] = {
    "Small delta": "SmallDelta",
    "Big Delta": "BigDelta",
    "Diffusion mode": "DiffusionMode",
    "Directions": "DiffusionDirectionSet",
    "Diff. weightings": "DiffusionWeightings",
    "Max Diff Grad": "MaxDiffGradient",
    "Gradient mode": "GradientMode",
    "Echo spacing": "EchoSpacing",
    "PAT mode": "ParallelAcquisitionTechnique",
    "Accel. factor PE": "ParallelReductionFactorInPlane",
    "SMS Factor": "MultibandFactor",
}

# Order in which well-known DICOM fields appear in the output (others follow
# alphabetically, derived/custom fields last).
DICOM_FIELD_ORDER = [
    "Manufacturer",
    "ManufacturerModelName",
    "SoftwareVersions",
    "ProtocolName",
    "SeriesDescription",
    "ScanningSequence",
    "MRAcquisitionType",
    "RepetitionTime",
    "EchoTime",
    "InversionTime",
    "FlipAngle",
    "NumberOfAverages",
    "SliceThickness",
    "Rows",
    "Columns",
    "PixelSpacing",
    "PixelBandwidth",
    "EchoTrainLength",
    "NumberOfSlices",
    "InPlanePhaseEncodingDirection",
    "ReceiveCoilName",
    "DiffusionBValue",
]

# Match "b-value" or "b-value 1", "b-value 2", ... (the per-weighting rows).
_BVALUE_RE = re.compile(r"^b-value(?:\s+(\d+))?$", re.IGNORECASE)


# ============================================================================
# Value parsing
# ============================================================================

def _split_value_unit(raw: str) -> Tuple[Any, Optional[str]]:
    """
    Split a Siemens "ValueAndUnit" string into a typed value and unit.

    Examples:
        "3900 ms"   -> (3900.0, "ms")
        "100.0 %"   -> (100.0, "%")
        "2272 Hz/Px"-> (2272.0, "Hz/Px")
        "20 deg"    -> (20.0, "deg")
        "256"       -> (256.0, None)        # numeric, no unit
        "On"        -> ("On", None)
        "A >> P"    -> ("A >> P", None)     # compound descriptive string
        "L2.4 P2.0 H0.0 mm" -> ("L2.4 P2.0 H0.0 mm", None)  # not a simple scalar

    Returns:
        (value, unit). value is a float when the string is a single numeric
        token (optionally followed by a unit), otherwise the cleaned string.
    """
    s = (raw or "").strip()
    if s == "":
        return "", None

    # A simple scalar: an optional sign, digits/decimal, optionally followed by
    # a single unit token (no internal spaces in the numeric part).
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*(\S.*)?$", s)
    if m:
        number_part = m.group(1)
        unit_part = (m.group(2) or "").strip() or None
        # Reject cases where the "unit" is actually more numbers/coords
        # (e.g. "0.5 0.5 7.0" or "2 TRs" we keep unit; "1 / 2" we reject).
        if unit_part is not None and re.search(r"\d", unit_part):
            # Contains further digits -> treat whole thing as a string
            return s, None
        try:
            return float(number_part), unit_part
        except ValueError:
            return s, None

    return s, None


def _coerce_number(value: Any) -> Any:
    """Return an int when a float is integral, else the value unchanged."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _parse_header_title(title: str) -> Dict[str, str]:
    """
    Extract manufacturer/model/software from the protocol header title.

    Example: "SIEMENS MAGNETOM ConnectomA syngo MR D11"
        -> Manufacturer="SIEMENS",
           ManufacturerModelName="MAGNETOM ConnectomA",
           SoftwareVersions="syngo MR D11"
    """
    fields: Dict[str, str] = {}
    if not title:
        return fields
    title = title.strip()
    fields["Manufacturer"] = "SIEMENS"

    m = re.search(r"MAGNETOM\s+(\S+)", title)
    if m:
        fields["ManufacturerModelName"] = f"MAGNETOM {m.group(1)}"

    m = re.search(r"(syngo\s+MR\s+\S+)", title)
    if m:
        fields["SoftwareVersions"] = m.group(1)

    return fields


# ============================================================================
# Raw parsing: XML
# ============================================================================

def _parse_printprot_xml(content: str) -> List[Dict[str, Any]]:
    """
    Parse the XML serialisation into a list of raw protocol dicts.

    Returns one dict per ``<Protocol>``:
        {
            "name": "AX_delta30",
            "title": "SIEMENS MAGNETOM ConnectomA syngo MR D11",
            "params": OrderedDict[(card_name, label) -> value_string],
        }
    """
    root = ET.fromstring(content)
    protocols: List[Dict[str, Any]] = []

    for prot in root.iter("Protocol"):
        title_el = prot.find("HeaderTitle")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""

        path_el = prot.find(".//HeaderProtPath")
        if path_el is not None and path_el.text:
            name = path_el.text.replace("/", "\\").split("\\")[-1].strip()
        else:
            name = title or "Protocol"

        params: Dict[Tuple[str, str], str] = {}
        for card in prot.findall("Card"):
            card_name = card.get("name") or ""
            for pp in card.findall("ProtParameter"):
                label_el = pp.find("Label")
                value_el = pp.find("ValueAndUnit")
                label = label_el.text.strip() if label_el is not None and label_el.text else ""
                value = value_el.text.strip() if value_el is not None and value_el.text else ""
                if label:
                    params[(card_name, label)] = value

        protocols.append({"name": name, "title": title, "params": params})

    return protocols


# ============================================================================
# Raw parsing: TXT
# ============================================================================

# A protocol path line, e.g. "\\USER\saper7dev\axcal_repro\25062019-2\localizer"
_TXT_PATH_RE = re.compile(r"^\s*\\\\USER\\.*\\([^\\]+?)\s*$")
# A divider line of dashes
_TXT_DIVIDER_RE = re.compile(r"^\s*-{5,}\s*$")
# A card heading: text starting at column 0 (no leading whitespace)
_TXT_CARD_RE = re.compile(r"^(\S.*?)\s*$")
# A parameter line: leading whitespace, label, 2+ spaces, value
_TXT_PARAM_RE = re.compile(r"^\s+(\S.*?)\s{2,}(\S.*?)\s*$")


def _parse_printprot_txt(content: str) -> List[Dict[str, Any]]:
    """
    Parse the TXT serialisation into the same raw protocol dict list as
    :func:`_parse_printprot_xml`.
    """
    # Normalise CR/CRLF/CRCRLF endings to plain newlines.
    text = content.replace("\r", "\n")
    lines = text.split("\n")

    protocols: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_card = ""
    pending_title = ""  # scanner title line seen just before a path line

    for line in lines:
        if line.strip() == "":
            continue

        stripped = line.strip()

        if _TXT_DIVIDER_RE.match(line):
            continue

        # Scanner title line (may be indented). Always precedes a path line, so
        # remember it for the next protocol block.
        if "MAGNETOM" in stripped or stripped.startswith("SIEMENS"):
            pending_title = stripped
            continue

        # Protocol path line: starts a new protocol block.
        path_match = _TXT_PATH_RE.match(line)
        if path_match:
            current = {
                "name": path_match.group(1).strip(),
                "title": pending_title,
                "params": {},
            }
            protocols.append(current)
            current_card = ""
            continue

        # Card heading: a column-0 (non-indented) line within a protocol block.
        if current is not None and not line[:1].isspace():
            current_card = stripped
            continue

        # Parameter line: indented label + 2-space gap + value, only once we are
        # inside a card (this skips the indented TA:/PAT: property line, which
        # appears before any card heading).
        param_match = _TXT_PARAM_RE.match(line)
        if param_match and current is not None and current_card:
            label = param_match.group(1).strip()
            value = param_match.group(2).strip()
            if label:
                current["params"][(current_card, label)] = value

    return protocols


# ============================================================================
# Mapping raw params -> DICOM fields
# ============================================================================

def apply_printprot_to_dicom_mapping(protocol: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert one raw protocol dict to DICOM-compatible field names.

    Args:
        protocol: dict with "name", "title", "params" (from a raw parser).

    Returns:
        Ordered dict of DICOM/derived field names -> typed values.
    """
    params: Dict[Tuple[str, str], str] = protocol.get("params", {})
    dicom_fields: Dict[str, Any] = {}

    # Header-derived identity fields.
    dicom_fields.update(_parse_header_title(protocol.get("title", "")))
    dicom_fields["ProtocolName"] = protocol.get("name", "Protocol")

    # Flatten params by label (first card wins on duplicate labels). Keep track
    # of b-value rows separately for series handling.
    bvalues: List[float] = []
    base_resolution: Optional[float] = None
    fov_read: Optional[float] = None
    fov_phase: Optional[float] = None
    seen_labels = set()

    for (card_name, label), raw_value in params.items():
        value, _unit = _split_value_unit(raw_value)
        if value == "" or value is None:
            continue

        # Collect b-values (numbered or not) for series handling.
        bm = _BVALUE_RE.match(label)
        if bm:
            if isinstance(value, (int, float)):
                bvalues.append(float(value))
            continue

        # Remember geometry sources for derived fields.
        if label == "Base resolution" and isinstance(value, (int, float)):
            base_resolution = float(value)
        elif label == "FoV read" and isinstance(value, (int, float)):
            fov_read = float(value)
        elif label == "FoV phase" and isinstance(value, (int, float)):
            fov_phase = float(value)

        # Avoid clobbering an already-set label from an earlier card.
        if label in seen_labels:
            continue

        if label in PRINTPROT_TO_DICOM_MAPPING:
            field = PRINTPROT_TO_DICOM_MAPPING[label]
            dicom_fields[field] = _coerce_number(value)
            seen_labels.add(label)
        elif label in PRINTPROT_TO_DERIVED_MAPPING:
            field = PRINTPROT_TO_DERIVED_MAPPING[label]
            dicom_fields[field] = _coerce_number(value)
            seen_labels.add(label)
        # Unmapped labels are intentionally dropped to avoid noise.

    # Base resolution maps to both Rows and Columns (square base matrix).
    if base_resolution is not None:
        dicom_fields["Rows"] = _coerce_number(base_resolution)
        dicom_fields["Columns"] = _coerce_number(base_resolution)

    # PixelSpacing from FoV read / base resolution (in-plane, mm).
    if fov_read is not None and base_resolution and base_resolution > 0:
        spacing = round(fov_read / base_resolution, 4)
        dicom_fields["PixelSpacing"] = [spacing, spacing]

    # PercentPhaseFieldOfView from FoV phase (already a percentage in the print
    # protocol, e.g. "100.0 %").
    if fov_phase is not None:
        dicom_fields["PercentPhaseFieldOfView"] = _coerce_number(fov_phase)

    # b-values: a single value goes to acquisition-level DiffusionBValue;
    # multiple distinct values become series (handled downstream).
    unique_bvalues = sorted(set(bvalues))
    if len(unique_bvalues) == 1:
        dicom_fields["DiffusionBValue"] = _coerce_number(unique_bvalues[0])
    elif len(unique_bvalues) > 1:
        # Stored temporarily; _extract_series_parameters reads it out.
        dicom_fields["DiffusionBValue"] = [_coerce_number(b) for b in unique_bvalues]

    return _sort_output_fields(dicom_fields)


def _sort_output_fields(dicom_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Order known DICOM fields first, other DICOM fields alphabetically, then
    derived/custom fields alphabetically last."""
    order_index = {f: i for i, f in enumerate(DICOM_FIELD_ORDER)}
    derived_names = set(PRINTPROT_TO_DERIVED_MAPPING.values()) | {
        "PercentPhaseFieldOfView",
    }

    ordered, other, derived = [], [], []
    for key in dicom_fields:
        if key in derived_names:
            derived.append(key)
        elif key in order_index:
            ordered.append(key)
        else:
            other.append(key)

    ordered.sort(key=lambda k: order_index[k])
    other.sort()
    derived.sort()

    return {k: dicom_fields[k] for k in ordered + other + derived}


# ============================================================================
# Schema format conversion
# ============================================================================

def _extract_series_parameters(dicom_fields: Dict[str, Any]) -> Dict[str, List]:
    """Extract parameters that create series variations (multiple b-values)."""
    series_params: Dict[str, List] = {}
    bval = dicom_fields.get("DiffusionBValue")
    if isinstance(bval, list) and len(bval) > 1:
        series_params["DiffusionBValue"] = bval
    return series_params


def _generate_series_combinations(series_params: Dict[str, List]) -> List[Dict[str, Any]]:
    """Generate series combinations from varying parameters (cartesian product)."""
    if not series_params:
        return []

    param_names = list(series_params.keys())
    value_lists = [series_params[name] for name in param_names]

    series_list = []
    for i, combo in enumerate(itertools.product(*value_lists)):
        series_fields = [
            {"field": param_names[j], "value": combo[j]} for j in range(len(param_names))
        ]
        series_list.append({"name": f"Series {i + 1:02d}", "fields": series_fields})

    return series_list


def _convert_to_schema_format(
    dicom_fields: Dict[str, Any], protocol_name: str, source_path: str
) -> Dict[str, Any]:
    """Convert DICOM fields to the dicompare schema-compatible format."""
    series_params = _extract_series_parameters(dicom_fields)
    series_list = _generate_series_combinations(series_params)
    series_varying = set(series_params.keys())

    acquisition_fields = []
    for field_name, value in dicom_fields.items():
        if field_name in series_varying:
            continue
        if value is None or value == "":
            continue
        acquisition_fields.append({"field": field_name, "value": value})

    return {
        "acquisition_info": {
            "protocol_name": protocol_name,
            "source_type": "printprot",
            "printprot_path": str(source_path),
            "printprot_filename": Path(source_path).name,
        },
        "fields": acquisition_fields,
        "series": series_list,
    }


# ============================================================================
# Format detection + public API
# ============================================================================

def _detect_format(content: str) -> str:
    """Return 'xml' or 'txt' for the given protocol content."""
    head = content.lstrip()[:512]
    if head.startswith("<?xml") or "<PrintOut" in head or "<PrintProtocol" in head:
        return "xml"
    return "txt"


def _read_content(path: Union[str, Path]) -> str:
    """Read a print-protocol file as text (latin-1 tolerant of Siemens bytes)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Print protocol file not found: {path}")
    data = p.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def load_printprot_file(printprot_path: Union[str, Path]) -> List[Dict[str, Any]]:
    """
    Load a Siemens print-protocol file (XML or TXT) and return raw DICOM-mapped
    fields, one dict per protocol.

    Returns:
        List of dicts: ``{"protocol_name": str, "fields": {field: value}}``.
    """
    content = _read_content(printprot_path)
    fmt = _detect_format(content)
    protocols = _parse_printprot_xml(content) if fmt == "xml" else _parse_printprot_txt(content)

    results = []
    for proto in protocols:
        dicom_fields = apply_printprot_to_dicom_mapping(proto)
        results.append({"protocol_name": proto["name"], "fields": dicom_fields})
    return results


def load_printprot_file_schema_format(
    printprot_path: Union[str, Path],
) -> List[Dict[str, Any]]:
    """
    Load a Siemens print-protocol file (XML or TXT) into schema-compatible
    format, one acquisition per protocol.

    Returns:
        List of dicts in schema format:
        ``[{"acquisition_info": {...}, "fields": [...], "series": [...]}, ...]``
    """
    content = _read_content(printprot_path)
    fmt = _detect_format(content)
    protocols = _parse_printprot_xml(content) if fmt == "xml" else _parse_printprot_txt(content)

    results = []
    for proto in protocols:
        dicom_fields = apply_printprot_to_dicom_mapping(proto)
        schema = _convert_to_schema_format(dicom_fields, proto["name"], str(printprot_path))
        results.append(schema)
    return results
