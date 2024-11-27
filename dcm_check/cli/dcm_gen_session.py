#!/usr/bin/env python

import argparse
import json
import os
import sys
from typing import Optional, Dict, Union, Any
from dcm_check import load_dicom
import pandas as pd

class MissingFieldDict(dict):
    """Custom dictionary for formatting that returns 'N/A' for missing keys."""
    def __missing__(self, key):
        return "N/A"


def generate_json_ref(
    in_session_dir: Optional[str] = None,
    acquisition_fields=None,
    reference_fields=None,
    name_template="{ProtocolName}-{SeriesDescription}",
    dicom_files: Optional[Union[Dict[str, bytes], Any]] = None
):
    """Generate a JSON reference for DICOM compliance with at least one series per acquisition.

    Args:
        in_session_dir (Optional[str]): Directory containing DICOM files for the session.
        acquisition_fields (list): Fields to uniquely identify each acquisition.
        reference_fields (list): Fields to include in JSON reference with their values.
        name_template (str): Naming template for each acquisition series.
        dicom_files (Optional[Dict[str, bytes]]): In-memory dictionary of DICOM files.

    Returns:
        dict: JSON structure with acquisition data.
    """

    acquisitions = {}
    dicom_data = []

    # Ensure acquisition_fields and reference_fields are lists
    if isinstance(acquisition_fields, str):
        acquisition_fields = acquisition_fields.split(",")
    elif not isinstance(acquisition_fields, list):
        acquisition_fields = list(acquisition_fields)

    if isinstance(reference_fields, str):
        reference_fields = reference_fields.split(",")
    elif not isinstance(reference_fields, list):
        reference_fields = list(reference_fields)

    # Process either in_session_dir or dicom_files
    if dicom_files is not None:
        files_to_process = dicom_files.items()
    elif in_session_dir:
        files_to_process = [
            (os.path.join(root, file), None) for root, _, files in os.walk(in_session_dir)
            for file in files if file.endswith((".dcm", ".IMA"))
        ]
    else:
        raise ValueError("Either in_session_dir or dicom_files must be provided.")

    # Load and process each DICOM file
    for dicom_path, dicom_content in files_to_process:
        dicom_values = load_dicom(dicom_content or dicom_path)
        dicom_entry = {field: dicom_values.get(field, "N/A") for field in acquisition_fields + reference_fields if field in dicom_values}
        dicom_entry['dicom_path'] = dicom_path
        dicom_data.append(dicom_entry)

    # Convert collected DICOM data to a DataFrame
    dicom_df = pd.DataFrame(dicom_data)

    # Handle list-type entries for duplicate detection
    for field in acquisition_fields + reference_fields:
        if field not in dicom_df.columns:
            continue
        if dicom_df[field].apply(lambda x: isinstance(x, list)).any():
            dicom_df[field] = dicom_df[field].apply(lambda x: tuple(x) if isinstance(x, list) else x)

    # Sort and process the DataFrame
    dicom_df = dicom_df.sort_values(by=acquisition_fields + reference_fields).reset_index(drop=True)
    unique_series_df = dicom_df.drop_duplicates(subset=acquisition_fields)

    id = 1
    for _, unique_row in unique_series_df.iterrows():
        series_df = dicom_df[dicom_df[acquisition_fields].eq(unique_row[acquisition_fields]).all(axis=1)]
        unique_groups = {}

        # Ensure there is always at least one group
        if series_df.empty:
            series_df = pd.DataFrame([unique_row])

        # Create groups by reference field combinations
        for _, group_row in series_df.drop(columns=acquisition_fields).drop_duplicates().iterrows():
            group_values = tuple((field, group_row[field]) for field in reference_fields)
            if group_values not in unique_groups:
                unique_groups[group_values] = group_row['dicom_path']

        groups = []
        group_number = 1
        for group, ref_path in unique_groups.items():
            group_fields = [{"field": field, "value": value} for field, value in group]
            groups.append({
                "name": f"Series {group_number}",
                "fields": group_fields,
                "ref": ref_path
            })
            group_number += 1

        # Ensure there is at least one series
        if not groups:
            ref_path = series_df.iloc[0]['dicom_path']
            group_fields = [{"field": field, "value": unique_row[field]} for field in reference_fields]
            groups.append({
                "name": "Series 1",
                "fields": group_fields,
                "ref": ref_path
            })

        # Format the series name using the template
        try:
            series_name = name_template.format_map(MissingFieldDict(unique_row.to_dict()))
        except KeyError as e:
            print(f"Error formatting series name: Missing field '{e.args[0]}'.", file=sys.stderr)
            continue

        final_series_name = series_name if series_name not in acquisitions else f"{series_name}_{id}"
        id += 1

        # Add acquisition-level fields
        acquisition_fields_list = [{"field": field, "value": unique_row[field]} for field in acquisition_fields]

        # Always include series, even if reference fields are constant
        acquisitions[final_series_name] = {
            "ref": unique_row['dicom_path'],
            "fields": acquisition_fields_list,
            "series": groups
        }

    return {"acquisitions": acquisitions}



def main():
    parser = argparse.ArgumentParser(description="Generate a JSON reference for DICOM compliance.")
    parser.add_argument("--in_session_dir", required=True, help="Directory containing DICOM files for the session.")
    parser.add_argument("--out_json_ref", required=True, help="Path to save the generated JSON reference.")
    parser.add_argument("--acquisition_fields", nargs="+", required=True, help="Fields to uniquely identify each acquisition.")
    parser.add_argument("--reference_fields", nargs="+", required=True, help="Fields to include in JSON reference with their values.")
    parser.add_argument("--name_template", default="{ProtocolName}-{SeriesDescription}", help="Naming template for each acquisition series.")
    args = parser.parse_args()

    output = generate_json_ref(args.in_session_dir, args.acquisition_fields, args.reference_fields, args.name_template)

    # Write JSON to output file
    with open(args.out_json_ref, "w") as f:
        json.dump(output, f, indent=4)
    print(f"JSON reference saved to {args.out_json_ref}")

if __name__ == "__main__":
    main()
    