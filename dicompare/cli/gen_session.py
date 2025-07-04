#!/usr/bin/env python

import argparse
import json
import logging
import pandas as pd
from typing import List, Dict, Any
from dicompare.io import load_dicom_session
from dicompare.generate_schema import create_json_schema

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a JSON schema for DICOM compliance.")
    parser.add_argument("--in_session_dir", required=True, help="Directory containing DICOM files for the session.")
    parser.add_argument("--out_json_schema", required=True, help="Path to save the generated JSON schema.")
    parser.add_argument("--reference_fields", nargs="+", required=True, help="Fields to include in JSON schema with their values.")
    parser.add_argument("--name_template", default="{ProtocolName}", help="Naming template for each acquisition series.")
    args = parser.parse_args()

    # Read DICOM session
    session_data = load_dicom_session(
        session_dir=args.in_session_dir,
        show_progress=True
    )

    # Generate JSON schema
    json_schema = create_json_schema(
        session_df=session_data,
        reference_fields=args.reference_fields
    )

    # Write JSON to output file
    with open(args.out_json_schema, "w") as f:
        json.dump(json_schema, f, indent=4)
    logger.info(f"JSON schema saved to {args.out_json_schema}")


if __name__ == "__main__":
    main()
