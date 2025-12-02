"""
Acquisition identification and labeling for DICOM sessions.

This module provides functions for assigning acquisition and run numbers to DICOM sessions
in a clean, single-pass approach that builds complete acquisition signatures upfront
rather than iteratively splitting and reassigning.
"""

import pandas as pd
import logging
import warnings
from typing import List, Optional

from ..config import DEFAULT_SETTINGS_FIELDS, DEFAULT_SERIES_FIELDS
from ..utils import clean_string, make_hashable
from ..data_utils import make_dataframe_hashable

logger = logging.getLogger(__name__)


def _dicom_time_to_seconds(time_str):
    """
    Convert DICOM time string (HHMMSS or HHMMSS.FFFFFF) to seconds.

    Args:
        time_str: DICOM time string

    Returns:
        float: Time in seconds since midnight
    """
    if pd.isna(time_str) or time_str == '':
        return 0

    # Handle string type
    if isinstance(time_str, str):
        # Remove fractional seconds if present
        time_str = time_str.split('.')[0]
        # Pad with zeros if needed
        time_str = time_str.ljust(6, '0')

        hours = int(time_str[0:2])
        minutes = int(time_str[2:4])
        seconds = int(time_str[4:6])

        return hours * 3600 + minutes * 60 + seconds

    # If it's already numeric, return as is
    return float(time_str)


def _normalize_series_description_for_run_detection(series_desc):
    """
    Normalize SeriesDescription for run detection by removing _RR suffixes.

    Siemens scanners append '_RR' suffixes to SeriesDescription during image export.
    This can cause images from the same acquisition to have different SeriesDescriptions,
    breaking run detection. This function strips these suffixes so that runs can be
    properly grouped.

    Args:
        series_desc: SeriesDescription string

    Returns:
        str: Normalized SeriesDescription with trailing _RR patterns removed

    Examples:
        't2star_qsm_tra_p3_224_Iso1mm_5TEs_RR' -> 't2star_qsm_tra_p3_224_Iso1mm_5TEs'
        't2star_qsm_tra_p3_224_Iso1mm_5TEs_RR_RR' -> 't2star_qsm_tra_p3_224_Iso1mm_5TEs'
        't2star_qsm_tra_p3_224_Iso1mm_5TEs' -> 't2star_qsm_tra_p3_224_Iso1mm_5TEs'
    """
    import re
    if pd.isna(series_desc) or series_desc == '':
        return series_desc
    # Remove one or more trailing '_RR' patterns
    return re.sub(r'(_RR)+$', '', str(series_desc))


