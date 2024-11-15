#!/usr/bin/env python

import json
import argparse
import pandas as pd
from tabulate import tabulate
from dcm_check import load_ref_json, load_dicom, get_compliance_summary, read_session

def get_compliance_summaries_json(json_ref: str, in_session: str, output_json: str = "compliance_report.json") -> pd.DataFrame:
    """
    Generate a compliance summary for each matched acquisition in an input DICOM session.

    Args:
        json_ref (str): Path to the JSON reference file.
        in_session (str): Directory path for the DICOM session.
        output_json (str): Path to save the JSON compliance summary report.

    Returns:
        pd.DataFrame: Compliance summary DataFrame.
    """
    # Step 1: Identify matched acquisitions and series in the session
    session_df = read_session(json_ref, in_session)
    grouped_compliance = {}

    # Step 2: Iterate over each matched acquisition-series pair
    for _, row in session_df.dropna(subset=["Acquisition"]).iterrows():
        acquisition = row["Acquisition"]
        series = row["Series"]
        first_dicom_path = row["First_DICOM"]
        
        try:
            # Step 3: Load the reference model for the matched acquisition and series
            reference_model = load_ref_json(json_ref, acquisition, series)

            # Step 4: Load DICOM values for the first DICOM in the series
            dicom_values = load_dicom(first_dicom_path)

            # Step 5: Run compliance check and gather results
            compliance_summary = get_compliance_summary(reference_model, dicom_values, acquisition, series)

            # Organize results in nested format without "Model_Name"
            if acquisition not in grouped_compliance:
                grouped_compliance[acquisition] = {"Acquisition": acquisition, "Series": []}
            
            if series:
                series_entry = next((g for g in grouped_compliance[acquisition]["Series"] if g["Name"] == series), None)
                if not series_entry:
                    series_entry = {"Name": series, "Parameters": []}
                    grouped_compliance[acquisition]["Series"].append(series_entry)
                for entry in compliance_summary:
                    entry.pop("Acquisition", None)
                    entry.pop("Series", None)
                series_entry["Parameters"].extend(compliance_summary)
            else:
                # If no series, add parameters directly under acquisition
                for entry in compliance_summary:
                    entry.pop("Acquisition", None)
                    entry.pop("Series", None)
                grouped_compliance[acquisition]["Parameters"] = compliance_summary

        except Exception as e:
            print(f"Error processing acquisition '{acquisition}' and series '{series}': {e}")

    # Convert the grouped data to a list for JSON serialization
    grouped_compliance_list = list(grouped_compliance.values())

    # Save grouped compliance summary to JSON
    with open(output_json, "w") as json_file:
        json.dump(grouped_compliance_list, json_file, indent=4)

    # Convert the compliance summary to a DataFrame for tabulated output
    compliance_df = pd.json_normalize(
        grouped_compliance_list,
        record_path=["Series", "Parameters"],
        meta=["Acquisition", ["Series", "Name"]],
        errors="ignore"
    )

    # Rename "Series.name" to "Series" and reorder columns
    compliance_df.rename(columns={"Series.Name": "Series"}, inplace=True)
    compliance_df = compliance_df[["Acquisition", "Series", "Parameter", "Value", "Expected"]]

    return compliance_df

def main():
    parser = argparse.ArgumentParser(description="Generate compliance summaries for a DICOM session based on JSON reference.")
    parser.add_argument("--json_ref", required=True, help="Path to the JSON reference file.")
    parser.add_argument("--in_session", required=True, help="Directory path for the DICOM session.")
    parser.add_argument("--output_json", default="compliance_report.json", help="Path to save the JSON compliance summary report.")
    args = parser.parse_args()

    # Generate compliance summaries
    compliance_df = get_compliance_summaries_json(args.json_ref, args.in_session, args.output_json)
    
    # Print formatted output with tabulate
    print(tabulate(compliance_df, headers="keys", tablefmt="simple"))

if __name__ == "__main__":
    main()
