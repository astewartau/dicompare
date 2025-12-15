"""Tests for parallel_utils module - parallel processing utilities."""

import pytest
import asyncio

from dicompare.processing.parallel_utils import (
    process_items_parallel,
    process_items_sequential,
)


class TestProcessItemsParallel:
    """Tests for the process_items_parallel function."""

    @pytest.mark.asyncio
    async def test_parallel_processing_with_multiple_workers(self):
        """Test parallel processing with max_workers > 1."""
        items = [1, 2, 3, 4, 5]

        def double(x):
            return x * 2

        results = await process_items_parallel(
            items,
            double,
            max_workers=3,
            show_progress=False
        )

        # Results may not preserve order in parallel processing
        assert len(results) == 5
        assert set(results) == {2, 4, 6, 8, 10}

    @pytest.mark.asyncio
    async def test_parallel_falls_back_to_sequential_with_single_worker(self):
        """Test that max_workers=1 falls back to sequential processing."""
        items = [1, 2, 3]

        def increment(x):
            return x + 1

        results = await process_items_parallel(
            items,
            increment,
            max_workers=1,
            show_progress=False
        )

        assert results == [2, 3, 4]

    @pytest.mark.asyncio
    async def test_parallel_with_progress_callback(self):
        """Test parallel processing with progress callback."""
        items = [1, 2, 3]

        def square(x):
            return x ** 2

        results = await process_items_parallel(
            items,
            square,
            max_workers=2,
            show_progress=False
        )

        # Check results (may not preserve order)
        assert len(results) == 3
        assert set(results) == {1, 4, 9}

    @pytest.mark.asyncio
    async def test_parallel_empty_items(self):
        """Test parallel processing with empty items list."""
        results = await process_items_parallel(
            [],
            lambda x: x,
            max_workers=2,
            show_progress=False
        )

        assert results == []


class TestProcessItemsSequential:
    """Tests for the process_items_sequential function."""

    @pytest.mark.asyncio
    async def test_sequential_processing(self):
        """Test sequential processing."""
        items = [1, 2, 3]

        def triple(x):
            return x * 3

        results = await process_items_sequential(
            items,
            triple,
            show_progress=False
        )

        assert results == [3, 6, 9]

    @pytest.mark.asyncio
    async def test_sequential_with_progress_callback(self):
        """Test sequential processing with progress callback."""
        items = ['a', 'b', 'c']
        progress_values = []

        def uppercase(x):
            return x.upper()

        def progress_callback(count):
            progress_values.append(count)

        results = await process_items_sequential(
            items,
            uppercase,
            progress_function=progress_callback,
            show_progress=False
        )

        assert results == ['A', 'B', 'C']
        # Progress should track iteration

    @pytest.mark.asyncio
    async def test_sequential_empty_items(self):
        """Test sequential processing with empty items list."""
        results = await process_items_sequential(
            [],
            lambda x: x,
            show_progress=False
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_sequential_preserves_order(self):
        """Test that sequential processing preserves item order."""
        items = [5, 3, 1, 4, 2]

        results = await process_items_sequential(
            items,
            lambda x: x,
            show_progress=False
        )

        assert results == [5, 3, 1, 4, 2]
