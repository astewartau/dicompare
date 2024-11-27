#!/usr/bin/env python

import argparse
import json
from dcm_check import read_dicom_session

def main():
    parser = argparse.ArgumentParser(description="Generate a JSON reference for DICOM compliance.")
    parser.add_argument("--in_session_dir", required=True, help="Directory containing DICOM files for the session.")
    parser.add_argument("--out_json_ref", required=True, help="Path to save the generated JSON reference.")
    parser.add_argument("--acquisition_fields", nargs="+", required=True, help="Fields to uniquely identify each acquisition.")
    parser.add_argument("--reference_fields", nargs="+", required=True, help="Fields to include in JSON reference with their values.")
    parser.add_argument("--name_template", default="{ProtocolName}-{SeriesDescription}", help="Naming template for each acquisition series.")
    args = parser.parse_args()

    # Read DICOM session
    session_data = read_dicom_session(
        reference_fields=args.reference_fields,
        session_dir=args.in_session_dir,
        acquisition_fields=args.acquisition_fields
    )

    # Write JSON to output file
    with open(args.out_json_ref, "w") as f:
        json.dump(session_data, f, indent=4)
    print(f"JSON reference saved to {args.out_json_ref}")

if __name__ == "__main__":
    main()

