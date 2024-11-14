import os
import json
import pandas as pd
import argparse
import re
from dcm_check import load_dicom
from Levenshtein import distance as levenshtein_distance

def calculate_field_difference(expected, actual, tolerance=None, contains=None):
    """Calculate the difference between expected and actual values with support for tolerance and 'contains'."""
    # Pattern matching with wildcards
    if isinstance(expected, str) and ("*" in expected or "?" in expected):
        # Convert wildcard pattern to regex
        pattern = re.compile("^" + expected.replace("*", ".*").replace("?", ".") + "$")
        if pattern.match(actual):
            return 0  # Pattern matched, no difference
        return 5  # Pattern did not match, assign a fixed penalty
    
    if contains:
        # Check if actual value (list or string) contains the required substring or element
        if (isinstance(actual, str) and contains in actual) or (isinstance(actual, (list, tuple)) and contains in actual):
            return 0  # Contains requirement fulfilled, no difference
        else:
            return float("inf")  # Does not fulfill 'contains', assign max difference
    
    if tolerance is not None:
        # Check if actual value is within tolerance for numerical values
        try:
            expected_value = float(expected)
            actual_value = float(actual)
            if abs(expected_value - actual_value) <= tolerance:
                return 0  # Within tolerance, no difference
            return abs(expected_value - actual_value)  # Outside tolerance, compute absolute difference
        except ValueError:
            pass  # Fall back to regular difference if not numeric

    if isinstance(expected, (list, tuple)) or isinstance(actual, (list, tuple)):
        expected_tuple = tuple(expected) if not isinstance(expected, tuple) else expected
        actual_tuple = tuple(actual) if not isinstance(actual, tuple) else actual

        max_length = max(len(expected_tuple), len(actual_tuple))
        expected_padded = expected_tuple + ("",) * (max_length - len(expected_tuple))
        actual_padded = actual_tuple + ("",) * (max_length - len(actual_tuple))
        
        return sum(levenshtein_distance(str(e), str(a)) for e, a in zip(expected_padded, actual_padded))
    
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(expected - actual)
    
    return levenshtein_distance(str(expected), str(actual))

def calculate_total_difference(acquisition, dicom_entry):
    """Calculate the difference score between an acquisition reference and a DICOM entry."""
    diff_score = 0.0
    for field, expected_value in acquisition["fields"].items():
        actual_value = dicom_entry.get(field, "N/A")
        
        tolerance = acquisition.get("tolerance", {}).get(field)
        contains = acquisition.get("contains", {}).get(field)
        
        diff = min(10, calculate_field_difference(expected_value, actual_value, tolerance=tolerance, contains=contains))

        # Debugging: Log any mismatches and differences
        if diff > 0:
            print(f"Field '{field}': Expected '{expected_value}' vs Actual '{actual_value}', Diff = {diff}")

        diff_score += diff
    
    return diff_score

def find_closest_match(dicom_entry, acquisitions_info):
    """Find the closest matching acquisition and group for a given DICOM entry."""
    best_acquisition = None
    best_group = None
    best_score = float('inf')

    for acquisition in acquisitions_info:
        acq_name = acquisition["name"]
        acq_diff_score = calculate_total_difference(acquisition, dicom_entry)

        if acq_diff_score < best_score:
            best_acquisition = acq_name
            best_score = acq_diff_score
            best_group = None  # Reset group since we are re-evaluating for a new acquisition

            # Find closest group within this acquisition
            group_diffs = [
                (group["name"], calculate_total_difference(group, dicom_entry))
                for group in acquisition["groups"]
            ]
            if group_diffs:
                best_group_info = min(group_diffs, key=lambda x: x[1])
                best_group, group_diff_score = best_group_info
                best_score += group_diff_score  # Aggregate score with group diff
            else:
                print(f"No matching groups found for acquisition '{acq_name}'. Defaulting to acquisition-only match.")

    return best_acquisition, best_group, best_score

def read_session(reference_json, session_dir):
    """Read a session directory and map it to the closest acquisitions and groups in a reference JSON file."""
    with open(reference_json, 'r') as f:
        reference_data = json.load(f)
    
    # Extract acquisition and group fields, handling "value" or "contains"
    acquisitions_info = [
        {
            "name": acq_name,
            "fields": {field["field"]: field.get("value", field.get("contains")) for field in acquisition.get("fields", [])},
            "tolerance": {field["field"]: field["tolerance"] for field in acquisition.get("fields", []) if "tolerance" in field},
            "contains": {field["field"]: field["contains"] for field in acquisition.get("fields", []) if "contains" in field},
            "groups": [
                {
                    "name": group["name"], 
                    "fields": {field["field"]: field.get("value", field.get("contains")) for field in group.get("fields", [])},
                    "tolerance": {field["field"]: field["tolerance"] for field in group.get("fields", []) if "tolerance" in field},
                    "contains": {field["field"]: field["contains"] for field in group.get("fields", []) if "contains" in field}
                } 
                for group in acquisition.get("groups", [])
            ]
        }
        for acq_name, acquisition in reference_data.get("acquisitions", {}).items()
    ]
    
    # Collect all unique fields from acquisitions and groups
    acquisition_fields = {field for acq in acquisitions_info for field in acq["fields"].keys()}
    group_fields = {field for acq in acquisitions_info for group in acq["groups"] for field in group["fields"].keys()}
    all_fields = list(acquisition_fields | group_fields)

    session_data = []
    for root, _, files in os.walk(session_dir):
        for file in files:
            if file.endswith((".dcm", ".IMA")):
                dicom_path = os.path.join(root, file)
                dicom_values = load_dicom(dicom_path)
                
                dicom_entry = {field: tuple(dicom_values[field]) if isinstance(dicom_values.get(field), list) 
                               else dicom_values.get(field, "N/A") 
                               for field in all_fields}
                session_data.append(dicom_entry)

    unique_session_df = pd.DataFrame(session_data).drop_duplicates()

    acquisition_matches, group_matches, match_scores = [], [], []
    for _, row in unique_session_df.iterrows():
        acq_match, grp_match, match_score = find_closest_match(row, acquisitions_info)
        acquisition_matches.append(acq_match)
        group_matches.append(grp_match)
        match_scores.append(match_score)

    unique_session_df["Acquisition"] = acquisition_matches
    unique_session_df["Group"] = group_matches
    unique_session_df["Match_Score"] = match_scores

    unique_session_df.sort_values(["Acquisition", "Group", "Match_Score"], inplace=True)

    return unique_session_df

def main():
    parser = argparse.ArgumentParser(description="Map a DICOM session directory to a JSON reference file and print the closest acquisition and group matches.")
    parser.add_argument("--ref", required=True, help="Path to the reference JSON file.")
    parser.add_argument("--session_dir", required=True, help="Directory containing DICOM files for the session.")
    args = parser.parse_args()
    
    df = read_session(args.ref, args.session_dir)
    print(df)

if __name__ == "__main__":
    main()
