import os
import json
import pandas as pd
import argparse
import re
import curses
from curses import wrapper
from dcm_check import load_dicom
from Levenshtein import distance as levenshtein_distance
from scipy.optimize import linear_sum_assignment

MAX_DIFF_SCORE = 10  # Maximum allowed difference score for each field to avoid unmanageably large values

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

def calculate_match_score(acquisition, series_row):
    """Calculate the capped total difference score between an acquisition and a DICOM entry."""
    diff_score = 0.0
    for field, expected_value in acquisition["fields"].items():
        actual_value = series_row.get(field, "N/A")
        tolerance = acquisition.get("tolerance", {}).get(field)
        contains = acquisition.get("contains", {}).get(field)
        diff = calculate_field_score(expected_value, actual_value, tolerance=tolerance, contains=contains)
        diff_score += diff
    return round(diff_score, 2)

def find_closest_matches(session_df, acquisitions_info):
    """Compute minimal score assignments for acquisitions, handling unassigned rows."""
    cost_matrix = []
    possible_assignments = []

    for i, row in session_df.iterrows():
        row_costs = []
        row_assignments = []
        
        for acq_info in acquisitions_info:
            acq_name = acq_info["name"]
            acq_match_score = calculate_match_score(acq_info, row)

            if not acq_info["series"]:  # Acquisitions without groups (assign group as None)
                row_costs.append(acq_match_score)
                row_assignments.append((i, acq_name, None, acq_match_score))
            else:
                for series in acq_info["series"]:
                    series_name = series["name"]
                    series_diff_score = calculate_match_score(series, row)
                    total_score = acq_match_score + series_diff_score
                    row_costs.append(total_score)
                    row_assignments.append((i, acq_name, series_name, total_score))

        cost_matrix.append(row_costs)
        possible_assignments.append(row_assignments)

    cost_matrix = pd.DataFrame(cost_matrix)
    row_indices, col_indices = linear_sum_assignment(cost_matrix)

    best_acquisitions = [None] * len(session_df)
    best_series = [None] * len(session_df)
    best_scores = [None] * len(session_df)  # Use NaN for unmatched scores

    for row_idx, col_idx in zip(row_indices, col_indices):
        _, acq_name, series_name, score = possible_assignments[row_idx][col_idx]
        best_acquisitions[row_idx] = acq_name
        best_series[row_idx] = series_name
        best_scores[row_idx] = score if acq_name else None  # Only assign score if acquisition is matched

    return best_acquisitions, best_series, best_scores

