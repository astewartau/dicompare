"""
Check a whole session against a schema in one call.

``map_session`` maps each reference acquisition in the schema to an input
acquisition, ``check_session`` also runs ``check_acquisition_compliance`` on
every mapped pair, and ``save_report`` writes the results as JSON. Together
they are the library form of ``dicompare check``.
"""

import json
import os
from typing import Any, Dict, Optional, Union

import pandas as pd

from .io import load_dicom_session, make_json_serializable, validate_schema
from .session import assign_acquisition_and_run_numbers, map_to_json_reference
from .utils import normalize_numeric_values
from .validation import check_acquisition_compliance

# Columns describing the mapping, placed first in the results DataFrame.
MAPPING_COLUMNS = [
    "reference_acquisition",
    "input_acquisition",
    "mapping_cost",
    "mapping_confidence",
]

# Keys of a record from check_acquisition_compliance.
RESULT_COLUMNS = ["field", "series", "rule_name", "value", "expected", "message", "passed", "status"]

# Status of the row added for a reference acquisition with no input acquisition.
UNMAPPED_STATUS = "unmapped"

# Statuses that count as a failure (passed is False, dicompare check exits 1).
FAILING_STATUSES = ("error", UNMAPPED_STATUS)


def mapping_confidence(cost: float) -> str:
    """
    Describe a mapping cost from ``map_to_json_reference`` as a confidence level.

    Returns "exact" for a cost of 0, "high" below 5, "medium" below 20 and
    "low" otherwise.
    """
    if cost == 0:
        return "exact"
    elif cost < 5:
        return "high"
    elif cost < 20:
        return "medium"
    else:
        return "low"


