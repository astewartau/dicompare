"""
Unit tests for enhanced utilities in dicompare.utils module.
Tests for filter_available_fields and detect_constant_fields functions.
"""

import unittest
import pandas as pd
import numpy as np
from unittest.mock import patch, Mock
import logging

from dicompare.utils import filter_available_fields, detect_constant_fields


class TestUtilsEnhanced(unittest.TestCase):
    """Test cases for enhanced utility functions."""
    
    def setUp(self):
        """Set up test data."""
        # Create a sample DataFrame for testing
        self.df = pd.DataFrame({
            'A': [1, 2, 3, 4],
            'B': [10, 20, 30, 40],
            'C': ['x', 'y', 'z', 'w'],
            'D': [1.1, 2.2, 3.3, 4.4],
            'E': [100, 100, 100, 100],  # Constant field
            'F': ['same', 'same', 'same', 'same'],  # Constant string field
            'G': [1, 2, np.nan, 4],  # Field with NaN
            'H': [np.nan, np.nan, np.nan, np.nan]  # All NaN field
        })
    
    def test_filter_available_fields_basic(self):
        """Test basic functionality of filter_available_fields."""
        # All requested fields exist
        requested = ['A', 'B', 'C']
        result = filter_available_fields(self.df, requested)
        self.assertEqual(result, ['A', 'B', 'C'])
    
    def test_filter_available_fields_partial_match(self):
        """Test when only some requested fields exist."""
        # Some fields exist, some don't
        requested = ['A', 'X', 'B', 'Y']
        result = filter_available_fields(self.df, requested)
        self.assertEqual(result, ['A', 'B'])
    
    def test_filter_available_fields_no_match(self):
        """Test when no requested fields exist."""
        requested = ['X', 'Y', 'Z']
        with self.assertRaises(ValueError) as cm:
            filter_available_fields(self.df, requested)
        
        error_msg = str(cm.exception)
        self.assertIn("No suitable fields found", error_msg)
        self.assertIn("Requested: ['X', 'Y', 'Z']", error_msg)
    
    def test_filter_available_fields_with_fallback(self):
        """Test filter_available_fields with fallback fields."""
        # No requested fields exist, but fallback fields do
        requested = ['X', 'Y', 'Z']
        fallback = ['A', 'B']
        result = filter_available_fields(self.df, requested, fallback)
        self.assertEqual(result, ['A', 'B'])
    
    def test_filter_available_fields_partial_fallback(self):
        """Test with partial fallback match."""
        requested = ['X', 'Y']
        fallback = ['A', 'X', 'B', 'Z']
        result = filter_available_fields(self.df, requested, fallback)
        self.assertEqual(result, ['A', 'B'])
    
    def test_filter_available_fields_no_fallback_match(self):
        """Test when neither requested nor fallback fields exist."""
        requested = ['X', 'Y']
        fallback = ['Z', 'W']
        
        with self.assertRaises(ValueError) as cm:
            filter_available_fields(self.df, requested, fallback)
        
        error_msg = str(cm.exception)
        self.assertIn("No suitable fields found", error_msg)
        self.assertIn("Fallback: ['Z', 'W']", error_msg)
    
    def test_filter_available_fields_empty_dataframe(self):
        """Test with empty DataFrame."""
        empty_df = pd.DataFrame()
        requested = ['A', 'B']
        
        with self.assertRaises(ValueError):
            filter_available_fields(empty_df, requested)
    
    def test_filter_available_fields_empty_requests(self):
        """Test with empty requested fields list."""
        requested = []
        fallback = ['A', 'B']
        result = filter_available_fields(self.df, requested, fallback)
        self.assertEqual(result, ['A', 'B'])
    
    def test_detect_constant_fields_basic(self):
        """Test basic functionality of detect_constant_fields."""
        fields = ['A', 'B', 'E', 'F']
        constant, variable = detect_constant_fields(self.df, fields)
        
        # E and F should be constant
        self.assertEqual(constant, {'E': 100, 'F': 'same'})
        self.assertEqual(set(variable), {'A', 'B'})
    
    def test_detect_constant_fields_with_nan(self):
        """Test detect_constant_fields with NaN values."""
        fields = ['G', 'H']
        constant, variable = detect_constant_fields(self.df, fields)
        
        # G has multiple values (ignoring NaN), so it's variable
        # H has all NaN, so it's constant with None value
        self.assertEqual(constant, {'H': None})
        self.assertEqual(variable, ['G'])
    
    def test_detect_constant_fields_all_constant(self):
        """Test when all fields are constant."""
        fields = ['E', 'F']
        constant, variable = detect_constant_fields(self.df, fields)
        
        self.assertEqual(constant, {'E': 100, 'F': 'same'})
        self.assertEqual(variable, [])
    
    def test_detect_constant_fields_all_variable(self):
        """Test when all fields are variable."""
        fields = ['A', 'B', 'C']
        constant, variable = detect_constant_fields(self.df, fields)
        
        self.assertEqual(constant, {})
        self.assertEqual(set(variable), {'A', 'B', 'C'})
    
    def test_detect_constant_fields_nonexistent_field(self):
        """Test with fields that don't exist in DataFrame."""
        fields = ['A', 'NONEXISTENT', 'E']
        
        with patch('dicompare.utils.logger') as mock_logger:
            constant, variable = detect_constant_fields(self.df, fields)
            
            # Should log warning for nonexistent field
            mock_logger.warning.assert_called_once_with(
                "Field 'NONEXISTENT' not found in dataframe columns"
            )
            
            # Should still process existing fields
            self.assertEqual(constant, {'E': 100})
            self.assertEqual(variable, ['A'])
    
    def test_detect_constant_fields_empty_fields_list(self):
        """Test with empty fields list."""
        fields = []
        constant, variable = detect_constant_fields(self.df, fields)
        
        self.assertEqual(constant, {})
        self.assertEqual(variable, [])
    
    def test_detect_constant_fields_single_value(self):
        """Test with DataFrame containing single row."""
        single_row_df = pd.DataFrame({
            'A': [42],
            'B': ['test'],
            'C': [np.nan]
        })
        
        fields = ['A', 'B', 'C']
        constant, variable = detect_constant_fields(single_row_df, fields)
        
        # All should be constant in single-row DataFrame
        self.assertEqual(constant, {'A': 42, 'B': 'test', 'C': None})
        self.assertEqual(variable, [])
    
    def test_detect_constant_fields_mixed_types(self):
        """Test with mixed data types."""
        mixed_df = pd.DataFrame({
            'int_constant': [5, 5, 5],
            'float_constant': [3.14, 3.14, 3.14],
            'str_constant': ['hello', 'hello', 'hello'],
            'bool_constant': [True, True, True],
            'int_variable': [1, 2, 3],
            'float_variable': [1.1, 2.2, 3.3],
            'str_variable': ['a', 'b', 'c'],
            'bool_variable': [True, False, True]
        })
        
        fields = list(mixed_df.columns)
        constant, variable = detect_constant_fields(mixed_df, fields)
        
        expected_constant = {
            'int_constant': 5,
            'float_constant': 3.14,
            'str_constant': 'hello',
            'bool_constant': True
        }
        expected_variable = ['int_variable', 'float_variable', 'str_variable', 'bool_variable']
        
        self.assertEqual(constant, expected_constant)
        self.assertEqual(set(variable), set(expected_variable))
    
    def test_detect_constant_fields_edge_cases(self):
        """Test edge cases for detect_constant_fields."""
        edge_df = pd.DataFrame({
            'zeros': [0, 0, 0],
            'empty_strings': ['', '', ''],
            'mixed_empty': ['', np.nan, ''],
            'single_non_null': [np.nan, 42, np.nan]
        })
        
        fields = list(edge_df.columns)
        constant, variable = detect_constant_fields(edge_df, fields)
        
        # zeros and empty_strings should be constant
        # mixed_empty should be constant (empty string)
        # single_non_null should be constant (42)
        expected_constant = {
            'zeros': 0,
            'empty_strings': '',
            'mixed_empty': '',
            'single_non_null': 42
        }
        
        self.assertEqual(constant, expected_constant)
        self.assertEqual(variable, [])
    
    def test_filter_available_fields_preserves_order(self):
        """Test that filter_available_fields preserves the order of requested fields."""
        requested = ['C', 'A', 'B', 'D']
        result = filter_available_fields(self.df, requested)
        self.assertEqual(result, ['C', 'A', 'B', 'D'])
    
    def test_detect_constant_fields_preserves_order(self):
        """Test that detect_constant_fields preserves order in variable list."""
        fields = ['D', 'A', 'E', 'B', 'F']
        constant, variable = detect_constant_fields(self.df, fields)
        
        # Variable fields should maintain the order they appeared in input
        expected_variable = ['D', 'A', 'B']
        self.assertEqual(variable, expected_variable)
    
    def test_filter_available_fields_real_world_scenario(self):
        """Test with realistic DICOM field names."""
        dicom_df = pd.DataFrame({
            'RepetitionTime': [2000, 2000, 2000],
            'EchoTime': [0.01, 0.02, 0.03],
            'FlipAngle': [30, 30, 30],
            'SliceThickness': [1.0, 1.0, 1.0],
            'AcquisitionMatrix': ['256\\256', '256\\256', '256\\256'],
            'PixelSpacing': ['1.0\\1.0', '1.0\\1.0', '1.0\\1.0'],
            'MagneticFieldStrength': [3.0, 3.0, 3.0]
        })
        
        # Request priority fields that exist
        priority_fields = [
            'RepetitionTime', 'EchoTime', 'FlipAngle', 'SliceThickness',
            'FieldOfView', 'BandwidthPerPixel'  # These don't exist
        ]
        
        fallback_fields = ['AcquisitionMatrix', 'PixelSpacing', 'MagneticFieldStrength']
        
        result = filter_available_fields(dicom_df, priority_fields, fallback_fields)
        expected = ['RepetitionTime', 'EchoTime', 'FlipAngle', 'SliceThickness']
        self.assertEqual(result, expected)
    
    def test_detect_constant_fields_real_world_scenario(self):
        """Test detect_constant_fields with realistic DICOM data."""
        dicom_df = pd.DataFrame({
            'RepetitionTime': [2000, 2000, 2000],  # Constant
            'EchoTime': [0.01, 0.02, 0.03],       # Variable
            'FlipAngle': [30, 30, 30],             # Constant
            'InstanceNumber': [1, 2, 3],           # Variable
            'SliceThickness': [1.0, 1.0, 1.0],    # Constant
            'AcquisitionNumber': [1, 1, 1]         # Constant
        })
        
        fields = list(dicom_df.columns)
        constant, variable = detect_constant_fields(dicom_df, fields)
        
        expected_constant = {
            'RepetitionTime': 2000,
            'FlipAngle': 30,
            'SliceThickness': 1.0,
            'AcquisitionNumber': 1
        }
        expected_variable = ['EchoTime', 'InstanceNumber']
        
        self.assertEqual(constant, expected_constant)
        self.assertEqual(set(variable), set(expected_variable))


if __name__ == '__main__':
    unittest.main()