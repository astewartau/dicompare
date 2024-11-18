#!/usr/bin/env python

import sys
import json
import argparse
import pandas as pd
from tabulate import tabulate
from dcm_check import load_ref_json, load_dicom, get_compliance_summary, read_session, interactive_mapping

def get_compliance_summaries_json(json_ref: str, in_session: str, output_json: str = "compliance_report.json", interactive=True) -> pd.DataFrame:
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
    session_df, acquisitions_info = read_session(json_ref, in_session, return_acquisitions_info=True)
    grouped_compliance = {}

    # Step 2: Interactive mapping adjustment (if enabled by the user)
    if sys.stdin.isatty() and interactive:
        print("Entering interactive mapping mode. Use arrow keys to navigate, Enter to select and move, and Esc to finish.")
        session_df = interactive_mapping(session_df, acquisitions_info)

    # Step 3: Iterate over each matched acquisition-series pair
    for _, row in session_df.dropna(subset=["Acquisition"]).iterrows():
        acquisition = row["Acquisition"]
        series = row["Series"]
        first_dicom_path = row["First_DICOM"]
        
        try:
            # Load the reference model for the matched acquisition and series
            reference_model = load_ref_json(json_ref, acquisition, series)
            # Load DICOM values for the first DICOM in the series
            dicom_values = load_dicom(first_dicom_path)
            # Run compliance check and gather results
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

    # Check if there are any compliance issues to report (ie. if the 'Parameters' list is empty for all acquisitions)
    compliance_issues = any(acq.get("Parameters") or any(series.get("Parameters") for series in acq.get("Series", [])) for acq in grouped_compliance_list)
    print(compliance_issues)
    if not compliance_issues:
        return pd.DataFrame(columns=["Acquisition", "Series", "Parameter", "Value", "Expected"])
    
    # Step 6: Normalize into DataFrame
    df_with_series = pd.json_normalize(
        grouped_compliance_list,
        record_path=["Series", "Parameters"],
        meta=["Acquisition", ["Series", "Name"]],
        errors="ignore"
    )
    df_with_series.rename(columns={"Series.Name": "Series"}, inplace=True)
    df_with_series = df_with_series[["Acquisition", "Series", "Parameter", "Value", "Expected"]]

    # Normalize acquisitions without series directly
    df_without_series = pd.json_normalize(
        [acq for acq in grouped_compliance_list if "Parameters" in acq],
        record_path="Parameters",
        meta=["Acquisition"],
        errors="ignore"
    )
    df_without_series.insert(1, "Series", None)  # Add Series column with None values
    df_without_series = df_without_series[["Acquisition", "Series", "Parameter", "Value", "Expected"]]

    # Combine both DataFrames
    compliance_df = pd.concat([df_with_series, df_without_series], ignore_index=True)

    return compliance_df

def main():
    parser = argparse.ArgumentParser(description="Generate compliance summaries for a DICOM session based on JSON reference.")
    parser.add_argument("--json_ref", required=True, help="Path to the JSON reference file.")
    parser.add_argument("--in_session", required=True, help="Directory path for the DICOM session.")
    parser.add_argument("--output_json", default="compliance_report.json", help="Path to save the JSON compliance summary report.")
    parser.add_argument("--auto_yes", action="store_true", help="Automatically map acquisitions to series.")
    args = parser.parse_args()

    # Generate compliance summaries with interactive mapping
    compliance_df = get_compliance_summaries_json(args.json_ref, args.in_session, args.output_json, not args.auto_yes)

    # if compliance_df is empty, print message and exit
    if compliance_df.empty:
        print("Session is fully compliant with the reference model.")
        return
    
    # Print formatted output with tabulate
    print(tabulate(compliance_df, headers="keys", tablefmt="simple"))

if __name__ == "__main__":
    main()
