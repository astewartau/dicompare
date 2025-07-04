"""
This module provides functions for mapping DICOM input data to reference models (JSON or Python modules).

"""

import re
import numpy as np
import pandas as pd

from typing import Any, Dict
from tabulate import tabulate
from scipy.optimize import linear_sum_assignment
from .config import MAX_DIFF_SCORE

try:
    import curses
except ImportError:
    curses = None

# MAX_DIFF_SCORE imported from config

def levenshtein_distance(s1, s2):
    """
    Calculate the Levenshtein distance (edit distance) between two strings.

    Notes:
        - Uses a dynamic programming approach.
        - Distance is the number of single-character edits required to convert one string to another.

    Args:
        s1 (str): First string.
        s2 (str): Second string.

    Returns:
        int: The Levenshtein distance between the two strings.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    # Initialize a row with incremental values [0, 1, 2, ..., len(s2)]
    previous_row = range(len(s2) + 1)

    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]

def calculate_field_score(expected, actual, tolerance=None, contains=None):
    """
    Calculate the difference score between expected and actual values, applying specific rules.

    Notes:
        - Handles numeric comparisons with optional tolerance.
        - Applies substring containment checks.
        - String comparisons use Levenshtein distance.
        - Missing values incur a high penalty.

    Args:
        expected (Any): The expected value.
        actual (Any): The actual value.
        tolerance (Optional[float]): Tolerance for numeric comparisons.
        contains (Optional[str]): Substring or value that should be contained in `actual`.

    Returns:
        float: A difference score capped at `MAX_DIFF_SCORE`.
    """

    if actual is None:
        # Assign a high penalty for missing actual value
        return MAX_DIFF_SCORE

    if isinstance(expected, str) and ("*" in expected or "?" in expected):
        pattern = re.compile("^" + expected.replace("*", ".*").replace("?", ".") + "$")
        if pattern.match(actual):
            return 0  # Pattern matched, no difference
        return min(MAX_DIFF_SCORE, 5)  # Pattern did not match, fixed penalty

    if contains:
        if (isinstance(actual, str) and contains in actual) or (isinstance(actual, (list, tuple)) and contains in actual):
            return 0  # Contains requirement fulfilled, no difference
        return min(MAX_DIFF_SCORE, 5)  # 'Contains' not met, fixed penalty

    if isinstance(expected, (list, tuple)) or isinstance(actual, (list, tuple)):
        expected_tuple = tuple(expected) if not isinstance(expected, tuple) else expected
        actual_tuple = tuple(actual) if not isinstance(actual, tuple) else actual
        
        if all(isinstance(e, (int, float)) for e in expected_tuple) and all(isinstance(a, (int, float)) for a in actual_tuple) and len(expected_tuple) == len(actual_tuple):
            if tolerance is not None:
                return min(MAX_DIFF_SCORE, sum(abs(e - a) for e, a in zip(expected_tuple, actual_tuple) if abs(e - a) > tolerance))

        max_length = max(len(expected_tuple), len(actual_tuple))
        expected_padded = expected_tuple + ("",) * (max_length - len(expected_tuple))
        actual_padded = actual_tuple + ("",) * (max_length - len(actual_tuple))
        return min(MAX_DIFF_SCORE, sum(levenshtein_distance(str(e), str(a)) for e, a in zip(expected_padded, actual_padded)))
    
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if tolerance is not None:
            if abs(expected - actual) <= tolerance:
                return 0
        return min(MAX_DIFF_SCORE, abs(expected - actual))
    
    return min(MAX_DIFF_SCORE, levenshtein_distance(str(expected), str(actual)))

def calculate_match_score(ref_row, in_row):
    """
    Calculate the total difference score for a reference row and an input row.

    Args:
        ref_row (dict): Dictionary representing a reference acquisition or series.
        in_row (dict): Dictionary representing an input acquisition or series.

    Returns:
        float: The total difference score.
    """

    diff_score = 0.0

    in_fields = in_row.get("fields", [])

    for ref_field in ref_row.get("fields", []):
        expected = ref_field.get("value")
        tolerance = ref_field.get("tolerance")
        contains = ref_field.get("contains")
        in_field = next((f for f in in_fields if f["field"] == ref_field["field"]), {})
        actual = in_field.get("value")

        diff = calculate_field_score(expected, actual, tolerance=tolerance, contains=contains)
        diff_score += diff

    return round(diff_score, 2)


def compute_series_cost_matrix(
    ref_acq_series_defs: list,
    in_acq_df: pd.DataFrame
):
    """
    Build a cost matrix for (reference-series-definitions) vs. (rows in input acquisition).
    Each row is treated as a potential 'series' match. 
    """
    # Each row is a candidate for matching one reference series definition
    candidate_rows = in_acq_df.index.to_list()
    n_ref_series = len(ref_acq_series_defs)
    n_rows = len(candidate_rows)
    cost_matrix = np.zeros((n_ref_series, n_rows), dtype=float)

    for i, ref_series_def in enumerate(ref_acq_series_defs):
        fields_data = ref_series_def.get("fields", [])
        for j, row_idx in enumerate(candidate_rows):
            row_data = in_acq_df.loc[row_idx]

            # Sum cost for all fields in the reference series
            total_cost = 0.0
            for fdef in fields_data:
                field_name = fdef["field"]
                expected_value = fdef.get("value")
                tolerance = fdef.get("tolerance")
                contains = fdef.get("contains")

                # If field missing, big cost
                if field_name not in row_data:
                    total_cost += 9999.0
                    continue

                actual_value = row_data[field_name]
                # If it's multiple unique values, or array-like, handle that logic if needed
                # (Here we assume each row is a single value.)
                cost = calculate_field_score(expected_value, actual_value,
                                             tolerance=tolerance, contains=contains)
                total_cost += cost

            cost_matrix[i, j] = total_cost

    return cost_matrix, candidate_rows


def map_to_json_reference(
    in_session_df: pd.DataFrame,
    ref_session: Dict[str, Any]
) -> dict:
    """
    Automatic assignment of reference acquisitions to input acquisitions,
    including nested assignment for series within each acquisition.
    Returns { ref_acquisition: in_acquisition }.
    """
    from scipy.optimize import linear_sum_assignment

    ref_acquisitions = ref_session["acquisitions"]
    ref_acq_list = sorted(ref_acquisitions.keys())
    input_acq_list = sorted(in_session_df["Acquisition"].unique())

    # Prepare a top-level cost matrix: rows = ref acquisitions, cols = input acquisitions
    top_cost_matrix = np.zeros((len(ref_acq_list), len(input_acq_list)), dtype=float)

    for i, ref_acq_name in enumerate(ref_acq_list):
        ref_acq = ref_acquisitions[ref_acq_name]
        ref_fields = ref_acq.get("fields", [])
        ref_series_defs = ref_acq.get("series", [])

        for j, in_acq_name in enumerate(input_acq_list):
            # Filter the input DataFrame for this candidate acquisition
            subset_df = in_session_df[in_session_df["Acquisition"] == in_acq_name]

            # --- 1) Compute acquisition-level cost ---
            acq_level_cost = 0.0
            for fdef in ref_fields:
                field_name = fdef["field"]
                expected_value = fdef.get("value")
                tolerance = fdef.get("tolerance")
                contains = fdef.get("contains")

                if field_name in subset_df.columns:
                    vals = subset_df[field_name].unique()
                    # If there's exactly one unique value, use it. Otherwise big cost
                    if len(vals) == 1:
                        actual_value = vals[0]
                    else:
                        # Multiple distinct values => can't pick one easily => big cost
                        actual_value = None
                else:
                    actual_value = None

                acq_level_cost += calculate_field_score(expected_value, actual_value,
                                                        tolerance=tolerance, contains=contains)

            # --- 2) If we have reference-series definitions, do a nested assignment ---
            series_cost_total = 0.0
            if ref_series_defs:
                cost_matrix, candidate_rows = compute_series_cost_matrix(ref_series_defs, subset_df)
                if cost_matrix.size > 0:
                    row_idx, col_idx = linear_sum_assignment(cost_matrix)
                    # Sum minimal cost
                    series_cost_total = cost_matrix[row_idx, col_idx].sum()

            # Combine acquisition-level + series-level
            total_cost = acq_level_cost + series_cost_total
            top_cost_matrix[i, j] = total_cost

    # Solve final assignment across acquisitions
    row_indices, col_indices = linear_sum_assignment(top_cost_matrix)

    # Build map {reference_acquisition: input_acquisition}
    mapping = {}
    for row, col in zip(row_indices, col_indices):
        ref_acq = ref_acq_list[row]
        in_acq = input_acq_list[col]
        mapping[ref_acq] = in_acq

    return mapping

def interactive_mapping_to_json_reference(in_session_df: pd.DataFrame, ref_session: dict, initial_mapping=None):
    """
    Interactive CLI for mapping input acquisitions to JSON reference acquisitions.

    Notes:
        - Presents a terminal interface for selecting which input acquisition
          should map to each reference acquisition.
        - Provides a list of reference acquisitions on the left (one is "selected").
        - Press RIGHT to select from input acquisitions. Press LEFT to go back.
        - Press 'u' to unmap the currently selected reference acquisition.
        - Press 'q' to quit and finalize the mapping.

    Args:
        in_session_df (pd.DataFrame): DataFrame of input session metadata.
        ref_session (dict): Reference session data in JSON format.
        initial_mapping (dict, optional): Initial acquisition-level mapping.
            Example format: {"RefAcqA": "InputAcqB", "RefAcqC": "InputAcqD"}

    Returns:
        dict: Final mapping of {reference_acquisition: input_acquisition}.
    """
    
    # Gather all reference acquisition names
    reference_acq_names = sorted(ref_session["acquisitions"].keys())

    # Gather all unique input acquisitions
    input_acq_names = sorted(in_session_df["Acquisition"].unique())

    # Optional: create a dictionary with partial metadata about input acquisitions
    # for display. You can store more fields if desired.
    input_acquisition_meta = {}
    for in_acq_name in input_acq_names:
        subset = in_session_df[in_session_df["Acquisition"] == in_acq_name]
        # Example: store ProtocolName if available
        protocol_values = subset["ProtocolName"].unique() if "ProtocolName" in subset.columns else []
        proto_str = protocol_values[0] if len(protocol_values) == 1 else "multiple"
        input_acquisition_meta[in_acq_name] = {"ProtocolName": proto_str}

    # Build the mapping structure, using any initial mapping
    mapping = {}
    if initial_mapping:
        for ref_acq, in_acq in initial_mapping.items():
            if ref_acq in reference_acq_names and in_acq in input_acq_names:
                mapping[ref_acq] = in_acq

    # Utility to produce the text table of reference acquisitions
    def format_mapping_table(selected_ref_idx):
        """
        Build a text table with columns:
          - Selection marker (>> or whitespace)
          - Reference acquisition name (+ optional info)
          - Current mapping
        """
        table_rows = []
        for i, ref_acq in enumerate(reference_acq_names):
            row_indicator = ">>" if i == selected_ref_idx else "  "
            current_map = mapping.get(ref_acq, "Unmapped")

            # Optionally show some reference info from ref_session
            ref_info = ref_session["acquisitions"][ref_acq].get("fields", [])
            # Just show the first few fields or some summary
            ref_info_str = ""
            if ref_info:
                # Example: show up to 2 fields in "field=value" style
                limited_fields = [f"{f['field']}={f.get('value', 'None')}" for f in ref_info[:2]]
                ref_info_str = f" ({', '.join(limited_fields)})"

            # If there is a mapped input acquisition, show some metadata about it
            if current_map != "Unmapped":
                in_meta = input_acquisition_meta.get(current_map, {})
                proto_str = in_meta.get("ProtocolName", "N/A")
                current_map += f" (ProtocolName={proto_str})"

            table_rows.append([row_indicator, f"{ref_acq}{ref_info_str}", current_map])
        
        return tabulate(table_rows, headers=["", "Reference Acquisition", "Mapped Input"], tablefmt="simple")

    def run_curses(stdscr):
        curses.curs_set(0)

        # Indices to track selection
        selected_ref_idx = 0
        selected_input_idx = None  # None means we're not currently picking input

        while True:
            stdscr.clear()

            # 1. Show table of reference acquisitions
            table_str = format_mapping_table(selected_ref_idx)
            stdscr.addstr(0, 0, "Use UP/DOWN to select a reference acquisition.")
            stdscr.addstr(1, 0, "Press RIGHT to pick from input acquisitions, 'u' to unmap, 'q' to quit.")
            stdscr.addstr(3, 0, table_str)

            # 2. If picking input, show the list of input acquisitions
            base_line = 5 + len(reference_acq_names)
            if selected_input_idx is not None:
                stdscr.addstr(base_line, 0, "Select Input Acquisition (UP/DOWN, ENTER=confirm, LEFT=cancel):")
                for i, in_acq_name in enumerate(input_acq_names):
                    marker = ">>" if i == selected_input_idx else "  "
                    # Show input acquisition plus some metadata
                    meta = input_acquisition_meta.get(in_acq_name, {})
                    proto_str = meta.get("ProtocolName", "N/A")
                    stdscr.addstr(base_line + 2 + i, 0, f"{marker} {in_acq_name} (ProtocolName={proto_str})")

            stdscr.refresh()
            key = stdscr.getch()

            # --- Navigation & actions ---
            if key == curses.KEY_UP:
                if selected_input_idx is None:
                    selected_ref_idx = max(0, selected_ref_idx - 1)
                else:
                    selected_input_idx = max(0, selected_input_idx - 1)
            elif key == curses.KEY_DOWN:
                if selected_input_idx is None:
                    selected_ref_idx = min(len(reference_acq_names) - 1, selected_ref_idx + 1)
                else:
                    selected_input_idx = min(len(input_acq_names) - 1, selected_input_idx + 1)
            elif key == curses.KEY_RIGHT and selected_input_idx is None:
                # Start selecting input acquisitions
                selected_input_idx = 0
            elif key == curses.KEY_LEFT and selected_input_idx is not None:
                # Cancel picking input
                selected_input_idx = None
            elif key == ord("u"):
                # Unmap the currently selected reference
                ref_acq = reference_acq_names[selected_ref_idx]
                if ref_acq in mapping:
                    del mapping[ref_acq]
            elif key == curses.KEY_ENTER or key == 10 or key == 13:
                # ENTER: if picking input, finalize assignment
                if selected_input_idx is not None:
                    ref_acq = reference_acq_names[selected_ref_idx]
                    in_acq = input_acq_names[selected_input_idx]
                    mapping[ref_acq] = in_acq
                    # Done picking input
                    selected_input_idx = None
                else:
                    # Not picking input, do nothing
                    pass
            elif key == ord("q"):
                # Quit
                break

    curses.wrapper(run_curses)

    # Return a simple dictionary: { reference_acquisition: input_acquisition }
    return mapping

def interactive_mapping_to_python_reference(in_session_df: pd.DataFrame, ref_models: dict, initial_mapping=None):
    """
    Interactive CLI for mapping input acquisitions to Python module references.

    Notes:
        - Designed for Python module-based validation where mappings are at the acquisition level.
        - Provides an interactive terminal interface for adjusting mappings.
        - Displays available input acquisitions for selection.

    Args:
        in_session_df (pd.DataFrame): DataFrame of input session metadata.
        ref_models (dict): Dictionary of reference validation models keyed by acquisition names.
        initial_mapping (dict, optional): Initial mapping to use as a starting point.

    Returns:
        dict: Final mapping of reference acquisitions -> input acquisitions.
    """
    # Prepare input acquisitions
    input_acquisitions = {
        ("input", acq_name): in_session_df[in_session_df["Acquisition"] == acq_name]
        for acq_name in in_session_df["Acquisition"].unique()
    }

    # Prepare reference acquisitions from models
    reference_acquisitions = {
        ("reference", ref_acq_name): ref_model
        for ref_acq_name, ref_model in ref_models.items()
    }

    # Initialize the mapping (reference -> input)
    mapping = {}
    if initial_mapping:
        # Normalize the keys in the initial mapping to include prefixes
        for ref_key, input_key in initial_mapping.items():
            normalized_ref_key = ("reference", ref_key)
            normalized_input_key = ("input", input_key)
            mapping[normalized_ref_key] = normalized_input_key

    # Reverse mapping for easy lookup of current assignments
    reverse_mapping = {v: k for k, v in mapping.items()}

    def format_mapping_table(ref_keys, mapping, current_idx):
        """
        Format the mapping table for display.

        Args:
            ref_keys (list): List of reference keys.
            mapping (dict): Current mapping of reference to input acquisitions.
            current_idx (int): Index of the currently selected reference acquisition.

        Returns:
            str: Formatted table as a string.
        """
        table = []
        for idx, ref_key in enumerate(ref_keys):
            ref_acq = ref_key[1]
            current_mapping = mapping.get(ref_key, "Unmapped")

            # Clean up input display
            if current_mapping != "Unmapped":
                input_acq = current_mapping[1]
                current_mapping = f"{input_acq}"

            # Add indicator for current selection
            row_indicator = ">>" if idx == current_idx else "  "
            table.append([row_indicator, ref_acq, current_mapping])

        return tabulate(table, headers=["", "Reference Acquisition", "Mapped Input Acquisition"], tablefmt="simple")

    def run_curses(stdscr):
        # Disable cursor
        curses.curs_set(0)

        # Track the selected reference and input indices
        selected_ref_idx = 0
        selected_input_idx = None

        while True:
            # Clear the screen
            stdscr.clear()

            # Format the mapping table
            ref_keys = list(reference_acquisitions.keys())
            table = format_mapping_table(ref_keys, mapping, selected_ref_idx)

            # Display the table
            stdscr.addstr(0, 0, "Reference Acquisitions (use UP/DOWN to select, ENTER to assign, 'u' to unmap):")
            stdscr.addstr(2, 0, table)

            # If a reference is selected, display the input acquisitions
            if selected_input_idx is not None:
                stdscr.addstr(len(ref_keys) + 4, 0, "Select Input Acquisition (use UP/DOWN, ENTER to confirm):")
                input_keys = list(input_acquisitions.keys())
                for idx, input_key in enumerate(input_keys):
                    marker = ">>" if idx == selected_input_idx else "  "
                    input_acq = input_key[1]
                    stdscr.addstr(len(ref_keys) + 6 + idx, 0, f"{marker} {input_acq}")

            # Refresh the screen
            stdscr.refresh()

            # Handle key inputs
            key = stdscr.getch()

            if key == curses.KEY_UP:
                if selected_input_idx is None:
                    selected_ref_idx = max(0, selected_ref_idx - 1)
                else:
                    selected_input_idx = max(0, selected_input_idx - 1)

            elif key == curses.KEY_DOWN:
                if selected_input_idx is None:
                    selected_ref_idx = min(len(ref_keys) - 1, selected_ref_idx + 1)
                else:
                    selected_input_idx = min(len(input_acquisitions) - 1, selected_input_idx + 1)

            elif key == ord("\n"):  # Enter key
                if selected_input_idx is not None:
                    ref_key = ref_keys[selected_ref_idx]
                    input_key = list(input_acquisitions.keys())[selected_input_idx]

                    # Update the mapping
                    mapping[ref_key] = input_key
                    reverse_mapping[input_key] = ref_key
                    selected_input_idx = None  # Reset input selection

                elif selected_input_idx is None:
                    # Move to input selection
                    selected_input_idx = 0

            elif key == ord("q"):  # Quit
                break

            elif key == ord("u") and selected_input_idx is None:
                # Unmap the currently selected reference
                ref_key = ref_keys[selected_ref_idx]
                if ref_key in mapping:
                    del mapping[ref_key]

    # Run the curses application
    curses.wrapper(run_curses)

    # Return the final mapping without prefixes
    return {ref_key[1]: input_key[1] for ref_key, input_key in mapping.items()}
