"""
Vendor protocol and diffusion gradient loading for the web UI.

Split out of web_utils.py; the public entry points remain exported from
dicompare.interface.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union, Tuple
import json
import logging

from ..io import make_json_serializable

logger = logging.getLogger(__name__)

def load_protocol_for_ui(
    file_content: bytes,
    file_name: str,
    file_type: str
) -> List[Dict[str, Any]]:
    """
    Load a protocol file and return UI-ready acquisition(s).

    Args:
        file_content: Binary content of the protocol file
        file_name: Name of the file
        file_type: Type of protocol file ('pro', 'exar1', 'examcard', 'lxprotocol', 'printprot')

    Returns:
        List of UI-ready acquisition dictionaries with:
        - id, protocolName, seriesDescription
        - acquisitionFields (with tag, name, keyword, value, vr, dataType, fieldType)
        - seriesFields
        - series (with fields array)
        - metadata
    """
    from ..io import (
        load_pro_file_schema_format, load_exar_file_schema_format,
        load_examcard_file_schema_format, load_lxprotocol_file_schema_format,
        load_printprot_file_schema_format
    )
    from ..schema import get_tag_info
    from pydicom.datadict import dictionary_VR
    import tempfile
    import os
    import time

    # Helper to get VR
    def _get_vr(field_name: str) -> str:
        try:
            tag_info = get_tag_info(field_name)
            if tag_info["tag"]:
                tag_str = tag_info["tag"].strip("()")
                tag_parts = tag_str.split(",")
                tag_tuple = (int(tag_parts[0], 16), int(tag_parts[1], 16))
                return dictionary_VR(tag_tuple) or 'LO'
        except:
            pass
        return 'LO'

    # Helper to determine data type from value
    def _get_data_type(value: Any) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return 'number'
        elif isinstance(value, list):
            if len(value) == 0:
                return 'list_string'
            elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
                return 'list_number'
            else:
                return 'list_string'
        else:
            return 'string'

    # Helper to convert schema format to UI format
    def _convert_to_ui_acquisition(schema_data: Dict[str, Any], source_type: str, idx: int) -> Dict[str, Any]:
        acq_info = schema_data.get('acquisition_info', {})
        protocol_name = acq_info.get('protocol_name', file_name)

        # Process acquisition-level fields
        acquisition_fields = []
        for field_data in schema_data.get('fields', []):
            field_name = field_data.get('field', '')
            field_value = field_data.get('value')

            # Get tag info
            tag_info = get_tag_info(field_name)
            tag = tag_info.get('tag')
            field_tag = tag.strip("()") if tag else None
            field_type = tag_info.get('fieldType', 'standard')

            # Handle single-element arrays
            processed_value = field_value
            data_type = _get_data_type(field_value)
            if isinstance(field_value, list) and len(field_value) == 1:
                if isinstance(field_value[0], (int, float)) and not isinstance(field_value[0], bool):
                    data_type = 'number'
                    processed_value = field_value[0]
                elif isinstance(field_value[0], str):
                    data_type = 'string'
                    processed_value = field_value[0]

            acquisition_fields.append({
                'tag': field_tag,
                'name': field_name,
                'keyword': field_name,
                'value': processed_value,
                'vr': _get_vr(field_name),
                'level': 'acquisition',
                'dataType': data_type,
                'fieldType': field_type,
                'validationRule': {'type': 'exact'}
            })

        # Process series
        series_fields = []
        series_list = []
        schema_series = schema_data.get('series', [])

        if schema_series:
            # Collect series field definitions from first series
            first_series = schema_series[0] if schema_series else {}
            series_field_values = {}

            for series_data in schema_series:
                for field_data in series_data.get('fields', []):
                    field_name = field_data.get('field', '')
                    field_value = field_data.get('value')

                    if field_name not in series_field_values:
                        series_field_values[field_name] = []
                    series_field_values[field_name].append(field_value)

            # Create series fields
            for field_name, values in series_field_values.items():
                tag_info = get_tag_info(field_name)
                tag = tag_info.get('tag')
                field_tag = tag.strip("()") if tag else None
                field_type = tag_info.get('fieldType', 'standard')

                series_fields.append({
                    'tag': field_tag,
                    'name': field_name,
                    'keyword': field_name,
                    'values': values,
                    'vr': _get_vr(field_name),
                    'level': 'series',
                    'dataType': _get_data_type(values[0]) if values else 'string',
                    'fieldType': field_type,
                    'validationRule': {'type': 'exact'}
                })

            # Create series with fields as array
            for series_data in schema_series:
                series_name = series_data.get('name', f'Series {len(series_list) + 1}')
                series_fields_array = []

                for field_data in series_data.get('fields', []):
                    field_name = field_data.get('field', '')
                    field_value = field_data.get('value')

                    tag_info = get_tag_info(field_name)
                    tag = tag_info.get('tag')
                    field_tag = tag.strip("()") if tag else None
                    field_type = tag_info.get('fieldType', 'standard')

                    series_fields_array.append({
                        'name': field_name,
                        'tag': field_tag,
                        'value': field_value,
                        'fieldType': field_type,
                        'validationRule': {'type': 'exact'}
                    })

                series_list.append({
                    'name': series_name,
                    'fields': series_fields_array
                })

        timestamp = int(time.time() * 1000)
        return {
            'id': f'{source_type}_{timestamp}_{idx}',
            'protocolName': protocol_name,
            'seriesDescription': f'Protocol from {file_name}',
            'totalFiles': 1,
            'acquisitionFields': acquisition_fields,
            'seriesFields': series_fields,
            'series': series_list,
            'metadata': {
                'source': source_type,
                'originalFileName': file_name,
                'acquisitionInfo': acq_info
            }
        }

    # Write to temp file
    suffix_map = {
        'pro': '.pro',
        'exar1': '.exar1',
        'examcard': '.ExamCard',
        'lxprotocol': '',
        'printprot': ''
    }
    suffix = suffix_map.get(file_type, '')
    mode = 'wb' if file_type in ['exar1', 'examcard', 'printprot'] else 'w'

    with tempfile.NamedTemporaryFile(mode=mode, suffix=suffix, delete=False) as f:
        if mode == 'wb':
            f.write(file_content)
        else:
            f.write(file_content.decode('utf-8'))
        temp_path = f.name

    try:
        # Load based on file type
        if file_type == 'pro':
            schema_data = load_pro_file_schema_format(temp_path)
            return make_json_serializable([_convert_to_ui_acquisition(schema_data, 'siemens_protocol', 0)])

        elif file_type == 'exar1':
            # Use schema format so multi-echo / magnitude-phase acquisitions are
            # expanded into series (matching the .pro path), rather than collapsed
            # into a single row holding tuples of echo times.
            protocols = load_exar_file_schema_format(temp_path)
            result = []
            for idx, schema_format in enumerate(protocols):
                result.append(_convert_to_ui_acquisition(schema_format, 'siemens_exar', idx))
            return make_json_serializable(result)

        elif file_type == 'examcard':
            scans = load_examcard_file_schema_format(temp_path)
            result = []
            for idx, scan_data in enumerate(scans):
                result.append(_convert_to_ui_acquisition(scan_data, 'philips_examcard', idx))
            return make_json_serializable(result)

        elif file_type == 'lxprotocol':
            scans = load_lxprotocol_file_schema_format(temp_path)
            result = []
            for idx, scan_data in enumerate(scans):
                result.append(_convert_to_ui_acquisition(scan_data, 'ge_lxprotocol', idx))
            return make_json_serializable(result)

        elif file_type == 'printprot':
            scans = load_printprot_file_schema_format(temp_path)
            result = []
            for idx, scan_data in enumerate(scans):
                result.append(_convert_to_ui_acquisition(scan_data, 'siemens_printprot', idx))
            return make_json_serializable(result)

        else:
            raise ValueError(f"Unknown file type: {file_type}")

    finally:
        os.unlink(temp_path)


def load_gradient_file_for_ui(
    files: Dict[str, str],
    b_max: Optional[float] = None
) -> Dict[str, Any]:
    """
    Derive diffusion descriptor fields from a gradient file and return them as
    UI-ready derived fields, ready to merge into an acquisition.

    The raw gradient content is consumed to compute descriptors and then
    discarded — dicompare schemas store validation requirements, not files.

    Args:
        files: Mapping of kind -> text content. Either {'dvs': <text>} or
            {'bvec': <text>, 'bval': <text>}.
        b_max: The acquisition's max b-value (DiffusionBValue). Required for
            'dvs' (b-values are magnitude-modulated); ignored for bvec/bval.

    Returns:
        {"fields": [ {tag, name, keyword, value, vr, level, dataType,
                      fieldType, validationRule}, ... ]}
        where every field is a derived diffusion descriptor.
    """
    from ..io import descriptors_from_dvs, descriptors_from_bvec_bval

    if 'dvs' in files:
        if b_max is None:
            raise ValueError("b_max (DiffusionBValue) is required to interpret a .dvs file")
        descriptors = descriptors_from_dvs(files['dvs'], float(b_max))
    elif 'bvec' in files and 'bval' in files:
        descriptors = descriptors_from_bvec_bval(files['bvec'], files['bval'])
    else:
        raise ValueError("Provide either {'dvs': ...} or {'bvec': ..., 'bval': ...}")

    def _data_type(value: Any) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return 'number'
        if isinstance(value, list):
            if value and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
                return 'list_number'
            return 'list_string'
        return 'string'

    fields = []
    for name, value in descriptors.items():
        fields.append({
            'tag': None,
            'name': name,
            'keyword': name,
            'value': value,
            'vr': 'LO',
            'level': 'acquisition',
            'dataType': _data_type(value),
            'fieldType': 'derived',
            'validationRule': {'type': 'exact'},
        })

    return make_json_serializable({"fields": fields})


# ============================================================================
# Gradient-to-acquisition binding
# ============================================================================

def _gradient_file_kind(name: str) -> Optional[str]:
    """Classify a gradient file by extension: 'dvs', 'bvec', 'bval', or None."""
    lower = name.lower()
    if lower.endswith('.dvs'):
        return 'dvs'
    if lower.endswith('.bvec'):
        return 'bvec'
    if lower.endswith('.bval'):
        return 'bval'
    return None


def _gradient_base_name(name: str) -> str:
    """Strip directory and extension: 'a/b/Foo.dvs' -> 'Foo'."""
    base = name.replace('\\', '/').split('/')[-1]
    dot = base.rfind('.')
    return base[:dot] if dot > 0 else base


def _acq_field_value(acquisition: Dict[str, Any], name: str) -> Any:
    """Read an acquisition field value by keyword (or name)."""
    for field in acquisition.get('acquisitionFields', []) or []:
        if (field.get('keyword') or field.get('name')) == name:
            return field.get('value')
    return None


def _is_diffusion_acquisition(acquisition: Dict[str, Any]) -> bool:
    return (_acq_field_value(acquisition, 'DiffusionBValue') is not None
            or _acq_field_value(acquisition, 'DiffusionDirectionSet') is not None)


def _merge_descriptor_fields(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge derived descriptor fields, replacing any existing same-named ones."""
    names = {(f.get('keyword') or f.get('name')) for f in incoming}
    kept = [f for f in (existing or []) if (f.get('keyword') or f.get('name')) not in names]
    return kept + incoming


