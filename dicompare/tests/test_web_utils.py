"""
Test cases for web utility functions.
"""

import unittest
import pandas as pd
import numpy as np
import asyncio
import pytest
from unittest.mock import patch, Mock, MagicMock

from dicompare.interface import (
    analyze_dicom_files_for_web,
)


class TestWebUtils(unittest.TestCase):
    """Test cases for web utility functions."""

    @pytest.mark.asyncio
    async def test_analyze_dicom_files_for_web_basic(self):
        """Test analyze_dicom_files_for_web with valid DICOM data."""
        # Mock the dependencies
        with patch('dicompare.interface.web_utils.async_load_dicom_session') as mock_load, \
             patch('dicompare.interface.web_utils.assign_acquisition_and_run_numbers') as mock_assign, \
             patch('dicompare.interface.web_utils.create_json_schema') as mock_schema, \
             patch('dicompare.interface.web_utils.DEFAULT_DICOM_FIELDS', ['SeriesDescription', 'RepetitionTime']):

            # Setup mocks
            mock_df = pd.DataFrame({
                'SeriesDescription': ['T1_MPRAGE', 'T1_MPRAGE'],
                'RepetitionTime': [2300, 2300],
                'Acquisition': ['T1', 'T1']
            })
            mock_load.return_value = mock_df
            mock_assign.return_value = mock_df
            mock_schema.return_value = {
                'acquisitions': {
                    'T1': {
                        'fields': [{'field': 'RepetitionTime', 'value': 2300}]
                    }
                }
            }

            # Test data
            dicom_files = {
                'file1.dcm': b'mock_dicom_data_1',
                'file2.dcm': b'mock_dicom_data_2'
            }

            # Call function
            result = await analyze_dicom_files_for_web(dicom_files)

            # Verify results
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['total_files'], 2)
            self.assertIn('acquisitions', result)
            self.assertIn('field_summary', result)

    @pytest.mark.asyncio
    async def test_analyze_dicom_files_for_web_default_fields(self):
        """Test analyze_dicom_files_for_web uses default fields when none provided."""
        with patch('dicompare.interface.web_utils.async_load_dicom_session') as mock_load, \
             patch('dicompare.interface.web_utils.assign_acquisition_and_run_numbers') as mock_assign, \
             patch('dicompare.interface.web_utils.create_json_schema') as mock_schema, \
             patch('dicompare.interface.web_utils.DEFAULT_DICOM_FIELDS', ['SeriesDescription']):

            mock_df = pd.DataFrame({
                'SeriesDescription': ['T1_MPRAGE'],
                'Acquisition': ['T1']
            })
            mock_load.return_value = mock_df
            mock_assign.return_value = mock_df
            mock_schema.return_value = {'acquisitions': {}}

            dicom_files = {'file1.dcm': b'mock_data'}

            # Call with None reference_fields
            result = await analyze_dicom_files_for_web(dicom_files, None)

            self.assertEqual(result['status'], 'success')
            # Should have used DEFAULT_DICOM_FIELDS
            mock_schema.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_dicom_files_for_web_empty_files(self):
        """Test analyze_dicom_files_for_web with empty files dict."""
        with patch('dicompare.interface.web_utils.async_load_dicom_session') as mock_load:
            # Make async_load_dicom_session raise ValueError for no data
            mock_load.side_effect = ValueError("No session data found to process.")

            dicom_files = {}

            result = await analyze_dicom_files_for_web(dicom_files)

            self.assertEqual(result['status'], 'error')
            self.assertIn('Error analyzing DICOM files', result['message'])


if __name__ == '__main__':
    unittest.main()