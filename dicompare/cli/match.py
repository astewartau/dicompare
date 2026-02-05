"""
Match command: find best-matching schemas for input DICOM data.

Searches a library of schemas and ranks which acquisitions best match
each input acquisition, using compliance-based scoring consistent with
the dicompare web interface.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd

from dicompare.io import load_dicom_session, load_schema
from dicompare.session import assign_acquisition_and_run_numbers
from dicompare.validation import check_acquisition_compliance

logger = logging.getLogger(__name__)


def compute_compliance_score(
    in_session: pd.DataFrame,
    schema_acquisition: Dict[str, Any],
    acquisition_name: str,
    validation_rules: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Run compliance check and compute a pass/fail percentage score.

    Uses the same scoring formula as the web interface:
        score = pass_count / total_count * 100
    where total_count excludes 'na' statuses.

    Args:
        in_session: Input session DataFrame.
        schema_acquisition: Single acquisition definition from schema.
        acquisition_name: Name of the input acquisition to check.
        validation_rules: Optional validation rules for this acquisition.

    Returns:
        Dict with score (0-100), pass_count, fail_count, warning_count,
        total_count (excluding na), and na_count.
    """
    results = check_acquisition_compliance(
        in_session=in_session,
        schema_acquisition=schema_acquisition,
        acquisition_name=acquisition_name,
        validation_rules=validation_rules
    )

    pass_count = sum(1 for r in results if r.get('status') == 'ok')
    fail_count = sum(1 for r in results if r.get('status') == 'error')
    warning_count = sum(1 for r in results if r.get('status') == 'warning')
    na_count = sum(1 for r in results if r.get('status') in ('na', 'unknown'))
    total_count = len(results) - na_count

    score = round((pass_count / total_count) * 100, 1) if total_count > 0 else 0.0

    return {
        'score': score,
        'pass_count': pass_count,
        'fail_count': fail_count,
        'warning_count': warning_count,
        'total_count': total_count,
        'na_count': na_count,
    }


def load_schemas_from_paths(paths: List[str]) -> Dict[str, Tuple[List[str], Dict[str, Any], Dict[str, Any]]]:
    """
    Load schemas from file paths or directories.

    Args:
        paths: List of file paths or directory paths containing JSON schemas.

    Returns:
        Dict mapping schema_path -> (reference_fields, schema_dict, validation_rules)
    """
    schemas = {}
    for path_str in paths:
        p = Path(path_str)
        if p.is_file() and p.suffix == '.json':
            try:
                schemas[str(p)] = load_schema(str(p))
            except Exception as e:
                logger.warning(f"Failed to load schema {p}: {e}")
        elif p.is_dir():
            for json_file in sorted(p.glob("*.json")):
                if json_file.name == "index.json":
                    continue
                try:
                    schemas[str(json_file)] = load_schema(str(json_file))
                except Exception as e:
                    logger.warning(f"Failed to load schema {json_file}: {e}")
        else:
            logger.warning(f"Skipping {p}: not a JSON file or directory")
    return schemas


def match_command(args) -> None:
    """
    Find best-matching schemas for input DICOM data.

    For each input acquisition, checks against every acquisition in every
    loaded schema and ranks by compliance score.
    """
    # Load DICOM session
    logger.info(f"Loading DICOM session from {args.dicoms}...")
    in_session = load_dicom_session(session_dir=args.dicoms, show_progress=True)
    in_session = assign_acquisition_and_run_numbers(in_session)

    input_acquisitions = sorted(in_session["Acquisition"].unique())
    logger.info(f"Found {len(input_acquisitions)} input acquisition(s): {input_acquisitions}")

    # Load schemas
    all_schemas = {}

    if args.library:
        from dicompare.schemas import load_all_bundled_schemas
        bundled = load_all_bundled_schemas()
        for filename, schema_tuple in bundled.items():
            all_schemas[f"[library] {filename}"] = schema_tuple

    if args.schemas:
        user_schemas = load_schemas_from_paths(args.schemas)
        all_schemas.update(user_schemas)

    if not all_schemas:
        logger.error("No schemas loaded. Use --library for bundled schemas or --schemas <path>.")
        return

    logger.info(f"Loaded {len(all_schemas)} schema(s).")

    top_n = args.top

    # Compute scores: for each input acquisition x each schema acquisition
    all_match_results = {}

    for in_acq_name in input_acquisitions:
        matches = []

        for schema_id, (ref_fields, schema_dict, validation_rules) in all_schemas.items():
            schema_name = schema_dict.get('name', schema_id)

            for ref_acq_name, schema_acq in schema_dict.get('acquisitions', {}).items():
                acq_rules = validation_rules.get(ref_acq_name) if validation_rules else None

                try:
                    score_info = compute_compliance_score(
                        in_session=in_session,
                        schema_acquisition=schema_acq,
                        acquisition_name=in_acq_name,
                        validation_rules=acq_rules
                    )
                except Exception as e:
                    logger.debug(f"Error scoring {in_acq_name} vs {schema_name}/{ref_acq_name}: {e}")
                    continue

                matches.append({
                    'schema_source': schema_id,
                    'schema_name': schema_name,
                    'ref_acquisition': ref_acq_name,
                    'score': score_info['score'],
                    'pass_count': score_info['pass_count'],
                    'fail_count': score_info['fail_count'],
                    'warning_count': score_info['warning_count'],
                    'total_count': score_info['total_count'],
                    'na_count': score_info['na_count'],
                })

        # Sort by score descending, then pass_count descending for ties
        matches.sort(key=lambda m: (m['score'], m['pass_count']), reverse=True)
        all_match_results[in_acq_name] = matches[:top_n]

    # Output results
    for in_acq_name in input_acquisitions:
        matches = all_match_results[in_acq_name]
        logger.info("")
        logger.info(f"=== {in_acq_name} ===")
        logger.info(f"  {'#':<4} {'Score':>6} {'Pass/Total':>12}  {'Schema':<30} {'Acquisition'}")
        logger.info("  " + "-" * 90)

        for rank, match in enumerate(matches, 1):
            pass_total = f"{match['pass_count']}/{match['total_count']}"
            schema_display = match['schema_name']
            if len(schema_display) > 28:
                schema_display = schema_display[:25] + "..."

            logger.info(
                f"  {rank:<4} {match['score']:>5.1f}% {pass_total:>12}  "
                f"{schema_display:<30} {match['ref_acquisition']}"
            )

        if not matches:
            logger.info("  No matching schemas found.")

    # Save report if requested
    if hasattr(args, 'report') and args.report:
        report_data = {}
        for in_acq_name, matches in all_match_results.items():
            report_data[in_acq_name] = matches

        with open(args.report, "w") as f:
            json.dump(report_data, f, indent=2)
        logger.info(f"\nMatch report saved to {args.report}")
