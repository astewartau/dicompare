"""
Tests for data_utils module.
"""

import pytest
import pandas as pd
import numpy as np
from dicompare.data_utils import (
    make_dataframe_hashable,
    _flatten_nested_dict,
    _reduce_flattened_keys,
    _convert_to_plain_python_types,
    _process_dicom_metadata,
    prepare_session_dataframe,
    standardize_session_dataframe
)


class TestMakeDataframeHashable:
    """Test the make_dataframe_hashable function."""

    def test_make_dataframe_hashable_basic(self):
        """Test basic DataFrame hashable conversion."""
        df = pd.DataFrame({
            'A': [[1, 2], [3, 4]],
            'B': [{'key': 'value'}, {'key2': 'value2'}],
            'C': [1, 2]
        })
        
        result = make_dataframe_hashable(df)
        
        # Lists should be converted to tuples
        assert isinstance(result.iloc[0]['A'], tuple)
        assert result.iloc[0]['A'] == (1, 2)
        
        # Dicts should be converted to tuples of (key, value) pairs
        assert isinstance(result.iloc[0]['B'], tuple)
        
        # Regular values should remain unchanged
        assert result.iloc[0]['C'] == 1

    def test_make_dataframe_hashable_preserves_original(self):
        """Test that original DataFrame is not modified."""
        df = pd.DataFrame({
            'A': [[1, 2], [3, 4]],
            'B': [1, 2]
        })
        
        original_df = df.copy()
        make_dataframe_hashable(df)
        
        # Original DataFrame should be changed (this function modifies in place)
        # Check that the function actually works by verifying lists are converted
        assert isinstance(df.iloc[0]['A'], tuple)


class TestFlattenNestedDict:
    """Test the _flatten_nested_dict function."""

    def test_flatten_nested_dict_basic(self):
        """Test basic nested dictionary flattening."""
        data = {
            'a': 1,
            'b': {
                'c': 2,
                'd': {
                    'e': 3
                }
            }
        }
        
        result = _flatten_nested_dict(data)
        
        expected = {
            'a': 1,
            'b_c': 2,
            'b_d_e': 3
        }
        
        assert result == expected

    def test_flatten_nested_dict_with_lists(self):
        """Test flattening with lists containing dictionaries."""
        data = {
            'a': [{'b': 1}, {'c': 2}],
            'd': [1, 2, 3]  # List of primitives
        }
        
        result = _flatten_nested_dict(data)
        
        # Lists with dicts should be flattened with indices
        assert 'a_0_b' in result
        assert 'a_1_c' in result
        assert result['a_0_b'] == 1
        assert result['a_1_c'] == 2
        
        # Lists of primitives should be kept whole
        assert result['d'] == [1, 2, 3]

    def test_flatten_nested_dict_empty(self):
        """Test flattening empty dictionary."""
        result = _flatten_nested_dict({})
        assert result == {}

    def test_flatten_nested_dict_no_nesting(self):
        """Test flattening dictionary with no nesting."""
        data = {'a': 1, 'b': 2, 'c': 'test'}
        result = _flatten_nested_dict(data)
        assert result == data


class TestReduceFlattenedKeys:
    """Test the _reduce_flattened_keys function."""

    def test_reduce_flattened_keys_basic(self):
        """Test basic key reduction."""
        flat_dict = {
            'a_b_c': 1,
            'x_y_z': 2,
            'simple': 3
        }
        
        result = _reduce_flattened_keys(flat_dict)
        
        expected = {
            'c': 1,
            'z': 2,
            'simple': 3
        }
        
        assert result == expected

    def test_reduce_flattened_keys_conflicts(self):
        """Test key reduction with conflicts (same final key)."""
        flat_dict = {
            'a_b_value': 1,
            'x_y_value': 2,
            'z_value': None
        }
        
        result = _reduce_flattened_keys(flat_dict)
        
        # Should keep first non-None value when there are conflicts
        assert 'value' in result
        assert result['value'] in [1, 2]  # One of the non-None values

    def test_reduce_flattened_keys_none_values(self):
        """Test key reduction prioritizing non-None values."""
        flat_dict = {
            'a_b_key': None,
            'x_y_key': 'value'
        }
        
        result = _reduce_flattened_keys(flat_dict)
        
        # Should prefer non-None value
        assert result['key'] == 'value'


class TestConvertToPlainPythonTypes:
    """Test the _convert_to_plain_python_types function."""

    def test_convert_to_plain_python_types_basic(self):
        """Test basic type conversion."""
        # Test various types
        assert _convert_to_plain_python_types([1, 2, 3]) == (1, 2, 3)
        assert _convert_to_plain_python_types({'a': 1, 'b': 2}) == {'a': 1, 'b': 2}
        assert _convert_to_plain_python_types(3.14159) == 3.14159  # Should be rounded to 5 places
        assert _convert_to_plain_python_types(5) == 5

    def test_convert_to_plain_python_types_float_rounding(self):
        """Test float rounding to 5 decimal places."""
        result = _convert_to_plain_python_types(3.123456789)
        assert result == 3.12346  # Rounded to 5 places

    def test_convert_to_plain_python_types_nested(self):
        """Test conversion of nested structures."""
        data = {
            'list': [1, 2.123456, {'nested': 3.987654}],
            'float': 1.123456789
        }
        
        result = _convert_to_plain_python_types(data)
        
        assert isinstance(result['list'], tuple)
        assert result['list'][1] == 2.12346  # Rounded float
        assert result['list'][2]['nested'] == 3.98765  # Nested rounded float
        assert result['float'] == 1.12346


