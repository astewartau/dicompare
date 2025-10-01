"""
Interface module for dicompare.

This module provides user interface utilities including web interfaces,
visualization, and data preparation for external consumption.
"""

from .web_utils import (
    analyze_dicom_files_for_web,
)

__all__ = [
    # Web utilities
    'analyze_dicom_files_for_web',
]