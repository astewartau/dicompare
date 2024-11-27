from typing import Optional, Union, Dict, Any
import sys
import json
import argparse
import pandas as pd
from tabulate import tabulate
from dcm_check import load_ref_json, load_dicom, get_compliance_summary, read_session, interactive_mapping

def get_compliance_summaries_json(
    json_ref: str,
    in_session: Optional[str] = None,
    output_json: str = "compliance_report.json",
    interactive=True,
    dicom_bytes: Optional[Union[Dict[str, bytes], Any]] = None
) -> pd.DataFrame:
    """
    Generate a compliance summary for each matched acquisition in an input DICOM session.

    Args:
        json_ref (str): Path to the JSON reference file.
        in_session (Optional[str]): Directory path for the DICOM session.
        output_json (str): Path to save the JSON compliance summary report.
        interactive (bool): Flag to enable interactive mapping.
        dicom_bytes (Optional[Union[Dict[str, bytes], Any]]): Dictionary of DICOM byte content for processing.

    Returns:
        pd.DataFrame: Compliance summary DataFrame.
    """
    if dicom_bytes is not None:
        # Adjusted read_session to accept dicom_files instead of a directory path.
        session_df, acquisitions_info = read_session(json_ref, dicom_bytes=dicom_bytes, return_acquisitions_info=True)
    elif in_session is not None:
        session_df, acquisitions_info = read_session(json_ref, session_dir=in_session, return_acquisitions_info=True)
    else:
        raise ValueError("Either in_session or dicom_files must be provided.")

    grouped_compliance = {}

    if sys.stdin.isatty() and interactive:
        print("Entering interactive mapping mode. Use arrow keys to navigate, Enter to select and move, and Esc to finish.")
        session_df = interactive_mapping(session_df, acquisitions_info)

    for _, row in session_df.dropna(subset=["Acquisition"]).iterrows():
        acquisition = row["Acquisition"]
        series = row["Series"]
        first_dicom_path = row["First_DICOM"]
        dicom_binary = row["DICOM_Binary"]
        reference_model = load_ref_json(json_ref, acquisition, series)

        # If using dicom_files, use the dictionary content
        if dicom_binary:
            dicom_values = load_dicom(dicom_binary)
        else:
            dicom_values = load_dicom(first_dicom_path)

        compliance_summary = get_compliance_summary(reference_model, dicom_values, acquisition, series)

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
            for entry in compliance_summary:
                entry.pop("Acquisition", None)
                entry.pop("Series", None)
            grouped_compliance[acquisition]["Parameters"] = compliance_summary

    grouped_compliance_list = list(grouped_compliance.values())

    with open(output_json, "w") as json_file:
        json.dump(grouped_compliance_list, json_file, indent=4)

    compliance_issues = any(acq.get("Parameters") or any(series.get("Parameters") for series in acq.get("Series", [])) for acq in grouped_compliance_list)
    if not compliance_issues:
        return pd.DataFrame(columns=["Acquisition", "Series", "Parameter", "Value", "Expected"])
    
    # Processing compliance summary results
    compliance_rows = []
    for acquisition in grouped_compliance_list:
        acq_name = acquisition["Acquisition"]
        
        # Handle parameters without a series
        for param in acquisition.get("Parameters", []):
            compliance_rows.append({
                "Acquisition": acq_name,
                "Series": None,
                "Parameter": param["Parameter"],
                "Value": param.get("Value"),
                "Expected": param.get("Expected"),
            })
        
        # Handle parameters within each series
        for series in acquisition.get("Series", []):
            series_name = series["Name"]
            for param in series.get("Parameters", []):
                compliance_rows.append({
                    "Acquisition": acq_name,
                    "Series": series_name,
                    "Parameter": param["Parameter"],
                    "Value": param.get("Value"),
                    "Expected": param.get("Expected"),
                })

    # Create DataFrame directly from constructed rows
    compliance_df = pd.DataFrame(compliance_rows, columns=["Acquisition", "Series", "Parameter", "Value", "Expected"])

    # Save to JSON file
    compliance_df.to_json(output_json, orient="records", indent=4)
    
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
