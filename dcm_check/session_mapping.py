import pandas as pd
import re
import numpy as np
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

def interactive_mapping(df, acquisitions_info):
    """
    Launch an interactive CLI for adjusting acquisition mappings with dynamic match score updates.
    """
    if not curses:
        raise ImportError("curses module is not available. Please install it to use interactive mode.")
    
    def calculate_column_widths(df, padding=2):
        column_widths = {}
        for col in df.columns:
            max_content_width = max(len(str(x)) for x in df[col]) if len(df) > 0 else 10
            column_widths[col] = max(len(col), max_content_width) + padding
        return column_widths

    def draw_menu(stdscr, df, highlighted_row, column_widths, selected_values):
        stdscr.clear()
        h, w = stdscr.getmaxyx()  # Get the screen height and width

        # Calculate total row height and truncate rows if needed
        max_visible_rows = h - 2  # Leave space for header row and bottom navigation

        # Calculate column widths and truncate if they exceed screen width
        available_width = w - 2  # Start with screen width, adjusted for padding
        truncated_column_widths = {}
        for col_name in df.columns:
            # skip First_DICOM and Count columns
            if col_name in ["First_DICOM", "Count"]:
                continue
            col_width = min(column_widths[col_name], available_width)
            truncated_column_widths[col_name] = col_width
            available_width -= col_width
            if available_width <= 0:
                break  # No more space left for additional columns

        # Draw headers
        x = 2
        for col_name in truncated_column_widths.keys():
            header_text = col_name.ljust(truncated_column_widths[col_name])[:truncated_column_widths[col_name]]
            stdscr.addstr(1, x, header_text)
            x += truncated_column_widths[col_name]

        # Draw rows with Acquisition and Series columns highlighted
        visible_rows = df.iloc[:max_visible_rows]  # Limit to max visible rows
        for idx, row in visible_rows.iterrows():
            y = idx + 2
            x = 2
            for col_name in truncated_column_widths.keys():
                is_selected_column = col_name in ["Acquisition", "Series"] and idx == highlighted_row
                cell_text = str(selected_values[col_name] if is_selected_column and selected_values is not None else row[col_name]).ljust(truncated_column_widths[col_name])[:truncated_column_widths[col_name]]

                if is_selected_column:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(y, x, cell_text)
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(y, x, cell_text)
                x += truncated_column_widths[col_name]
        stdscr.refresh()


    def recalculate_match_score(row_idx, df, acquisitions_info):
        acquisition_name = df.at[row_idx, "Acquisition"]
        series_name = df.at[row_idx, "Series"]

        if pd.notna(acquisition_name):
            acquisition_info = next((acq for acq in acquisitions_info if acq["name"] == acquisition_name), None)
            if acquisition_info:
                if pd.notna(series_name):
                    series_info = next((series for series in acquisition_info["series"] if series["name"] == series_name), None)
                    if series_info:
                        score = calculate_match_score(acquisition_info, df.loc[row_idx]) + calculate_match_score(series_info, df.loc[row_idx])
                    else:
                        score = float('inf')
                else:
                    score = calculate_match_score(acquisition_info, df.loc[row_idx])
                return score
        return float('inf')
    
    def interactive_loop(stdscr, df):
        curses.curs_set(0)  # Hide the cursor
        highlighted_row = 0
        last_highlighted_row = 0
        selected_row = None
        selected_values = None
        column_widths = calculate_column_widths(df)

        while True:
            draw_menu(stdscr, df, highlighted_row, column_widths, selected_values)
            key = stdscr.getch()

            if key in [curses.KEY_UP, curses.KEY_DOWN]:
                # Store the last highlighted row before moving
                last_highlighted_row = highlighted_row
                highlighted_row += -1 if key == curses.KEY_UP else 1
                highlighted_row = max(0, min(len(df) - 1, highlighted_row))

                # If we're moving a selected assignment, perform a dynamic swap and recalculate scores
                if selected_values is not None:
                    # Swap values between the last and current highlighted rows
                    df.loc[last_highlighted_row, ["Acquisition", "Series"]], df.loc[highlighted_row, ["Acquisition", "Series"]] = (
                        df.loc[highlighted_row, ["Acquisition", "Series"]].values,
                        selected_values.values()
                    )
                    
                    # Recalculate and update match scores for both swapped rows
                    df.at[last_highlighted_row, "Match_Score"] = recalculate_match_score(last_highlighted_row, df, acquisitions_info)
                    df.at[highlighted_row, "Match_Score"] = recalculate_match_score(highlighted_row, df, acquisitions_info)

            elif key == 10:  # Enter key
                if selected_row is None:
                    # Start moving the selected assignment
                    selected_row = highlighted_row
                    selected_values = df.loc[selected_row, ["Acquisition", "Series"]].to_dict()
                    # Clear original position
                    df.loc[selected_row, ["Acquisition", "Series"]] = None
                else:
                    # Place assignment at the new position and deselect
                    df.loc[highlighted_row, ["Acquisition", "Series"]] = pd.Series(selected_values)
                    df.at[highlighted_row, "Match_Score"] = recalculate_match_score(highlighted_row, df, acquisitions_info)
                    selected_row = None
                    selected_values = None  # Reset selected values

            elif key == 27:  # ESC key
                # Exit the interactive loop
                break

    curses.wrapper(interactive_loop, df)
    return df
