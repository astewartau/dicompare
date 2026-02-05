"""Tests for mapping module - acquisition and series mapping functions."""

import pytest
import pandas as pd
import numpy as np

from dicompare.session.mapping import (
    levenshtein_distance,
    calculate_field_score,
    calculate_match_score,
    compute_series_cost_matrix,
    map_to_json_reference,
)
from dicompare.config import MAX_DIFF_SCORE


class TestLevenshteinDistance:
    """Tests for the levenshtein_distance function."""

    def test_identical_strings(self):
        """Test that identical strings have distance 0."""
        assert levenshtein_distance("hello", "hello") == 0

    def test_empty_strings(self):
        """Test distance between empty strings."""
        assert levenshtein_distance("", "") == 0
        assert levenshtein_distance("abc", "") == 3
        assert levenshtein_distance("", "xyz") == 3

    def test_single_insertion(self):
        """Test single character insertion."""
        assert levenshtein_distance("cat", "cats") == 1

    def test_single_deletion(self):
        """Test single character deletion."""
        assert levenshtein_distance("cats", "cat") == 1

    def test_single_substitution(self):
        """Test single character substitution."""
        assert levenshtein_distance("cat", "bat") == 1

    def test_completely_different_strings(self):
        """Test completely different strings."""
        assert levenshtein_distance("abc", "xyz") == 3

    def test_swap_order_same_result(self):
        """Test that order doesn't matter (symmetric)."""
        assert levenshtein_distance("abc", "def") == levenshtein_distance("def", "abc")


class TestCalculateFieldScore:
    """Tests for the calculate_field_score function."""

    def test_missing_actual_value(self):
        """Test that missing actual value returns MAX_DIFF_SCORE."""
        score = calculate_field_score("expected", None)
        assert score == MAX_DIFF_SCORE

    def test_exact_match_strings(self):
        """Test exact string match returns 0."""
        score = calculate_field_score("value", "value")
        assert score == 0

    def test_exact_match_numbers(self):
        """Test exact number match returns 0."""
        score = calculate_field_score(100, 100)
        assert score == 0

    def test_numeric_difference_no_tolerance(self):
        """Test numeric difference without tolerance."""
        score = calculate_field_score(100, 110)
        assert score == 10

    def test_numeric_within_tolerance(self):
        """Test numeric value within tolerance returns 0."""
        score = calculate_field_score(100, 105, tolerance=10)
        assert score == 0

    def test_numeric_outside_tolerance(self):
        """Test numeric value outside tolerance returns difference capped at MAX_DIFF_SCORE."""
        score = calculate_field_score(100, 120, tolerance=5)
        # Outside tolerance (diff=20 > tol=5), returns diff capped at MAX_DIFF_SCORE=10
        assert score == MAX_DIFF_SCORE

    def test_wildcard_pattern_match(self):
        """Test wildcard pattern matching."""
        score = calculate_field_score("T1*", "T1_MPRAGE")
        assert score == 0

    def test_wildcard_pattern_no_match(self):
        """Test wildcard pattern that doesn't match."""
        score = calculate_field_score("T1*", "T2_FLAIR")
        assert score == 5  # Fixed penalty for pattern mismatch

    def test_question_mark_wildcard(self):
        """Test single character wildcard."""
        score = calculate_field_score("T?", "T1")
        assert score == 0

    def test_contains_string_found(self):
        """Test contains check when substring is found."""
        score = calculate_field_score(None, "Hello World", contains="World")
        assert score == 0

    def test_contains_string_not_found(self):
        """Test contains check when substring is not found."""
        score = calculate_field_score(None, "Hello", contains="World")
        assert score == 5  # Fixed penalty

    def test_contains_in_list(self):
        """Test contains check in list."""
        score = calculate_field_score(None, ["a", "b", "c"], contains="b")
        assert score == 0

    def test_list_comparison_exact_match(self):
        """Test list comparison with exact match."""
        score = calculate_field_score(["a", "b"], ["a", "b"])
        assert score == 0

    def test_list_comparison_different_values(self):
        """Test list comparison with different values."""
        score = calculate_field_score(["a", "b"], ["a", "c"])
        assert score > 0

    def test_numeric_list_with_tolerance(self):
        """Test numeric list comparison with tolerance."""
        score = calculate_field_score([1.0, 2.0], [1.0, 2.5], tolerance=1.0)
        assert score == 0  # Both elements within tolerance

    def test_tuple_comparison(self):
        """Test tuple comparison."""
        score = calculate_field_score((1, 2), (1, 2))
        assert score == 0

    def test_list_different_lengths(self):
        """Test lists with different lengths."""
        score = calculate_field_score(["a", "b", "c"], ["a", "b"])
        assert score > 0  # Should handle padding

    def test_score_capped_at_max(self):
        """Test that score is capped at MAX_DIFF_SCORE."""
        # Very different strings should be capped
        score = calculate_field_score("a" * 100, "b" * 100)
        assert score <= MAX_DIFF_SCORE


