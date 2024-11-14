import os
import json
import pandas as pd
import argparse
import re
from dcm_check import load_dicom
from Levenshtein import distance as levenshtein_distance
from scipy.optimize import linear_sum_assignment

MAX_DIFF_SCORE = 10  # Maximum allowed difference score for each field to avoid unmanageably large values

def calculate_field_difference(expected, actual, tolerance=None, contains=None):
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


def calculate_total_difference(acquisition, dicom_entry):
    """Calculate the capped total difference score between an acquisition and a DICOM entry."""
    diff_score = 0.0
    for field, expected_value in acquisition["fields"].items():
        actual_value = dicom_entry.get(field, "N/A")
        tolerance = acquisition.get("tolerance", {}).get(field)
        contains = acquisition.get("contains", {}).get(field)
        diff = calculate_field_difference(expected_value, actual_value, tolerance=tolerance, contains=contains)
        diff_score += diff
    return diff_score



def find_closest_matches(session_df, acquisitions_info):
    """Compute minimal score assignments for acquisitions, handling unassigned rows."""
    cost_matrix = []
    possible_assignments = []

    for i, row in session_df.iterrows():
        row_costs = []
        row_assignments = []
        
        for acq_info in acquisitions_info:
            acq_name = acq_info["name"]
            acq_diff_score = calculate_total_difference(acq_info, row)

            if not acq_info["groups"]:  # Acquisitions without groups (assign group as None)
                row_costs.append(acq_diff_score)
                row_assignments.append((i, acq_name, None, acq_diff_score))
            else:
                for group in acq_info["groups"]:
                    group_name = group["name"]
                    group_diff_score = calculate_total_difference(group, row)
                    total_score = acq_diff_score + group_diff_score
                    row_costs.append(total_score)
                    row_assignments.append((i, acq_name, group_name, total_score))

        cost_matrix.append(row_costs)
        possible_assignments.append(row_assignments)

    cost_matrix = pd.DataFrame(cost_matrix)
    row_indices, col_indices = linear_sum_assignment(cost_matrix)

    best_acquisitions = [None] * len(session_df)
    best_groups = [None] * len(session_df)
    best_scores = [None] * len(session_df)  # Use NaN for unmatched scores

    for row_idx, col_idx in zip(row_indices, col_indices):
        _, acq_name, group_name, score = possible_assignments[row_idx][col_idx]
        best_acquisitions[row_idx] = acq_name
        best_groups[row_idx] = group_name
        best_scores[row_idx] = score if acq_name else None  # Only assign score if acquisition is matched

    return best_acquisitions, best_groups, best_scores


def read_session(reference_json, session_dir):
    with open(reference_json, 'r') as f:
        reference_data = json.load(f)
    
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
    
    all_fields = {field for acq in acquisitions_info for field in acq["fields"].keys()}
    all_fields.update({field for acq in acquisitions_info for group in acq["groups"] for field in group["fields"].keys()})

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

                if "InstanceNumber" in dicom_values and "InstanceNumber" not in dicom_entry:
                    dicom_entry["InstanceNumber"] = int(dicom_values["InstanceNumber"])

                session_data.append(dicom_entry)

    session_df = pd.DataFrame(session_data)

    # sort by InstanceNumber if available
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

    acquisitions, groups, scores = find_closest_matches(series_count_df, acquisitions_info)

    series_count_df["Acquisition"] = acquisitions
    series_count_df["Group"] = groups
    series_count_df["Match_Score"] = scores

    series_count_df.sort_values(["Acquisition", "Group", "Match_Score"], inplace=True)

    return series_count_df

def main():
    parser = argparse.ArgumentParser(description="Map a DICOM session directory to a JSON reference file and print the closest acquisition and group matches.")
    parser.add_argument("--ref", required=True, help="Path to the reference JSON file.")
    parser.add_argument("--session_dir", required=True, help="Directory containing DICOM files for the session.")
    args = parser.parse_args()
    
    df = read_session(args.ref, args.session_dir)
    
    # Save the results to a CSV file
    df.to_csv("output.csv", index=False)

    # drop First_DICOM and Count columns
    df.drop(columns=["First_DICOM", "Count"], inplace=True)
    print(df)

if __name__ == "__main__":
    main()
