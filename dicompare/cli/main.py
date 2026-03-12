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

# Set up logging — only show warnings and errors; CLI output uses print()
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
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
    print(f"JSON schema saved to {args.schema}")


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
    print()
    print("Acquisition Mapping:")
    print("-" * 80)
    print(f"  {'Reference':<35} {'Input':<25} {'Cost':>6}  {'Confidence'}")
    print("-" * 80)
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
        ref_display = ref_acq[:33] + ".." if len(ref_acq) > 35 else ref_acq
        in_display = in_acq[:23] + ".." if len(in_acq) > 25 else in_acq
        print(f"  {ref_display:<35} {in_display:<25} {cost:>6.1f}  {confidence}")
    # Show unmapped reference acquisitions
    for ref_acq_name in json_schema["acquisitions"]:
        if ref_acq_name not in session_map:
            ref_display = ref_acq_name[:33] + ".." if len(ref_acq_name) > 35 else ref_acq_name
            print(f"  {ref_display:<35} {'(unmapped)':<25}     --  --")
    print("-" * 80)
    print()

    if not args.auto_yes and sys.stdin.isatty():
        session_map = interactive_mapping_to_json_reference(in_session, json_schema, initial_mapping=session_map)

    # Check compliance for each acquisition, grouped by ref acquisition
    compliance_summary = []
    acq_groups = []  # list of (display_name, results)

    unmapped_acquisitions = []

    for ref_acq_name, schema_acq in json_schema["acquisitions"].items():
        if ref_acq_name not in session_map:
            unmapped_acquisitions.append(ref_acq_name)
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
        display_name = f"{ref_acq_name}  ->  {input_acq_name}"
        acq_groups.append((display_name, results))

    # If no results at all
    if not compliance_summary and not unmapped_acquisitions:
        print("Session is fully compliant with the schema model.")
        return

    # Print compliance results
    verbose = getattr(args, 'verbose', False)

    for display_name, results in acq_groups:
        pass_count = sum(1 for r in results if r.get('status') == 'ok')
        fail_count = sum(1 for r in results if r.get('status') == 'error')
        warn_count = sum(1 for r in results if r.get('status') == 'warning')
        na_count = sum(1 for r in results if r.get('status') == 'na')
        total = len(results)

        print(f"=== {display_name} ===")
        parts = [f"{pass_count} passed"]
        if fail_count: parts.append(f"{fail_count} failed")
        if warn_count: parts.append(f"{warn_count} warnings")
        if na_count: parts.append(f"{na_count} n/a")
        print(f"  {', '.join(parts)} ({total} total)")
        print()

        for entry in results:
            status = entry.get('status', '')
            if not verbose and status == 'ok':
                continue

            field = entry.get('field', '')
            series = entry.get('series')
            value = entry.get('value')
            expected = entry.get('expected')
            message = entry.get('message', '')
            rule_name = entry.get('rule_name')

            status_label = {'ok': 'PASS', 'error': 'FAIL', 'warning': 'WARN', 'na': 'N/A'}.get(status, status.upper())

            location = field
            if series:
                location = f"{field} [{series}]"
            if rule_name:
                location = f"{rule_name}: {field}" if field else rule_name

            if status == 'ok' and value is not None:
                print(f"  [{status_label}] {location} ({value})")
            else:
                print(f"  [{status_label}] {location}")
            if expected is not None and status != 'ok':
                print(f"         expected: {expected}")
            if value is not None and status != 'ok':
                print(f"         got:      {value}")
            if message and status != 'ok' and message not in ('Passed.', 'OK'):
                print(f"         {message}")

        print()

    if unmapped_acquisitions:
        for acq_name in unmapped_acquisitions:
            print(f"  [WARN] Acquisition unmapped: '{acq_name}'")
        print()

    if not verbose:
        total_pass = sum(1 for r in compliance_summary if r.get('status') == 'ok')
        total_fail = sum(1 for r in compliance_summary if r.get('status') == 'error')
        if total_fail == 0 and not unmapped_acquisitions:
            print("All checks passed.")
        elif total_fail == 0:
            print("All compliance checks passed.")
        else:
            print(f"Use --verbose to see all {total_pass + total_fail} results including passes.")

    # Save compliance summary to JSON
    if args.report:
        with open(args.report, "w") as f:
            json.dump(compliance_summary, f, indent=4)
        print(f"Compliance report saved to {args.report}")


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
    check_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show all results including passes (default: only failures and warnings)"
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
