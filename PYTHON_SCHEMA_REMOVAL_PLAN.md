# Python Schema Format Removal Plan

## Summary

The dicompare package currently supports TWO validation schema formats:

1. **OLD FORMAT (to be removed)**: Separate Python modules with `BaseValidationModel` classes
2. **NEW FORMAT (current)**: JSON schemas with embedded Python code in `rules` fields

## New Format Examples

See `/dicompare-web/public/schemas/`:
- `QSM_Consensus_Guidelines_v1.0.json` - Uses only embedded rules (no fields)
- `UK_Biobank_v1.0.json` - Uses both fields and embedded rules

### New JSON Schema Structure
```json
{
  "version": "1.0",
  "name": "Schema Name",
  "acquisitions": {
    "AcquisitionName": {
      "fields": [
        {
          "field": "RepetitionTime",
          "value": 2000,
          "tolerance": 10
        }
      ],
      "series": [...],
      "rules": [
        {
          "id": "rule_id",
          "name": "Rule Name",
          "description": "Rule description",
          "implementation": "# Python code here\nif condition:\n    raise ValidationError('message')",
          "fields": ["FieldName1", "FieldName2"]
        }
      ]
    }
  }
}
```

## Old Format (To Remove)

### Python Module Format
```python
from dicompare.validation import BaseValidationModel, validator, ValidationError

class QSM(BaseValidationModel):
    @validator(["EchoTime"], "Multi-echo", "Need multiple echoes")
    def validate_echo_count(cls, value):
        if len(value["EchoTime"].unique()) < 3:
            raise ValidationError("Need at least 3 echoes")
        return value

ACQUISITION_MODELS = {
    "QSM": QSM,
}
```

## Components to Remove

### 1. CLI (`dicompare/cli/check_session.py`)
**Lines to remove:** 20, 32-33, 61-62, 72-77

Current code:
```python
parser.add_argument("--python_schema", help="Path to the Python module containing validation models.")

elif args.python_schema:
    py_schema = load_python_schema(module_path=args.python_schema)

else:
    session_map = interactive_mapping_to_python_reference(in_session, py_schema)

else:
    compliance_summary = check_session_compliance_with_python_module(
        in_session=in_session,
        ref_models=py_schema,
        session_map=session_map
    )
```

**Action:** Remove all `--python_schema` argument handling

### 2. Functions to Remove

#### `dicompare/io/json.py`
- **Function:** `load_python_schema()` (lines 117-146)
- **Imports:** `import importlib.util` (only used for this function)

#### `dicompare/validation/compliance.py`
- **Function:** `check_session_compliance_with_python_module()` (lines 181-296)

#### `dicompare/session/mapping.py`
- **Function:** `interactive_mapping_to_python_reference()` (lines 406+)

### 3. Exports to Remove

#### `dicompare/__init__.py` (line 4)
Remove from import:
```python
from .io import load_python_schema
```

Remove from import (line 10):
```python
check_session_compliance_with_python_module
```

Remove from import (line 12):
```python
interactive_mapping_to_python_reference
```

#### `dicompare/io/__init__.py`
Remove `load_python_schema` from exports

#### `dicompare/validation/__init__.py`
Remove `check_session_compliance_with_python_module` from exports

#### `dicompare/session/__init__.py`
Remove `interactive_mapping_to_python_reference` from exports

### 4. Tests to Remove

#### `dicompare/tests/test_compliance.py`
- `test_check_session_compliance_with_python_module_pass` (line 131)
- `test_check_session_compliance_with_python_module_fail` (line 139)
- `test_check_session_compliance_with_python_module_empty_acquisition` (line 147)
- `test_check_session_compliance_with_python_module_raise_error` (line 155)
- `test_load_python_schema_qsm_fixture` (line 192)
- Tests using `load_python_schema` at lines 222, 234
- Test at line 594 using `check_session_compliance_with_python_module`

#### `dicompare/tests/test_io.py`
- Section "Tests for load_python_schema" (line 663+)
- `test_load_python_schema_valid` (line 749)
- `test_load_python_schema_no_models` (line 754)
- `test_load_python_schema_invalid` (line 758)

### 5. Test Fixtures to Remove (Optional)

Files that are only used for Python module testing:
- `dicompare/tests/fixtures/ref_qsm.py` - Keep? (might be useful as reference)
- Any pytest fixtures in test files that create Python module files

### 6. Legacy Files to Keep (For Reference)

These files use the OLD format but may serve as examples/documentation:
- `guidelines/qsm/qsm.py` - QSM consensus guidelines in old format
- `dicompare/tests/fixtures/ref_qsm.py` - Test fixture

**Decision needed:** Keep or remove these?

### 7. Documentation to Update

#### README.md
Remove all references to:
- Python schema validation
- `load_python_schema` examples
- `check_session_compliance_with_python_module` examples
- `interactive_mapping_to_python_reference` examples
- `--python_schema` CLI argument
- `BaseValidationModel` class examples

Current sections to update:
- Line 52-58: Remove Python schema CLI example
- Line 168-213: Remove Python validation model sections

## What to Keep

### Core validation classes (used by NEW format)
These are still needed because the new JSON format uses them internally:

- `BaseValidationModel` class (`dicompare/validation/core.py`)
- `@validator` decorator (`dicompare/validation/core.py`)
- `ValidationError` exception (`dicompare/validation/core.py`)
- `ValidationWarning` exception (`dicompare/validation/core.py`)
- `safe_exec_rule()` function - executes embedded Python code from JSON
- `create_validation_model_from_rules()` - creates models from JSON rules
- `create_validation_models_from_rules()` - creates models from JSON rules

These functions convert the NEW JSON format (with embedded Python) into validation models internally.

## Migration Path for Users

Users with old Python module schemas should:
1. Convert their Python modules to JSON format with embedded rules
2. Use the `rules` array in the JSON schema
3. Put their validation logic in the `implementation` field as a string

## Verification Steps

After removal:
1. Run all remaining tests: `pytest dicompare/tests/`
2. Test CLI with JSON schema: `dcm-check-session --json_schema schema.json --in_session /path/to/session`
3. Test embedded rules execution works correctly
4. Verify imports still work: `from dicompare import check_session_compliance_with_json_schema`
5. Update package version (breaking change)

## Files Summary

### Files to modify:
- `dicompare/cli/check_session.py` - Remove --python_schema handling
- `dicompare/io/json.py` - Remove load_python_schema function
- `dicompare/validation/compliance.py` - Remove check_session_compliance_with_python_module
- `dicompare/session/mapping.py` - Remove interactive_mapping_to_python_reference
- `dicompare/__init__.py` - Remove exports
- `dicompare/io/__init__.py` - Remove exports
- `dicompare/validation/__init__.py` - Remove exports
- `dicompare/session/__init__.py` - Remove exports
- `dicompare/tests/test_compliance.py` - Remove related tests
- `dicompare/tests/test_io.py` - Remove related tests
- `README.md` - Remove documentation

### Files to consider removing:
- `guidelines/qsm/qsm.py` (old format example)
- `dicompare/tests/fixtures/ref_qsm.py` (test fixture)

### Core validation files to KEEP:
- `dicompare/validation/core.py` - Contains BaseValidationModel, validator, etc. (needed for new format)
- `dicompare/validation/helpers.py` - Validation helper functions