def read_session(reference_json, session_dir, return_acquisitions_info=False):
    """
    Read a DICOM session directory and map it to the closest acquisitions and series in a reference JSON file.

    Args:
        reference_json (str): Path to the JSON reference file.
        session_dir (str): Directory path containing DICOM files for the session.
        return_acquisitions_info (bool): If True, returns acquisitions_info for dynamic score recalculation.

    Returns:
        pd.DataFrame: DataFrame containing matched acquisitions and series with scores.
        acquisitions_info (optional): List of acquisitions and series info, used for score recalculation.
    """
    with open(reference_json, 'r') as f:
        reference_data = json.load(f)
    
    # Load acquisition and series configurations from JSON
    acquisitions_info = [
        {
            "name": acq_name,
            "fields": {field["field"]: field.get("value", field.get("contains")) for field in acquisition.get("fields", [])},
            "tolerance": {field["field"]: field["tolerance"] for field in acquisition.get("fields", []) if "tolerance" in field},
            "contains": {field["field"]: field["contains"] for field in acquisition.get("fields", []) if "contains" in field},
            "series": [
                {
                    "name": series["name"], 
                    "fields": {field["field"]: field.get("value", field.get("contains")) for field in series.get("fields", [])},
                    "tolerance": {field["field"]: field["tolerance"] for field in series.get("fields", []) if "tolerance" in field},
                    "contains": {field["field"]: field["contains"] for field in series.get("fields", []) if "contains" in field}
                } 
                for series in acquisition.get("series", [])
            ]
        }
        for acq_name, acquisition in reference_data.get("acquisitions", {}).items()
    ]
    
    # Collect all unique fields across acquisitions and series
    all_fields = {field for acq in acquisitions_info for field in acq["fields"].keys()}
    all_fields.update({field for acq in acquisitions_info for series in acq["series"] for field in series["fields"].keys()})

    session_data = []
    for root, _, files in os.walk(session_dir):
        for file in files:
            if file.endswith((".dcm", ".IMA")):
                dicom_path = os.path.join(root, file)
                dicom_values = load_dicom(dicom_path)
                
                dicom_entry = {field: tuple(dicom_values[field]) if isinstance(dicom_values.get(field), list) 
                               else dicom_values.get(field, "N/A") 
                               for field in all_fields}
                
                dicom_entry["DICOM_Path"] = dicom_path  # Store the DICOM path
                dicom_entry["InstanceNumber"] = int(dicom_values.get("InstanceNumber", 0))  # Add InstanceNumber if available

                session_data.append(dicom_entry)

    session_df = pd.DataFrame(session_data)

    # Sort by InstanceNumber or DICOM_Path
    if "InstanceNumber" in session_df.columns:
        session_df.sort_values("InstanceNumber", inplace=True)
    else:
        session_df.sort_values("DICOM_Path", inplace=True)
    
    # Group by unique series fields and calculate 'First_DICOM' and 'Count'
    dedup_fields = all_fields
    series_count_df = (
        session_df.groupby(list(dedup_fields))
        .agg(First_DICOM=('DICOM_Path', 'first'), Count=('DICOM_Path', 'size'))
        .reset_index()
    )

    # Find closest matches for each series and calculate scores
    acquisitions, series, scores = find_closest_matches(series_count_df, acquisitions_info)

    series_count_df["Acquisition"] = acquisitions
    series_count_df["Series"] = series
    series_count_df["Match_Score"] = scores


    # Order headers with fields associated with acquisition_info first, then fields associated with series
    acquisition_fields = {field for acq in acquisitions_info for field in acq["fields"].keys()}
    series_fields = {field for acq in acquisitions_info for series in acq["series"] for field in series["fields"].keys() if field not in acquisition_fields}
    ordered_headers = list(acquisition_fields) + list(series_fields) + ["First_DICOM", "Count", "Acquisition", "Series", "Match_Score"]
    series_count_df = series_count_df[ordered_headers]
    series_count_df.sort_values(["Acquisition", "Series", "Match_Score"], inplace=True)

    # Return the DataFrame and optionally acquisitions_info
    if return_acquisitions_info:
        return series_count_df, acquisitions_info
    return series_count_df

def interactive_mapping(df, acquisitions_info):
    """
    Launch an interactive CLI for adjusting acquisition mappings with dynamic match score updates.
    """
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

    wrapper(interactive_loop, df)
    return df

def main():
    parser = argparse.ArgumentParser(description="Map a DICOM session directory to a JSON reference file and print the closest acquisition and series matches.")
    parser.add_argument("--ref", required=True, help="Path to the JSON reference file.")
    parser.add_argument("--session_dir", required=True, help="Directory containing DICOM files for the session.")
    args = parser.parse_args()
    
    df, acquisitions_info = read_session(args.ref, args.session_dir, return_acquisitions_info=True)  # Adjusted read_session to return acquisitions_info
    # Drop First_DICOM and Count for display
    df.drop(columns=["First_DICOM", "Count"], inplace=True)

    # Interactive session
    print("Entering interactive mapping mode. Use arrow keys to navigate, Enter to select and move, and Esc to finish.")
    adjusted_df = interactive_mapping(df, acquisitions_info)
    
    # Display the adjusted dataframe
    print(adjusted_df)

if __name__ == "__main__":
    main()