import sys
import json
import argparse
import logging
import pandas as pd
from typing import List, Dict, Any

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

from dicompare.io import load_json_schema, load_python_schema, load_dicom_session
from dicompare.compliance import check_session_compliance_with_json_reference, check_session_compliance_with_python_module
from dicompare.mapping import map_to_json_reference, interactive_mapping_to_json_reference, interactive_mapping_to_python_reference
from dicompare.data_utils import standardize_session_dataframe

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate compliance summaries for a DICOM session.")
    parser.add_argument("--json_schema", help="Path to the JSON schema file.")
    parser.add_argument("--python_schema", help="Path to the Python module containing validation models.")
    parser.add_argument("--in_session", required=True, help="Directory path for the DICOM session.")
    parser.add_argument("--out_json", default="compliance_report.json", help="Path to save the JSON compliance summary report.")
    parser.add_argument("--auto_yes", action="store_true", help="Automatically map acquisitions to series.")
    args = parser.parse_args()

    if not (args.json_schema or args.python_schema):
        raise ValueError("You must provide either --json_schema or --python_schema.")

    # Load the schema models and fields
    if args.json_schema:
        reference_fields, json_schema = load_json_schema(json_schema_path=args.json_schema)
    elif args.python_schema:
        py_schema = load_python_schema(module_path=args.python_schema)
    acquisition_fields = ["ProtocolName"]

    # Load the input session
    in_session = load_dicom_session(
        session_dir=args.in_session,
        acquisition_fields=acquisition_fields,
    )

    if args.json_schema:
        # Standardize session DataFrame 
        in_session = standardize_session_dataframe(in_session, reference_fields)
        in_session.reset_index(drop=True, inplace=True)
        
        # Group by acquisition fields to create Series labels starting from 1 for each acquisition
        in_session["Series"] = (
            in_session.groupby(acquisition_fields).apply(
                lambda group: group.groupby(reference_fields, dropna=False).ngroup().add(1)
            ).reset_index(level=0, drop=True)  # Reset multi-index back to DataFrame
        ).apply(lambda x: f"Series {x}")
        # Sort by acquisition, then series, then all other fields
        in_session.sort_values(by=["Acquisition", "Series"] + acquisition_fields + reference_fields, inplace=True)


    if args.json_schema:
        session_map = map_to_json_reference(in_session, json_schema)
        if not args.auto_yes and sys.stdin.isatty():
            session_map = interactive_mapping_to_json_reference(in_session, json_schema, initial_mapping=session_map)
    else:
        session_map = interactive_mapping_to_python_reference(in_session, py_schema)
    

    # Perform compliance check
    if args.json_schema:
        compliance_summary = check_session_compliance_with_json_reference(
            in_session=in_session,
            ref_session=json_schema,
            session_map=session_map
        )
    else:
        compliance_summary = check_session_compliance_with_python_module(
            in_session=in_session,
            ref_models=py_schema,
            session_map=session_map
        )
    compliance_df = pd.DataFrame(compliance_summary)

    # If compliance_df is empty, log message and exit
    if compliance_df.empty:
        logger.info("Session is fully compliant with the schema model.")
        return

    # Inline summary output
    for entry in compliance_summary:
        if entry.get('input acquisition'):
            acq_text = f"Acquisition: {entry.get('input acquisition')}"
            if entry.get('reference acquisition'):
                acq_text += f" ({entry.get('reference acquisition')})"
            logger.info(acq_text)
        if entry.get('input series'): logger.info(f"Series: {entry.get('input series')}")
        if entry.get('field'): logger.info(f"Field: {entry.get('field')}")
        if entry.get('series'): logger.info(f"Series: {entry.get('series')}")
        if entry.get('expected'): logger.info(f"Expected: {entry.get('expected')}")
        if entry.get('value'): logger.info(f"Value: {entry.get('value')}")
        if entry.get('message'): logger.info(f"Message: {entry.get('message')}")
        if entry.get('passed'): logger.info(f"Passed: {entry.get('passed')}")
        logger.info("-" * 40)

    # Save compliance summary to JSON
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(compliance_summary, f)

if __name__ == "__main__":
    main()

