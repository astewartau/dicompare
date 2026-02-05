#!/usr/bin/env python

import sys
import json
import argparse
import logging
import pandas as pd

from dicompare.io import load_dicom_session, load_schema
from dicompare.io.json import make_json_serializable
from dicompare.schema import build_schema
from dicompare.validation import check_acquisition_compliance
from dicompare.validation.helpers import ComplianceStatus, create_compliance_record
from dicompare.session import map_to_json_reference, interactive_mapping_to_json_reference, assign_acquisition_and_run_numbers

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def build_command(args) -> None:
    """Generate a JSON schema from a DICOM session."""
    # Read DICOM session
    session_data = load_dicom_session(
        session_dir=args.dicoms,
        show_progress=True
    )

    # Generate JSON schema
    json_schema = build_schema(session_df=session_data)

    # Write JSON to output file
    serializable_schema = make_json_serializable(json_schema)
    with open(args.schema, "w") as f:
        json.dump(serializable_schema, f, indent=4)
    logger.info(f"JSON schema saved to {args.schema}")


def check_command(args) -> None:
    """Check a DICOM session against a schema for compliance."""
    # Load the schema
    reference_fields, json_schema, validation_rules = load_schema(json_schema_path=args.schema)

    # Load the input session
    in_session = load_dicom_session(
        session_dir=args.dicoms,
    )

    # Assign acquisition and series using canonical process
    in_session = assign_acquisition_and_run_numbers(in_session)

    # Map and perform compliance check
    session_map, cost_details = map_to_json_reference(in_session, json_schema, return_costs=True)

    # Display mapping summary with confidence
    logger.info("")
    logger.info("Acquisition Mapping:")
    logger.info("-" * 80)
    logger.info(f"  {'Reference':<30} {'Input':<30} {'Cost':>6}  {'Confidence'}")
    logger.info("-" * 80)
    for ref_acq in sorted(session_map.keys()):
        in_acq = session_map[ref_acq]
        cost = cost_details['assigned_costs'].get(ref_acq, float('nan'))
        if cost == 0:
            confidence = "exact"
        elif cost < 5:
            confidence = "high"
        elif cost < 20:
            confidence = "medium"
        else:
            confidence = "low"
        logger.info(f"  {ref_acq:<30} {in_acq:<30} {cost:>6.1f}  {confidence}")
    logger.info("-" * 80)
    logger.info("")

    if not args.auto_yes and sys.stdin.isatty():
        session_map = interactive_mapping_to_json_reference(in_session, json_schema, initial_mapping=session_map)

    # Check compliance for each acquisition
    compliance_summary = []
    for ref_acq_name, schema_acq in json_schema["acquisitions"].items():
        if ref_acq_name not in session_map:
            compliance_summary.append(create_compliance_record(
                field="Acquisition Mapping",
                message=f"Reference acquisition '{ref_acq_name}' is not mapped to any input acquisition.",
                status=ComplianceStatus.ERROR,
                expected=f"Acquisition '{ref_acq_name}' to be mapped"
            ))
            continue

        input_acq_name = session_map[ref_acq_name]
        acq_validation_rules = validation_rules.get(ref_acq_name) if validation_rules else None
        results = check_acquisition_compliance(
            in_session,
            schema_acq,
            acquisition_name=input_acq_name,
            validation_rules=acq_validation_rules
        )
        compliance_summary.extend(results)
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
        # Handle 'field' (single) or derive from 'expected' keys
        if entry.get('field'):
            logger.info(f"Field: {entry.get('field')}")
        elif entry.get('expected') and isinstance(entry.get('expected'), dict):
            logger.info(f"Fields: {list(entry.get('expected').keys())}")
        if entry.get('series'): logger.info(f"Series: {entry.get('series')}")
        if entry.get('expected') is not None: logger.info(f"Expected: {entry.get('expected')}")
        if entry.get('value') is not None: logger.info(f"Value: {entry.get('value')}")
        if entry.get('message'): logger.info(f"Message: {entry.get('message')}")
        logger.info("-" * 40)

    # Save compliance summary to JSON
    if args.report:
        with open(args.report, "w") as f:
            json.dump(compliance_summary, f, indent=4)
        logger.info(f"Compliance report saved to {args.report}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DICOM compliance validation tool",
        prog="dicompare"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Build subcommand
    build_parser = subparsers.add_parser(
        "build",
        help="Build a JSON schema from a DICOM session"
    )
    build_parser.add_argument(
        "dicoms",
        nargs="?",
        help="Directory containing DICOM files"
    )
    build_parser.add_argument(
        "schema",
        nargs="?",
        help="Output path for the JSON schema"
    )
    build_parser.add_argument(
        "--dicoms",
        dest="dicoms_named",
        metavar="PATH",
        help="Directory containing DICOM files"
    )
    build_parser.add_argument(
        "--schema",
        dest="schema_named",
        metavar="PATH",
        help="Output path for the JSON schema"
    )
    build_parser.add_argument(
        "--name-template",
        default="{ProtocolName}",
        help="Naming template for acquisitions (default: {ProtocolName})"
    )

    # Check subcommand
    check_parser = subparsers.add_parser(
        "check",
        help="Check a DICOM session against a schema"
    )
    check_parser.add_argument(
        "dicoms",
        nargs="?",
        help="Directory containing DICOM files to check"
    )
    check_parser.add_argument(
        "schema",
        nargs="?",
        help="Path to the JSON schema file"
    )
    check_parser.add_argument(
        "report",
        nargs="?",
        help="Output path for the compliance report"
    )
    check_parser.add_argument(
        "--dicoms",
        dest="dicoms_named",
        metavar="PATH",
        help="Directory containing DICOM files to check"
    )
    check_parser.add_argument(
        "--schema",
        dest="schema_named",
        metavar="PATH",
        help="Path to the JSON schema file"
    )
    check_parser.add_argument(
        "--report",
        dest="report_named",
        metavar="PATH",
        help="Output path for the compliance report"
    )
    check_parser.add_argument(
        "--auto-yes", "-y",
        action="store_true",
        help="Automatically map acquisitions without prompting"
    )

    # Match subcommand
    match_parser = subparsers.add_parser(
        "match",
        help="Find best-matching schemas for input DICOM data"
    )
    match_parser.add_argument(
        "dicoms",
        nargs="?",
        help="Directory containing DICOM files"
    )
    match_parser.add_argument(
        "--dicoms",
        dest="dicoms_named",
        metavar="PATH",
        help="Directory containing DICOM files"
    )
    match_parser.add_argument(
        "--schemas",
        nargs="+",
        metavar="PATH",
        help="Path(s) to schema files or directories containing schemas"
    )
    match_parser.add_argument(
        "--library",
        action="store_true",
        help="Include bundled schema library in search"
    )
    match_parser.add_argument(
        "--report",
        metavar="PATH",
        help="Output path for the match report (JSON)"
    )
    match_parser.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="Number of top matches to show per acquisition (default: 5)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve positional vs named arguments
    if args.command == "build":
        args.dicoms = args.dicoms or args.dicoms_named
        args.schema = args.schema or args.schema_named

        if not args.dicoms or not args.schema:
            build_parser.error("the following arguments are required: dicoms, schema")

        build_command(args)

    elif args.command == "check":
        args.dicoms = args.dicoms or args.dicoms_named
        args.schema = args.schema or args.schema_named
        args.report = args.report or args.report_named

        if not args.dicoms or not args.schema:
            check_parser.error("the following arguments are required: dicoms, schema")

        check_command(args)

    elif args.command == "match":
        from dicompare.cli.match import match_command

        args.dicoms = args.dicoms or args.dicoms_named

        if not args.dicoms:
            match_parser.error("the following arguments are required: dicoms")

        if not args.schemas and not args.library:
            match_parser.error("at least one of --schemas or --library is required")

        match_command(args)


if __name__ == "__main__":
    main()
