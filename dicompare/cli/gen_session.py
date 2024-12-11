#!/usr/bin/env python

import argparse
import json
import pandas as pd
from dicompare.io import load_dicom_session
from dicompare.utils import clean_string

def make_hashable(value):
    """
    Convert a value into a hashable format.
    Handles lists, dictionaries, and other non-hashable types.
    """
    if isinstance(value, list):
        return tuple(value)
    elif isinstance(value, dict):
        return tuple((k, make_hashable(v)) for k, v in value.items())
    elif isinstance(value, set):
        return tuple(sorted(make_hashable(v) for v in value))
    return value


def create_json_reference(session_df, acquisition_fields, reference_fields, name_template="{ProtocolName}-{SeriesDescription}"):
    """
    Create a JSON reference from the session DataFrame.

    Args:
        session_df (pd.DataFrame): DataFrame of the DICOM session.
        acquisition_fields (List[str]): Fields to uniquely identify each acquisition.
        reference_fields (List[str]): Fields to include in JSON reference.
        name_template (str): Naming template for acquisitions/series.

    Returns:
        dict: JSON structure representing the reference.
    """
    # Ensure all values in the DataFrame are hashable
    for col in session_df.columns:
        session_df[col] = session_df[col].apply(make_hashable)

    json_reference = {"acquisitions": {}}

    # Group by acquisition
    for acquisition_name, group in session_df.groupby("Acquisition"):
        acquisition_entry = {"fields": [], "series": []}

        # Add acquisition-level fields
        for field in acquisition_fields:
            unique_values = group[field].dropna().unique()
            if len(unique_values) == 1:
                acquisition_entry["fields"].append({"field": field, "value": unique_values[0]})

        # Group by series within each acquisition
        series_fields = list(set(reference_fields) - set(acquisition_fields))
        if series_fields:
            series_groups = group.groupby(series_fields, dropna=False)

            for i, (series_key, series_group) in enumerate(series_groups, start=1):
                series_entry = {
                    "name": f"Series {i}",
                    "fields": [{"field": field, "value": series_key[j]} for j, field in enumerate(series_fields)]
                }
                acquisition_entry["series"].append(series_entry)

        # Exclude reference fields from acquisition-level fields if they appear in series
        acquisition_entry["fields"] = [
            field for field in acquisition_entry["fields"] if field["field"] not in reference_fields
        ]

        # Add to JSON reference
        json_reference["acquisitions"][clean_string(acquisition_name)] = acquisition_entry

    return json_reference



def main():
    parser = argparse.ArgumentParser(description="Generate a JSON reference for DICOM compliance.")
    parser.add_argument("--in_session_dir", required=True, help="Directory containing DICOM files for the session.")
    parser.add_argument("--out_json_ref", required=True, help="Path to save the generated JSON reference.")
    parser.add_argument("--acquisition_fields", nargs="+", required=True, help="Fields to uniquely identify each acquisition.")
    parser.add_argument("--reference_fields", nargs="+", required=True, help="Fields to include in JSON reference with their values.")
    parser.add_argument("--name_template", default="{ProtocolName}-{SeriesDescription}", help="Naming template for each acquisition series.")
    args = parser.parse_args()

    # Read DICOM session
    session_data = load_dicom_session(
        session_dir=args.in_session_dir,
        acquisition_fields=args.acquisition_fields,
    )

    # Filter fields in DataFrame
    relevant_fields = set(args.acquisition_fields + args.reference_fields)
    session_data = session_data[list(relevant_fields.intersection(session_data.columns)) + ["Acquisition"]]

    # Generate JSON reference
    json_reference = create_json_reference(
        session_df=session_data,
        acquisition_fields=args.acquisition_fields,
        reference_fields=args.reference_fields,
        name_template=args.name_template,
    )

    # Write JSON to output file
    with open(args.out_json_ref, "w") as f:
        json.dump(json_reference, f, indent=4)
    print(f"JSON reference saved to {args.out_json_ref}")


if __name__ == "__main__":
    main()