class TestCalculateMatchScore:
    """Tests for the calculate_match_score function."""

    def test_empty_fields(self):
        """Test with no fields."""
        ref_row = {"fields": []}
        in_row = {"fields": []}
        score = calculate_match_score(ref_row, in_row)
        assert score == 0.0

    def test_matching_fields(self):
        """Test with matching fields."""
        ref_row = {
            "fields": [
                {"field": "EchoTime", "value": 30}
            ]
        }
        in_row = {
            "fields": [
                {"field": "EchoTime", "value": 30}
            ]
        }
        score = calculate_match_score(ref_row, in_row)
        assert score == 0.0

    def test_mismatched_fields(self):
        """Test with mismatched field values."""
        ref_row = {
            "fields": [
                {"field": "EchoTime", "value": 30}
            ]
        }
        in_row = {
            "fields": [
                {"field": "EchoTime", "value": 40}
            ]
        }
        score = calculate_match_score(ref_row, in_row)
        assert score == 10.0

    def test_missing_input_field(self):
        """Test with missing input field."""
        ref_row = {
            "fields": [
                {"field": "EchoTime", "value": 30}
            ]
        }
        in_row = {
            "fields": []
        }
        score = calculate_match_score(ref_row, in_row)
        assert score == MAX_DIFF_SCORE

    def test_with_tolerance(self):
        """Test with tolerance parameter."""
        ref_row = {
            "fields": [
                {"field": "EchoTime", "value": 30, "tolerance": 5}
            ]
        }
        in_row = {
            "fields": [
                {"field": "EchoTime", "value": 33}
            ]
        }
        score = calculate_match_score(ref_row, in_row)
        assert score == 0.0

    def test_with_contains(self):
        """Test with contains parameter."""
        ref_row = {
            "fields": [
                {"field": "ProtocolName", "contains": "T1"}
            ]
        }
        in_row = {
            "fields": [
                {"field": "ProtocolName", "value": "T1_MPRAGE"}
            ]
        }
        score = calculate_match_score(ref_row, in_row)
        assert score == 0.0


class TestComputeSeriesCostMatrix:
    """Tests for the compute_series_cost_matrix function."""

    def test_single_series_single_row(self):
        """Test cost matrix with single series and single row."""
        ref_series_defs = [
            {"fields": [{"field": "EchoTime", "value": 30}]}
        ]
        in_df = pd.DataFrame({"EchoTime": [30]})

        cost_matrix, candidate_rows = compute_series_cost_matrix(ref_series_defs, in_df)

        assert cost_matrix.shape == (1, 1)
        assert cost_matrix[0, 0] == 0.0

    def test_multiple_series_multiple_rows(self):
        """Test cost matrix with multiple series and rows."""
        ref_series_defs = [
            {"fields": [{"field": "EchoTime", "value": 10}]},
            {"fields": [{"field": "EchoTime", "value": 20}]}
        ]
        in_df = pd.DataFrame({"EchoTime": [10, 20]})

        cost_matrix, candidate_rows = compute_series_cost_matrix(ref_series_defs, in_df)

        assert cost_matrix.shape == (2, 2)
        # Perfect match on diagonal
        assert cost_matrix[0, 0] == 0.0  # ref 10 vs row 10
        assert cost_matrix[1, 1] == 0.0  # ref 20 vs row 20
        # Mismatch off diagonal (numeric difference)
        assert cost_matrix[0, 1] > 0  # ref 10 vs row 20
        assert cost_matrix[1, 0] > 0  # ref 20 vs row 10

    def test_missing_field_high_cost(self):
        """Test that missing field incurs high cost."""
        ref_series_defs = [
            {"fields": [{"field": "EchoTime", "value": 30}]}
        ]
        in_df = pd.DataFrame({"OtherField": [100]})

        cost_matrix, _ = compute_series_cost_matrix(ref_series_defs, in_df)

        assert cost_matrix[0, 0] >= 9999.0

    def test_with_tolerance_and_contains(self):
        """Test cost matrix with tolerance and contains."""
        ref_series_defs = [
            {"fields": [
                {"field": "EchoTime", "value": 30, "tolerance": 5},
                {"field": "ProtocolName", "contains": "T1"}
            ]}
        ]
        # Use Python floats to ensure numeric comparison works correctly
        in_df = pd.DataFrame({
            "EchoTime": [32.0],  # Within tolerance of 5 from 30
            "ProtocolName": ["T1_MPRAGE"]  # Contains "T1"
        })

        cost_matrix, _ = compute_series_cost_matrix(ref_series_defs, in_df)

        # With tolerance and contains both satisfied, cost should be 0
        assert cost_matrix[0, 0] == 0.0


