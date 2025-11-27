"""
Unit tests for enhanced utilities in dicompare.utils module.
Tests for detect_constant_fields function.
"""

import unittest
import pandas as pd
import numpy as np
import pytest

from dicompare.utils import detect_constant_fields


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

        # Note: Warning logging is tested in test_detect_constant_fields_nonexistent_field_logs_warning
        constant, variable = detect_constant_fields(self.df, fields)

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

    def test_detect_constant_fields_preserves_order(self):
        """Test that detect_constant_fields preserves order in variable list."""
        fields = ['D', 'A', 'E', 'B', 'F']
        constant, variable = detect_constant_fields(self.df, fields)
        
        # Variable fields should maintain the order they appeared in input
        expected_variable = ['D', 'A', 'B']
        self.assertEqual(variable, expected_variable)

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


def test_detect_constant_fields_nonexistent_field_logs_warning(caplog):
    """Test that detect_constant_fields logs warning for nonexistent fields."""
    df = pd.DataFrame({
        'A': [1, 2, 3, 4],
        'E': [100, 100, 100, 100],
    })
    fields = ['A', 'NONEXISTENT', 'E']

    with caplog.at_level('WARNING', logger='dicompare.utils'):
        constant, variable = detect_constant_fields(df, fields)

    # Should log warning for nonexistent field
    assert "Field 'NONEXISTENT' not found in dataframe columns" in caplog.text

    # Should still process existing fields
    assert constant == {'E': 100}
    assert variable == ['A']


if __name__ == '__main__':
    unittest.main()