"""
Progress tracking utilities for dicompare operations.

This module provides consistent progress tracking across the codebase,
reducing repetitive progress update patterns.
"""

import asyncio
import logging
from typing import Optional, Callable, Any, List
from tqdm import tqdm

logger = logging.getLogger(__name__)


class ProgressTracker:
    """
    Manages progress tracking with optional callback function and async support.
    
    Provides consistent progress updates while eliminating repetitive
    progress tracking code patterns throughout the codebase.
    """
    
    def __init__(
        self, 
        total: int, 
        progress_function: Optional[Callable[[int], None]] = None,
        show_progress: bool = False,
        description: str = "Processing"
    ):
        """
        Initialize progress tracker.
        
        Args:
            total: Total number of items to process
            progress_function: Optional callback for progress updates (percentage 0-100)
            show_progress: Whether to show tqdm progress bar
            description: Description for progress bar
        """
        self.total = total
        self.progress_function = progress_function
        self.show_progress = show_progress
        self.description = description
        self.completed = 0
        self.last_reported_percentage = 0
        
        # Initialize tqdm if requested
        self.pbar = None
        if self.show_progress:
            self.pbar = tqdm(total=total, desc=description)
    
    async def update(self, increment: int = 1) -> None:
        """
        Update progress by specified increment.
        
        Args:
            increment: Number of items completed
        """
        self.completed += increment
        
        # Update tqdm progress bar
        if self.pbar:
            self.pbar.update(increment)
        
        # Call progress function if provided
        if self.progress_function:
            percentage = round(100 * self.completed / self.total)
            if percentage > self.last_reported_percentage:
                self.last_reported_percentage = percentage
                self.progress_function(percentage)
                await asyncio.sleep(0)  # Yield control
    
    def close(self) -> None:
        """Close the progress tracker and clean up resources."""
        if self.pbar:
            self.pbar.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


async def track_async_completion(
    futures: List[Any],
    progress_function: Optional[Callable[[int], None]] = None,
    show_progress: bool = False,
    description: str = "Processing"
) -> List[Any]:
    """
    Track completion of async futures with progress updates.
    
    Args:
        futures: List of futures to track
        progress_function: Optional progress callback
        show_progress: Whether to show progress bar
        description: Description for progress bar
        
    Returns:
        List of results from completed futures
    """
    results = []
    
    with ProgressTracker(
        total=len(futures), 
        progress_function=progress_function,
        show_progress=show_progress,
        description=description
    ) as tracker:
        for fut in asyncio.as_completed(futures):
            result = await fut
            results.append(result)
            await tracker.update()
    
    return results


async def track_iteration(
    items: List[Any],
    process_func: Callable,
    progress_function: Optional[Callable[[int], None]] = None,
    show_progress: bool = False,
    description: str = "Processing"
) -> List[Any]:
    """
    Track progress during sequential iteration.
    
    Args:
        items: Items to process
        process_func: Function to apply to each item
        progress_function: Optional progress callback
        show_progress: Whether to show progress bar
        description: Description for progress bar
        
    Returns:
        List of processed results
    """
    results = []
    
    with ProgressTracker(
        total=len(items),
        progress_function=progress_function, 
        show_progress=show_progress,
        description=description
    ) as tracker:
        for item in items:
            try:
                result = process_func(item)
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing {item}: {e}")
            
            await tracker.update()
    
    return results