def _load_schema_dict(schema: Union[str, os.PathLike, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(schema, dict):
        schema_data = schema
    else:
        with open(schema, "r") as f:
            schema_data = json.load(f)
    validate_schema(schema_data)
    return normalize_numeric_values(schema_data)


def _load_session(session: Union[pd.DataFrame, str, os.PathLike]) -> pd.DataFrame:
    if isinstance(session, pd.DataFrame):
        session_df = session
    else:
        session_df = load_dicom_session(session_dir=str(session))
    return assign_acquisition_and_run_numbers(session_df)


def _mapping_rows(session_df, schema_data, mapping):
    """One dict of mapping columns per reference acquisition, in schema order."""
    reference_acquisitions = schema_data["acquisitions"]
    auto_mapping, cost_details = map_to_json_reference(session_df, schema_data, return_costs=True)

    if mapping is None:
        mapping = auto_mapping
    else:
        input_acquisitions = set(cost_details["input_acq_list"])
        for ref_acq, in_acq in mapping.items():
            if ref_acq not in reference_acquisitions:
                raise ValueError(f"Mapping names reference acquisition '{ref_acq}', which is not in the schema")
            if in_acq not in input_acquisitions:
                raise ValueError(f"Mapping names input acquisition '{in_acq}', which is not in the session")

    ref_index = {name: i for i, name in enumerate(cost_details["ref_acq_list"])}
    in_index = {name: j for j, name in enumerate(cost_details["input_acq_list"])}
    cost_matrix = cost_details["cost_matrix"]

    rows = []
    for ref_acq_name in reference_acquisitions:
        if ref_acq_name not in mapping:
            rows.append({
                "reference_acquisition": ref_acq_name,
                "input_acquisition": None,
                "mapping_cost": None,
                "mapping_confidence": None,
            })
            continue
        input_acq_name = mapping[ref_acq_name]
        cost = float(cost_matrix[ref_index[ref_acq_name], in_index[input_acq_name]])
        rows.append({
            "reference_acquisition": ref_acq_name,
            "input_acquisition": input_acq_name,
            "mapping_cost": cost,
            "mapping_confidence": mapping_confidence(cost),
        })
    return rows


def _as_records_frame(rows, columns) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    extra = [c for c in df.columns if c not in columns]
    return df.reindex(columns=columns + extra).astype(object).where(lambda d: d.notna(), None)


def map_session(
    session: Union[pd.DataFrame, str, os.PathLike],
    schema: Union[str, os.PathLike, Dict[str, Any]],
    mapping: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Map the acquisitions of a session to the acquisitions of a schema.

    This is the first step of ``check_session``, for when you want to see or
    adjust the mapping before checking. Takes the same arguments.

    Returns:
        pd.DataFrame: One row per reference acquisition in the schema, with
        ``reference_acquisition``, ``input_acquisition``, ``mapping_cost`` and
        ``mapping_confidence`` ("exact", "high", "medium" or "low"). An
        unmapped reference acquisition has no input acquisition, cost or
        confidence.

    Example:
        >>> map_session("/path/to/dicoms", "schema.json")
    """
    rows = _mapping_rows(_load_session(session), _load_schema_dict(schema), mapping)
    return _as_records_frame(rows, MAPPING_COLUMNS)


def check_session(
    session: Union[pd.DataFrame, str, os.PathLike],
    schema: Union[str, os.PathLike, Dict[str, Any]],
    mapping: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Check every acquisition in a session against a schema.

    Args:
        session: A session DataFrame (from ``load_dicom_session`` or similar)
            or the path to a directory of DICOM files. Acquisition and run
            numbers are assigned if the DataFrame has no ``Acquisition`` column.
        schema: Path to a JSON schema file, or the schema as a dict. It is
            validated against the metaschema either way.
        mapping: Optional ``{reference_acquisition: input_acquisition}``. When
            given it is used as is, and reference acquisitions left out of it
            are reported as unmapped. When omitted, acquisitions are mapped
            automatically with ``map_to_json_reference``.

    Returns:
        pd.DataFrame: One row per check, with the columns of
        ``check_acquisition_compliance`` records (``field``, ``series``,
        ``rule_name``, ``value``, ``expected``, ``message``, ``passed``,
        ``status``) after the mapping columns ``reference_acquisition``,
        ``input_acquisition``, ``mapping_cost`` and ``mapping_confidence``
        ("exact", "high", "medium" or "low"). Each unmapped reference
        acquisition gets one row with ``status`` "unmapped" and no input
        acquisition or cost. ``passed`` is False for "error" and "unmapped"
        rows and True otherwise, matching the exit status of ``dicompare check``.

    Raises:
        ValueError: If ``mapping`` names an acquisition that is not in the
            schema or the session.

    Example:
        >>> results = check_session("/path/to/dicoms", "schema.json")
        >>> failed = results[~results["passed"]]
    """
    schema_data = _load_schema_dict(schema)
    session_df = _load_session(session)

    rows = []
    for mapping_info in _mapping_rows(session_df, schema_data, mapping):
        ref_acq_name = mapping_info["reference_acquisition"]
        input_acq_name = mapping_info["input_acquisition"]
        if input_acq_name is None:
            rows.append({
                **mapping_info,
                "message": f"No input acquisition mapped to reference acquisition '{ref_acq_name}'",
                "status": UNMAPPED_STATUS,
            })
            continue

        schema_acq = schema_data["acquisitions"][ref_acq_name]
        results = check_acquisition_compliance(
            session_df,
            schema_acq,
            acquisition_name=input_acq_name,
            validation_rules=schema_acq.get("rules"),
        )
        rows.extend({**mapping_info, **result} for result in results)

    df = _as_records_frame(rows, MAPPING_COLUMNS + RESULT_COLUMNS)
    # A real bool column, so that results[~results["passed"]] works
    df["passed"] = ~df["status"].isin(FAILING_STATUSES).astype(bool)
    return df


def save_report(results: pd.DataFrame, path: Union[str, os.PathLike]) -> None:
    """
    Save ``check_session`` results as a JSON list of records.

    This is the format ``dicompare check`` writes with ``--report``.
    """
    with open(path, "w") as f:
        json.dump(make_json_serializable(results.to_dict(orient="records")), f, indent=4)
