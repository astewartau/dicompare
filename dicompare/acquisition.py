"""
Acquisition identification and labeling for DICOM sessions.

This module provides functions for assigning acquisition and run numbers to DICOM sessions
in a clean, single-pass approach that builds complete acquisition signatures upfront
rather than iteratively splitting and reassigning.
"""

import pandas as pd
import logging
from typing import List, Optional

from .config import DEFAULT_SETTINGS_FIELDS, DEFAULT_ACQUISITION_FIELDS, DEFAULT_RUN_GROUP_FIELDS
from .utils import clean_string, make_hashable

logger = logging.getLogger(__name__)


def _validate_and_setup_fields(session_df, settings_fields, acquisition_fields, run_group_fields):
    """
    Validate inputs and set up default field lists.
    
    Args:
        session_df (pd.DataFrame): Input session DataFrame
        reference_fields (Optional[List[str]]): Fields for detecting acquisition settings
        acquisition_fields (Optional[List[str]]): Fields for grouping acquisitions
        run_group_fields (Optional[List[str]]): Fields for identifying runs
        
    Returns:
        Tuple[List[str], List[str], List[str]]: Validated field lists
    """
    if settings_fields is None:
        settings_fields = DEFAULT_SETTINGS_FIELDS.copy()
    
    if acquisition_fields is None:
        acquisition_fields = DEFAULT_ACQUISITION_FIELDS.copy()
        
    if run_group_fields is None:
        run_group_fields = DEFAULT_RUN_GROUP_FIELDS.copy()
    
    # Ensure ProtocolName exists
    if "ProtocolName" not in session_df.columns:
        logger.warning("'ProtocolName' not found in session_df columns. Setting it to 'SeriesDescription' instead.")
        session_df["ProtocolName"] = session_df.get("SeriesDescription", "Unknown")
    
    # Ensure ProtocolName values are strings and handle NaN values
    session_df["ProtocolName"] = session_df["ProtocolName"].fillna("Unknown").astype(str)
    
    return settings_fields, acquisition_fields, run_group_fields


def _get_series_differentiator(group):
    """
    Choose SeriesTime or SeriesInstanceUID as the series differentiator.
    
    Args:
        group (pd.DataFrame): DataFrame group to check for time fields
        
    Returns:
        str: Field name to use for series differentiation
    """
    if "SeriesTime" in group.columns:
        return "SeriesTime"
    else:
        return "SeriesInstanceUID"


def _determine_settings_group_fields(session_df):
    """
    Determine which fields to use for settings grouping based on CoilType availability.
    
    Args:
        session_df (pd.DataFrame): Input session DataFrame
        
    Returns:
        List[str]: Fields to use for settings grouping
    """
    base_fields = ["PatientName", "PatientID", "StudyDate", "RunNumber"]
    
    if "CoilType" in session_df.columns:
        coil_type_counts = session_df["CoilType"].value_counts()
        has_combined = "Combined" in coil_type_counts.index
        has_uncombined = "Uncombined" in coil_type_counts.index
        
        if has_combined and has_uncombined:
            return [f for f in base_fields + ["CoilType"] if f in session_df.columns]
    
    return [f for f in base_fields if f in session_df.columns]


def build_acquisition_signatures(session_df, acquisition_fields, reference_fields):
    """
    Build complete acquisition signatures that include protocol + settings.
    
    This function creates comprehensive signatures that capture all relevant differences
    between acquisitions, eliminating the need for later splitting operations.
    
    Args:
        session_df (pd.DataFrame): Input session DataFrame
        acquisition_fields (List[str]): Fields for basic acquisition grouping
        reference_fields (List[str]): Fields for detecting settings differences
        
    Returns:
        pd.DataFrame: Session DataFrame with 'AcquisitionSignature' column added
    """
    # Make all values hashable
    for col in session_df.columns:
        session_df[col] = session_df[col].apply(make_hashable)
    
    # Create basic acquisition labels
    def clean_acquisition_values(row):
        return "-".join(str(val) if pd.notnull(val) else "NA" for val in row)

    session_df["BaseAcquisition"] = "acq-" + session_df[acquisition_fields].apply(
        clean_acquisition_values, axis=1
    ).apply(clean_string)
    
    # Build comprehensive signatures by protocol
    logger.debug("Building acquisition signatures...")
    
    for protocol_name, protocol_group in session_df.groupby("ProtocolName"):
        logger.debug(f"Processing protocol '{protocol_name}' with {len(protocol_group)} rows")
        
        # Determine settings group fields
        settings_group_fields = _determine_settings_group_fields(protocol_group)
        
        # First, identify unique parameter combinations by looking at actual field values
        # Group by all reference fields to detect different settings
        reference_fields_present = [f for f in reference_fields if f in protocol_group.columns]
        
        # Add CoilType if present
        grouping_fields = reference_fields_present.copy()
        if "CoilType" in protocol_group.columns:
            grouping_fields.append("CoilType")
        
        param_to_signature = {}
        counter = 1
        
        if grouping_fields:
            # Group by the actual field values to detect different settings
            unique_combinations = list(protocol_group.groupby(grouping_fields))
            
            for param_vals, param_group in unique_combinations:
                # Create parameter tuple for this unique combination
                if len(grouping_fields) == 1:
                    param_vals = (param_vals,)
                
                param_tuple = tuple(zip(grouping_fields, param_vals))
                
                # Assign signature number for this parameter combination
                if param_tuple not in param_to_signature:
                    param_to_signature[param_tuple] = counter
                    logger.debug(f"  - NEW parameter combination #{counter}: {param_tuple}")
                    counter += 1
                
                signature_num = param_to_signature[param_tuple]
                
                # Create full acquisition signature  
                base_acq = param_group["BaseAcquisition"].iloc[0]
                if len(unique_combinations) > 1:  # Only add suffix if multiple settings detected
                    signature = f"{base_acq}-{signature_num}"
                else:
                    signature = base_acq
                    
                session_df.loc[param_group.index, "AcquisitionSignature"] = signature
        else:
            # No reference fields to group by, use base acquisition
            base_acq = protocol_group["BaseAcquisition"].iloc[0]
            session_df.loc[protocol_group.index, "AcquisitionSignature"] = base_acq
    
    return session_df