def assign_acquisition_and_run_numbers(
    session_df,
    settings_fields: Optional[List[str]] = None,
    series_fields: Optional[List[str]] = None
):
    """
    Assign acquisition, series, and run numbers using a canonical 4-stage process.

    This function implements the correct sequential process:
    1. Identify acquisitions by ProtocolName (fallback: SequenceName)
    2. Identify series within acquisitions using non-settings fields
    3. Identify runs within series using SeriesInstanceUID/SeriesTime
    4. Split acquisitions where settings changed between runs

    Args:
        session_df (pd.DataFrame): Input session DataFrame
        settings_fields (Optional[List[str]]): Fields that represent acquisition settings.
            Defaults to DEFAULT_SETTINGS_FIELDS if not provided.
        series_fields (Optional[List[str]]): Fields for differentiating series (not settings).
            Defaults to ["SeriesDescription", "ImageType", "InversionTime"] if not provided.

    Returns:
        pd.DataFrame: Session DataFrame with Acquisition, Series, and RunNumber columns
    """

    logger.debug("Starting assign_acquisition_and_run_numbers")

    # Check if 'Acquisition' column already exists
    if 'Acquisition' in session_df.columns:
        logger.debug("  'Acquisition' column already exists, returning original DataFrame")
        return session_df.copy()

    # Suppress DataFrame fragmentation warnings
    warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)

    # Set defaults
    if settings_fields is None:
        settings_fields = DEFAULT_SETTINGS_FIELDS.copy()
    if series_fields is None:
        series_fields = DEFAULT_SERIES_FIELDS.copy()

    session_df = session_df.copy()
    session_df = make_dataframe_hashable(session_df)

    # ===== STAGE 1: Identify acquisitions by ProtocolName (fallback: SequenceName) =====
    logger.debug("Stage 1: Identifying acquisitions by ProtocolName/SequenceName")

    # Use ProtocolName if available, otherwise fall back to SequenceName on a per-file basis
    has_protocol_name = "ProtocolName" in session_df.columns
    has_sequence_name = "SequenceName" in session_df.columns

    if not has_protocol_name and not has_sequence_name:
        raise ValueError("Neither ProtocolName nor SequenceName found in session data")

    if has_protocol_name and has_sequence_name:
        # Use ProtocolName where available, SequenceName as fallback
        session_df["_AcquisitionProtocol"] = session_df.apply(
            lambda row: row["ProtocolName"] if pd.notna(row["ProtocolName"])
                       else (row["SequenceName"] if pd.notna(row["SequenceName"]) else "Unknown"),
            axis=1
        )
        logger.debug(f"  Using ProtocolName (with SequenceName fallback) for acquisition identification")
    elif has_protocol_name:
        session_df["_AcquisitionProtocol"] = session_df["ProtocolName"].fillna("Unknown")
        logger.debug(f"  Using ProtocolName for acquisition identification")
    else:
        session_df["_AcquisitionProtocol"] = session_df["SequenceName"].fillna("Unknown")
        logger.debug(f"  Using SequenceName for acquisition identification")

    # Clean the protocol name
    session_df["_AcquisitionProtocol"] = session_df["_AcquisitionProtocol"].apply(
        lambda x: clean_string(str(x)) if pd.notna(x) else "Unknown"
    )

    logger.debug(f"  Found {session_df['_AcquisitionProtocol'].nunique()} unique protocols")

    # Create Patient identifier (combination of PatientName and PatientID)
    # RunNumber will restart at 1 for each unique Patient
    has_patient_name = "PatientName" in session_df.columns
    has_patient_id = "PatientID" in session_df.columns

    if has_patient_name and has_patient_id:
        session_df["Patient"] = session_df.apply(
            lambda row: f"{row['PatientName']}|{row['PatientID']}"
            if pd.notna(row['PatientName']) and pd.notna(row['PatientID'])
            else (row['PatientName'] if pd.notna(row['PatientName'])
                  else (row['PatientID'] if pd.notna(row['PatientID']) else "Unknown")),
            axis=1
        )
    elif has_patient_name:
        session_df["Patient"] = session_df["PatientName"].fillna("Unknown")
    elif has_patient_id:
        session_df["Patient"] = session_df["PatientID"].fillna("Unknown")
    else:
        session_df["Patient"] = "Unknown"

    logger.debug(f"  Found {session_df['Patient'].nunique()} unique patients")

    # ===== STAGE 2: Identify series within acquisitions =====
    logger.debug(f"Stage 2: Identifying series using fields: {series_fields}")

    available_series_fields = [f for f in series_fields if f in session_df.columns]
    logger.debug(f"  Available series fields: {available_series_fields}")

    session_df["_SeriesSignature"] = ""
    session_df["_NormalizedSeriesSignature"] = ""  # For run detection (with _RR stripped)

    for acq_protocol, acq_group in session_df.groupby("_AcquisitionProtocol"):
        if available_series_fields:
            # Create series signatures (will be used for final series naming)
            for series_vals, series_group in acq_group.groupby(available_series_fields, dropna=False):
                # Create a hashable signature for this series combination
                sig = tuple(series_vals) if isinstance(series_vals, tuple) else (series_vals,)
                session_df.loc[series_group.index, "_SeriesSignature"] = str(sig)

                # Create normalized signature for run detection
                # Normalize SeriesDescription by stripping _RR suffixes
                normalized_vals = list(sig)
                if "SeriesDescription" in available_series_fields:
                    sd_idx = available_series_fields.index("SeriesDescription")
                    normalized_vals[sd_idx] = _normalize_series_description_for_run_detection(
                        normalized_vals[sd_idx]
                    )
                normalized_sig = tuple(normalized_vals)
                session_df.loc[series_group.index, "_NormalizedSeriesSignature"] = str(normalized_sig)
        else:
            # No series fields available
            session_df.loc[acq_group.index, "_SeriesSignature"] = "default"
            session_df.loc[acq_group.index, "_NormalizedSeriesSignature"] = "default"

    # ===== STAGE 3: Identify runs using SeriesInstanceUID =====
    # RunNumber will restart at 1 for each unique Patient within each acquisition
    # Uses _NormalizedSeriesSignature to detect repeated series (handles _RR suffixes)
    logger.debug("Stage 3: Identifying runs using SeriesInstanceUID (per patient)")

    session_df["_OriginalRunNumber"] = 1

    for acq_protocol, acq_group in session_df.groupby("_AcquisitionProtocol"):
        # Process each patient separately within this acquisition
        for patient, patient_group in acq_group.groupby("Patient"):
            # Determine which time field to use (prefer SeriesTime over AcquisitionTime)
            time_field = None
            if "SeriesTime" in patient_group.columns and patient_group["SeriesTime"].notna().any():
                time_field = "SeriesTime"
            elif "AcquisitionTime" in patient_group.columns and patient_group["AcquisitionTime"].notna().any():
                time_field = "AcquisitionTime"

            if time_field is None:
                logger.debug(f"  {acq_protocol}/{patient}: No time field available, defaulting to single run")
                continue

            # Check if SeriesInstanceUID is available
            if "SeriesInstanceUID" not in patient_group.columns:
                logger.debug(f"  {acq_protocol}/{patient}: No SeriesInstanceUID available, defaulting to single run")
                continue

            # Step 1: Find normalized series signatures that have multiple SeriesInstanceUIDs (repeated series)
            # Using normalized signatures allows detection even when SeriesDescription changes between runs
            # (e.g., _RR suffix variations)
            repeated_series = {}  # {normalized_series_sig: [uid1, uid2, ...]}

            for series_sig, sig_group in patient_group.groupby("_NormalizedSeriesSignature"):
                unique_uids = sig_group["SeriesInstanceUID"].dropna().unique()
                if len(unique_uids) > 1:
                    repeated_series[series_sig] = sorted(unique_uids)

            if not repeated_series:
                logger.debug(f"  {acq_protocol}/{patient}: No repeated series found, defaulting to single run")
                continue

            logger.debug(f"  {acq_protocol}/{patient}: Found {len(repeated_series)} series with multiple UIDs")

            # Step 2: Assign run numbers to repeated series based on their SeriesInstanceUID
            # We need to map UIDs to run numbers - use temporal ordering
            all_uid_times = {}  # {uid: median_time}

            for series_sig, uids in repeated_series.items():
                sig_group = patient_group[patient_group["_NormalizedSeriesSignature"] == series_sig]

                for uid in uids:
                    uid_files = sig_group[sig_group["SeriesInstanceUID"] == uid]
                    times = uid_files[time_field].apply(_dicom_time_to_seconds).dropna()
                    if len(times) > 0:
                        median_time = times.median()
                        all_uid_times[uid] = median_time

            # Sort UIDs by their median time
            sorted_uids = sorted(all_uid_times.keys(), key=lambda uid: all_uid_times[uid])
            sorted_times = [all_uid_times[uid] for uid in sorted_uids]

            # Cluster UIDs by time - UIDs within 60s span belong to the same run
            # Check span from first UID in cluster to current UID
            gap_threshold = 60  # seconds - if span from cluster start > 60s, start new run

            uid_to_run = {}
            current_run = 1
            cluster_start_time = sorted_times[0]

            for i, uid in enumerate(sorted_uids):
                uid_time = sorted_times[i]

                if i == 0:
                    # First UID is always run 1
                    uid_to_run[uid] = current_run
                else:
                    # Check time span from start of current cluster
                    time_span = uid_time - cluster_start_time

                    if time_span > gap_threshold:
                        # Span too large - start new run
                        current_run += 1
                        cluster_start_time = uid_time

                    uid_to_run[uid] = current_run

            num_runs = current_run
            logger.debug(f"  {acq_protocol}/{patient}: Clustered {len(sorted_uids)} UIDs into {num_runs} runs")

            # Assign run numbers to files with these UIDs
            for series_sig, uids in repeated_series.items():
                sig_group = patient_group[patient_group["_NormalizedSeriesSignature"] == series_sig]

                for uid in uids:
                    run_num = uid_to_run.get(uid, 1)
                    mask = (
                        (session_df["_AcquisitionProtocol"] == acq_protocol) &
                        (session_df["Patient"] == patient) &
                        (session_df["_NormalizedSeriesSignature"] == series_sig) &
                        (session_df["SeriesInstanceUID"] == uid)
                    )
                    session_df.loc[mask, "_OriginalRunNumber"] = run_num

            # Step 3: Calculate median time for each run (from repeated series ONLY)
            # Important: Only use files from repeated series to avoid pollution from orphan series
            # that still have the default _OriginalRunNumber = 1
            run_median_times = {}  # {run_num: median_time}
            for run_num in range(1, num_runs + 1):
                # Only include files from repeated series (not orphans)
                run_files = session_df[
                    (session_df["_AcquisitionProtocol"] == acq_protocol) &
                    (session_df["Patient"] == patient) &
                    (session_df["_OriginalRunNumber"] == run_num) &
                    (session_df["_NormalizedSeriesSignature"].isin([str(sig) for sig in repeated_series.keys()]))
                ]
                if len(run_files) > 0:
                    times = run_files[time_field].apply(_dicom_time_to_seconds).dropna()
                    if len(times) > 0:
                        run_median_times[run_num] = times.median()

            # Step 4: Assign unrepeated/orphan series to closest run by median time
            # Note: Orphan detection uses _NormalizedSeriesSignature, but there shouldn't be
            # any orphans now since normalization groups series with _RR suffixes together
            all_series_sigs = patient_group["_NormalizedSeriesSignature"].unique()
            orphan_series = [sig for sig in all_series_sigs if sig not in repeated_series]

            for series_sig in orphan_series:
                sig_group = patient_group[patient_group["_NormalizedSeriesSignature"] == series_sig]

                # Calculate median time for this orphan series
                times = sig_group[time_field].apply(_dicom_time_to_seconds).dropna()
                if len(times) == 0:
                    logger.debug(f"  {acq_protocol}/{patient}/{series_sig}: No time data, assigning to run 1")
                    mask = (
                        (session_df["_AcquisitionProtocol"] == acq_protocol) &
                        (session_df["Patient"] == patient) &
                        (session_df["_NormalizedSeriesSignature"] == series_sig)
                    )
                    session_df.loc[mask, "_OriginalRunNumber"] = 1
                    continue

                orphan_median_time = times.median()

                # Find closest run by median time
                closest_run = 1
                min_distance = float('inf')

                for run_num, run_median in run_median_times.items():
                    distance = abs(orphan_median_time - run_median)
                    if distance < min_distance:
                        min_distance = distance
                        closest_run = run_num

                logger.debug(f"  {acq_protocol}/{patient}/{series_sig}: Orphan series assigned to run {closest_run}")

                mask = (
                    (session_df["_AcquisitionProtocol"] == acq_protocol) &
                    (session_df["Patient"] == patient) &
                    (session_df["_NormalizedSeriesSignature"] == series_sig)
                )
                session_df.loc[mask, "_OriginalRunNumber"] = closest_run

    # ===== STAGE 4: Split acquisitions where settings changed between runs =====
    # Check settings changes within each patient separately using run-level signatures
    logger.debug("Stage 4: Checking for settings changes between runs (per patient, run-level signatures)")

    available_settings = [f for f in settings_fields if f in session_df.columns]
    logger.debug(f"  Checking {len(available_settings)} settings fields")

    session_df["_SettingsGroup"] = 0

    for acq_protocol, acq_group in session_df.groupby("_AcquisitionProtocol"):
        # Process each patient separately within this acquisition
        for patient, patient_group in acq_group.groupby("Patient"):
            runs = sorted(patient_group["_OriginalRunNumber"].unique())

            if len(runs) == 1:
                # Single run, no settings change possible
                continue

            # Build run-level signatures for each run
            # A signature is a dict of {field: set_of_unique_values}
            def build_run_signature(run_data):
                """Build a signature for a run by collecting unique values for each field."""
                signature = {}
                for field in available_settings:
                    if field not in run_data.columns:
                        signature[field] = frozenset()
                        continue

                    # Collect all unique values for this field across all files in the run
                    unique_values = set()
                    for val in run_data[field].dropna():
                        hashable_val = make_hashable(val)
                        if not pd.isna(hashable_val):
                            unique_values.add(hashable_val)

                    # Convert to frozenset for hashability and comparison
                    signature[field] = frozenset(unique_values)

                return signature

            # Compare settings between consecutive runs using signatures
            current_group = 0
            baseline_signature = None

            for run_num in runs:
                run_data = patient_group[patient_group["_OriginalRunNumber"] == run_num]
                run_signature = build_run_signature(run_data)

                if baseline_signature is None:
                    # First run, establish baseline
                    baseline_signature = run_signature
                else:
                    # Compare current run signature with baseline signature
                    settings_changed = False
                    changed_fields = []

                    for field in available_settings:
                        baseline_values = baseline_signature.get(field, frozenset())
                        current_values = run_signature.get(field, frozenset())

                        # Compare the sets of values
                        if baseline_values != current_values:
                            settings_changed = True
                            changed_fields.append(field)
                            logger.debug(f"  {acq_protocol}/{patient}: Field '{field}' changed between runs")
                            logger.debug(f"    Baseline: {sorted(baseline_values) if baseline_values else 'empty'}")
                            logger.debug(f"    Current:  {sorted(current_values) if current_values else 'empty'}")

                    if settings_changed:
                        # Settings changed, create new acquisition
                        current_group += 1
                        logger.debug(f"  {acq_protocol}/{patient}: Settings changed at run {run_num}")
                        logger.debug(f"    Changed fields: {changed_fields}")

                        # Update baseline for future comparisons
                        baseline_signature = run_signature

                # Assign settings group to this run
                mask = (
                    (session_df["_AcquisitionProtocol"] == acq_protocol) &
                    (session_df["Patient"] == patient) &
                    (session_df["_OriginalRunNumber"] == run_num)
                )
                session_df.loc[mask, "_SettingsGroup"] = current_group

    # ===== FINAL: Assign acquisition names, series numbers (local to each run), and run numbers =====
    # RunNumber restarts at 1 for each patient
    session_df["Acquisition"] = ""
    session_df["Series"] = ""
    session_df["RunNumber"] = 1

    for (acq_protocol, settings_group), group in session_df.groupby(
        ["_AcquisitionProtocol", "_SettingsGroup"]
    ):
        # Determine acquisition name based on settings group
        if settings_group == 0:
            acquisition_name = f"acq-{acq_protocol}"
        else:
            acquisition_name = f"acq-{acq_protocol}_{settings_group + 1}"

        # Process each patient separately - RunNumber restarts at 1 per patient
        for patient, patient_group in group.groupby("Patient"):
            # For each run within this patient's data, number series sequentially
            # Renumber runs starting from 1 for each patient
            for new_run_num, orig_run_num in enumerate(sorted(patient_group["_OriginalRunNumber"].unique()), start=1):
                run_data = patient_group[patient_group["_OriginalRunNumber"] == orig_run_num]

                # Get unique series signatures in this run
                unique_series = run_data["_SeriesSignature"].unique()

                # Assign series numbers sequentially within this run
                for series_idx, series_sig in enumerate(sorted(unique_series), start=1):
                    series_name = f"Series {series_idx:02d}"

                    mask = (
                        (session_df["_AcquisitionProtocol"] == acq_protocol) &
                        (session_df["Patient"] == patient) &
                        (session_df["_SettingsGroup"] == settings_group) &
                        (session_df["_OriginalRunNumber"] == orig_run_num) &
                        (session_df["_SeriesSignature"] == series_sig)
                    )
                    session_df.loc[mask, "Acquisition"] = acquisition_name
                    session_df.loc[mask, "Series"] = series_name
                    session_df.loc[mask, "RunNumber"] = new_run_num

    # Clean up temporary columns
    temp_cols = ["_AcquisitionProtocol", "_SeriesSignature", "_NormalizedSeriesSignature",
                 "_OriginalRunNumber", "_SettingsGroup"]
    # Only drop columns that exist
    cols_to_drop = [col for col in temp_cols if col in session_df.columns]
    session_df = session_df.drop(columns=cols_to_drop)

    logger.debug(f"Final result: {len(session_df['Acquisition'].unique())} acquisitions, "
                f"{len(session_df['Series'].unique())} series")
    logger.debug(f"Acquisitions: {sorted(session_df['Acquisition'].unique())}")

    return session_df