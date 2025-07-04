"""
Generic parallel processing utilities.

This module provides consistent parallel processing patterns that can be
used across different types of data processing tasks.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Callable, Any, Optional
from .progress_utils import track_async_completion, track_iteration


async def process_items_parallel(
    items: List[Any],
    worker_func: Callable,
    max_workers: int = 1,
    progress_function: Optional[Callable[[int], None]] = None,
    show_progress: bool = False,
    description: str = "Processing in parallel"
) -> List[Any]:
    """
    Process items in parallel using ThreadPoolExecutor.
    
    Args:
        items: Items to process
        worker_func: Function to apply to each item
        max_workers: Maximum number of parallel workers
        progress_function: Optional progress callback
        show_progress: Whether to show progress bar
        description: Description for progress bar
        
    Returns:
        List of processed results
    """
    if max_workers <= 1:
        # Fall back to sequential processing
        return await process_items_sequential(
            items, worker_func, progress_function, show_progress, description
        )
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(worker_func, item)
            for item in items
        ]
        
        return await track_async_completion(
            futures, progress_function, show_progress, description
        )


async def process_items_sequential(
    items: List[Any],
    worker_func: Callable,
    progress_function: Optional[Callable[[int], None]] = None,
    show_progress: bool = False,
    description: str = "Processing sequentially"
) -> List[Any]:
    """
    Process items sequentially with progress tracking.
    
    Args:
        items: Items to process
        worker_func: Function to apply to each item
        progress_function: Optional progress callback
        show_progress: Whether to show progress bar
        description: Description for progress bar
        
    Returns:
        List of processed results
    """
    return await track_iteration(
        items, worker_func, progress_function, show_progress, description
    )