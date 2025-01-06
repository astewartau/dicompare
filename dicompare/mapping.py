"""
This module provides functions for mapping DICOM input data to reference models (JSON or Python modules).

"""

import re
import numpy as np
import pandas as pd

from tabulate import tabulate
from scipy.optimize import linear_sum_assignment
from typing import List

try:
    import curses
except ImportError:
    curses = None

MAX_DIFF_SCORE = 10  # Maximum allowed difference score for each field to avoid unmanageably large values

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

def map_to_json_reference(in_session_df: pd.DataFrame, ref_session: dict) -> dict:
    """
    Automatically map input acquisitions/series to a JSON reference using the Hungarian algorithm.

    Notes:
        - Uses `calculate_field_score` to compute a cost matrix for mapping.
        - Assigns mappings to minimize total mapping cost.
        - Handles grouping and ranking of input series using unique combinations of fields.

    Args:
        in_session_df (pd.DataFrame): DataFrame of input session metadata.
        ref_session (dict): Reference session data in JSON format.

    Returns:
        dict: Mapping of (input_acquisition, input_series) -> (reference_acquisition, reference_series).
    """

    # Extract reference acquisitions and series fields
    reference_acquisitions = ref_session["acquisitions"]

    # Identify all unique series fields in the reference session
    series_fields = set()
    for ref_acq in reference_acquisitions.values():
        for series in ref_acq.get("series", []):
            for field in series.get("fields", []):
                series_fields.add(field["field"])
    series_fields = list(series_fields)

    # Prepare lists for input acquisitions + series and reference acquisitions + series
    input_acquisition_series = sorted(
        in_session_df[["Acquisition", "Series"]].drop_duplicates().values.tolist()
    )
    reference_acquisition_series = sorted(
        [
            (ref_acq_name, series["name"])
            for ref_acq_name, ref_acq in reference_acquisitions.items()
            for series in ref_acq.get("series", [])
        ]
    )

    # Initialize the cost matrix
    cost_matrix = []

    for in_acq, in_series in input_acquisition_series:
        # Filter input session DataFrame for the current acquisition and series
        input_series_df = in_session_df[
            (in_session_df["Acquisition"] == in_acq) & (in_session_df["Series"] == in_series)
        ]

        row = []
        for ref_acq, ref_series in reference_acquisition_series:
            # Find the reference series details
            ref_series_data = next(
                (series for series in reference_acquisitions[ref_acq]["series"] if series["name"] == ref_series),
                None,
            )
            if ref_series_data is None:
                row.append(np.inf)  # If no matching reference series, assign a high cost
                continue

            # Calculate the difference score for this mapping
            diff_score = 0.0
            for field in ref_series_data.get("fields", []):
                field_name = field["field"]
                expected_value = field.get("value")
                tolerance = field.get("tolerance")
                contains = field.get("contains")

                # Check the corresponding field in the input series DataFrame
                if field_name in input_series_df.columns:
                    actual_values = input_series_df[field_name].unique()
                    if len(actual_values) == 1:
                        actual_value = actual_values[0]
                    else:
                        actual_value = None  # Non-unique values are ambiguous
                else:
                    actual_value = None

                # Calculate the difference for this field
                diff = calculate_field_score(expected_value, actual_value, tolerance=tolerance, contains=contains)
                diff_score += diff

            row.append(diff_score)

        cost_matrix.append(row)

    # Convert cost_matrix to a numpy array for processing
    cost_matrix = np.array(cost_matrix)

    # Solve the assignment problem using the Hungarian algorithm
    row_indices, col_indices = linear_sum_assignment(cost_matrix)

    # Create the mapping
    mapping = {}
    for row, col in zip(row_indices, col_indices):
        if row < len(input_acquisition_series) and col < len(reference_acquisition_series):
            mapping[tuple(input_acquisition_series[row])] = tuple(reference_acquisition_series[col])

    return mapping

