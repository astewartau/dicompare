import sys
import json
import argparse
import pandas as pd
from tabulate import tabulate

from dicompare.io import read_json_session, load_python_module, read_dicom_session
from dicompare.compliance import check_session_compliance, check_session_compliance_python_module
from dicompare.mapping import map_session, interactive_mapping, interactive_mapping_2

def main():
    parser = argparse.ArgumentParser(description="Generate compliance summaries for a DICOM session.")
    parser.add_argument("--json_ref", help="Path to the JSON reference file.")
    parser.add_argument("--python_ref", help="Path to the Python module containing validation models.")
    parser.add_argument("--in_session", required=True, help="Directory path for the DICOM session.")
    parser.add_argument("--out_json", default="compliance_report.json", help="Path to save the JSON compliance summary report.")
    parser.add_argument("--auto_yes", action="store_true", help="Automatically map acquisitions to series.")
    args = parser.parse_args()

    if not (args.json_ref or args.python_ref):
        raise ValueError("You must provide either --json_ref or --python_ref.")

    # Load the reference models and fields
    if args.json_ref:
        acquisition_fields, reference_fields, ref_session = read_json_session(json_ref=args.json_ref)
    elif args.python_ref:
        acquisition_fields, reference_fields, ref_models = load_python_module(module_path=args.python_ref)

    # Load the input session
    in_session = read_dicom_session(
        session_dir=args.in_session,
        acquisition_fields=acquisition_fields,
        reference_fields=reference_fields
    )
    
    if args.json_ref:
        session_map = map_session(in_session, ref_session)
        if not args.auto_yes and sys.stdin.isatty():
            session_map = interactive_mapping(in_session, ref_session, initial_mapping=session_map)
    else:
        session_map = interactive_mapping_2(in_session, ref_models)
    

    # Perform compliance check
    if args.json_ref:
        compliance_summary = check_session_compliance(
            in_session=in_session,
            ref_session=ref_session,
            series_map=session_map
        )
    else:
        compliance_summary = check_session_compliance_python_module(
            in_session=in_session,
            ref_models=ref_models,
            acquisition_map=session_map
        )
    compliance_df = pd.DataFrame(compliance_summary)

    # If compliance_df is empty, print message and exit
    if compliance_df.empty:
        print("Session is fully compliant with the reference model.")
        return

    # Inline summary output
    for entry in compliance_summary:
        if entry.get('acquisition'): print(f"Acquisition: {entry.get('acquisition')}")
        if entry.get('field'): print(f"Field: {entry.get('field')}")
        if entry.get('value'): print(f"Value: {entry.get('value')}")
        if entry.get('rule'): print(f"Rule: {entry.get('rule')}")
        if entry.get('message'): print(f"Message: {entry.get('message')}")
        if entry.get('passed'): print(f"Passed: {entry.get('passed')}")
        print("-" * 40)

    # Save compliance summary to JSON
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(compliance_summary, f)

if __name__ == "__main__":
    main()

