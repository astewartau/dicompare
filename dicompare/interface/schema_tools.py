"""
Schema building, DICOM dictionary search, and rule test execution for the
web UI. Split out of web_utils.py; the public entry points remain exported
from dicompare.interface.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union, Tuple
import json
import logging

from ..io import make_json_serializable

logger = logging.getLogger(__name__)

def search_dicom_dictionary(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search DICOM dictionary for fields matching the query.

    Args:
        query: Search query (matches against keyword, name, or tag)
        limit: Maximum number of results to return

    Returns:
        List of matching field dictionaries with:
        - tag, name, keyword, vr, vm, description, suggested_data_type
    """
    from pydicom.datadict import DicomDictionary, dictionary_VR, dictionary_VM, dictionary_description
    from ..schema.tags import VR_TO_DATA_TYPE

    query_lower = query.lower()
    results = []
    count = 0

    # Search through pydicom's DICOM dictionary (tag_int -> (VR, VM, name,
    # is_retired, keyword)). Note keyword_for_tag is a function, not a mapping.
    for tag_int, entry in DicomDictionary.items():
        if count >= limit:
            break

        keyword = entry[4]
        if not keyword:
            continue

        # Convert tag to string format
        tag_str = f"{tag_int:08X}"
        tag_formatted = f"{tag_str[:4]},{tag_str[4:]}"

        # Get additional info
        try:
            vr = dictionary_VR(tag_int) or "UN"
            vm = dictionary_VM(tag_int) or "1"
            description = dictionary_description(tag_int) or keyword
        except:
            vr = "UN"
            vm = "1"
            description = keyword

        # Check if query matches
        if (query_lower in keyword.lower() or
            query_lower in description.lower() or
            query_lower in tag_formatted.lower() or
            query_lower in tag_str.lower()):

            # Determine suggested data type from VR
            suggested_type = VR_TO_DATA_TYPE.get(vr, 'string')
            if vm not in ['1', '1-1'] and suggested_type in ['string', 'number']:
                suggested_type = f"list_{suggested_type}"

            results.append({
                'tag': tag_formatted,
                'name': description,
                'keyword': keyword,
                'vr': vr,
                'vm': vm,
                'description': description,
                'suggested_data_type': suggested_type,
                'suggested_validation': 'exact',
                'common_values': []
            })
            count += 1

    return make_json_serializable(results)


