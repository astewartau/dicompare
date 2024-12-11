import sys
import json
import argparse
import pandas as pd

from dicompare.io import load_json_session, load_python_session, load_dicom_session
from dicompare.compliance import check_session_compliance_with_json_reference, check_session_compliance_with_python_module
from dicompare.mapping import map_to_json_reference, interactive_mapping_to_json_reference, interactive_mapping_to_python_reference

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
        acquisition_fields, reference_fields, ref_session = load_json_session(json_ref=args.json_ref)
    elif args.python_ref:
        ref_models = load_python_session(module_path=args.python_ref)
        acquisition_fields = ["ProtocolName"]

    # Load the input session
    in_session = load_dicom_session(
        session_dir=args.in_session,
        acquisition_fields=acquisition_fields,
    )

    if args.json_ref:
        # Group by all existing unique combinations of reference fields
        in_session = (
            in_session.groupby(reference_fields)
            .apply(lambda x: x.reset_index(drop=True))
            .reset_index(drop=True)  # Reset the index to avoid index/column ambiguity
        )

        # Assign unique group numbers for each combination of reference fields
        in_session["Series"] = (
            in_session.groupby(reference_fields, dropna=False).ngroup().add(1).apply(lambda x: f"Series {x}")
        )

    if args.json_ref:
        session_map = map_to_json_reference(in_session, ref_session)
        if not args.auto_yes and sys.stdin.isatty():
            session_map = interactive_mapping_to_json_reference(in_session, ref_session, initial_mapping=session_map)
    else:
        session_map = interactive_mapping_to_python_reference(in_session, ref_models)
    

    # Perform compliance check
    if args.json_ref:
        compliance_summary = check_session_compliance_with_json_reference(
            in_session=in_session,
            ref_session=ref_session,
            session_map=session_map
        )
    else:
        compliance_summary = check_session_compliance_with_python_module(
            in_session=in_session,
            ref_models=ref_models,
            session_map=session_map
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