def attach_gradient_files_to_acquisitions(
    acquisitions: List[Dict[str, Any]],
    files: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Bind diffusion gradient files (.dvs / .bvec+.bval) to the acquisitions they
    describe and merge the derived descriptors in. This is the shared binder used
    by the web app and the embed; it matches a gradient file to an acquisition,
    supplies the max b-value, derives descriptors, and merges them.

    Args:
        acquisitions: UI-acquisition dicts (with ``acquisitionFields``). These are
            the candidate acquisitions to bind against; callers pass a pre-scoped
            subset (e.g. only reference or only test-data acquisitions) when needed.
        files: List of ``{"name": str, "content": str}`` for each .dvs/.bvec/.bval.

    Returns:
        {
            "acquisitions": [...same list with descriptors merged in place...],
            "bound": [{"protocolName": str, "id": Any, "descriptors": [field names]}],
            "unmatched": [basename, ...]   # gradient groups that matched nothing
        }

    Matching rules (mirrors the web binding):
        - a .dvs binds to every acquisition whose ``DiffusionDirectionSet`` equals
          the file's basename; if none match, it binds to the sole diffusion
          acquisition if there is exactly one;
        - a .bvec/.bval pair (same basename) binds to the sole diffusion
          acquisition;
        - for a .dvs, the max b-value is taken from the target's
          ``DiffusionBValue``; bvec/bval carry absolute b-values already.
    """
    # Group by basename so a .bvec and its .bval pair up; a .dvs stands alone.
    groups: Dict[str, Dict[str, str]] = {}
    for f in files:
        kind = _gradient_file_kind(f.get('name', ''))
        if not kind:
            continue
        groups.setdefault(_gradient_base_name(f['name']), {})[kind] = f.get('content', '')

    diffusion_acqs = [a for a in acquisitions if _is_diffusion_acquisition(a)]
    bound: List[Dict[str, Any]] = []
    unmatched: List[str] = []

    for base_name, files_by_type in groups.items():
        if 'dvs' in files_by_type:
            targets = [a for a in acquisitions if _acq_field_value(a, 'DiffusionDirectionSet') == base_name]
            if not targets and len(diffusion_acqs) == 1:
                targets = [diffusion_acqs[0]]
        elif 'bvec' in files_by_type and 'bval' in files_by_type:
            targets = [diffusion_acqs[0]] if len(diffusion_acqs) == 1 else []
        else:
            unmatched.append(base_name)  # incomplete (need both .bvec and .bval)
            continue

        if not targets:
            unmatched.append(base_name)
            continue

        for target in targets:
            b_max: Optional[float] = None
            if 'dvs' in files_by_type:
                raw = _acq_field_value(target, 'DiffusionBValue')
                try:
                    b_max = float(raw)
                except (TypeError, ValueError):
                    unmatched.append(base_name)
                    continue
            try:
                derived = load_gradient_file_for_ui(files_by_type, b_max)['fields']
            except Exception:
                unmatched.append(base_name)
                continue
            target['acquisitionFields'] = _merge_descriptor_fields(
                target.get('acquisitionFields', []), derived
            )
            bound.append({
                'protocolName': target.get('protocolName'),
                'id': target.get('id'),
                'descriptors': [(f.get('keyword') or f.get('name')) for f in derived],
            })

    return make_json_serializable({
        "acquisitions": acquisitions,
        "bound": bound,
        "unmatched": unmatched,
    })


