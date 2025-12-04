"""Tests for schema validation against the DiCompare metaschema."""

import json
import os
from pathlib import Path

import pytest
from jsonschema import ValidationError

import dicompare


# Get the schemas directory path
SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"


class TestSchemaValidation:
    """Tests for validating schemas against the metaschema."""

    def test_validate_schema_function_exists(self):
        """Test that validate_schema function is exported."""
        assert hasattr(dicompare, 'validate_schema')
        assert callable(dicompare.validate_schema)

    def test_load_schema_validates_by_default(self, tmp_path):
        """Test that load_schema validates schemas by default."""
        # Create an invalid schema (missing required 'name' field)
        invalid_schema = {
            "acquisitions": {
                "T1": {"fields": []}
            }
        }
        schema_path = tmp_path / "invalid.json"
        with open(schema_path, "w") as f:
            json.dump(invalid_schema, f)

        with pytest.raises(ValidationError) as exc_info:
            dicompare.load_schema(str(schema_path))

        assert "name" in str(exc_info.value.message).lower() or "required" in str(exc_info.value.message).lower()

    def test_load_schema_can_skip_validation(self, tmp_path):
        """Test that load_schema can skip validation when requested."""
        # Create an invalid schema
        invalid_schema = {
            "acquisitions": {
                "T1": {"fields": []}
            }
        }
        schema_path = tmp_path / "invalid.json"
        with open(schema_path, "w") as f:
            json.dump(invalid_schema, f)

        # Should not raise when validation is disabled
        fields, schema_data, rules = dicompare.load_schema(str(schema_path), validate_schema=False)
        assert "acquisitions" in schema_data

    def test_validate_schema_rejects_invalid_json(self):
        """Test that validate_schema rejects schemas that are not valid JSON structure."""
        # Missing required 'name' field
        invalid_schema = {
            "acquisitions": {}
        }

        with pytest.raises(ValidationError):
            dicompare.validate_schema(invalid_schema)

    def test_validate_schema_rejects_invalid_contains_type(self):
        """Test that validate_schema rejects 'contains' field with boolean instead of string."""
        invalid_schema = {
            "name": "Test Schema",
            "acquisitions": {
                "T1": {
                    "fields": [
                        {
                            "field": "ScanOptions",
                            "contains": True  # Should be a string, not boolean
                        }
                    ]
                }
            }
        }

        with pytest.raises(ValidationError) as exc_info:
            dicompare.validate_schema(invalid_schema)

        # Error should mention 'contains' and type issue
        error_msg = str(exc_info.value.message).lower()
        assert "string" in error_msg or "type" in error_msg

    def test_validate_schema_rejects_invalid_tag_format(self):
        """Test that validate_schema rejects invalid DICOM tag formats."""
        invalid_schema = {
            "name": "Test Schema",
            "acquisitions": {
                "T1": {
                    "fields": [
                        {
                            "field": "EchoTime",
                            "tag": "invalid_tag_format"  # Should be XXXX,XXXX or unknown_*
                        }
                    ]
                }
            }
        }

        with pytest.raises(ValidationError) as exc_info:
            dicompare.validate_schema(invalid_schema)

        # Error should mention pattern matching failure
        error_msg = str(exc_info.value.message).lower()
        assert "does not match" in error_msg or "pattern" in error_msg

    def test_validate_schema_accepts_valid_tag_format(self, tmp_path):
        """Test that validate_schema accepts valid DICOM tag formats."""
        valid_schema = {
            "name": "Test Schema",
            "acquisitions": {
                "T1": {
                    "fields": [
                        {"field": "EchoTime", "tag": "0018,0081"},
                        {"field": "CustomField", "tag": "unknown_CustomField"}
                    ]
                }
            }
        }

        # Should not raise
        dicompare.validate_schema(valid_schema)

    def test_validate_schema_accepts_valid_contains_string(self, tmp_path):
        """Test that validate_schema accepts 'contains' field with string value."""
        valid_schema = {
            "name": "Test Schema",
            "acquisitions": {
                "T1": {
                    "fields": [
                        {
                            "field": "ScanOptions",
                            "contains": "IR"  # Correct: string value
                        }
                    ]
                }
            }
        }

        # Should not raise
        dicompare.validate_schema(valid_schema)


class TestBuiltInSchemas:
    """Tests that all built-in schemas in the schemas/ directory are valid."""

    def get_schema_files(self):
        """Get all JSON schema files from the schemas directory, excluding old/deprecated."""
        if not SCHEMAS_DIR.exists():
            return []

        schema_files = []
        for json_file in SCHEMAS_DIR.glob("*.json"):
            # Skip any files in subdirectories like hcp_OLD
            if json_file.is_file():
                schema_files.append(json_file)

        return schema_files

    def test_schemas_directory_exists(self):
        """Test that the schemas directory exists."""
        assert SCHEMAS_DIR.exists(), f"Schemas directory not found: {SCHEMAS_DIR}"

    def test_at_least_one_schema_exists(self):
        """Test that at least one schema file exists."""
        schema_files = self.get_schema_files()
        assert len(schema_files) > 0, "No schema files found in schemas directory"

    @pytest.mark.parametrize("schema_file", [
        pytest.param(f, id=f.name)
        for f in (Path(__file__).parent.parent.parent / "schemas").glob("*.json")
        if f.is_file()
    ] if (Path(__file__).parent.parent.parent / "schemas").exists() else [])
    def test_schema_loads_without_error(self, schema_file):
        """Test that each schema file loads without validation errors."""
        fields, schema_data, rules = dicompare.load_schema(str(schema_file))

        # Basic sanity checks
        assert isinstance(fields, list)
        assert isinstance(schema_data, dict)
        assert isinstance(rules, dict)
        assert "name" in schema_data or "acquisitions" in schema_data

    @pytest.mark.parametrize("schema_file", [
        pytest.param(f, id=f.name)
        for f in (Path(__file__).parent.parent.parent / "schemas").glob("*.json")
        if f.is_file()
    ] if (Path(__file__).parent.parent.parent / "schemas").exists() else [])
    def test_schema_validates_against_metaschema(self, schema_file):
        """Test that each schema file passes metaschema validation."""
        with open(schema_file) as f:
            schema_data = json.load(f)

        # Should not raise ValidationError
        dicompare.validate_schema(schema_data)


class TestMetaschemaStructure:
    """Tests for the metaschema itself."""

    def test_metaschema_file_exists(self):
        """Test that the metaschema.json file exists."""
        metaschema_path = Path(__file__).parent.parent / "metaschema.json"
        assert metaschema_path.exists(), f"Metaschema not found: {metaschema_path}"

    def test_metaschema_is_valid_json(self):
        """Test that the metaschema is valid JSON."""
        metaschema_path = Path(__file__).parent.parent / "metaschema.json"
        with open(metaschema_path) as f:
            metaschema = json.load(f)

        assert isinstance(metaschema, dict)
        assert "$schema" in metaschema
        assert "properties" in metaschema

    def test_metaschema_defines_required_fields(self):
        """Test that the metaschema defines the expected required fields."""
        metaschema_path = Path(__file__).parent.parent / "metaschema.json"
        with open(metaschema_path) as f:
            metaschema = json.load(f)

        required = metaschema.get("required", [])
        assert "name" in required
        assert "acquisitions" in required
