"""Tests for special_fields module - field categorization and encoding."""

import pytest
import pydicom

from dicompare.io.special_fields import (
    categorize_field,
    categorize_fields,
    encode_multiband_in_image_comments,
    apply_special_field_encoding,
    get_unhandled_field_warnings,
    get_field_categorization_summary,
    HANDLED_SPECIAL_FIELDS,
)


class TestCategorizeField:
    """Tests for the categorize_field function."""

    def test_standard_field_with_valid_tag(self):
        """Test that a standard DICOM field with valid tag is categorized correctly."""
        category, description = categorize_field('RepetitionTime', '0018,0080')
        assert category == 'standard'
        assert 'Standard DICOM field' in description

    def test_standard_field_with_parentheses_tag(self):
        """Test that tags with parentheses are handled."""
        category, description = categorize_field('EchoTime', '(0018,0081)')
        assert category == 'standard'

    def test_private_tag(self):
        """Test that private tags are categorized as standard (still DICOM)."""
        # Private tag (odd group number) - categorized as 'standard' either way
        category, description = categorize_field('VendorField', '0019,1001')
        assert category == 'standard'
        # Description can be either 'Standard DICOM field' or 'Private DICOM tag'
        assert 'DICOM' in description or 'Standard' in description

    def test_handled_special_field_multiband(self):
        """Test that MultibandFactor is categorized as handled."""
        category, description = categorize_field('MultibandFactor', '')
        assert category == 'handled'
        assert 'Multiband' in description or 'multiband' in description.lower()

    def test_handled_special_field_multiband_alias(self):
        """Test that MultibandAccelerationFactor is categorized as handled."""
        category, description = categorize_field('MultibandAccelerationFactor', '')
        assert category == 'handled'

    def test_handled_special_field_parallel_reduction(self):
        """Test that ParallelReductionFactorOutOfPlane is categorized as handled."""
        category, description = categorize_field('ParallelReductionFactorOutOfPlane', '')
        assert category == 'handled'

    def test_handled_special_field_phase_encoding_shift(self):
        """Test that PhaseEncodingShift is categorized as handled."""
        category, description = categorize_field('PhaseEncodingShift', '')
        assert category == 'handled'

    def test_unhandled_field(self):
        """Test that unknown fields are categorized as unhandled."""
        category, description = categorize_field('CustomUnknownField', '')
        assert category == 'unhandled'
        assert 'Non-standard' in description or 'no encoding' in description.lower()

    def test_invalid_tag_format_falls_through(self):
        """Test that invalid tag formats are handled gracefully."""
        # Invalid tag format - should fall through to check special fields
        category, description = categorize_field('MultibandFactor', 'invalid')
        assert category == 'handled'  # Still recognized as special field

    def test_invalid_tag_unknown_field(self):
        """Test that invalid tag with unknown field is unhandled."""
        category, description = categorize_field('UnknownField', 'invalid')
        assert category == 'unhandled'


class TestCategorizeFields:
    """Tests for the categorize_fields function."""

    def test_categorize_multiple_fields(self):
        """Test categorizing a list of fields."""
        fields = [
            {'name': 'RepetitionTime', 'tag': '0018,0080'},
            {'name': 'MultibandFactor', 'tag': ''},
            {'name': 'UnknownField', 'tag': ''}
        ]
        result = categorize_fields(fields)

        assert len(result['standard']) == 1
        assert len(result['handled']) == 1
        assert len(result['unhandled']) == 1

    def test_categorize_empty_list(self):
        """Test categorizing an empty list."""
        result = categorize_fields([])
        assert result['standard'] == []
        assert result['handled'] == []
        assert result['unhandled'] == []

    def test_categorized_fields_include_original_data(self):
        """Test that categorized fields include original field data."""
        fields = [{'name': 'RepetitionTime', 'tag': '0018,0080', 'value': 2000}]
        result = categorize_fields(fields)

        assert len(result['standard']) == 1
        assert result['standard'][0]['value'] == 2000
        assert 'category' in result['standard'][0]
        assert 'description' in result['standard'][0]


class TestEncodeMultibandInImageComments:
    """Tests for the encode_multiband_in_image_comments function."""

    def test_encode_multiband_factor_3(self):
        """Test encoding MB factor 3."""
        result = encode_multiband_in_image_comments(3)
        assert result == 'Unaliased MB3/PE2'

    def test_encode_multiband_factor_4(self):
        """Test encoding MB factor 4."""
        result = encode_multiband_in_image_comments(4)
        assert result == 'Unaliased MB4/PE3'

    def test_encode_with_explicit_pe_shift(self):
        """Test encoding with explicit phase encoding shift."""
        result = encode_multiband_in_image_comments(3, 3)
        assert result == 'Unaliased MB3/PE3'

    def test_encode_with_leak_block(self):
        """Test encoding with LeakBlock enabled."""
        result = encode_multiband_in_image_comments(4, 3, True)
        assert result == 'Unaliased MB4/PE3/LB'

    def test_encode_single_band(self):
        """Test encoding single-band (MB=1)."""
        result = encode_multiband_in_image_comments(1)
        assert 'Single-band' in result

    def test_encode_no_multiband(self):
        """Test encoding with MB=0."""
        result = encode_multiband_in_image_comments(0)
        assert 'Single-band' in result


