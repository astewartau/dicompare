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

    # Check if there are any compliance issues to report
    if not any(compliance.get("Parameters") for compliance in grouped_compliance_list):
        # Return an empty DataFrame with the expected columns if fully compliant
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
    args = parser.parse_args()

    # Generate compliance summaries
    compliance_df = get_compliance_summaries_json(args.json_ref, args.in_session, args.output_json)

    # if compliance_df is empty, print message and exit
    if compliance_df.empty:
        print("Session is fully compliant with the reference model.")
        return
    
    # Print formatted output with tabulate
    print(tabulate(compliance_df, headers="keys", tablefmt="simple"))

if __name__ == "__main__":
    main()
