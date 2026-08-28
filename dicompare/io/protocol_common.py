"""
Shared post-processing for protocol importers.

Every protocol importer (Siemens print protocol, Philips ExamCard, GE
LxProtocol, Siemens .pro) follows the same shape: parse the vendor source,
map labels to canonical field names (per-importer, inherently vendor
knowledge), then sort the output, expand series-varying parameters, and
convert to the dicompare schema format. The post-processing steps were
previously copy-pasted per importer, which is exactly where translation bugs
accumulated; they live here once instead.

The canonical *value* handling (vendor code translation, vocabulary
validation) lives in :mod:`dicompare.fields`; importers should route values
through ``fields.decode`` and funnel final output through
``fields.validate_fields``.
"""

import itertools
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

__all__ = [
    "sort_output_fields",
    "generate_series_combinations",
    "convert_to_schema_format",
]


def sort_output_fields(
    dicom_fields: Dict[str, Any],
    field_order: Sequence[str],
    is_last_group: Optional[Callable[[str], bool]] = None,
) -> Dict[str, Any]:
    """
    Order known DICOM fields first (by ``field_order``), other fields
    alphabetically, then fields matching ``is_last_group`` (vendor-prefixed or
    derived fields) alphabetically at the end.
    """
    order_index = {f: i for i, f in enumerate(field_order)}
    ordered, other, last = [], [], []

    for key in dicom_fields:
        if is_last_group is not None and is_last_group(key):
            last.append(key)
        elif key in order_index:
            ordered.append(key)
        else:
            other.append(key)

    ordered.sort(key=lambda k: order_index[k])
    other.sort()
    last.sort()
    return {k: dicom_fields[k] for k in ordered + other + last}


def generate_series_combinations(
    series_params: Dict[str, List],
    priority: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """
    Expand series-varying parameters into a series list (cartesian product).

    Args:
        series_params: parameter name -> list of values that vary per series.
        priority: parameter names to expand first (outermost), in order;
            remaining parameters follow in dict order.

    Returns:
        [{"name": "Series 01", "fields": [{"field": ..., "value": ...}]}, ...]
    """
    if not series_params:
        return []

    param_names = [p for p in priority if p in series_params]
    param_names += [p for p in series_params if p not in param_names]
    value_lists = [series_params[name] for name in param_names]

    series_list = []
    for i, combo in enumerate(itertools.product(*value_lists), 1):
        series_list.append({
            "name": f"Series {i:02d}",
            "fields": [
                {"field": param_names[j], "value": combo[j]}
                for j in range(len(param_names))
            ],
        })
    return series_list


def convert_to_schema_format(
    dicom_fields: Dict[str, Any],
    protocol_name: str,
    source_type: str,
    source_path: str,
    series_params: Optional[Dict[str, List]] = None,
    skip_fields: Iterable[str] = (),
    series_priority: Sequence[str] = (),
) -> Dict[str, Any]:
    """
    Convert a flat DICOM-field dict to the dicompare schema acquisition format.

    Series-varying parameters are expanded into the ``series`` list and
    excluded from acquisition-level fields, along with ``skip_fields``
    (importer metadata) and empty values.

    The ``acquisition_info`` block records provenance as
    ``{source_type}_path`` / ``{source_type}_filename``, matching the
    historical per-importer key naming.
    """
    series_params = series_params or {}
    series_list = generate_series_combinations(series_params, series_priority)
    excluded = set(series_params) | set(skip_fields)

    acquisition_fields = []
    for field_name, value in dicom_fields.items():
        if field_name in excluded:
            continue
        if value is None or value == "":
            continue
        acquisition_fields.append({"field": field_name, "value": value})

    return {
        "acquisition_info": {
            "protocol_name": protocol_name,
            "source_type": source_type,
            f"{source_type}_path": str(source_path),
            f"{source_type}_filename": Path(source_path).name,
        },
        "fields": acquisition_fields,
        "series": series_list,
    }
