"""
Unit tests for dicompare.visualization module.
"""

import unittest
import pandas as pd
import numpy as np
import tempfile
import shutil
from pathlib import Path

from dicompare.visualization import (
    extract_center_slice_data, prepare_slice_for_canvas,
    get_acquisition_preview_data, analyze_image_characteristics
)
from .test_dicom_factory import TestDicomFactory


class TestVisualization(unittest.TestCase):
    """Test cases for DICOM visualization functions."""
    
    def setUp(self):
        """Set up test data with real DICOM files."""
        # Create test DICOM factory
        self.dicom_factory = TestDicomFactory()
        
        # Create real DICOM files
        self.t1_paths, self.t1_bytes = self.dicom_factory.create_t1_mprage(num_slices=4)
        self.t2_paths, self.t2_bytes = self.dicom_factory.create_t2_flair(num_slices=3)
        
        # Combine all files
        all_paths = self.t1_paths + self.t2_paths
        self.dicom_files = {**self.t1_bytes, **self.t2_bytes}
        
        # Create session DataFrame with real paths
        session_data = []
        
        # Add T1 data
        for i, path in enumerate(self.t1_paths):
            session_data.append({
                'Acquisition': 'T1_MPRAGE',
                'DICOM_Path': path,
                'InstanceNumber': i + 1,
                'EchoTime': 2.46,
                'ImageType': 'ORIGINAL',
                'SeriesInstanceUID': '1.2.3.1',
                'Rows': 64,
                'Columns': 64,
                'SliceThickness': 1.0,
                'PixelSpacing': '0.9\\0.9'
            })
        
        # Add T2 data
        for i, path in enumerate(self.t2_paths):
            session_data.append({
                'Acquisition': 'T2_FLAIR',
                'DICOM_Path': path,
                'InstanceNumber': i + 1,
                'EchoTime': 85.0,
                'ImageType': 'ORIGINAL',
                'SeriesInstanceUID': '1.2.3.2',
                'Rows': 64,
                'Columns': 64,
                'SliceThickness': 3.0,
                'PixelSpacing': '0.7\\0.7'
            })
        
        self.session_df = pd.DataFrame(session_data)
    
    def tearDown(self):
        """Clean up test files."""
        self.dicom_factory.cleanup()
    
    def test_analyze_image_characteristics_basic(self):
        """Test basic functionality of analyze_image_characteristics."""
        result = analyze_image_characteristics(self.session_df, 'T1_MPRAGE')
        
        # Basic info
        self.assertEqual(result['acquisition'], 'T1_MPRAGE')
        self.assertEqual(result['total_files'], 4)
        
        # Matrix size
        self.assertEqual(result['matrix_size'], [64, 64])
        
        # Slice thickness
        self.assertEqual(result['slice_thickness'], 1.0)
        
        # Pixel spacing
        self.assertEqual(result['pixel_spacing'], [0.9, 0.9])
        
        # Series info
        self.assertFalse(result['has_multiple_series'])  # All have same EchoTime/ImageType
        self.assertEqual(len(result['series_info']), 0)
    
    def test_analyze_image_characteristics_multiple_series(self):
        """Test with acquisition that has multiple series."""
        # Create multi-echo BOLD data
        bold_paths, bold_bytes = self.dicom_factory.create_bold_fmri(num_echo_times=2)
        
        # Create DataFrame for multi-echo data
        session_data = []
        echo_times = [0.03, 0.06]
        series_uids = ['1.2.4.1', '1.2.4.2']
        
        for i, path in enumerate(bold_paths):
            echo_idx = i // 2  # 2 slices per echo
            session_data.append({
                'Acquisition': 'BOLD_fMRI',
                'DICOM_Path': path,
                'EchoTime': echo_times[echo_idx],
                'ImageType': 'ORIGINAL',
                'SeriesInstanceUID': series_uids[echo_idx],
                'Rows': 64,
                'Columns': 64,
                'SliceThickness': 2.0
            })
        
        multi_series_df = pd.DataFrame(session_data)
        
        result = analyze_image_characteristics(multi_series_df, 'BOLD_fMRI')
        
        self.assertTrue(result['has_multiple_series'])
        self.assertGreater(len(result['series_info']), 0)
        
        # Should identify EchoTime as varying field
        series_info = result['series_info'][0]
        self.assertEqual(series_info['varying_field'], 'EchoTime')
        self.assertEqual(series_info['unique_values'], 2)
    
    def test_analyze_image_characteristics_missing_fields(self):
        """Test with DataFrame missing some fields."""
        minimal_df = pd.DataFrame({
            'Acquisition': ['TEST'] * 2,
            'DICOM_Path': ['/a.dcm', '/b.dcm']
            # Missing Rows, Columns, SliceThickness, etc.
        })
        
        result = analyze_image_characteristics(minimal_df, 'TEST')
        
        self.assertEqual(result['acquisition'], 'TEST')
        self.assertEqual(result['total_files'], 2)
        self.assertIsNone(result['matrix_size'])
        self.assertIsNone(result['slice_thickness'])
        self.assertIsNone(result['pixel_spacing'])
    
    def test_analyze_image_characteristics_nonexistent_acquisition(self):
        """Test with acquisition that doesn't exist."""
        with self.assertRaises(ValueError) as cm:
            analyze_image_characteristics(self.session_df, 'NONEXISTENT')
        
        self.assertIn("No data found for acquisition: NONEXISTENT", str(cm.exception))
    
    def test_analyze_image_characteristics_pixel_spacing_formats(self):
        """Test different pixel spacing formats."""
        # Test with different pixel spacing formats
        test_cases = [
            ('1.0\\2.0', [1.0, 2.0]),
            ('0.5\\0.5', [0.5, 0.5]),
            ('invalid_format', None),
            ('1.0', None),  # Missing separator
        ]
        
        for spacing_str, expected in test_cases:
            df = pd.DataFrame({
                'Acquisition': ['TEST'],
                'DICOM_Path': ['/test.dcm'],
                'PixelSpacing': [spacing_str]
            })
            
            result = analyze_image_characteristics(df, 'TEST')
            self.assertEqual(result['pixel_spacing'], expected)
    
    def test_prepare_slice_for_canvas_basic(self):
        """Test basic slice preparation for canvas."""
        # Create test pixel data
        pixel_data = np.array([
            [100, 200, 300],
            [400, 500, 600],
            [700, 800, 900]
        ], dtype=float)
        
        result = prepare_slice_for_canvas(pixel_data)
        
        # Should be normalized to 0-255 range
        self.assertEqual(result.shape, (3, 3))
        self.assertEqual(result.dtype, np.uint8)
        self.assertEqual(result.min(), 0)
        self.assertEqual(result.max(), 255)
        
        # Check specific values (linear mapping from 100-900 to 0-255)
        self.assertEqual(result[0, 0], 0)     # 100 -> 0
        self.assertEqual(result[2, 2], 255)   # 900 -> 255
    
    def test_prepare_slice_for_canvas_with_windowing(self):
        """Test slice preparation with windowing."""
        pixel_data = np.array([
            [0, 100, 200],
            [300, 400, 500],
            [600, 700, 800]
        ], dtype=float)
        
        # Apply windowing (center=400, width=200)
        # Window range: 300-500
        result = prepare_slice_for_canvas(pixel_data, window_center=400, window_width=200)
        
        # Values below 300 should be clipped to 0
        # Values above 500 should be clipped to 255
        # 300-500 should be mapped to 0-255
        
        self.assertEqual(result[0, 0], 0)     # 0 clipped to 300, then mapped to 0
        self.assertEqual(result[1, 1], 127)   # 400 is center, maps to middle
        self.assertEqual(result[2, 2], 255)   # 800 clipped to 500, then mapped to 255
    
    def test_prepare_slice_for_canvas_uniform_data(self):
        """Test with uniform pixel data (all same value)."""
        pixel_data = np.full((3, 3), 500.0)
        result = prepare_slice_for_canvas(pixel_data)
        
        # All values should be 0 when data is uniform
        self.assertTrue(np.all(result == 0))
    
    def test_prepare_slice_for_canvas_negative_values(self):
        """Test with negative pixel values."""
        pixel_data = np.array([
            [-100, 0, 100],
            [200, 300, 400]
        ], dtype=float)
        
        result = prepare_slice_for_canvas(pixel_data)
        
        # Should handle negative values correctly
        self.assertEqual(result.shape, (2, 3))
        self.assertEqual(result.min(), 0)
        self.assertEqual(result.max(), 255)
    
    def test_extract_center_slice_data_basic(self):
        """Test basic DICOM pixel data extraction with real files."""
        result = extract_center_slice_data(self.session_df, 'T1_MPRAGE', self.dicom_files)
        
        # Should return data structure
        self.assertIn('series', result)
        self.assertEqual(len(result['series']), 1)
        
        series = result['series'][0]
        self.assertEqual(series['name'], 'T1_MPRAGE')
        self.assertEqual(series['width'], 64)  # Our test DICOMs are 64x64
        self.assertEqual(series['height'], 64)
        self.assertEqual(series['sliceCount'], 1)  # Only center slice
        self.assertEqual(series['total_slices'], 4)  # Total slices in acquisition
        
        # Check that we have valid pixel data
        self.assertIsInstance(series['slices'], list)
        self.assertEqual(len(series['slices']), 1)
        self.assertIsInstance(series['slices'][0], list)
        self.assertEqual(len(series['slices'][0]), 64)  # Height
        self.assertEqual(len(series['slices'][0][0]), 64)  # Width
    
    def test_extract_center_slice_data_multiple_series(self):
        """Test extraction with multiple series using real DICOM files."""
        # Create multi-echo BOLD data
        bold_paths, bold_bytes = self.dicom_factory.create_bold_fmri(num_echo_times=2)
        
        # Create DataFrame for multi-echo data
        session_data = []
        echo_times = [0.03, 0.06]
        
        for i, path in enumerate(bold_paths):
            echo_idx = i // 2  # 2 slices per echo
            session_data.append({
                'Acquisition': 'BOLD_fMRI',
                'DICOM_Path': path,
                'EchoTime': echo_times[echo_idx],
                'InstanceNumber': (i % 2) + 1
            })
        
        multi_df = pd.DataFrame(session_data)
        
        result = extract_center_slice_data(multi_df, 'BOLD_fMRI', bold_bytes)
        
        # Should have 2 series (two different echo times)
        self.assertEqual(len(result['series']), 2)
        
        # Series names should include EchoTime
        series_names = [s['name'] for s in result['series']]
        self.assertTrue(any('EchoTime' in name for name in series_names))
    
    def test_extract_center_slice_data_no_pixel_data(self):
        """Test when DICOM files have no pixel data."""
        # Create DICOM file without pixel data
        import tempfile
        from .test_dicom_factory import create_test_dicom_file
        import pydicom
        
        # Create a DICOM file, then remove pixel data
        temp_path = tempfile.mktemp(suffix='.dcm')
        create_test_dicom_file(temp_path)
        
        # Read it back and remove pixel data
        ds = pydicom.dcmread(temp_path)
        del ds.PixelData
        ds.save_as(temp_path)
        
        # Read as bytes
        with open(temp_path, 'rb') as f:
            no_pixel_bytes = {temp_path: f.read()}
        
        # Create minimal session df
        no_pixel_df = pd.DataFrame({
            'Acquisition': ['TEST'],
            'DICOM_Path': [temp_path],
            'InstanceNumber': [1]
        })
        
        try:
            with self.assertRaises(ValueError) as cm:
                extract_center_slice_data(no_pixel_df, 'TEST', no_pixel_bytes)
            
            self.assertIn("Could not extract pixel data", str(cm.exception))
        finally:
            # Cleanup
            Path(temp_path).unlink(missing_ok=True)
    
    def test_extract_center_slice_data_missing_pydicom(self):
        """Test behavior when pydicom is not available."""
        from unittest.mock import patch
        with patch.dict('sys.modules', {'pydicom': None}):
            with self.assertRaises(ImportError) as cm:
                extract_center_slice_data(self.session_df, 'T1_MPRAGE', self.dicom_files)
            
            self.assertIn("pydicom is required", str(cm.exception))
    
    def test_extract_center_slice_data_nonexistent_acquisition(self):
        """Test with acquisition that doesn't exist."""
        with self.assertRaises(ValueError):
            extract_center_slice_data(self.session_df, 'NONEXISTENT', self.dicom_files)
    
    def test_extract_center_slice_data_missing_files(self):
        """Test when DICOM files are missing from dictionary."""
        # Use only a subset of actual files
        incomplete_files = {self.t1_paths[0]: self.t1_bytes[self.t1_paths[0]]}  # Only one file
        
        # Should handle missing files gracefully but may fail if no valid files
        with self.assertRaises(ValueError) as cm:
            extract_center_slice_data(self.session_df, 'T1_MPRAGE', incomplete_files)
        
        self.assertIn("Could not extract pixel data", str(cm.exception))
    
    def test_get_acquisition_preview_data_success(self):
        """Test successful preview data generation with real data."""
        result = get_acquisition_preview_data(self.session_df, 'T1_MPRAGE', self.dicom_files)
        
        self.assertTrue(result['available'])
        self.assertEqual(result['acquisition'], 'T1_MPRAGE')
        self.assertEqual(result['series_count'], 1)
        self.assertTrue(result['full_data_available'])
        
        # Check thumbnail info
        thumbnails = result['thumbnails']
        self.assertEqual(len(thumbnails), 1)
        thumb = thumbnails[0]
        self.assertEqual(thumb['name'], 'T1_MPRAGE')
        self.assertEqual(thumb['original_width'], 64)
        self.assertEqual(thumb['original_height'], 64)
        self.assertEqual(thumb['slice_count'], 4)
    
    def test_get_acquisition_preview_data_failure(self):
        """Test preview data generation when extraction fails."""
        # Test with non-existent acquisition to trigger failure
        result = get_acquisition_preview_data(self.session_df, 'NONEXISTENT', self.dicom_files)
        
        self.assertFalse(result['available'])
        self.assertEqual(result['acquisition'], 'NONEXISTENT')
        self.assertIn('error', result)
        self.assertEqual(len(result['thumbnails']), 0)
    
    def test_get_acquisition_preview_data_max_series_limit(self):
        """Test preview data with series limit."""
        # Create multi-echo data which will have multiple series
        bold_paths, bold_bytes = self.dicom_factory.create_bold_fmri(num_echo_times=5)
        
        # Create DataFrame for multi-echo data
        session_data = []
        echo_times = [0.01, 0.02, 0.03, 0.04, 0.05]
        
        for i, path in enumerate(bold_paths):
            echo_idx = i // 2  # 2 slices per echo
            session_data.append({
                'Acquisition': 'BOLD_fMRI',
                'DICOM_Path': path,
                'EchoTime': echo_times[echo_idx],
                'InstanceNumber': (i % 2) + 1
            })
        
        multi_df = pd.DataFrame(session_data)
        
        result = get_acquisition_preview_data(
            multi_df, 'BOLD_fMRI', bold_bytes, max_series=3
        )
        
        # Should limit to 3 series
        self.assertEqual(result['series_count'], 3)
        self.assertEqual(len(result['thumbnails']), 3)
    
    def test_get_acquisition_preview_data_thumbnail_sizing(self):
        """Test thumbnail size calculation."""
        from unittest.mock import patch
        with patch('dicompare.visualization.extract_center_slice_data') as mock_extract:
            # Test different aspect ratios
            test_cases = [
                (256, 256, 64, 64),    # Square -> square thumbnail
                (512, 256, 64, 32),    # Wide -> wide thumbnail
                (256, 512, 32, 64),    # Tall -> tall thumbnail
            ]
            
            for width, height, expected_w, expected_h in test_cases:
                mock_extract.return_value = {
                    'series': [{
                        'name': 'Test',
                        'width': width,
                        'height': height,
                        'min': 0,
                        'max': 1000,
                        'total_slices': 1,
                        'slices': [[[100]]]
                    }]
                }
                
                result = get_acquisition_preview_data(
                    self.session_df, 'T1_MPRAGE', self.dicom_files
                )
                
                thumb = result['thumbnails'][0]
                self.assertEqual(thumb['width'], expected_w)
                self.assertEqual(thumb['height'], expected_h)
    
    def test_edge_cases_empty_dataframe(self):
        """Test with empty DataFrame."""
        empty_df = pd.DataFrame()
        
        with self.assertRaises(KeyError):  # Will raise KeyError for missing 'Acquisition' column
            analyze_image_characteristics(empty_df, 'ANY')
    
    def test_integration_real_world_scenario(self):
        """Test with realistic DICOM session structure."""
        # Create realistic test data
        realistic_df = pd.DataFrame({
            'Acquisition': ['localizer'] * 3 + ['t1_mprage_sag'] * 176 + ['t2_flair_tra'] * 25,
            'DICOM_Path': [f'/study/series_{i//50 + 1}/{i:03d}.dcm' for i in range(204)],
            'SeriesInstanceUID': ['1.2.3.1'] * 3 + ['1.2.3.2'] * 176 + ['1.2.3.3'] * 25,
            'InstanceNumber': list(range(1, 4)) + list(range(1, 177)) + list(range(1, 26)),
            'Rows': [256] * 3 + [256] * 176 + [512] * 25,
            'Columns': [256] * 3 + [256] * 176 + [512] * 25,
            'SliceThickness': [5.0] * 3 + [1.0] * 176 + [3.0] * 25,
            'PixelSpacing': ['1.0\\1.0'] * 3 + ['0.9\\0.9'] * 176 + ['0.5\\0.5'] * 25,
            'EchoTime': [1.23] * 3 + [2.46] * 176 + [85.0] * 25,
            'ImageType': ['ORIGINAL\\PRIMARY\\LOCALIZER'] * 3 + 
                        ['ORIGINAL\\PRIMARY\\M\\ND'] * 176 + 
                        ['ORIGINAL\\PRIMARY\\M\\ND\\NORM'] * 25
        })
        
        # Test analysis for each acquisition type
        for acq in ['localizer', 't1_mprage_sag', 't2_flair_tra']:
            result = analyze_image_characteristics(realistic_df, acq)
            
            self.assertEqual(result['acquisition'], acq)
            self.assertGreater(result['total_files'], 0)
            self.assertIsNotNone(result['matrix_size'])
            self.assertIsNotNone(result['slice_thickness'])
            self.assertIsNotNone(result['pixel_spacing'])


if __name__ == '__main__':
    unittest.main()