class TestMapToJsonReferenceReturnCosts:
    """Tests for return_costs parameter of map_to_json_reference."""

    def test_return_costs_gives_tuple(self):
        """Test that return_costs=True returns a tuple."""
        in_df = pd.DataFrame({
            "Acquisition": ["acq1", "acq1", "acq2", "acq2"],
            "EchoTime": [10, 10, 20, 20],
        })
        ref_session = {
            "acquisitions": {
                "RefA": {"fields": [{"field": "EchoTime", "value": 10}]},
                "RefB": {"fields": [{"field": "EchoTime", "value": 20}]},
            }
        }

        result = map_to_json_reference(in_df, ref_session, return_costs=True)
        assert isinstance(result, tuple)
        assert len(result) == 2

        mapping, cost_details = result
        assert isinstance(mapping, dict)
        assert "RefA" in mapping
        assert "RefB" in mapping
        assert "assigned_costs" in cost_details
        assert cost_details['assigned_costs']['RefA'] == 0.0
        assert cost_details['assigned_costs']['RefB'] == 0.0

    def test_default_returns_dict(self):
        """Test that default return_costs=False returns just a dict."""
        in_df = pd.DataFrame({
            "Acquisition": ["acq1"],
            "EchoTime": [10],
        })
        ref_session = {
            "acquisitions": {
                "RefA": {"fields": [{"field": "EchoTime", "value": 10}]},
            }
        }

        result = map_to_json_reference(in_df, ref_session)
        assert isinstance(result, dict)
        assert "RefA" in result

    def test_costs_nonzero_for_mismatch(self):
        """Test that mismatched acquisitions have nonzero cost."""
        in_df = pd.DataFrame({
            "Acquisition": ["acq1"],
            "EchoTime": [99.0],
        })
        ref_session = {
            "acquisitions": {
                "RefA": {"fields": [{"field": "EchoTime", "value": 10.0}]},
            }
        }

        mapping, cost_details = map_to_json_reference(in_df, ref_session, return_costs=True)
        assert cost_details['assigned_costs']['RefA'] > 0


class TestMapToJsonReference:
    """Tests for the map_to_json_reference function."""

    def test_simple_mapping(self):
        """Test simple acquisition mapping."""
        in_df = pd.DataFrame({
            "Acquisition": ["acq1", "acq1", "acq2", "acq2"],
            "EchoTime": [10, 10, 20, 20],
            "RepetitionTime": [1000, 1000, 2000, 2000]
        })

        ref_session = {
            "acquisitions": {
                "RefA": {
                    "fields": [{"field": "EchoTime", "value": 10}]
                },
                "RefB": {
                    "fields": [{"field": "EchoTime", "value": 20}]
                }
            }
        }

        mapping = map_to_json_reference(in_df, ref_session)

        assert "RefA" in mapping
        assert "RefB" in mapping
        assert mapping["RefA"] == "acq1"
        assert mapping["RefB"] == "acq2"

    def test_mapping_with_series(self):
        """Test mapping with series definitions."""
        in_df = pd.DataFrame({
            "Acquisition": ["acq1", "acq1"],
            "EchoTime": [10, 20]
        })

        ref_session = {
            "acquisitions": {
                "RefA": {
                    "fields": [],
                    "series": [
                        {"fields": [{"field": "EchoTime", "value": 10}]},
                        {"fields": [{"field": "EchoTime", "value": 20}]}
                    ]
                }
            }
        }

        mapping = map_to_json_reference(in_df, ref_session)

        assert "RefA" in mapping
        assert mapping["RefA"] == "acq1"

    def test_mapping_with_multiple_values(self):
        """Test mapping when input acquisition has multiple distinct values."""
        in_df = pd.DataFrame({
            "Acquisition": ["acq1", "acq1"],
            "EchoTime": [10, 20],  # Multiple distinct values
            "RepetitionTime": [1000, 1000]  # Single value
        })

        ref_session = {
            "acquisitions": {
                "RefA": {
                    "fields": [
                        {"field": "EchoTime", "value": 10},
                        {"field": "RepetitionTime", "value": 1000}
                    ]
                }
            }
        }

        # Should still work, but EchoTime will incur cost due to multiple values
        mapping = map_to_json_reference(in_df, ref_session)

        assert "RefA" in mapping

    def test_empty_series_defs(self):
        """Test mapping with empty series definitions."""
        in_df = pd.DataFrame({
            "Acquisition": ["acq1"],
            "EchoTime": [10]
        })

        ref_session = {
            "acquisitions": {
                "RefA": {
                    "fields": [{"field": "EchoTime", "value": 10}],
                    "series": []  # Empty series
                }
            }
        }

        mapping = map_to_json_reference(in_df, ref_session)

        assert "RefA" in mapping