def interactive_mapping_to_json_reference(in_session_df: pd.DataFrame, ref_session: dict, initial_mapping=None):
    """
    Interactive CLI for mapping input acquisitions/series to JSON references.

    Notes:
        - Provides an interactive terminal interface for customizing mappings.
        - Allows users to assign, unassign, and modify mappings dynamically.
        - Displays reference and input series fields for context.

    Args:
        in_session_df (pd.DataFrame): DataFrame of input session metadata.
        ref_session (dict): Reference session data in JSON format.
        initial_mapping (dict, optional): Initial mapping to use as a starting point.

    Returns:
        dict: Final mapping of (reference_acquisition, reference_series) -> (input_acquisition, input_series).
    """

    # Prepare input series from the DataFrame with detailed identifiers
    input_series = {
        ("input", acq_name, series_name): in_session_df[
            (in_session_df["Acquisition"] == acq_name) & (in_session_df["Series"] == series_name)
        ].iloc[0].to_dict()  # Extract the first row as a dictionary
        for acq_name in in_session_df["Acquisition"].unique()
        for series_name in in_session_df[in_session_df["Acquisition"] == acq_name]["Series"].unique()
    }

    # Prepare reference series from the JSON/dict
    reference_series = {
        ("reference", ref_acq_name, ref_series["name"]): ref_series
        for ref_acq_name, ref_acq in ref_session["acquisitions"].items()
        for ref_series in ref_acq.get("series", [])
    }

    # Define series_fields from the reference session
    series_fields = set()
    for ref_acq in ref_session["acquisitions"].values():
        for series in ref_acq.get("series", []):
            for field in series.get("fields", []):
                series_fields.add(field["field"])
    series_fields = list(series_fields)

    # Initialize the mapping (reference -> input)
    mapping = {}
    if initial_mapping:
        # Normalize the keys in the initial mapping to include prefixes
        for input_key, ref_key in initial_mapping.items():
            normalized_ref_key = ("reference", ref_key[0], ref_key[1])
            normalized_input_key = ("input", input_key[0], input_key[1])
            mapping[normalized_ref_key] = normalized_input_key

    # Reverse mapping for easy lookup of current assignments
    reverse_mapping = {v: k for k, v in mapping.items()}

    def format_mapping_table(ref_keys, mapping, current_idx):
        """
        Format the mapping table for display.

        Args:
            ref_keys (list): List of reference keys.
            mapping (dict): Current mapping of reference to input series.
            current_idx (int): Index of the currently selected reference series.

        Returns:
            str: Formatted table as a string.
        """
        table = []
        for idx, ref_key in enumerate(ref_keys):
            ref_acq, ref_series = ref_key[1], ref_key[2]
            ref_series_data = reference_series[ref_key]

            def truncate_string(value, max_length=30):
                return value if len(value) <= max_length else value[:max_length] + "..."

            ref_identifiers = ", ".join( # TODO FIX NONE VALUES
                truncate_string(f"{field['field']}={field['value'] if 'value' in field else 'None'}", max_length=30)
                for field in ref_series_data.get("fields", [])
                if field["field"] in series_fields
            )
            
            current_mapping = mapping.get(ref_key, "Unmapped")
            
            # Handle input mapping
            if current_mapping != "Unmapped":
                input_acq, input_series_name = current_mapping[1], current_mapping[2]
                input_series_data = input_series.get(("input", input_acq, input_series_name), {})
                input_identifiers = ", ".join(
                    f"{key}={value}" for key, value in input_series_data.items()
                    if key in series_fields  # Only include fields that change between series
                )
                current_mapping = f"{input_acq} - {input_series_name} ({input_identifiers})"
            
            # Add indicator for current selection
            row_indicator = ">>" if idx == current_idx else "  "
            table.append([row_indicator, f"{ref_acq} - {ref_series} ({ref_identifiers})", current_mapping])

        return tabulate(table, headers=["", "Reference Series", "Mapped Input Series"], tablefmt="simple")


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
            ref_keys = list(reference_series.keys())
            table = format_mapping_table(ref_keys, mapping, selected_ref_idx)

            # Display the table
            stdscr.addstr(0, 0, "Reference Acquisitions/Series (use UP/DOWN to select, ENTER to assign, 'u' to unmap):")
            stdscr.addstr(2, 0, table)

            # If a reference is selected, display the input acquisitions/series
            if selected_input_idx is not None:
                stdscr.addstr(
                    len(ref_keys) + 4, 0, "Select Input Acquisition/Series (use UP/DOWN, ENTER to confirm):"
                )
                stdscr.addstr(len(ref_keys) + 5, 0, "Unassign (None)" if selected_input_idx == -1 else "")
                input_keys = list(input_series.keys())
                for idx, input_key in enumerate(input_keys):
                    marker = ">>" if idx == selected_input_idx else "  "
                    input_acq, input_series_name = input_key[1], input_key[2]
                    stdscr.addstr(len(ref_keys) + 6 + idx, 0, f"{marker} {input_acq} - {input_series_name}")

            # Refresh the screen
            stdscr.refresh()

            # Handle key inputs
            key = stdscr.getch()

            if key == curses.KEY_UP:
                if selected_input_idx is None:
                    selected_ref_idx = max(0, selected_ref_idx - 1)
                else:
                    selected_input_idx = max(-1, selected_input_idx - 1)

            elif key == curses.KEY_DOWN:
                if selected_input_idx is None:
                    selected_ref_idx = min(len(ref_keys) - 1, selected_ref_idx + 1)
                else:
                    selected_input_idx = min(len(input_series) - 1, selected_input_idx + 1)

            elif key == curses.KEY_RIGHT and selected_input_idx is None:
                selected_input_idx = 0

            elif key == curses.KEY_LEFT and selected_input_idx is not None:
                selected_input_idx = None

            elif key == ord("u") and selected_input_idx is None:
                ref_key = ref_keys[selected_ref_idx]
                if ref_key in mapping:
                    old_input_key = mapping[ref_key]
                    del mapping[ref_key]
                    del reverse_mapping[old_input_key]

            elif key == ord("\n"):
                if selected_input_idx is not None:
                    ref_key = ref_keys[selected_ref_idx]
                    input_key = list(input_series.keys())[selected_input_idx]
                    mapping[ref_key] = input_key
                    reverse_mapping[input_key] = ref_key
                    selected_input_idx = None

                elif selected_input_idx is None:
                    selected_input_idx = 0

            elif key == ord("q"):
                break

    curses.wrapper(run_curses)

    return {
        (ref_key[1], ref_key[2]): (input_key[1], input_key[2])
        for ref_key, input_key in mapping.items()
    }

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
