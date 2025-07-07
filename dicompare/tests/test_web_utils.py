"""
Unit tests for dicompare.web_utils module.
"""

import unittest
import pandas as pd
import numpy as np
import json
from unittest.mock import patch, Mock, MagicMock

from dicompare.web_utils import (
    prepare_session_for_web, format_compliance_results_for_web,
    create_field_selection_helper, prepare_schema_generation_data,
    format_validation_error_for_web, convert_pyodide_data, create_download_data
)


class TestWebUtils(unittest.TestCase):
    """Test cases for web utility functions."""
    
    def setUp(self):
        """Set up test data."""
        # Create sample session DataFrame
        self.session_df = pd.DataFrame({
            'Acquisition': ['T1_MPRAGE'] * 3 + ['T2_FLAIR'] * 2,
            'DICOM_Path': [f'/path/{i}.dcm' for i in range(5)],
            'RepetitionTime': [2000, 2000, 2000, 9000, 9000],
            'EchoTime': [0.01, 0.01, 0.01, 0.1, 0.1],
            'FlipAngle': [30, 30, 30, 90, 90],
            'InstanceNumber': [1, 2, 3, 1, 2],
            'SliceThickness': [1.0, 1.0, 1.0, 3.0, 3.0],
            'ImageType': ['ORIGINAL'] * 5,
            'SeriesInstanceUID': ['1.2.3'] * 3 + ['1.2.4'] * 2
        })
        
        # Sample compliance results
        self.compliance_results = {
            'schema acquisition': {
                'T1_MPRAGE': {
                    'compliant': True,
                    'compliance_percentage': 95.0,
                    'message': 'Mostly compliant',
                    'detailed_results': [
                        {
                            'field': 'RepetitionTime',
                            'expected': 2000,
                            'actual': 2000,
                            'compliant': True,
                            'message': 'Match',
                            'difference_score': 0
                        },
                        {
                            'field': 'EchoTime',
                            'expected': 0.01,
                            'actual': 0.01,
                            'compliant': True,
                            'message': 'Match',
                            'difference_score': 0
                        }
                    ]
                },
                'T2_FLAIR': {
                    'compliant': False,
                    'compliance_percentage': 60.0,
                    'message': 'Some fields differ',
                    'detailed_results': [
                        {
                            'field': 'RepetitionTime',
                            'expected': 8000,
                            'actual': 9000,
                            'compliant': False,
                            'message': 'Value differs',
                            'difference_score': 5
                        }
                    ]
                }
            }
        }
    
    def test_prepare_session_for_web_basic(self):
        """Test basic functionality of prepare_session_for_web."""
        result = prepare_session_for_web(self.session_df)
        
        # Check structure
        self.assertIn('session_characteristics', result)
        self.assertIn('preview_data', result)
        self.assertIn('acquisition_summaries', result)
        self.assertEqual(result['status'], 'success')
        
        # Check session characteristics
        char = result['session_characteristics']
        self.assertEqual(char['total_files'], 5)
        self.assertEqual(char['total_acquisitions'], 2)
        self.assertIn('T1_MPRAGE', char['acquisition_names'])
        self.assertIn('T2_FLAIR', char['acquisition_names'])
        self.assertTrue(char['has_pixel_data_paths'])
    
    def test_prepare_session_for_web_preview_limit(self):
        """Test preview data limiting."""
        # Test with limit smaller than data
        result = prepare_session_for_web(self.session_df, max_preview_rows=3)
        
        preview = result['preview_data']
        self.assertEqual(preview['total_rows_shown'], 3)
        self.assertTrue(preview['is_truncated'])
        self.assertEqual(len(preview['data']), 3)
        
        # Test with limit larger than data
        result = prepare_session_for_web(self.session_df, max_preview_rows=10)
        preview = result['preview_data']
        self.assertEqual(preview['total_rows_shown'], 5)
        self.assertFalse(preview['is_truncated'])
    
    def test_prepare_session_for_web_acquisition_summaries(self):
        """Test acquisition summary generation with real function."""
        result = prepare_session_for_web(self.session_df)
        
        # Check acquisition summaries in result
        self.assertGreater(len(result['acquisition_summaries']), 0)
        
        # Verify actual summary structure
        summaries = result['acquisition_summaries']
        t1_summary = next((s for s in summaries if s['acquisition'] == 'T1_MPRAGE'), None)
        self.assertIsNotNone(t1_summary)
        self.assertEqual(t1_summary['file_count'], 3)
        self.assertEqual(t1_summary['display_name'], 'T1 Mprage')
    
    @patch('dicompare.web_utils.logger')
    @patch('dicompare.web_utils.create_acquisition_summary')
    def test_prepare_session_for_web_summary_error_handling(self, mock_summary, mock_logger):
        """Test error handling in acquisition summary generation."""
        # Make summary function raise an exception
        mock_summary.side_effect = Exception("Summary failed")
        
        result = prepare_session_for_web(self.session_df)
        
        # Should handle the error gracefully
        self.assertEqual(result['status'], 'success')
        mock_logger.warning.assert_called()
    
    def test_format_compliance_results_for_web_basic(self):
        """Test basic functionality of format_compliance_results_for_web."""
        result = format_compliance_results_for_web(self.compliance_results)
        
        # Check summary
        summary = result['summary']
        self.assertEqual(summary['total_acquisitions'], 2)
        self.assertEqual(summary['compliant_acquisitions'], 1)
        self.assertEqual(summary['compliance_rate'], 50.0)
        self.assertEqual(summary['status'], 'completed')
        
        # Check acquisition details (now a dictionary keyed by acquisition name)
        details = result['acquisition_details']
        self.assertEqual(len(details), 2)
        
        # Check that both acquisitions are present with correct data
        self.assertIn('T1_MPRAGE', details)
        self.assertIn('T2_FLAIR', details)
        self.assertEqual(details['T1_MPRAGE']['acquisition'], 'T1_MPRAGE')
        self.assertEqual(details['T1_MPRAGE']['compliance_percentage'], 95.0)
        self.assertEqual(details['T2_FLAIR']['acquisition'], 'T2_FLAIR')
        self.assertEqual(details['T2_FLAIR']['compliance_percentage'], 60.0)
    
    def test_format_compliance_results_for_web_detailed_results(self):
        """Test detailed results processing."""
        result = format_compliance_results_for_web(self.compliance_results)
        
        details = result['acquisition_details']
        
        # Check T1_MPRAGE details (now accessed by key)
        t1_details = details['T1_MPRAGE']
        self.assertEqual(t1_details['total_fields_checked'], 2)
        self.assertEqual(t1_details['compliant_fields'], 2)
        self.assertTrue(t1_details['compliant'])
        
        # Check detailed results structure
        detailed = t1_details['detailed_results']
        self.assertEqual(len(detailed), 2)
        self.assertEqual(detailed[0]['field'], 'RepetitionTime')
        self.assertTrue(detailed[0]['compliant'])
    
    def test_format_compliance_results_for_web_empty_results(self):
        """Test with empty compliance results."""
        empty_results = {'schema acquisition': {}}
        result = format_compliance_results_for_web(empty_results)
        
        summary = result['summary']
        self.assertEqual(summary['total_acquisitions'], 0)
        self.assertEqual(summary['compliant_acquisitions'], 0)
        self.assertEqual(summary['compliance_rate'], 0)
        
        self.assertEqual(len(result['acquisition_details']), 0)
    
    def test_create_field_selection_helper_basic(self):
        """Test basic functionality of create_field_selection_helper."""
        result = create_field_selection_helper(self.session_df, 'T1_MPRAGE')
        
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['acquisition'], 'T1_MPRAGE')
        self.assertEqual(result['total_files'], 3)
        
        # Check recommendations structure
        recommended = result['recommended']
        self.assertIn('constant_fields', recommended)
        self.assertIn('series_grouping_fields', recommended)
        self.assertIn('priority_constant', recommended)
        self.assertIn('priority_variable', recommended)
        
        # RepetitionTime should be constant for T1_MPRAGE
        self.assertIn('RepetitionTime', recommended['priority_constant'])
        
        # InstanceNumber should be variable 
        self.assertIn('InstanceNumber', recommended['series_grouping_fields'])
    
    def test_create_field_selection_helper_priority_fields(self):
        """Test priority field handling with custom priority list."""
        priority_fields = ['RepetitionTime', 'EchoTime', 'FlipAngle', 'InstanceNumber']
        result = create_field_selection_helper(
            self.session_df, 'T1_MPRAGE', priority_fields
        )
        
        recommended = result['recommended']
        
        # RepetitionTime should be in priority_constant (it's constant in our test data)
        self.assertIn('RepetitionTime', recommended['priority_constant'])
        
        # InstanceNumber should be in priority_variable (it varies in our test data)
        self.assertIn('InstanceNumber', recommended['priority_variable'])
    
    def test_create_field_selection_helper_error_handling(self):
        """Test error handling in field selection helper."""
        result = create_field_selection_helper(self.session_df, 'NONEXISTENT')
        
        self.assertEqual(result['status'], 'failed')
        self.assertIn('error', result)
        self.assertIn('No data found for acquisition', result['error'])
    
    def test_prepare_schema_generation_data_basic(self):
        """Test basic functionality of prepare_schema_generation_data."""
        result = prepare_schema_generation_data(self.session_df)
        
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['acquisition_count'], 2)
        self.assertEqual(result['total_files'], 5)
        self.assertIn('T1_MPRAGE', result['acquisitions'])
        self.assertIn('T2_FLAIR', result['acquisitions'])
        
        # Should have acquisition analysis
        self.assertIn('acquisition_analysis', result)
        self.assertEqual(len(result['acquisition_analysis']), 2)
        
        # Should have suggested fields (commonly constant across acquisitions)
        self.assertIn('suggested_fields', result)
        suggested = result['suggested_fields']
        # RepetitionTime is constant within each acquisition (though different values)
        # ImageType and SeriesInstanceUID are constant within each acquisition
        self.assertGreater(len(suggested), 0)
    
    def test_format_validation_error_for_web(self):
        """Test formatting of validation errors."""
        error = ValueError("Field 'EchoTime' not found in data")
        result = format_validation_error_for_web(error)
        
        self.assertEqual(result['error_type'], 'ValueError')
        self.assertIn("Field 'EchoTime' not found", result['error_message'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('user_message', result)
        self.assertIn('suggestions', result)
        self.assertIsInstance(result['suggestions'], list)
    
    def test_convert_pyodide_data_basic(self):
        """Test basic Pyodide data conversion."""
        # Test with regular Python objects
        regular_data = {'a': 1, 'b': [2, 3], 'c': {'d': 4}}
        result = convert_pyodide_data(regular_data)
        self.assertEqual(result, regular_data)
        
        # Test with mock JSProxy object
        class MockJSProxy:
            def to_py(self):
                return {'converted': True}
        
        js_data = MockJSProxy()
        result = convert_pyodide_data(js_data)
        self.assertEqual(result, {'converted': True})
    
    def test_convert_pyodide_data_nested(self):
        """Test nested Pyodide data conversion."""
        class MockJSProxy:
            def __init__(self, data):
                self.data = data
            def to_py(self):
                return self.data
        
        # Nested structure with JSProxy objects
        nested_data = {
            'normal': 'value',
            'js_object': MockJSProxy({'inner': 'converted'}),
            'list_with_js': [1, MockJSProxy('converted_item'), 3]
        }
        
        result = convert_pyodide_data(nested_data)
        
        expected = {
            'normal': 'value',
            'js_object': {'inner': 'converted'},
            'list_with_js': [1, 'converted_item', 3]
        }
        self.assertEqual(result, expected)
    
    def test_create_download_data_json(self):
        """Test JSON download data creation."""
        data = {'schema': {'acquisitions': {'T1': {'fields': []}}}}
        result = create_download_data(data, 'my_schema', 'json')
        
        self.assertEqual(result['filename'], 'my_schema.json')
        self.assertEqual(result['mime_type'], 'application/json')
        self.assertEqual(result['status'], 'ready')
        
        # Content should be valid JSON
        content = result['content']
        loaded = json.loads(content)
        self.assertEqual(loaded, data)
        
        # Should have size information
        self.assertIn('size_bytes', result)
        self.assertGreater(result['size_bytes'], 0)
    
    def test_create_download_data_csv(self):
        """Test CSV download data creation."""
        # Tabular data
        data = [
            {'field': 'RepetitionTime', 'value': 2000},
            {'field': 'EchoTime', 'value': 0.01}
        ]
        result = create_download_data(data, 'results', 'csv')
        
        self.assertEqual(result['filename'], 'results.csv')
        self.assertEqual(result['mime_type'], 'text/csv')
        
        # Content should be CSV format
        content = result['content']
        self.assertIn('field,value', content)
        self.assertIn('RepetitionTime,2000', content)
    
    def test_create_download_data_csv_non_tabular(self):
        """Test CSV creation with non-tabular data."""
        data = {'not': 'tabular'}
        result = create_download_data(data, 'test', 'csv')
        
        self.assertEqual(result['content'], 'No tabular data available')
    
    def test_create_download_data_default_format(self):
        """Test default format handling."""
        data = {'test': 'data'}
        result = create_download_data(data, 'test', 'unknown_format')
        
        # Should default to JSON
        self.assertEqual(result['filename'], 'test.json')
        self.assertEqual(result['mime_type'], 'application/json')
        
        # Content should be valid JSON
        loaded = json.loads(result['content'])
        self.assertEqual(loaded, data)
    
    def test_create_download_data_with_numpy_data(self):
        """Test download data creation with numpy arrays."""
        data = {
            'array': np.array([1, 2, 3]),
            'scalar': np.int64(42),
            'nested': {'inner_array': np.array([[1, 2], [3, 4]])}
        }
        
        result = create_download_data(data, 'numpy_test')
        
        # Should handle numpy serialization
        content = result['content']
        loaded = json.loads(content)
        
        self.assertEqual(loaded['array'], [1, 2, 3])
        self.assertEqual(loaded['scalar'], 42)
        self.assertEqual(loaded['nested']['inner_array'], [[1, 2], [3, 4]])
    
    def test_prepare_schema_generation_data_error_handling(self):
        """Test error handling in schema generation data preparation."""
        # Create DataFrame with an acquisition that will cause issues
        problematic_df = pd.DataFrame({
            'Acquisition': ['VALID', 'PROBLEMATIC'],
            'RepetitionTime': [2000, 'invalid_value'],  # Invalid data type
        })
        
        # Function should handle errors gracefully
        result = prepare_schema_generation_data(problematic_df)
        
        # Should complete successfully despite potential issues
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['acquisition_count'], 2)
        
        # May have partial analysis depending on which acquisitions succeed
        self.assertIn('acquisition_analysis', result)
    
    def test_edge_cases_empty_dataframe(self):
        """Test edge cases with empty DataFrame."""
        empty_df = pd.DataFrame()
        
        # prepare_session_for_web should handle empty data
        result = prepare_session_for_web(empty_df)
        char = result['session_characteristics']
        self.assertEqual(char['total_files'], 0)
        self.assertEqual(char['total_acquisitions'], 0)
    
    def test_json_serialization_integration(self):
        """Test that all web utils properly handle JSON serialization."""
        # Test data with various numpy/pandas types
        complex_df = self.session_df.copy()
        complex_df['numpy_field'] = np.array([1.1, 2.2, 3.3, 4.4, 5.5])
        complex_df['nan_field'] = [1, np.nan, 3, np.nan, 5]
        
        result = prepare_session_for_web(complex_df)
        
        # Should be JSON serializable
        json_str = json.dumps(result)
        loaded = json.loads(json_str)
        
        # Basic structure should be preserved
        self.assertIn('session_characteristics', loaded)
        self.assertIn('preview_data', loaded)


if __name__ == '__main__':
    unittest.main()