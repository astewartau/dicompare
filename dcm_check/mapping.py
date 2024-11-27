import pandas as pd
import re
import numpy as np
from tabulate import tabulate
from scipy.optimize import linear_sum_assignment

try:
    import curses
except ImportError:
    curses = None

MAX_DIFF_SCORE = 10  # Maximum allowed difference score for each field to avoid unmanageably large values

def levenshtein_distance(s1, s2):
    """
    Calculate the Levenshtein distance between two strings.
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
    """Calculate the difference between expected and actual values, with caps for large scores."""
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
    Calculate the difference score between a reference row and an input row.
    
    Args:
        ref_row (dict): A dictionary representing a reference acquisition or series.
        in_row (dict): A dictionary representing an input acquisition or series.

    Returns:
        float: Total difference score.
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

def map_session(in_session, ref_session):
    """
    Map an input session to a reference session to find the closest acquisitions and series
    using the Hungarian algorithm to minimize total cost.

    Args:
        in_session (dict): Input session data returned by `read_session`.
        ref_session (dict): Reference session data returned by `read_json_session`.

    Returns:
        dict: Mapping of (input_acquisition, input_series) -> (reference_acquisition, reference_series).
    """
    input_acquisitions = in_session["acquisitions"]
    reference_acquisitions = ref_session["acquisitions"]

    input_keys = []
    reference_keys = []
    cost_matrix = []

    # Prepare input and reference keys and calculate the cost matrix
    for in_acq_name, in_acq in input_acquisitions.items():
        in_acq_series = in_acq.get("series", [])
        for in_series in in_acq_series:
            in_key = (in_acq_name, in_series["name"])
            input_keys.append(in_key)

            row = []
            for ref_acq_name, ref_acq in reference_acquisitions.items():
                ref_acq_series = ref_acq.get("series", [])
                for ref_series in ref_acq_series:
                    ref_key = (ref_acq_name, ref_series["name"])
                    if ref_key not in reference_keys:
                        reference_keys.append(ref_key)

                    # Calculate the cost of assigning in_key to ref_key
                    acq_score = calculate_match_score(ref_acq, in_acq)
                    series_score = calculate_match_score(ref_series, in_series)
                    total_score = acq_score + series_score
                    row.append(total_score)

            cost_matrix.append(row)

    # Convert cost_matrix to a numpy array for processing
    cost_matrix = np.array(cost_matrix)

    # Solve the assignment problem using the Hungarian algorithm
    row_indices, col_indices = linear_sum_assignment(cost_matrix)

    # Create the mapping
    mapping = {}
    for row, col in zip(row_indices, col_indices):
        if row < len(input_keys) and col < len(reference_keys):
            mapping[input_keys[row]] = reference_keys[col]

    return mapping

def interactive_mapping(in_session, ref_session, initial_mapping=None):
    """
    Interactive CLI for customizing mappings from reference to input acquisitions/series.

    Args:
        in_session (dict): Input session data.
        ref_session (dict): Reference session data.
        initial_mapping (dict, optional): Initial mapping of reference to input acquisitions/series.

    Returns:
        dict: Final mapping of (reference_acquisition, reference_series) -> (input_acquisition, input_series).
    """
    # Prepare input and reference data
    input_series = {
        ("input", acq_name, series["name"]): series
        for acq_name, acq in in_session["acquisitions"].items()
        for series in acq.get("series", [])
    }

    reference_series = {
        ("reference", ref_acq_name, ref_series["name"]): ref_series
        for ref_acq_name, ref_acq in ref_session["acquisitions"].items()
        for ref_series in ref_acq.get("series", [])
    }

    # Initialize the mapping (reference -> input)
    mapping = {}
    if initial_mapping:
        # Normalize the keys in the initial mapping to include prefixes
        for ref_key, input_key in initial_mapping.items():
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
            current_mapping = mapping.get(ref_key, "Unmapped")

            # Clean up input display (remove 'input' prefix and show nicely)
            if current_mapping != "Unmapped":
                input_acq, input_series = current_mapping[1], current_mapping[2]
                current_mapping = f"{input_acq} - {input_series}"

            # Add indicator for current selection
            row_indicator = ">>" if idx == current_idx else "  "
            table.append([row_indicator, f"{ref_acq} - {ref_series}", current_mapping])

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
                # Clear the menu area to ensure no overlapping text
                stdscr.attron(curses.A_REVERSE)  # Turn on reversed colors
                menu_start_y = len(ref_keys) + 4
                menu_height = len(input_series) + 2  # Include "Unassign" option
                menu_width = curses.COLS - 1  # Use full screen width
                for i in range(menu_height):
                    stdscr.addstr(menu_start_y + i, 0, " " * menu_width)  # Fill with spaces

                # Draw the input selection menu
                stdscr.addstr(menu_start_y, 0, "Select Input Acquisition/Series (use UP/DOWN, ENTER to confirm):")
                stdscr.addstr(menu_start_y + 1, 0, "Unassign (None)" if selected_input_idx == -1 else "")
                input_keys = list(input_series.keys())
                for idx, input_key in enumerate(input_keys):
                    marker = ">>" if idx == selected_input_idx else "  "
                    input_acq, input_series_name = input_key[1], input_key[2]
                    stdscr.addstr(
                        menu_start_y + 2 + idx, 
                        0, 
                        f"{marker} {input_acq} - {input_series_name}", 
                        curses.A_REVERSE
                    )
                stdscr.attroff(curses.A_REVERSE)  # Turn off reversed colors

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
                # Move to input selection
                selected_input_idx = 0

            elif key == curses.KEY_LEFT and selected_input_idx is not None:
                # Move back to reference selection
                selected_input_idx = None

            elif key == ord("u") and selected_input_idx is None:
                # Unmap the currently selected reference
                ref_key = ref_keys[selected_ref_idx]
                if ref_key in mapping:
                    old_input_key = mapping[ref_key]
                    del mapping[ref_key]
                    del reverse_mapping[old_input_key]

            elif key == ord("\n"):  # Enter key
                if selected_input_idx is not None:
                    ref_key = ref_keys[selected_ref_idx]

                    if selected_input_idx == -1:  # Unassign option
                        # Unmap the selected reference if it is currently mapped
                        if ref_key in mapping:
                            old_input_key = mapping[ref_key]
                            del mapping[ref_key]
                            del reverse_mapping[old_input_key]
                    else:
                        input_key = list(input_series.keys())[selected_input_idx]

                        # Unmap the old reference for this input, if it exists
                        if input_key in reverse_mapping:
                            old_ref_key = reverse_mapping[input_key]
                            if old_ref_key != ref_key:  # Ensure we're not unmapping the currently selected reference
                                del mapping[old_ref_key]

                        # Unmap the old input for this reference, if it exists
                        if ref_key in mapping:
                            old_input_key = mapping[ref_key]
                            if old_input_key != input_key:  # Ensure we're not unmapping the current input
                                del reverse_mapping[old_input_key]

                        # Update the mapping
                        mapping[ref_key] = input_key
                        reverse_mapping[input_key] = ref_key

                    # Reset input selection
                    selected_input_idx = None

                elif selected_input_idx is None:
                    # If Enter is pressed while selecting a reference, move to input selection
                    selected_input_idx = 0

            elif key == ord("q"):  # Quit
                break

    # Run the curses application
    curses.wrapper(run_curses)

    # Remove prefixes from the final mapping before returning
    return {
        (ref_key[1], ref_key[2]): (input_key[1], input_key[2])
        for ref_key, input_key in mapping.items()
    }
