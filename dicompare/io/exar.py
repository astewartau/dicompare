"""
Siemens .exar1 exam archive parser.

.exar1 files are SQLite archives holding (optionally deflate-compressed)
XProtocol payloads; each embedded protocol is extracted to ASCCONV text and
then parsed through the ``pro`` machinery. Split out of ``pro.py``.
"""

import os
import glob
import json
import sqlite3
import zlib
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union, List, Callable

import pandas as pd
from twixtools.twixprot import parse_buffer

from ..data_utils import make_dataframe_hashable
# Late-bound module reference (not from-imports): callers and tests may
# monkeypatch attributes on dicompare.io.pro and expect this module to see it.
from . import pro as _pro
from .pro_derived import calculate_other_dicom_fields

def _decompress_raw_deflate(data: bytes) -> Optional[bytes]:
    """Decompress raw deflate data (no zlib header) used in .exar1 files."""
    try:
        return zlib.decompress(data, -zlib.MAX_WBITS)
    except zlib.error:
        return None


def _extract_protocol_text_from_xprotocol(json_text: str) -> Optional[str]:
    """
    Extract the protocol text from EdfProtocolContent JSON wrapper.

    The .exar1 format wraps protocol data in JSON like:
        EDF V1: ContentType=syngo.MR.ExamDataFoundation.Data.EdfProtocolContent;
        {"Data": "<XProtocol>...protocol text here..."}

    Args:
        json_text: The decompressed content from .exar1

    Returns:
        The protocol text in .pro-compatible format, or None if extraction fails
    """
    try:
        # Find the JSON part after the header
        json_start = json_text.find('{')
        if json_start < 0:
            return None

        json_str = json_text[json_start:]
        data = json.loads(json_str)
        protocol_data = data.get('Data', '')

        if protocol_data:
            return protocol_data
    except json.JSONDecodeError:
        pass

    # Fallback: return the whole text if it looks like protocol data
    if 'tProtocolName' in json_text:
        return json_text

    return None


def _describe_exar_contents(exar_path: str) -> Tuple[str, bool]:
    """
    Summarize what an EXAR archive actually contains, for error reporting.

    Args:
        exar_path: Path to the .exar1 file

    Returns:
        Tuple of (human-readable summary, whether any EdfProtocol entries exist)
    """
    try:
        conn = sqlite3.connect(exar_path)
        cursor = conn.cursor()

        cursor.execute("SELECT InstanceType, COUNT(*) FROM Instance GROUP BY InstanceType")
        type_counts = cursor.fetchall()

        # Folder/item names are stored as EdfString content: {"Texts": {"en": ...}}
        names = []
        cursor.execute("""
            SELECT c.Data FROM Instance i
            JOIN Content c ON i.ContentHash = c.Hash
            WHERE i.InstanceType = 'EdfString'
        """)
        for (data,) in cursor.fetchall():
            decompressed = _decompress_raw_deflate(data)
            if not decompressed:
                continue
            text = decompressed.decode('utf-8', errors='replace')
            json_start = text.find('{')
            if json_start < 0:
                continue
            try:
                name = json.loads(text[json_start:]).get('Texts', {}).get('en')
            except json.JSONDecodeError:
                continue
            if name:
                names.append(name)

        # Scanner software version from the branch baseline,
        # e.g. "MAJORVERSION:VA60A, PROTOCOL:66010002, ..."
        version = None
        cursor.execute("SELECT Baseline FROM Branch WHERE Baseline LIKE '%MAJORVERSION%'")
        row = cursor.fetchone()
        if row:
            for part in row[0].split(','):
                key, _, value = part.strip().partition(':')
                if key == 'MAJORVERSION':
                    version = value
                    break

        conn.close()
    except sqlite3.Error:
        return "", False

    has_protocols = any(t == 'EdfProtocol' for t, _ in type_counts)

    parts = []
    if version:
        parts.append(f"software version {version}")
    if type_counts:
        parts.append("contains only: " + ", ".join(f"{n}x {t}" for t, n in type_counts))
    else:
        parts.append("contains no entries at all")
    if names:
        parts.append("folder tree: " + " / ".join(names))

    return "; ".join(parts), has_protocols


