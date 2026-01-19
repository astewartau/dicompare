"""
Processing module for dicompare.

This module provides parallel processing and progress tracking utilities
for efficient data processing operations.
"""

from .parallel_utils import (
    process_items_parallel
)

from .progress_utils import (
    ProgressTracker,
    track_iteration
)

__all__ = [
    # Parallel processing
    'process_items_parallel',

    # Progress tracking
    'ProgressTracker',
    'track_iteration'
]