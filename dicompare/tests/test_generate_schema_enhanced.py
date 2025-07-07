"""
Unit tests for enhanced functions in dicompare.generate_schema module.
Tests for detect_acquisition_variability and create_acquisition_summary functions.
"""

import unittest
import pandas as pd
import numpy as np
from unittest.mock import patch, Mock

from dicompare.generate_schema import detect_acquisition_variability, create_acquisition_summary


class TestGenerateSchemaEnhanced(unittest.TestCase):
    """Test cases for enhanced schema generation functions."""
    
    def setUp(self):
        """Set up test data."""
        # Create a comprehensive test DataFrame
        self.session_df = pd.DataFrame({
            'Acquisition': ['T1_MPRAGE', 'T1_MPRAGE', 'T1_MPRAGE', 'T2_FLAIR', 'T2_FLAIR'],
            'DICOM_Path': ['/path/1.dcm', '/path/2.dcm', '/path/3.dcm', '/path/4.dcm', '/path/5.dcm'],
            'RepetitionTime': [2000, 2000, 2000, 9000, 9000],  # Constant within acquisition
            'EchoTime': [0.01, 0.01, 0.01, 0.1, 0.1],          # Constant within acquisition
            'FlipAngle': [30, 30, 30, 90, 90],                 # Constant within acquisition
            'SliceThickness': [1.0, 1.0, 1.0, 3.0, 3.0],      # Constant within acquisition
            'InstanceNumber': [1, 2, 3, 1, 2],                 # Variable within acquisition
            'ImageType': ['ORIGINAL', 'ORIGINAL', 'ORIGINAL', 'DERIVED', 'DERIVED'],  # Constant within acquisition
            'SeriesInstanceUID': ['1.2.3.1', '1.2.3.1', '1.2.3.1', '1.2.3.2', '1.2.3.2'],
            'AcquisitionMatrix': ['256\\256', '256\\256', '256\\256', '128\\128', '128\\128'],
            'PixelSpacing': ['1.0\\1.0', '1.0\\1.0', '1.0\\1.0', '2.0\\2.0', '2.0\\2.0'],
            'StudyDate': ['20230101', '20230101', '20230101', '20230101', '20230101'],
            'PatientName': ['John Doe', 'John Doe', 'John Doe', 'John Doe', 'John Doe'],
            'index': [0, 1, 2, 3, 4]  # System field to be excluded
        })
        
        # DataFrame with varying fields within single acquisition
        self.varying_df = pd.DataFrame({
            'Acquisition': ['BOLD_fMRI', 'BOLD_fMRI', 'BOLD_fMRI', 'BOLD_fMRI'],
            'DICOM_Path': ['/path/a.dcm', '/path/b.dcm', '/path/c.dcm', '/path/d.dcm'],
            'RepetitionTime': [2000, 2000, 2000, 2000],      # Constant
            'EchoTime': [0.03, 0.06, 0.09, 0.12],           # Variable (multi-echo)
            'FlipAngle': [90, 90, 90, 90],                   # Constant
            'ImageType': ['ORIGINAL', 'ORIGINAL', 'DERIVED', 'DERIVED'],  # Variable
            'SeriesInstanceUID': ['1.2.4.1', '1.2.4.1', '1.2.4.2', '1.2.4.2'],  # Variable
            'InstanceNumber': [1, 2, 3, 4],                  # Variable
            'SliceLocation': [10.0, 20.0, 10.0, 20.0]       # Variable
        })
    
    def test_detect_acquisition_variability_basic(self):
        """Test basic functionality of detect_acquisition_variability."""
        result = detect_acquisition_variability(self.session_df, 'T1_MPRAGE')
        
        # Check basic structure
        self.assertEqual(result['acquisition'], 'T1_MPRAGE')
        self.assertEqual(result['total_files'], 3)
        
        # Check constant fields (should include RepetitionTime, EchoTime, etc.)
        constant_fields = result['constant_fields']
        self.assertIn('RepetitionTime', constant_fields)
        self.assertEqual(constant_fields['RepetitionTime'], 2000)
        self.assertIn('EchoTime', constant_fields)
        self.assertEqual(constant_fields['EchoTime'], 0.01)
        
        # Check variable fields (should include InstanceNumber)
        variable_fields = result['variable_fields']
        self.assertIn('InstanceNumber', variable_fields)
        
        # Check field analysis
        self.assertIn('field_analysis', result)
        self.assertIn('RepetitionTime', result['field_analysis'])
        self.assertTrue(result['field_analysis']['RepetitionTime']['is_constant'])
    
    def test_detect_acquisition_variability_with_specified_fields(self):
        """Test with specific fields list."""
        fields = ['RepetitionTime', 'EchoTime', 'InstanceNumber']
        result = detect_acquisition_variability(self.session_df, 'T1_MPRAGE', fields)
        
        # Should only analyze specified fields
        all_analyzed_fields = set(result['constant_fields'].keys()) | set(result['variable_fields'])
        self.assertEqual(all_analyzed_fields, {'RepetitionTime', 'EchoTime', 'InstanceNumber'})
        
        # RepetitionTime and EchoTime should be constant
        self.assertIn('RepetitionTime', result['constant_fields'])
        self.assertIn('EchoTime', result['constant_fields'])
        
        # InstanceNumber should be variable
        self.assertIn('InstanceNumber', result['variable_fields'])
    
    def test_detect_acquisition_variability_nonexistent_acquisition(self):
        """Test with acquisition that doesn't exist."""
        with self.assertRaises(ValueError) as cm:
            detect_acquisition_variability(self.session_df, 'NONEXISTENT')
        
        self.assertIn("No data found for acquisition: NONEXISTENT", str(cm.exception))
    
    def test_detect_acquisition_variability_with_varying_fields(self):
        """Test with acquisition that has varying fields."""
        result = detect_acquisition_variability(self.varying_df, 'BOLD_fMRI')
        
        # Should identify varying fields
        variable_fields = result['variable_fields']
        self.assertIn('EchoTime', variable_fields)
        self.assertIn('ImageType', variable_fields)
        self.assertIn('SeriesInstanceUID', variable_fields)
        
        # Should have suggested series fields
        suggested = result['suggested_series_fields']
        self.assertLessEqual(len(suggested), 3)  # Should limit to 3
        self.assertIn('EchoTime', suggested)  # EchoTime should be prioritized
    
    def test_detect_acquisition_variability_field_analysis(self):
        """Test detailed field analysis."""
        result = detect_acquisition_variability(self.varying_df, 'BOLD_fMRI', 
                                               ['EchoTime', 'RepetitionTime'])
        
        field_analysis = result['field_analysis']
        
        # EchoTime analysis
        echo_analysis = field_analysis['EchoTime']
        self.assertEqual(echo_analysis['unique_count'], 4)
        self.assertEqual(echo_analysis['null_count'], 0)
        self.assertFalse(echo_analysis['is_constant'])
        self.assertEqual(len(echo_analysis['sample_values']), 4)
        
        # RepetitionTime analysis
        tr_analysis = field_analysis['RepetitionTime']
        self.assertEqual(tr_analysis['unique_count'], 1)
        self.assertEqual(tr_analysis['null_count'], 0)
        self.assertTrue(tr_analysis['is_constant'])
        self.assertEqual(tr_analysis['sample_values'], [2000])
    
    def test_detect_acquisition_variability_excludes_system_fields(self):
        """Test that system fields are excluded when fields=None."""
        result = detect_acquisition_variability(self.session_df, 'T1_MPRAGE')
        
        # System fields should be excluded
        all_fields = set(result['constant_fields'].keys()) | set(result['variable_fields'])
        self.assertNotIn('Acquisition', all_fields)
        self.assertNotIn('DICOM_Path', all_fields)
        self.assertNotIn('index', all_fields)
    
    def test_create_acquisition_summary_basic(self):
        """Test basic functionality of create_acquisition_summary."""
        result = create_acquisition_summary(self.session_df, 'T1_MPRAGE')
        
        # Check basic info
        self.assertEqual(result['acquisition'], 'T1_MPRAGE')
        self.assertEqual(result['display_name'], 'T1 Mprage')
        self.assertEqual(result['file_count'], 3)
        
        # Check key parameters
        key_params = result['key_parameters']
        self.assertIn('RepetitionTime', key_params)
        self.assertEqual(key_params['RepetitionTime'], 2000)
        
        # Check field counts
        self.assertGreater(result['constant_field_count'], 0)
        self.assertGreater(result['variable_field_count'], 0)
        
        # Check sample DICOM paths
        self.assertEqual(len(result['sample_dicom_paths']), 3)
        self.assertIn('/path/1.dcm', result['sample_dicom_paths'])
    
    def test_create_acquisition_summary_with_series_suggestion(self):
        """Test series suggestion logic."""
        result = create_acquisition_summary(self.varying_df, 'BOLD_fMRI')
        
        # Should have series suggestion due to varying fields
        series_suggestion = result['series_suggestion']
        self.assertIsNotNone(series_suggestion)
        self.assertIn('field', series_suggestion)
        self.assertIn('series_count', series_suggestion)
        self.assertIn('values', series_suggestion)
        
        # EchoTime should be suggested as primary grouping field
        self.assertEqual(series_suggestion['field'], 'EchoTime')
        self.assertEqual(series_suggestion['series_count'], 4)
    
    def test_create_acquisition_summary_key_parameters(self):
        """Test key parameter extraction for different scenarios."""
        # Test with constant key parameters
        result = create_acquisition_summary(self.session_df, 'T1_MPRAGE')
        key_params = result['key_parameters']
        
        # Should include standard DICOM parameters that are constant
        expected_constant = ['RepetitionTime', 'EchoTime', 'FlipAngle', 'SliceThickness']
        for param in expected_constant:
            if param in key_params:
                self.assertIsInstance(key_params[param], (int, float, np.integer, np.floating))
    
    def test_create_acquisition_summary_variable_key_parameters(self):
        """Test key parameter handling when they vary."""
        result = create_acquisition_summary(self.varying_df, 'BOLD_fMRI')
        key_params = result['key_parameters']
        
        # EchoTime varies, so should show range
        if 'EchoTime' in key_params:
            self.assertIn(' - ', str(key_params['EchoTime']))  # Should be a range string
    
    def test_create_acquisition_summary_display_name_formatting(self):
        """Test display name formatting."""
        # Test various acquisition name formats
        test_cases = [
            ('T1_MPRAGE', 'T1 Mprage'),
            ('t2_flair_sag', 'T2 Flair Sag'),
            ('BOLD_fMRI_task', 'Bold Fmri Task'),
            ('DWI', 'Dwi'),
            ('single_word', 'Single Word')
        ]
        
        for original, expected in test_cases:
            # Create minimal test data
            test_df = pd.DataFrame({
                'Acquisition': [original],
                'DICOM_Path': ['/test.dcm'],
                'RepetitionTime': [1000]
            })
            
            result = create_acquisition_summary(test_df, original)
            self.assertEqual(result['display_name'], expected)
    
    def test_create_acquisition_summary_empty_dicom_paths(self):
        """Test when DICOM_Path column is missing."""
        df_no_paths = self.session_df.drop('DICOM_Path', axis=1)
        result = create_acquisition_summary(df_no_paths, 'T1_MPRAGE')
        
        # Should handle missing DICOM_Path gracefully
        self.assertEqual(result['sample_dicom_paths'], [])
    
    def test_create_acquisition_summary_specified_fields(self):
        """Test with specified fields parameter."""
        fields = ['RepetitionTime', 'EchoTime', 'InstanceNumber']
        result = create_acquisition_summary(self.session_df, 'T1_MPRAGE', fields)
        
        # Variability analysis should only consider specified fields
        variability = result['variability_analysis']
        all_analyzed = set(variability['constant_fields'].keys()) | set(variability['variable_fields'])
        self.assertEqual(all_analyzed, {'RepetitionTime', 'EchoTime', 'InstanceNumber'})
    
    def test_create_acquisition_summary_with_nan_values(self):
        """Test handling of NaN values in the data."""
        # Create data with NaN values
        nan_df = pd.DataFrame({
            'Acquisition': ['TEST', 'TEST', 'TEST'],
            'DICOM_Path': ['/a.dcm', '/b.dcm', '/c.dcm'],
            'RepetitionTime': [2000, 2000, np.nan],
            'EchoTime': [np.nan, np.nan, np.nan],
            'FlipAngle': [30, 45, 60]
        })
        
        result = create_acquisition_summary(nan_df, 'TEST')
        
        # Should handle NaN values appropriately
        self.assertEqual(result['acquisition'], 'TEST')
        self.assertEqual(result['file_count'], 3)
        
        # Key parameters should handle NaN appropriately
        key_params = result['key_parameters']
        # RepetitionTime has 2 non-NaN values that are the same, might be considered constant
        # FlipAngle varies, so should show range
        if 'FlipAngle' in key_params:
            self.assertIn(' - ', str(key_params['FlipAngle']))
    
    def test_create_acquisition_summary_single_file(self):
        """Test with acquisition containing single file."""
        single_df = pd.DataFrame({
            'Acquisition': ['SINGLE'],
            'DICOM_Path': ['/single.dcm'],
            'RepetitionTime': [1500],
            'EchoTime': [0.05],
            'FlipAngle': [25]
        })
        
        result = create_acquisition_summary(single_df, 'SINGLE')
        
        self.assertEqual(result['file_count'], 1)
        self.assertEqual(len(result['sample_dicom_paths']), 1)
        self.assertIsNone(result['series_suggestion'])  # No variability to suggest series
    
    def test_both_functions_integration(self):
        """Test integration between detect_acquisition_variability and create_acquisition_summary."""
        # Both functions should give consistent results
        variability = detect_acquisition_variability(self.varying_df, 'BOLD_fMRI')
        summary = create_acquisition_summary(self.varying_df, 'BOLD_fMRI')
        
        # Summary should include the variability analysis
        self.assertEqual(summary['variability_analysis'], variability)
        
        # Counts should match
        self.assertEqual(summary['constant_field_count'], len(variability['constant_fields']))
        self.assertEqual(summary['variable_field_count'], len(variability['variable_fields']))
        
        # File counts should match
        self.assertEqual(summary['file_count'], variability['total_files'])
    
    def test_error_handling_nonexistent_acquisition(self):
        """Test error handling for nonexistent acquisitions."""
        with self.assertRaises(ValueError):
            detect_acquisition_variability(self.session_df, 'DOES_NOT_EXIST')
        
        with self.assertRaises(ValueError):
            create_acquisition_summary(self.session_df, 'DOES_NOT_EXIST')
    
    def test_edge_case_empty_dataframe(self):
        """Test with empty DataFrame."""
        empty_df = pd.DataFrame(columns=['Acquisition', 'RepetitionTime', 'EchoTime'])
        
        with self.assertRaises(ValueError):
            detect_acquisition_variability(empty_df, 'ANY')
        
        with self.assertRaises(ValueError):
            create_acquisition_summary(empty_df, 'ANY')


if __name__ == '__main__':
    unittest.main()