def _extract_protocols_from_exar(exar_path: str) -> List[str]:
    """
    Extract protocol text content from a .exar1 file.

    Args:
        exar_path: Path to the .exar1 file

    Returns:
        List of protocol text strings (in .pro-compatible format)

    Raises:
        FileNotFoundError: If the file doesn't exist
        Exception: If the file cannot be read as SQLite
    """
    exar_file = Path(exar_path)
    if not exar_file.exists():
        raise FileNotFoundError(f"EXAR file not found: {exar_path}")

    protocol_texts = []

    try:
        conn = sqlite3.connect(exar_path)
        cursor = conn.cursor()

        # Get EdfProtocol entries which contain the actual protocol data
        cursor.execute("""
            SELECT i.Id, c.Data
            FROM Instance i
            LEFT JOIN Content c ON i.ContentHash = c.Hash
            WHERE i.InstanceType = 'EdfProtocol'
        """)

        for row in cursor.fetchall():
            data = row[1]
            if not data:
                continue

            # Decompress using raw deflate
            decompressed = _decompress_raw_deflate(data)
            if not decompressed:
                continue

            text = decompressed.decode('utf-8', errors='replace')

            # Extract protocol text from JSON wrapper
            protocol_text = _extract_protocol_text_from_xprotocol(text)
            if protocol_text:
                protocol_texts.append(protocol_text)

        conn.close()

    except sqlite3.Error as e:
        raise Exception(f"Failed to read EXAR file as SQLite database: {e}")

    return protocol_texts


def load_exar_file(exar_file_path: str) -> List[Dict[str, Any]]:
    """
    Load and parse a Siemens .exar1 protocol file into DICOM-compatible format.

    The .exar1 format is a SQLite database containing multiple protocols.
    This function extracts all protocols and parses them using the same
    infrastructure as .pro files.

    Args:
        exar_file_path: Path to the .exar1 protocol file

    Returns:
        List of dictionaries with DICOM-compatible field names and values,
        one per protocol in the archive

    Raises:
        FileNotFoundError: If the specified file path does not exist
        Exception: If the file cannot be parsed
    """
    exar_path = Path(exar_file_path)
    if not exar_path.exists():
        raise FileNotFoundError(f"Protocol file not found: {exar_file_path}")

    # Extract protocol texts from the .exar1 file
    protocol_texts = _extract_protocols_from_exar(exar_file_path)

    if not protocol_texts:
        details, has_protocol_entries = _describe_exar_contents(exar_file_path)
        if has_protocol_entries:
            message = (
                f"No protocols could be read from EXAR file '{exar_path.name}': the archive "
                f"contains protocol entries, but none of them could be decoded"
            )
        else:
            message = (
                f"No protocols found in EXAR file '{exar_path.name}': the archive was read "
                f"successfully, but it contains no protocol (EdfProtocol) entries"
            )
        if details:
            message += f" ({details})"
        if not has_protocol_entries:
            message += (
                ". This usually means the export itself was empty — when exporting from "
                "Dot Cockpit, make sure the programs/protocols themselves are selected, "
                "not just a folder."
            )
        raise Exception(message)

    results = []

    for protocol_text in protocol_texts:
        try:
            # Parse using the same twixtools parser as .pro files
            parsed_data = parse_buffer(protocol_text)

            # Convert to DICOM-compatible format
            dicom_fields = _pro.apply_pro_to_dicom_mapping(parsed_data)
            calculate_other_dicom_fields(dicom_fields, parsed_data)

            # Add source information
            dicom_fields["EXAR_Path"] = str(exar_file_path)
            dicom_fields["EXAR_FileName"] = exar_path.name

            results.append(dicom_fields)

        except Exception as e:
            # Log warning but continue with other protocols
            protocol_name = "Unknown"
            if 'tProtocolName' in protocol_text:
                import re
                match = re.search(r'tProtocolName\s*=\s*"([^"]+)"', protocol_text)
                if match:
                    protocol_name = match.group(1)
            print(f"Warning: Failed to parse protocol '{protocol_name}': {e}")
            continue

    return results