def build_schema_from_ui_acquisitions(
    acquisitions: List[Dict[str, Any]],
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build a dicompare schema from UI acquisition format.

    This is the inverse of analyze_dicom_files_for_ui() - it takes UI
    acquisition data and creates a dicompare-compatible schema.

    Args:
        acquisitions: List of UI acquisition dictionaries
        metadata: Schema metadata (name, description, version, authors, tags)

    Returns:
        Dicompare-compatible schema dictionary
    """
    from ..schema import get_tag_info

    dicompare_acquisitions = {}

    for acquisition in acquisitions:
        acq_name = acquisition.get('protocolName', acquisition.get('id', 'Unknown'))

        # Process acquisition fields
        acq_fields = []
        for field in acquisition.get('acquisitionFields', []):
            field_entry = {
                'field': field.get('keyword', field.get('name', '')),
                'tag': field.get('tag') or field.get('fieldType', 'derived')
            }

            # Get actual value and validation rule
            actual_value = field.get('value')
            validation_rule = field.get('validationRule', {})

            # Handle complex value objects (read nested validationRule before
            # unwrapping the scalar value out of the dict)
            if isinstance(actual_value, dict) and ('validationRule' in actual_value or 'dataType' in actual_value):
                validation_rule = actual_value.get('validationRule', validation_rule)
                actual_value = actual_value.get('value')

            # Apply validation rules to create flat structure
            rule_type = validation_rule.get('type', 'exact') if validation_rule else 'exact'

            if rule_type == 'tolerance':
                if validation_rule.get('value') is not None and validation_rule.get('tolerance') is not None:
                    field_entry['value'] = validation_rule['value']
                    field_entry['tolerance'] = validation_rule['tolerance']
                else:
                    field_entry['value'] = actual_value
            elif rule_type == 'range':
                min_val = validation_rule.get('min')
                max_val = validation_rule.get('max')
                if min_val is not None:
                    field_entry['min'] = min_val
                if max_val is not None:
                    field_entry['max'] = max_val
                # Don't set 'value' for range constraints - min/max are the constraints
            elif rule_type == 'contains':
                if validation_rule.get('contains') is not None:
                    field_entry['contains'] = validation_rule['contains']
                else:
                    field_entry['value'] = actual_value
            elif rule_type == 'contains_any':
                if validation_rule.get('contains_any') is not None:
                    field_entry['contains_any'] = validation_rule['contains_any']
                else:
                    field_entry['value'] = actual_value
            elif rule_type == 'contains_all':
                if validation_rule.get('contains_all') is not None:
                    field_entry['contains_all'] = validation_rule['contains_all']
                else:
                    field_entry['value'] = actual_value
            else:
                field_entry['value'] = actual_value

            acq_fields.append(field_entry)

        # Process series
        series_data = []
        for series in acquisition.get('series', []):
            series_fields = []
            fields_array = series.get('fields', [])

            # Handle both array and object formats
            if isinstance(fields_array, dict):
                fields_array = [
                    {'name': k, 'tag': k, 'value': v.get('value') if isinstance(v, dict) else v,
                     'validationRule': v.get('validationRule', {'type': 'exact'}) if isinstance(v, dict) else {'type': 'exact'}}
                    for k, v in fields_array.items()
                ]

            for field in fields_array:
                field_entry = {
                    'field': field.get('keyword', field.get('name', '')),
                    'tag': field.get('tag') or field.get('fieldType', 'derived')
                }

                actual_value = field.get('value')
                validation_rule = field.get('validationRule', {})
                rule_type = validation_rule.get('type', 'exact') if validation_rule else 'exact'

                if rule_type == 'tolerance':
                    if validation_rule.get('value') is not None and validation_rule.get('tolerance') is not None:
                        field_entry['value'] = validation_rule['value']
                        field_entry['tolerance'] = validation_rule['tolerance']
                    else:
                        field_entry['value'] = actual_value
                elif rule_type == 'range':
                    min_val = validation_rule.get('min')
                    max_val = validation_rule.get('max')
                    if min_val is not None:
                        field_entry['min'] = min_val
                    if max_val is not None:
                        field_entry['max'] = max_val
                    # Don't set 'value' for range constraints - min/max are the constraints
                elif rule_type == 'contains':
                    if validation_rule.get('contains') is not None:
                        field_entry['contains'] = validation_rule['contains']
                    else:
                        field_entry['value'] = actual_value
                elif rule_type == 'contains_any':
                    if validation_rule.get('contains_any') is not None:
                        field_entry['contains_any'] = validation_rule['contains_any']
                    else:
                        field_entry['value'] = actual_value
                elif rule_type == 'contains_all':
                    if validation_rule.get('contains_all') is not None:
                        field_entry['contains_all'] = validation_rule['contains_all']
                    else:
                        field_entry['value'] = actual_value
                else:
                    field_entry['value'] = actual_value

                # Only include fields with actual constraints
                if 'value' in field_entry or 'contains' in field_entry or 'tolerance' in field_entry or 'min' in field_entry or 'max' in field_entry:
                    series_fields.append(field_entry)

            if series_fields:
                series_entry = {
                    'name': series.get('name', f'Series {len(series_data) + 1}'),
                    'fields': series_fields
                }
                series_images = series.get('images', [])
                if series_images:
                    series_entry['images'] = series_images
                series_data.append(series_entry)

        # Build acquisition entry
        acq_entry = {
            'description': acquisition.get('seriesDescription', ''),
            'detailed_description': acquisition.get('detailedDescription', ''),
            'fields': acq_fields,
            'series': series_data
        }

        # Add tags if present
        acq_tags = acquisition.get('tags', [])
        if acq_tags:
            acq_entry['tags'] = acq_tags

        # Add images if present
        acq_images = acquisition.get('images', [])
        if acq_images:
            acq_entry['images'] = acq_images

        # Add validation rules if present
        validation_functions = acquisition.get('validationFunctions', [])
        if validation_functions:
            acq_entry['rules'] = [
                {
                    'id': func.get('id', f"rule_{acq_name.lower().replace(' ', '_')}_{idx}"),
                    'name': func.get('customName', func.get('name', '')),
                    'description': func.get('customDescription', func.get('description', '')),
                    'implementation': func.get('customImplementation', func.get('implementation', '')),
                    'parameters': func.get('configuredParams', func.get('parameters', {})),
                    'fields': func.get('customFields', func.get('fields', [])),
                    'testCases': func.get('customTestCases', func.get('testCases', []))
                }
                for idx, func in enumerate(validation_functions)
            ]

        dicompare_acquisitions[acq_name] = acq_entry

    # Build schema (only include fields defined in metaschema)
    schema = {
        'name': metadata.get('name', 'Generated Schema'),
        'description': metadata.get('description', ''),
        'version': metadata.get('version', '1.0'),
        'authors': metadata.get('authors', []),
        'acquisitions': dicompare_acquisitions
    }

    return make_json_serializable(schema)


def run_rule_test_case(
    rule: Dict[str, Any],
    test_data: Dict[str, Any],
    acquisition_name: str = "test",
) -> Dict[str, Any]:
    """
    Run a single validation rule against one test case.

    This uses the SAME execution path as real compliance checking
    (``create_validation_model_from_rules`` -> ``safe_exec_rule``) and the SAME
    data representation (list-valued cells become tuples via ``make_hashable``,
    values grouped into a DataFrame). It exists so the schema builder's
    "Test function" button exercises a rule exactly as it will run in production,
    instead of a bespoke, more permissive environment that can mask real bugs
    (blocked imports, tuple-vs-string list cells, etc.).

    Args:
        rule: Rule dict with at least ``id``, ``fields`` and ``implementation``
            (optionally ``name`` / ``description``).
        test_data: Mapping of field name -> list of per-row cell values. A cell
            may itself be a list for list-valued fields (e.g. DiffusionBValues).
            Column lengths may differ; shorter columns are padded with ``None``.
        acquisition_name: Label used for the synthetic acquisition.

    Returns:
        Dict with ``result`` ('pass' | 'warning' | 'fail'), ``passed`` (bool),
        ``message`` (str) and ``status`` (compliance status string).
    """
    from ..utils import make_hashable
    from ..validation.core import create_validation_model_from_rules

    norm_rule = {
        'id': rule.get('id') or 'test_rule',
        'name': rule.get('name', rule.get('id', 'test_rule')),
        'description': rule.get('description', ''),
        'fields': list(rule.get('fields', [])),
        'implementation': rule.get('implementation', ''),
    }

    # Determine the number of rows across all provided columns.
    col_lengths = [len(v) for v in test_data.values() if isinstance(v, list)]
    n_rows = max(col_lengths) if col_lengths else 1

    rows = []
    for i in range(n_rows):
        row = {'Acquisition': acquisition_name}
        for field, values in test_data.items():
            if isinstance(values, list):
                cell = values[i] if i < len(values) else None
            else:
                cell = values
            row[field] = make_hashable(cell)
        rows.append(row)

    session_df = pd.DataFrame(rows)

    model = create_validation_model_from_rules(acquisition_name, [norm_rule])
    _success, errors, warnings, passes = model.validate(session_df)

    if errors:
        return {
            'result': 'fail',
            'passed': False,
            'message': errors[0].get('message', ''),
            'status': errors[0].get('status', 'error'),
        }
    if warnings:
        return {
            'result': 'warning',
            'passed': True,
            'message': warnings[0].get('message', ''),
            'status': warnings[0].get('status', 'warning'),
        }
    return {
        'result': 'pass',
        'passed': True,
        'message': passes[0].get('message', 'OK') if passes else 'OK',
        'status': 'ok',
    }