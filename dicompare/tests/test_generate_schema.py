"""
Tests for generate_schema module.
"""

import pytest
import pandas as pd
from dicompare.generate_schema import create_json_schema


class TestCreateJsonSchema:
    """Test the create_json_schema function."""

    def test_create_json_schema_basic(self):
        """Test basic schema generation with constant and varying fields."""
        # Create test DataFrame
        df = pd.DataFrame({
            'Acquisition': ['BOLD', 'BOLD', 'T1', 'T1'],
            'RepetitionTime': [2000, 2000, 1000, 1000],
            'EchoTime': [30, 35, 5, 5],
            'FlipAngle': [90, 90, 8, 12],
            'SeriesDescription': ['func1', 'func2', 'anat1', 'anat2']
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime', 'FlipAngle']
        
        schema = create_json_schema(df, reference_fields)
        
        # Verify basic structure
        assert 'acquisitions' in schema
        assert len(schema['acquisitions']) == 2
        
        # Check BOLD acquisition
        bold_acq = schema['acquisitions']['bold']
        # RepetitionTime and FlipAngle are constant, EchoTime varies
        assert len(bold_acq['fields']) == 2  # RepetitionTime and FlipAngle are constant
        field_names = [field['field'] for field in bold_acq['fields']]
        assert 'RepetitionTime' in field_names
        assert 'FlipAngle' in field_names
        
        # Check that EchoTime varies, so it's in series
        assert len(bold_acq['series']) == 2
        series_fields = [field['field'] for series in bold_acq['series'] for field in series['fields']]
        assert 'EchoTime' in series_fields
        
        # Check T1 acquisition
        t1_acq = schema['acquisitions']['t1']
        assert len(t1_acq['fields']) == 2  # RepetitionTime and EchoTime are constant
        field_names = [field['field'] for field in t1_acq['fields']]
        assert 'RepetitionTime' in field_names
        assert 'EchoTime' in field_names
        
        # FlipAngle varies, so it's in series
        assert len(t1_acq['series']) == 2

    def test_create_json_schema_all_constant_fields(self):
        """Test schema generation when all reference fields are constant within acquisitions."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD', 'BOLD', 'T1', 'T1'],
            'RepetitionTime': [2000, 2000, 1000, 1000],
            'EchoTime': [30, 30, 5, 5],
            'FlipAngle': [90, 90, 8, 8]
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime', 'FlipAngle']
        
        schema = create_json_schema(df, reference_fields)
        
        # All fields should be at acquisition level
        bold_acq = schema['acquisitions']['bold']
        assert len(bold_acq['fields']) == 3
        assert len(bold_acq['series']) == 0
        
        t1_acq = schema['acquisitions']['t1']
        assert len(t1_acq['fields']) == 3
        assert len(t1_acq['series']) == 0

    def test_create_json_schema_all_varying_fields(self):
        """Test schema generation when all reference fields vary within acquisitions."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD', 'BOLD'],
            'RepetitionTime': [2000, 2500],
            'EchoTime': [30, 35],
            'FlipAngle': [90, 85]
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime', 'FlipAngle']
        
        schema = create_json_schema(df, reference_fields)
        
        # All fields should be at series level
        bold_acq = schema['acquisitions']['bold']
        assert len(bold_acq['fields']) == 0
        assert len(bold_acq['series']) == 2
        
        # Each series should have all 3 varying fields
        for series in bold_acq['series']:
            assert len(series['fields']) == 3

    def test_create_json_schema_single_acquisition(self):
        """Test schema generation with a single acquisition."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD', 'BOLD'],
            'RepetitionTime': [2000, 2000],
            'EchoTime': [30, 35]
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime']
        
        schema = create_json_schema(df, reference_fields)
        
        assert len(schema['acquisitions']) == 1
        bold_acq = schema['acquisitions']['bold']
        assert len(bold_acq['fields']) == 1  # RepetitionTime constant
        assert bold_acq['fields'][0]['field'] == 'RepetitionTime'
        assert len(bold_acq['series']) == 2  # EchoTime varies

    def test_create_json_schema_with_missing_acquisition_column(self):
        """Test schema generation when Acquisition column is missing (should be added)."""
        df = pd.DataFrame({
            'ProtocolName': ['BOLD', 'BOLD', 'T1'],
            'SeriesDescription': ['func1', 'func2', 'anat'],
            'SeriesInstanceUID': ['1.2.3.4.1', '1.2.3.4.2', '1.2.3.4.3'],
            'RepetitionTime': [2000, 2000, 1000],
            'EchoTime': [30, 35, 5]
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime']
        
        # Should not raise an error - acquisition assignment should be handled
        schema = create_json_schema(df, reference_fields)
        
        assert 'acquisitions' in schema
        # The exact number depends on acquisition assignment logic

    def test_create_json_schema_empty_dataframe(self):
        """Test error handling for empty DataFrame."""
        df = pd.DataFrame()
        reference_fields = ['RepetitionTime']
        
        with pytest.raises(ValueError, match="Session DataFrame cannot be empty"):
            create_json_schema(df, reference_fields)

    def test_create_json_schema_empty_reference_fields(self):
        """Test error handling for empty reference fields."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD'],
            'RepetitionTime': [2000]
        })
        reference_fields = []
        
        with pytest.raises(ValueError, match="Reference fields list cannot be empty"):
            create_json_schema(df, reference_fields)

    def test_create_json_schema_series_naming(self):
        """Test that series are named correctly."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD', 'BOLD', 'BOLD'],
            'RepetitionTime': [2000, 2000, 2000],
            'EchoTime': [30, 35, 40]
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime']
        
        schema = create_json_schema(df, reference_fields)
        
        bold_acq = schema['acquisitions']['bold']
        series_names = [series['name'] for series in bold_acq['series']]
        
        assert 'Series 1' in series_names
        assert 'Series 2' in series_names
        assert 'Series 3' in series_names

    def test_create_json_schema_with_nan_values(self):
        """Test schema generation with NaN values."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD', 'BOLD', 'BOLD'],
            'RepetitionTime': [2000, 2000, 2000],
            'EchoTime': [30, None, 35]  # NaN value
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime']
        
        # Should handle NaN values gracefully
        schema = create_json_schema(df, reference_fields)
        
        assert 'acquisitions' in schema
        bold_acq = schema['acquisitions']['bold']
        
        # RepetitionTime should be constant
        assert len(bold_acq['fields']) == 1
        assert bold_acq['fields'][0]['field'] == 'RepetitionTime'
        
        # EchoTime varies (including NaN), so should be in series
        assert len(bold_acq['series']) > 0

    def test_create_json_schema_complex_acquisition_names(self):
        """Test schema generation with complex acquisition names that need cleaning."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD_task-rest', 'BOLD_task-rest', 'T1w_MPRAGE'],
            'RepetitionTime': [2000, 2000, 1000],
            'EchoTime': [30, 35, 5]
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime']
        
        schema = create_json_schema(df, reference_fields)
        
        # Check that acquisition names are cleaned
        acq_names = list(schema['acquisitions'].keys())
        
        # Should have cleaned names (clean_string removes some special characters)
        for name in acq_names:
            assert '_' not in name  # clean_string should remove underscores
            # Note: hyphens are not in the forbidden_chars list, so they remain
            assert name.islower()  # Should be lowercase

    def test_create_json_schema_preserves_dataframe(self):
        """Test that the original DataFrame is not modified."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD', 'BOLD'],
            'RepetitionTime': [2000, 2000],
            'EchoTime': [30, 35]
        })
        
        original_df = df.copy()
        reference_fields = ['RepetitionTime', 'EchoTime']
        
        create_json_schema(df, reference_fields)
        
        # Original DataFrame should be unchanged
        pd.testing.assert_frame_equal(df, original_df)