def load_exar_file_schema_format(exar_file_path: str) -> List[Dict[str, Any]]:
    """
    Load a Siemens .exar1 file into schema-compatible format, one entry per protocol.

    Unlike load_exar_file (which returns a flat dict per protocol), this expands
    series-determining parameters (echo times, magnitude/phase image types,
    inversion times) into an explicit series list, exactly like
    load_pro_file_schema_format does for .pro files. This is what validation and
    the web UI need so that, e.g., a multi-echo acquisition is seen as multiple
    echoes rather than a single row holding a tuple of echo times.

    Args:
        exar_file_path: Path to the .exar1 protocol file

    Returns:
        List of schema-format dictionaries (acquisition_info, fields, series),
        one per protocol in the archive.

    Raises:
        FileNotFoundError: If the specified file path does not exist
        Exception: If the file cannot be parsed
    """
    exar_path = Path(exar_file_path)
    if not exar_path.exists():
        raise FileNotFoundError(f"Protocol file not found: {exar_file_path}")

    protocol_texts = _extract_protocols_from_exar(exar_file_path)

    if not protocol_texts:
        # Reuse the same rich diagnostics as load_exar_file
        load_exar_file(exar_file_path)
        return []

    results = []

    for protocol_text in protocol_texts:
        try:
            parsed_data = parse_buffer(protocol_text)

            flat_dicom_data = _pro.apply_pro_to_dicom_mapping(parsed_data)
            calculate_other_dicom_fields(flat_dicom_data, parsed_data)

            schema_result = _pro._convert_flat_to_schema_format(
                flat_dicom_data, parsed_data, exar_file_path
            )

            # Tag as coming from an .exar1 archive rather than a bare .pro file
            schema_result["acquisition_info"]["source_type"] = "exar1"
            schema_result["acquisition_info"]["exar_path"] = str(exar_file_path)
            schema_result["acquisition_info"]["exar_filename"] = exar_path.name

            results.append(schema_result)

        except Exception as e:
            protocol_name = "Unknown"
            if 'tProtocolName' in protocol_text:
                import re
                match = re.search(r'tProtocolName\s*=\s*"([^"]+)"', protocol_text)
                if match:
                    protocol_name = match.group(1)
            print(f"Warning: Failed to parse protocol '{protocol_name}': {e}")
            continue

    return results


def _load_one_exar_protocol(exar_path: str, protocol_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Helper function for processing a single protocol from an .exar1 file.

    Args:
        exar_path: Path to the .exar1 file
        protocol_data: Parsed protocol data dictionary

    Returns:
        Dictionary with DICOM-compatible field names and values
    """
    # Use ProtocolName as the equivalent of "Acquisition"
    protocol_name = protocol_data.get("ProtocolName", "Unknown")
    protocol_data["Acquisition"] = protocol_name

    return protocol_data


def load_exar_session(
    session_dir: Optional[str] = None,
    exar_files: Optional[List[str]] = None,
    pattern: str = "*.exar1",
    show_progress: bool = False,
    progress_function: Optional[Callable[[int], None]] = None,
) -> pd.DataFrame:
    """
    Load and process all .exar1 files in a session directory or from a list of file paths.

    Args:
        session_dir: Path to a directory containing .exar1 files
        exar_files: List of specific .exar1 file paths to load
        pattern: Glob pattern for finding .exar1 files (default: "*.exar1")
        show_progress: Whether to show a progress bar (ignored for simple loading)
        progress_function: Optional callback function for progress updates

    Returns:
        pd.DataFrame: A DataFrame containing metadata for all protocols in the .exar1 files

    Raises:
        ValueError: If neither session_dir nor exar_files is provided, or if no files are found
    """
    # Determine data source
    if exar_files is not None:
        exar_items = exar_files
    elif session_dir is not None:
        exar_items = glob.glob(os.path.join(session_dir, "**", pattern), recursive=True)
    else:
        raise ValueError("Either session_dir or exar_files must be provided.")

    if not exar_items:
        raise ValueError(f"No .exar1 files found in the specified location.")

    # Process .exar1 files sequentially
    session_data = []
    total_files = len(exar_items)

    for idx, exar_path in enumerate(exar_items):
        try:
            # Load all protocols from this .exar1 file
            protocols = load_exar_file(exar_path)

            for protocol_data in protocols:
                processed = _load_one_exar_protocol(exar_path, protocol_data)
                session_data.append(processed)

        except Exception as e:
            print(f"Warning: Failed to load {exar_path}: {e}")
            continue

        # Update progress if callback provided
        if progress_function:
            progress = int((idx + 1) / total_files * 100)
            progress_function(progress)

    # Create DataFrame
    if not session_data:
        raise ValueError("No valid protocols could be loaded from .exar1 files.")

    session_df = pd.DataFrame(session_data)

    # Apply standard dataframe processing
    session_df = make_dataframe_hashable(session_df)

    return session_df


