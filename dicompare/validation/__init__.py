"""
Validation module for dicompare.

This module provides validation framework, compliance checking, and helper utilities
for DICOM session validation.
"""

from .core import (
    BaseValidationModel,
    RuleContext,
    ValidationError,
    ValidationWarning,
    validator,
    safe_exec_rule,
    create_validation_model_from_rules,
    create_validation_models_from_rules,
)

from .compliance import (
    check_acquisition_compliance
)

from .helpers import (
    ComplianceStatus,
    # Low-level comparison helpers, kept importable for backwards
    # compatibility but no longer part of the curated API (they are
    # implementation details of check_acquisition_compliance).
    validate_constraint,
    validate_field_values,
    create_compliance_record,
    format_constraint_description,
    normalize_value,
    check_equality,
    check_contains,
    check_contains_any,
    check_contains_all
)

__all__ = [
    # Core validation framework
    'BaseValidationModel',
    'RuleContext',
    'ValidationError',
    'ValidationWarning',
    'validator',
    'safe_exec_rule',
    'create_validation_model_from_rules',
    'create_validation_models_from_rules',

    # Compliance checking
    'check_acquisition_compliance',
    'ComplianceStatus',
]