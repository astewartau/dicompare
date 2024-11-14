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

def generate_json_ref(in_session_dir, out_json_ref, unique_fields, name_template):
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
            dicom_entry = {field: dicom_values.get(field, "N/A") for field in unique_fields}
            dicom_entry['dicom_path'] = dicom_path
            dicom_data.append(dicom_entry)

    # Convert collected DICOM data to a DataFrame
    dicom_df = pd.DataFrame(dicom_data)
    print(dicom_df)

    # Convert any list-type entries in unique_fields columns to tuples
    for field in unique_fields:
        if field not in dicom_df.columns:
            print(f"Error: Field '{field}' not found in DICOM data.", file=sys.stderr)
            continue
        if dicom_df[field].apply(lambda x: isinstance(x, list)).any():
            dicom_df[field] = dicom_df[field].apply(lambda x: tuple(x) if isinstance(x, list) else x)

    # Drop duplicates based on unique fields
    dicom_df = dicom_df.drop_duplicates(subset=unique_fields)

    print(f"Found {len(dicom_df)} unique series in {in_session_dir}")

    # Iterate over unique series in the DataFrame
    id = 1
    for idx, row in dicom_df.iterrows():
        # Create the unique key from unique_fields
        unique_key = tuple(row[field] for field in unique_fields)

        # Format the series name based on the template using MissingFieldDict to handle missing keys
        try:
            series_name = name_template.format_map(MissingFieldDict(row.to_dict()))
        except KeyError as e:
            print(f"Error formatting series name: Missing field '{e.args[0]}'.", file=sys.stderr)
            continue

        # Make sure the series_name is unique by appending an index if necessary
        final_series_name = series_name if series_name not in acquisitions else f"{series_name}_{id}"
        id += 1

        # Add each unique series to acquisitions
        acquisitions[final_series_name] = {
            "ref": row['dicom_path'],  # Reference the first DICOM file for this unique series
            "fields": [
                {"field": field, "value": row[field]} for field in unique_fields  # Include both the field name and value
            ],
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
    parser.add_argument("--unique_fields", nargs="+", required=True, help="Fields to uniquely identify each DICOM series.")
    parser.add_argument("--name_template", default="{ProtocolName}-{SeriesDescription}", help="Naming template for each acquisition series.")
    args = parser.parse_args()

    generate_json_ref(args.in_session_dir, args.out_json_ref, args.unique_fields, args.name_template)

if __name__ == "__main__":
    main()
