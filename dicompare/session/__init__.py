"""
Session module for dicompare.

This module provides session analysis utilities including acquisition identification,
run assignment, and mapping between sessions.
"""

from .acquisition import (
    assign_acquisition_and_run_numbers
)

from .mapping import (
    map_to_json_reference,
    interactive_mapping_to_json_reference
)

__all__ = [
    # Acquisition identification
    'assign_acquisition_and_run_numbers',

    # Session mapping
    'map_to_json_reference',
    'interactive_mapping_to_json_reference'
]