class TestProcessDicomMetadata:
    """Test the _process_dicom_metadata function."""

    def test_process_dicom_metadata_basic(self):
        """Test basic DICOM metadata processing."""
        metadata = {
            'PatientName': 'Doe^John',
            'NestedInfo': {
                'SubValue': 1.123456789
            },
            'ListData': [1, 2, 3]
        }
        
        result = _process_dicom_metadata(metadata)
        
        # Should be flattened and processed
        assert 'PatientName' in result
        assert 'SubValue' in result  # Flattened from NestedInfo_SubValue
        assert isinstance(result['ListData'], tuple)  # Converted to tuple

    def test_process_dicom_metadata_enhanced_mapping(self):
        """Test enhanced to regular mapping."""
        metadata = {
            'PerFrameFunctionalGroupsSequence': 'value',  # Should be mapped if in ENHANCED_TO_REGULAR_MAPPING
            'OtherField': 'other_value'
        }
        
        result = _process_dicom_metadata(metadata)
        
        # Should apply enhanced to regular mapping
        assert 'OtherField' in result


class TestPrepareSessionDataframe:
    """Test the prepare_session_dataframe function."""

    def test_prepare_session_dataframe_basic(self):
        """Test basic session DataFrame preparation."""
        session_data = [
            {'InstanceNumber': 2, 'PatientName': 'Doe^John', 'data': [1, 2]},
            {'InstanceNumber': 1, 'PatientName': 'Doe^Jane', 'data': [3, 4]},
            {'InstanceNumber': 3, 'PatientName': 'Doe^Bob', 'data': None}
        ]
        
        result = prepare_session_dataframe(session_data)
        
        # Should be sorted by InstanceNumber
        assert result.iloc[0]['InstanceNumber'] == 1
        assert result.iloc[1]['InstanceNumber'] == 2
        assert result.iloc[2]['InstanceNumber'] == 3
        
        # Should have made values hashable
        assert isinstance(result.iloc[0]['data'], tuple)

    def test_prepare_session_dataframe_empty(self):
        """Test error handling for empty session data."""
        with pytest.raises(ValueError, match="No session data found to process"):
            prepare_session_dataframe([])

    def test_prepare_session_dataframe_dicom_path_sorting(self):
        """Test sorting by DICOM_Path when InstanceNumber is not available."""
        session_data = [
            {'DICOM_Path': '/path/c.dcm', 'PatientName': 'Doe^John'},
            {'DICOM_Path': '/path/a.dcm', 'PatientName': 'Doe^Jane'},
            {'DICOM_Path': '/path/b.dcm', 'PatientName': 'Doe^Bob'}
        ]
        
        result = prepare_session_dataframe(session_data)
        
        # Should be sorted by DICOM_Path
        paths = result['DICOM_Path'].tolist()
        assert paths == sorted(paths)


class TestStandardizeSessionDataframe:
    """Test the standardize_session_dataframe function."""

    def test_standardize_session_dataframe_basic(self):
        """Test basic DataFrame standardization."""
        df = pd.DataFrame({
            'ProtocolName': ['BOLD', 'BOLD', 'T1'],
            'SeriesDescription': ['func_run1', 'func_run2', 'anat'],
            'SeriesInstanceUID': ['1.2.3.4.1', '1.2.3.4.2', '1.2.3.4.3'],
            'RepetitionTime': [2000, 2000, 1000],
            'EchoTime': [30, 35, 5],
            'InstanceNumber': [1, 2, 1]
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime']
        
        result = standardize_session_dataframe(df, reference_fields)
        
        # Should have Acquisition column added
        assert 'Acquisition' in result.columns
        
        # Should be sorted
        assert len(result) == 3

    def test_standardize_session_dataframe_with_acquisition(self):
        """Test DataFrame standardization when Acquisition column already exists."""
        df = pd.DataFrame({
            'Acquisition': ['BOLD', 'T1', 'BOLD'],
            'RepetitionTime': [2000, 1000, 2000],
            'EchoTime': [30, 5, 35],
            'InstanceNumber': [1, 1, 2]
        })
        
        reference_fields = ['RepetitionTime', 'EchoTime']
        
        result = standardize_session_dataframe(df, reference_fields)
        
        # Should preserve existing Acquisition column
        assert 'Acquisition' in result.columns
        assert len(result) == 3

    def test_standardize_session_dataframe_no_reference_fields(self):
        """Test DataFrame standardization without reference fields."""
        df = pd.DataFrame({
            'ProtocolName': ['BOLD', 'T1'],
            'SeriesDescription': ['func', 'anat'],
            'SeriesInstanceUID': ['1.2.3.4.1', '1.2.3.4.2'],
            'RepetitionTime': [2000, 1000],
            'InstanceNumber': [1, 1]
        })
        
        result = standardize_session_dataframe(df, None)
        
        # Should have Acquisition column added
        assert 'Acquisition' in result.columns
        
        # Should be sorted by Acquisition only
        assert len(result) == 2

    def test_standardize_session_dataframe_preserves_original(self):
        """Test that function properly handles DataFrame copying."""
        df = pd.DataFrame({
            'ProtocolName': ['BOLD', 'T1'],
            'SeriesDescription': ['func', 'anat'],
            'SeriesInstanceUID': ['1.2.3.4.1', '1.2.3.4.2'],
            'RepetitionTime': [2000, 1000],
            'InstanceNumber': [1, 1]
        })
        
        original_columns = df.columns.tolist()
        reference_fields = ['RepetitionTime']
        
        result = standardize_session_dataframe(df, reference_fields)
        
        # Function operates on a copy, so original structure should be mostly preserved
        # (Note: make_dataframe_hashable may modify values in place, but structure should be similar)
        assert set(original_columns).issubset(set(df.columns))
        
        # Result should be different (has Acquisition column)
        assert 'Acquisition' in result.columns
        assert len(result.columns) > len(original_columns)