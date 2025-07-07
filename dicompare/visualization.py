"""
DICOM visualization utilities for dicompare.

This module provides functions to extract and prepare DICOM pixel data
for visualization in web interfaces.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def extract_center_slice_data(session_df: pd.DataFrame, 
                            acquisition: str,
                            dicom_files: Dict[str, bytes]) -> Dict[str, Any]:
    """
    Extract center slice pixel data from DICOM files for visualization.
    
    Args:
        session_df: DataFrame containing DICOM session data
        acquisition: Acquisition name to visualize
        dicom_files: Dict mapping DICOM paths to file bytes
        
    Returns:
        Dict containing extracted pixel data and metadata
        
    Raises:
        ValueError: If acquisition not found or no pixel data available
        ImportError: If pydicom is not available
        
    Examples:
        >>> data = extract_center_slice_data(df, 'T1_MPRAGE', dicom_bytes)
        >>> data['series'][0]['width']
        256
    """
    try:
        import pydicom
        from io import BytesIO
    except ImportError:
        raise ImportError("pydicom is required for DICOM visualization. Install with: pip install pydicom")
    
    # Filter to target acquisition
    acq_data = session_df[session_df['Acquisition'] == acquisition]
    if acq_data.empty:
        raise ValueError(f"No data found for acquisition: {acquisition}")
    
    logger.info(f"Found {len(acq_data)} DICOM files for acquisition {acquisition}")
    
    # Identify series based on varying fields
    series_results = []
    varying_fields = []
    
    # Check which fields vary within this acquisition to group into series
    for field in ['EchoTime', 'ImageType', 'SeriesInstanceUID']:
        if field in acq_data.columns:
            unique_vals = acq_data[field].dropna().unique()
            if len(unique_vals) > 1:
                varying_fields.append(field)
    
    if varying_fields:
        # Group by the first varying field
        primary_field = varying_fields[0]
        unique_series = acq_data.groupby([primary_field])
        logger.info(f"Found {len(unique_series)} unique {primary_field} values")
    else:
        # Single series
        unique_series = [(acquisition, acq_data)]
        logger.info(f"Single series acquisition: {acquisition}")
    
    # Process each series
    for series_key, series_data in unique_series:
        if varying_fields:
            series_name = f"{varying_fields[0]} ({series_key})"
        else:
            series_name = acquisition
            
        logger.info(f"Processing series: {series_name} ({len(series_data)} slices)")
        
        # Sort by InstanceNumber for proper slice ordering
        if 'InstanceNumber' in series_data.columns:
            series_data_sorted = series_data.sort_values('InstanceNumber')
        else:
            series_data_sorted = series_data
        
        # Get center instance
        center_idx = len(series_data_sorted) // 2
        center_row = series_data_sorted.iloc[center_idx]
        center_dicom_path = center_row.get('DICOM_Path', '')
        
        if center_dicom_path not in dicom_files:
            logger.warning(f"Center DICOM path not found in dicom_files: {center_dicom_path}")
            continue
            
        try:
            # Read DICOM with pixel data
            ds = pydicom.dcmread(BytesIO(dicom_files[center_dicom_path]), 
                               force=True, stop_before_pixels=False)
            
            if not hasattr(ds, 'pixel_array'):
                logger.warning(f"No pixel data in {center_dicom_path}")
                continue
                
            pixel_array = ds.pixel_array
            
            # Handle different dimensions
            if len(pixel_array.shape) == 3:
                # Take middle slice if it's 3D
                middle_slice = pixel_array.shape[0] // 2
                pixel_array = pixel_array[middle_slice]
            elif len(pixel_array.shape) > 3:
                # Take first of each extra dimension
                while len(pixel_array.shape) > 2:
                    pixel_array = pixel_array[0]
            
            # Ensure it's 2D and convert to float
            if len(pixel_array.shape) != 2:
                logger.warning(f"Could not get 2D slice from {center_dicom_path}")
                continue
                
            center_slice = pixel_array.astype(float)
            
            # Calculate statistics
            series_min = float(np.min(center_slice))
            series_max = float(np.max(center_slice))
            
            series_results.append({
                "name": series_name,
                "slices": [center_slice.tolist()],
                "width": int(center_slice.shape[1]),
                "height": int(center_slice.shape[0]),
                "min": series_min,
                "max": series_max,
                "sliceCount": 1,
                "total_slices": len(series_data_sorted)
            })
            
            logger.info(f"Successfully extracted center slice for {series_name}")
            
        except Exception as e:
            logger.error(f"Error reading DICOM {center_dicom_path}: {e}")
            continue
    
    if not series_results:
        raise ValueError("Could not extract pixel data from any series. Make sure DICOM files contain pixel data.")
    
    return {"series": series_results}


def prepare_slice_for_canvas(pixel_data: np.ndarray, 
                           window_center: Optional[float] = None,
                           window_width: Optional[float] = None) -> np.ndarray:
    """
    Prepare pixel data for HTML canvas rendering.
    
    Args:
        pixel_data: 2D numpy array of pixel values
        window_center: Optional window center for windowing
        window_width: Optional window width for windowing
        
    Returns:
        Normalized pixel data ready for canvas rendering (0-255 range)
        
    Examples:
        >>> pixel_data = np.array([[100, 200], [300, 400]])
        >>> canvas_data = prepare_slice_for_canvas(pixel_data)
        >>> canvas_data.max()
        255.0
    """
    # Apply windowing if specified
    if window_center is not None and window_width is not None:
        window_min = window_center - window_width / 2
        window_max = window_center + window_width / 2
        windowed_data = np.clip(pixel_data, window_min, window_max)
    else:
        windowed_data = pixel_data
    
    # Normalize to 0-255 range
    data_min = np.min(windowed_data)
    data_max = np.max(windowed_data)
    
    if data_max > data_min:
        normalized = ((windowed_data - data_min) / (data_max - data_min)) * 255
    else:
        normalized = np.zeros_like(windowed_data)
    
    return normalized.astype(np.uint8)


def get_acquisition_preview_data(session_df: pd.DataFrame,
                               acquisition: str,
                               dicom_files: Dict[str, bytes],
                               max_series: int = 3) -> Dict[str, Any]:
    """
    Get preview data for an acquisition suitable for web display.
    
    Args:
        session_df: DataFrame containing DICOM session data
        acquisition: Acquisition name to preview
        dicom_files: Dict mapping DICOM paths to file bytes
        max_series: Maximum number of series to include in preview
        
    Returns:
        Dict containing preview data with thumbnails and metadata
        
    Examples:
        >>> preview = get_acquisition_preview_data(df, 'T1_MPRAGE', dicom_bytes)
        >>> len(preview['thumbnails'])
        2
    """
    try:
        full_data = extract_center_slice_data(session_df, acquisition, dicom_files)
    except (ValueError, ImportError) as e:
        logger.warning(f"Could not extract preview data for {acquisition}: {e}")
        return {
            "acquisition": acquisition,
            "available": False,
            "error": str(e),
            "thumbnails": []
        }
    
    # Limit to max_series
    series_data = full_data["series"][:max_series]
    
    # Create thumbnails (smaller versions for preview)
    thumbnails = []
    for series in series_data:
        if series["slices"]:
            # Get thumbnail size (max 64x64)
            original_width = series["width"]
            original_height = series["height"]
            
            # Calculate thumbnail dimensions maintaining aspect ratio
            max_thumb_size = 64
            if original_width > original_height:
                thumb_width = max_thumb_size
                thumb_height = int((original_height / original_width) * max_thumb_size)
            else:
                thumb_height = max_thumb_size
                thumb_width = int((original_width / original_height) * max_thumb_size)
            
            # For simplicity, just include metadata (actual resizing would require image processing)
            thumbnails.append({
                "name": series["name"],
                "width": thumb_width,
                "height": thumb_height,
                "original_width": original_width,
                "original_height": original_height,
                "value_range": [series["min"], series["max"]],
                "slice_count": series["total_slices"]
            })
    
    return {
        "acquisition": acquisition,
        "available": True,
        "series_count": len(series_data),
        "thumbnails": thumbnails,
        "full_data_available": True
    }


def analyze_image_characteristics(session_df: pd.DataFrame,
                                acquisition: str) -> Dict[str, Any]:
    """
    Analyze image characteristics for an acquisition without loading pixel data.
    
    Args:
        session_df: DataFrame containing DICOM session data
        acquisition: Acquisition name to analyze
        
    Returns:
        Dict containing image characteristics from DICOM headers
        
    Examples:
        >>> chars = analyze_image_characteristics(df, 'T1_MPRAGE')
        >>> chars['matrix_size']
        [256, 256]
    """
    acq_data = session_df[session_df['Acquisition'] == acquisition]
    if acq_data.empty:
        raise ValueError(f"No data found for acquisition: {acquisition}")
    
    characteristics = {
        "acquisition": acquisition,
        "total_files": len(acq_data),
        "matrix_size": None,
        "slice_thickness": None,
        "pixel_spacing": None,
        "image_orientation": None,
        "image_position": None,
        "has_multiple_series": False,
        "series_info": []
    }
    
    # Get matrix size
    if 'Rows' in acq_data.columns and 'Columns' in acq_data.columns:
        rows = acq_data['Rows'].dropna().iloc[0] if not acq_data['Rows'].dropna().empty else None
        cols = acq_data['Columns'].dropna().iloc[0] if not acq_data['Columns'].dropna().empty else None
        if rows is not None and cols is not None:
            characteristics["matrix_size"] = [int(rows), int(cols)]
    
    # Get slice thickness
    if 'SliceThickness' in acq_data.columns:
        thickness = acq_data['SliceThickness'].dropna()
        if not thickness.empty:
            characteristics["slice_thickness"] = float(thickness.iloc[0])
    
    # Get pixel spacing
    if 'PixelSpacing' in acq_data.columns:
        spacing = acq_data['PixelSpacing'].dropna()
        if not spacing.empty:
            # PixelSpacing is typically stored as a string like "1.0\\2.0"
            spacing_str = str(spacing.iloc[0])
            try:
                if '\\' in spacing_str:
                    parts = spacing_str.split('\\')
                    characteristics["pixel_spacing"] = [float(parts[0]), float(parts[1])]
            except (ValueError, IndexError):
                pass
    
    # Check for multiple series
    varying_fields = ['EchoTime', 'ImageType', 'SeriesInstanceUID']
    for field in varying_fields:
        if field in acq_data.columns:
            unique_vals = acq_data[field].dropna().unique()
            if len(unique_vals) > 1:
                characteristics["has_multiple_series"] = True
                characteristics["series_info"].append({
                    "varying_field": field,
                    "unique_values": len(unique_vals),
                    "sample_values": unique_vals[:3].tolist()
                })
                break
    
    return characteristics