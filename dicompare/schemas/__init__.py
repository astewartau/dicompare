"""
Bundled schema library for dicompare.

Provides functions to list and load schemas that ship with the package.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# Directory containing bundled schemas
_SCHEMAS_DIR = Path(__file__).parent


def list_bundled_schemas() -> List[str]:
    """
    List all bundled schema filenames.

    Returns:
        List of schema JSON filenames (e.g., ["hcp_schema.json", ...])
    """
    index_path = _SCHEMAS_DIR / "index.json"
    if index_path.exists():
        with open(index_path, "r") as f:
            return json.load(f)
    # Fallback: glob for *.json excluding index.json
    return sorted(
        p.name for p in _SCHEMAS_DIR.glob("*.json")
        if p.name != "index.json"
    )


def get_bundled_schema_path(filename: str) -> Path:
    """
    Get the absolute path to a bundled schema file.

    Args:
        filename: Schema filename (e.g., "hcp_schema.json")

    Returns:
        Path to the schema file.

    Raises:
        FileNotFoundError: If the schema file does not exist.
    """
    path = _SCHEMAS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Bundled schema not found: {filename}")
    return path


def load_bundled_schema(filename: str) -> Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
    """
    Load a bundled schema using the standard load_schema function.

    Args:
        filename: Schema filename (e.g., "hcp_schema.json")

    Returns:
        Same tuple as load_schema: (reference_fields, schema_dict, validation_rules)
    """
    from ..io.json import load_schema
    path = get_bundled_schema_path(filename)
    return load_schema(str(path))


def load_all_bundled_schemas() -> Dict[str, Tuple[List[str], Dict[str, Any], Dict[str, Any]]]:
    """
    Load all bundled schemas.

    Returns:
        Dict mapping filename -> (reference_fields, schema_dict, validation_rules)
    """
    result = {}
    for filename in list_bundled_schemas():
        try:
            result[filename] = load_bundled_schema(filename)
        except Exception as e:
            logger.warning(f"Failed to load bundled schema {filename}: {e}")
            continue
    return result