class TestApplySpecialFieldEncoding:
    """Tests for the apply_special_field_encoding function."""

    def test_apply_multiband_factor(self):
        """Test applying MultibandFactor encoding to dataset."""
        ds = pydicom.Dataset()
        field_values = {'MultibandFactor': 3}
        apply_special_field_encoding(ds, field_values)

        assert hasattr(ds, 'ImageComments')
        assert 'MB3' in ds.ImageComments

    def test_apply_multiband_with_pe_shift(self):
        """Test applying MultibandFactor with PhaseEncodingShift."""
        ds = pydicom.Dataset()
        field_values = {'MultibandFactor': 3, 'PhaseEncodingShift': 3}
        apply_special_field_encoding(ds, field_values)

        assert 'MB3/PE3' in ds.ImageComments

    def test_apply_multiband_acceleration_factor_alias(self):
        """Test that MultibandAccelerationFactor works as alias."""
        ds = pydicom.Dataset()
        field_values = {'MultibandAccelerationFactor': 4}
        apply_special_field_encoding(ds, field_values)

        assert 'MB4' in ds.ImageComments

    def test_apply_parallel_reduction_alias(self):
        """Test that ParallelReductionFactorOutOfPlane works as alias."""
        ds = pydicom.Dataset()
        field_values = {'ParallelReductionFactorOutOfPlane': 2}
        apply_special_field_encoding(ds, field_values)

        assert 'MB2' in ds.ImageComments

    def test_apply_no_special_fields(self):
        """Test that applying empty field values doesn't change dataset."""
        ds = pydicom.Dataset()
        field_values = {'RegularField': 'value'}
        apply_special_field_encoding(ds, field_values)

        assert not hasattr(ds, 'ImageComments')


class TestGetUnhandledFieldWarnings:
    """Tests for the get_unhandled_field_warnings function."""

    def test_warnings_for_unhandled_fields_with_data(self):
        """Test that warnings are generated for unhandled fields with data."""
        field_defs = [
            {'name': 'UnknownField1', 'tag': ''},
            {'name': 'UnknownField2', 'tag': ''}
        ]
        test_data = [{'UnknownField1': 123}]
        warnings = get_unhandled_field_warnings(field_defs, test_data)

        assert len(warnings) == 1
        assert 'UnknownField1' in warnings[0]

    def test_no_warnings_for_standard_fields(self):
        """Test that no warnings for standard DICOM fields."""
        field_defs = [{'name': 'RepetitionTime', 'tag': '0018,0080'}]
        test_data = [{'RepetitionTime': 2000}]
        warnings = get_unhandled_field_warnings(field_defs, test_data)

        assert len(warnings) == 0

    def test_no_warnings_for_handled_special_fields(self):
        """Test that no warnings for handled special fields."""
        field_defs = [{'name': 'MultibandFactor', 'tag': ''}]
        test_data = [{'MultibandFactor': 3}]
        warnings = get_unhandled_field_warnings(field_defs, test_data)

        assert len(warnings) == 0

    def test_no_warnings_when_no_data(self):
        """Test that no warnings when field has no data."""
        field_defs = [{'name': 'UnknownField', 'tag': ''}]
        test_data = [{'OtherField': 'value'}]
        warnings = get_unhandled_field_warnings(field_defs, test_data)

        assert len(warnings) == 0

    def test_no_warnings_empty_inputs(self):
        """Test that no warnings with empty inputs."""
        assert get_unhandled_field_warnings([], []) == []
        assert get_unhandled_field_warnings([{'name': 'Field', 'tag': ''}], []) == []

    def test_warnings_skip_none_values(self):
        """Test that None values don't generate warnings."""
        field_defs = [{'name': 'UnknownField', 'tag': ''}]
        test_data = [{'UnknownField': None}]
        warnings = get_unhandled_field_warnings(field_defs, test_data)

        assert len(warnings) == 0


class TestGetFieldCategorizationSummary:
    """Tests for the get_field_categorization_summary function."""

    def test_summary_counts(self):
        """Test that summary includes correct counts."""
        fields = [
            {'name': 'RepetitionTime', 'tag': '0018,0080'},
            {'name': 'EchoTime', 'tag': '0018,0081'},
            {'name': 'MultibandFactor', 'tag': ''},
            {'name': 'UnknownField', 'tag': ''}
        ]
        summary = get_field_categorization_summary(fields)

        assert summary['counts']['standard'] == 2
        assert summary['counts']['handled'] == 1
        assert summary['counts']['unhandled'] == 1
        assert summary['counts']['total'] == 4

    def test_summary_has_unhandled_flag(self):
        """Test that summary includes has_unhandled flag."""
        fields_with_unhandled = [{'name': 'UnknownField', 'tag': ''}]
        summary = get_field_categorization_summary(fields_with_unhandled)
        assert summary['has_unhandled'] is True

        fields_without_unhandled = [{'name': 'RepetitionTime', 'tag': '0018,0080'}]
        summary = get_field_categorization_summary(fields_without_unhandled)
        assert summary['has_unhandled'] is False

    def test_summary_includes_fields_dict(self):
        """Test that summary includes categorized fields."""
        fields = [{'name': 'RepetitionTime', 'tag': '0018,0080'}]
        summary = get_field_categorization_summary(fields)

        assert 'fields' in summary
        assert 'standard' in summary['fields']
        assert len(summary['fields']['standard']) == 1


class TestHandledSpecialFieldsConstant:
    """Tests for the HANDLED_SPECIAL_FIELDS constant."""

    def test_multiband_factor_is_handled(self):
        """Test that MultibandFactor is in handled fields."""
        assert 'MultibandFactor' in HANDLED_SPECIAL_FIELDS

    def test_handled_fields_have_encoding(self):
        """Test that all handled fields have encoding info."""
        for field_name, info in HANDLED_SPECIAL_FIELDS.items():
            assert 'encoding' in info
            assert 'description' in info
