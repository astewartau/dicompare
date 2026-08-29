"""
dicompare: vendor-independent validation and comparison of MRI acquisition
protocols using DICOM metadata.

Public API overview:

- Loading data: ``load_dicom_session`` and friends, plus one importer family
  per vendor protocol format (``load_pro_file``, ``load_examcard_file``,
  ``load_lxprotocol_file``, ``load_printprot_file``, ... — each with a
  ``_schema_format`` variant).
- Schemas: ``build_schema``, ``load_schema``, ``validate_schema`` (metaschema),
  and ``lint_schema`` (best-practice checks, also ``dicompare lint`` on the
  command line).
- Validation: ``check_acquisition_compliance`` plus the rule framework
  (``BaseValidationModel``, ``RuleContext``, ``ValidationError`` /
  ``ValidationWarning``).
- Field registry: ``dicompare.fields`` is the single source of truth for
  per-field metadata (canonical names, vocabularies, units, vendor
  encodings); ``FieldDef``, ``get_field``, ``check_value`` and
  ``validate_fields`` are re-exported here.
"""

__version__ = "0.0.0"  # Replaced at build time by the publish workflow

# ---------------------------------------------------------------------------
# Data loading (DICOM, NIfTI, and vendor protocol formats)
# ---------------------------------------------------------------------------
from .io import (
    get_dicom_values,
    load_dicom,
    load_dicom_session,
    async_load_dicom_session,
    load_nifti_session,
    load_pro_file,
    load_pro_file_schema_format,
    load_pro_session,
    load_exar_file,
    load_exar_file_schema_format,
    load_exar_session,
    load_examcard_file,
    load_examcard_file_schema_format,
    load_lxprotocol_file,
    load_lxprotocol_file_schema_format,
    load_lxprotocol_session,
    load_printprot_file,
    load_printprot_file_schema_format,
    generate_test_dicoms_from_schema,
    make_json_serializable,
)

# ---------------------------------------------------------------------------
# Schemas: build, load, validate, lint
# ---------------------------------------------------------------------------
from .io import load_schema, validate_schema
from .schema import (
    build_schema,
    get_tag_info,
    get_all_tags_in_dataset,
    determine_field_type_from_values,
    lint_schema,
    format_findings,
    LintFinding,
)
from .schemas import (
    list_bundled_schemas,
    get_bundled_schema_path,
    load_bundled_schema,
    load_all_bundled_schemas,
)

# ---------------------------------------------------------------------------
# Canonical field registry
# ---------------------------------------------------------------------------
from .fields import (
    FieldDef,
    FIELD_REGISTRY,
    get_field,
    check_value,
    validate_fields,
)

# ---------------------------------------------------------------------------
# Validation and compliance
# ---------------------------------------------------------------------------
from .validation import (
    check_acquisition_compliance,
    BaseValidationModel,
    RuleContext,
    ValidationError,
    ValidationWarning,
    validator,
    safe_exec_rule,
    resolve_rule_params,
    create_validation_model_from_rules,
    create_validation_models_from_rules,
)

# ---------------------------------------------------------------------------
# Session handling
# ---------------------------------------------------------------------------
from .session import (
    assign_acquisition_and_run_numbers,
    map_to_json_reference,
    interactive_mapping_to_json_reference,
)

# ---------------------------------------------------------------------------
# Configuration and utilities
# ---------------------------------------------------------------------------
from .config import (
    DEFAULT_SETTINGS_FIELDS,
    DEFAULT_ACQUISITION_FIELDS,
    DEFAULT_DICOM_FIELDS,
)
from .utils import clean_string, make_hashable

# ---------------------------------------------------------------------------
# Web/UI interface (called from dicompare-web via pyodide)
# ---------------------------------------------------------------------------
from .interface import (
    analyze_dicom_files_for_ui,
    validate_acquisition_direct,
    load_protocol_for_ui,
    load_gradient_file_for_ui,
    attach_gradient_files_to_acquisitions,
    search_dicom_dictionary,
    build_schema_from_ui_acquisitions,
    run_rule_test_case,
)

__all__ = [
    # Data loading
    "get_dicom_values",
    "load_dicom",
    "load_dicom_session",
    "async_load_dicom_session",
    "load_nifti_session",
    "load_pro_file",
    "load_pro_file_schema_format",
    "load_pro_session",
    "load_exar_file",
    "load_exar_file_schema_format",
    "load_exar_session",
    "load_examcard_file",
    "load_examcard_file_schema_format",
    "load_lxprotocol_file",
    "load_lxprotocol_file_schema_format",
    "load_lxprotocol_session",
    "load_printprot_file",
    "load_printprot_file_schema_format",
    "generate_test_dicoms_from_schema",
    "make_json_serializable",
    # Schemas
    "load_schema",
    "validate_schema",
    "build_schema",
    "get_tag_info",
    "get_all_tags_in_dataset",
    "determine_field_type_from_values",
    "lint_schema",
    "format_findings",
    "LintFinding",
    "list_bundled_schemas",
    "get_bundled_schema_path",
    "load_bundled_schema",
    "load_all_bundled_schemas",
    # Field registry
    "FieldDef",
    "FIELD_REGISTRY",
    "get_field",
    "check_value",
    "validate_fields",
    # Validation
    "check_acquisition_compliance",
    "BaseValidationModel",
    "RuleContext",
    "ValidationError",
    "ValidationWarning",
    "validator",
    "safe_exec_rule",
    "resolve_rule_params",
    "create_validation_model_from_rules",
    "create_validation_models_from_rules",
    # Session handling
    "assign_acquisition_and_run_numbers",
    "map_to_json_reference",
    "interactive_mapping_to_json_reference",
    # Configuration and utilities
    "DEFAULT_SETTINGS_FIELDS",
    "DEFAULT_ACQUISITION_FIELDS",
    "DEFAULT_DICOM_FIELDS",
    "clean_string",
    "make_hashable",
    # Web/UI interface
    "analyze_dicom_files_for_ui",
    "validate_acquisition_direct",
    "load_protocol_for_ui",
    "load_gradient_file_for_ui",
    "attach_gradient_files_to_acquisitions",
    "search_dicom_dictionary",
    "build_schema_from_ui_acquisitions",
    "run_rule_test_case",
]