def assign_temporal_runs(session_df, run_group_fields):
    """
    Identify temporal runs within each acquisition signature.
    
    Args:
        session_df (pd.DataFrame): Session DataFrame with AcquisitionSignature column
        run_group_fields (List[str]): Fields for identifying run groups
        
    Returns:
        pd.DataFrame: Session DataFrame with RunNumber column added
    """
    logger.debug("Assigning temporal runs...")
    
    # Initialize RunNumber column
    session_df["RunNumber"] = 1
    
    # Build run grouping keys
    run_keys = [f for f in run_group_fields if f in session_df.columns]
    
    # Group by run identification fields
    for key_vals, group in session_df.groupby(run_keys):
        series_differentiator = _get_series_differentiator(group)
        group = group.sort_values(series_differentiator)
        
        # Within each acquisition signature, detect temporal runs
        for acq_sig, acq_group in group.groupby("AcquisitionSignature"):
            for series_desc, series_group in acq_group.groupby("SeriesDescription"):
                # Get unique time points for this series
                times = sorted(series_group[series_differentiator].unique())
                
                if len(times) > 1:
                    logger.debug(f"  - Detected {len(times)} runs for {acq_sig}/{series_desc}")
                    # Assign run numbers based on time order
                    for run_num, time_point in enumerate(times, start=1):
                        mask = (
                            (session_df["AcquisitionSignature"] == acq_sig) &
                            (session_df["SeriesDescription"] == series_desc) &
                            (session_df[series_differentiator] == time_point)
                        )
                        # Add run key matching
                        for i, key in enumerate(run_keys):
                            val = key_vals[i] if isinstance(key_vals, tuple) else key_vals
                            mask &= (session_df[key] == val)
                        
                        session_df.loc[mask, "RunNumber"] = run_num
    
    return session_df


def assign_acquisition_and_run_numbers(
    session_df, 
    reference_fields: Optional[List[str]] = None, 
    acquisition_fields: Optional[List[str]] = None, 
    run_group_fields: Optional[List[str]] = None
):
    """
    Assign acquisition and run numbers in a single coherent pass.
    
    This function builds complete acquisition signatures upfront and then assigns
    temporal runs, avoiding the need for iterative splitting and reassignment.
    
    Args:
        session_df (pd.DataFrame): Input session DataFrame
        reference_fields (Optional[List[str]]): Fields for detecting acquisition settings
        acquisition_fields (Optional[List[str]]): Fields for grouping acquisitions  
        run_group_fields (Optional[List[str]]): Fields for identifying runs
        
    Returns:
        pd.DataFrame: Session DataFrame with Acquisition and RunNumber columns
    """
    logger.debug("Starting assign_acquisition_and_run_numbers (refactored)")
    
    # 1. Validate inputs and set up fields
    reference_fields, acquisition_fields, run_group_fields = _validate_and_setup_fields(
        session_df, reference_fields, acquisition_fields, run_group_fields
    )
    
    logger.debug(f"Using fields - acquisition: {acquisition_fields}, reference: {len(reference_fields)} fields, run_group: {run_group_fields}")
    
    # 2. Build complete acquisition signatures
    session_df = build_acquisition_signatures(session_df, acquisition_fields, reference_fields)
    
    # 3. Assign temporal runs within each signature
    session_df = assign_temporal_runs(session_df, run_group_fields)
    
    # 4. Create final Acquisition labels from signatures
    session_df["Acquisition"] = session_df["AcquisitionSignature"].fillna("Unknown").astype(str)
    
    # 5. Clean up temporary columns
    session_df = session_df.drop(columns=["BaseAcquisition", "AcquisitionSignature"]).reset_index(drop=True)
    
    logger.debug(f"Final result - {len(session_df['Acquisition'].unique())} unique acquisitions")
    logger.debug(f"Acquisitions: {list(session_df['Acquisition'].unique())}")
    
    return session_df