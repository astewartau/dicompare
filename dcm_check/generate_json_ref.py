#!/usr/bin/env python

import argparse
import json
import os
import sys
from dcm_check import load_dicom
from collections import defaultdict
import pandas as pd

class MissingFieldDict(dict):
    """Custom dictionary for formatting that returns 'N/A' for missing keys."""
    def __missing__(self, key):
        return "N/A"

def generate_json_ref(in_session_dir, out_json_ref, acquisition_fields, reference_fields, name_template):
    acquisitions = {}
    dicom_data = []

    print(f"Generating JSON reference for DICOM files in {in_session_dir}")

    # Walk through all files in the specified session directory
    for root, _, files in os.walk(in_session_dir):
        for file in files:
            if not (file.endswith(".dcm") or file.endswith(".IMA")):
                continue  # Skip non-DICOM files

            dicom_path = os.path.join(root, file)
            dicom_values = load_dicom(dicom_path)

            # Store the data for easier handling with pandas
            dicom_entry = {field: dicom_values.get(field, "N/A") for field in acquisition_fields + reference_fields}
            dicom_entry['dicom_path'] = dicom_path
            dicom_data.append(dicom_entry)

    # Convert collected DICOM data to a DataFrame
    dicom_df = pd.DataFrame(dicom_data)

    # Handle list-type entries for duplicate detection
    for field in acquisition_fields + reference_fields:
        if field not in dicom_df.columns:
            print(f"Error: Field '{field}' not found in DICOM data.", file=sys.stderr)
            continue
        if dicom_df[field].apply(lambda x: isinstance(x, list)).any():
            dicom_df[field] = dicom_df[field].apply(lambda x: tuple(x) if isinstance(x, list) else x)

    # Drop duplicates based on unique fields
    unique_series_df = dicom_df.drop_duplicates(subset=acquisition_fields)

    print(f"Found {len(unique_series_df)} unique series in {in_session_dir}")

    # Iterate over unique series in the DataFrame
    id = 1
    for _, unique_row in unique_series_df.iterrows():
        # Filter rows that match the unique fields in this row
        series_df = dicom_df[dicom_df[acquisition_fields].eq(unique_row[acquisition_fields]).all(axis=1)]

        # Dictionary to store unique groups of reference fields
        unique_groups = {}

        # Group by reference field combinations and gather representative paths
        for _, group_row in series_df.drop(columns=acquisition_fields).drop_duplicates().iterrows():
            # Create a tuple for the current field combination
            group_values = tuple((field, group_row[field]) for field in reference_fields)

            # Check if this combination is already stored
            if group_values not in unique_groups:
                unique_groups[group_values] = group_row['dicom_path']

        # Format the series name based on the template using MissingFieldDict to handle missing keys
        try:
            series_name = name_template.format_map(MissingFieldDict(unique_row.to_dict()))
        except KeyError as e:
            print(f"Error formatting series name: Missing field '{e.args[0]}'.", file=sys.stderr)
            continue

        # Ensure series_name is unique by appending an index if necessary
        final_series_name = series_name if series_name not in acquisitions else f"{series_name}_{id}"
        id += 1

        # Convert unique groups back into the desired JSON structure
        groups = [
            {
                "fields": [{"field": field, "value": value} for field, value in group],
                "example": example_path
            }
            for group, example_path in unique_groups.items()
        ]

        # Add each unique series to acquisitions with grouped field combinations
        acquisitions[final_series_name] = {
            "ref": unique_row['dicom_path'],  # Reference the first DICOM file for this unique series
            "groups": groups
        }

    # Build the JSON output structure
    output = {
        "acquisitions": acquisitions
    }

    # Write JSON to output file
    with open(out_json_ref, "w") as f:
        json.dump(output, f, indent=4)
    print(f"JSON reference saved to {out_json_ref}")



def main():
    parser = argparse.ArgumentParser(description="Generate a JSON reference for DICOM compliance.")
    parser.add_argument("--in_session_dir", required=True, help="Directory containing DICOM files for the session.")
    parser.add_argument("--out_json_ref", required=True, help="Path to save the generated JSON reference.")
    parser.add_argument("--acquisition_fields", nargs="+", required=True, help="Fields to uniquely identify each acquisition.")
    parser.add_argument("--reference_fields", nargs="+", required=True, help="Fields to include in JSON reference with their values.")
    parser.add_argument("--name_template", default="{ProtocolName}-{SeriesDescription}", help="Naming template for each acquisition series.")
    args = parser.parse_args()

    generate_json_ref(args.in_session_dir, args.out_json_ref, args.acquisition_fields, args.reference_fields, args.name_template)

if __name__ == "__main__":
    main()
    