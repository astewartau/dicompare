#!/usr/bin/env python
"""
Generate a comprehensive test DICOM dataset for testing the dicompare interface.

This script creates a realistic set of DICOM files that mimics what users would 
upload to the interface, including multiple acquisitions with different series
and varying field values.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

# Add the parent directory to the path so we can import dicompare
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dicompare.tests.test_dicom_factory import DicomTestFactory, create_test_dicom_series


def create_comprehensive_test_dataset(output_dir: str) -> Dict[str, List[str]]:
    """
    Create a comprehensive test dataset with multiple acquisitions and series.
    
    Args:
        output_dir: Directory where to save the DICOM files
        
    Returns:
        Dictionary mapping acquisition names to list of file paths
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    dataset_info = {}
    all_bytes = {}
    
    # Create T1 MPRAGE acquisition with 3 series (different echo times)
    print("Creating T1_MPRAGE acquisition...")
    t1_dir = output_path / "T1_MPRAGE"
    t1_dir.mkdir(exist_ok=True)
    
    # Series 1: Standard T1
    t1_s1_paths, t1_s1_bytes = create_test_dicom_series(
        str(t1_dir / "series_001"),
        "T1_MPRAGE",
        num_slices=3,
        metadata_base={
            'RepetitionTime': 2000.0,
            'EchoTime': 2.46,
            'FlipAngle': 9.0,
            'SliceThickness': 1.0,
            'SeriesNumber': 1,
            'SeriesDescription': 'T1_MPRAGE_0.8mm'
        }
    )
    
    # Series 2: Different echo time
    t1_s2_paths, t1_s2_bytes = create_test_dicom_series(
        str(t1_dir / "series_002"),
        "T1_MPRAGE",
        num_slices=3,
        metadata_base={
            'RepetitionTime': 2000.0,
            'EchoTime': 3.5,  # Different echo time
            'FlipAngle': 9.0,
            'SliceThickness': 1.0,
            'SeriesNumber': 2,
            'SeriesDescription': 'T1_MPRAGE_0.8mm_TE3.5'
        }
    )
    
    dataset_info['T1_MPRAGE'] = t1_s1_paths + t1_s2_paths
    all_bytes.update(t1_s1_bytes)
    all_bytes.update(t1_s2_bytes)
    
    # Create T2 FLAIR acquisition with 2 series (different slice thickness)
    print("Creating T2_FLAIR acquisition...")
    t2_dir = output_path / "T2_FLAIR"
    t2_dir.mkdir(exist_ok=True)
    
    # Series 1: Standard T2 FLAIR
    t2_s1_paths, t2_s1_bytes = create_test_dicom_series(
        str(t2_dir / "series_001"),
        "T2_FLAIR",
        num_slices=2,
        metadata_base={
            'RepetitionTime': 9000.0,
            'EchoTime': 85.0,
            'FlipAngle': 150.0,
            'SliceThickness': 3.0,
            'SeriesNumber': 3,
            'SeriesDescription': 'T2_FLAIR_3mm'
        }
    )
    
    # Series 2: Different slice thickness
    t2_s2_paths, t2_s2_bytes = create_test_dicom_series(
        str(t2_dir / "series_002"),
        "T2_FLAIR",
        num_slices=2,
        metadata_base={
            'RepetitionTime': 9000.0,
            'EchoTime': 85.0,
            'FlipAngle': 150.0,
            'SliceThickness': 5.0,  # Different slice thickness
            'SeriesNumber': 4,
            'SeriesDescription': 'T2_FLAIR_5mm'
        }
    )
    
    dataset_info['T2_FLAIR'] = t2_s1_paths + t2_s2_paths
    all_bytes.update(t2_s1_bytes)
    all_bytes.update(t2_s2_bytes)
    
    # Create DWI acquisition with varying b-values
    print("Creating DWI acquisition...")
    dwi_dir = output_path / "DWI"
    dwi_dir.mkdir(exist_ok=True)
    
    # Create DWI with different b-values
    b_values = [0, 1000, 2000]
    dwi_paths = []
    
    for b_idx, b_value in enumerate(b_values):
        paths, bytes_dict = create_test_dicom_series(
            str(dwi_dir / f"b{b_value}"),
            "DWI",
            num_slices=2,
            metadata_base={
                'RepetitionTime': 3000.0,
                'EchoTime': 80.0,
                'FlipAngle': 90.0,
                'SliceThickness': 2.5,
                'SeriesNumber': 5 + b_idx,
                'SeriesDescription': f'DWI_b{b_value}',
                'DiffusionBValue': float(b_value)
            }
        )
        dwi_paths.extend(paths)
        all_bytes.update(bytes_dict)
    
    dataset_info['DWI'] = dwi_paths
    
    # Print summary
    print("\nTest dataset created successfully!")
    print(f"Total acquisitions: {len(dataset_info)}")
    for acq_name, paths in dataset_info.items():
        print(f"  {acq_name}: {len(paths)} files")
    print(f"Total DICOM files: {sum(len(paths) for paths in dataset_info.values())}")
    
    # Save a summary file
    summary_path = output_path / "dataset_summary.txt"
    with open(summary_path, 'w') as f:
        f.write("Test DICOM Dataset Summary\n")
        f.write("=" * 50 + "\n\n")
        
        for acq_name, paths in dataset_info.items():
            f.write(f"Acquisition: {acq_name}\n")
            f.write(f"Files: {len(paths)}\n")
            f.write("File paths:\n")
            for path in paths:
                f.write(f"  - {Path(path).relative_to(output_path)}\n")
            f.write("\n")
    
    return dataset_info, all_bytes


def create_minimal_test_dataset(output_dir: str) -> Dict[str, List[str]]:
    """
    Create a minimal test dataset with just 2 acquisitions for quick testing.
    
    Args:
        output_dir: Directory where to save the DICOM files
        
    Returns:
        Dictionary mapping acquisition names to list of file paths
    """
    factory = DicomTestFactory(output_dir)
    
    dataset_info = {}
    all_bytes = {}
    
    # Just T1 and T2
    print("Creating minimal test dataset...")
    
    t1_paths, t1_bytes = factory.create_t1_mprage(num_slices=2)
    dataset_info['T1_MPRAGE'] = t1_paths
    all_bytes.update(t1_bytes)
    
    t2_paths, t2_bytes = factory.create_t2_flair(num_slices=2)
    dataset_info['T2_FLAIR'] = t2_paths
    all_bytes.update(t2_bytes)
    
    print(f"Created minimal dataset with {sum(len(p) for p in dataset_info.values())} files")
    
    return dataset_info, all_bytes


def export_as_bytes_dict(dataset_info: Dict[str, List[str]]) -> Dict[str, bytes]:
    """
    Export the dataset as a dictionary of filename to bytes for easy testing.
    
    Args:
        dataset_info: Dictionary from create_*_test_dataset
        
    Returns:
        Dictionary mapping relative filenames to file bytes
    """
    bytes_dict = {}
    
    for acq_name, paths in dataset_info.items():
        for path in paths:
            # Use relative path as key
            rel_path = f"{acq_name}/{Path(path).name}"
            with open(path, 'rb') as f:
                bytes_dict[rel_path] = f.read()
    
    return bytes_dict


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate test DICOM dataset")
    parser.add_argument("output_dir", help="Output directory for DICOM files")
    parser.add_argument("--minimal", action="store_true", help="Create minimal dataset (faster)")
    parser.add_argument("--export-bytes", action="store_true", 
                       help="Also export as bytes dictionary (for JavaScript tests)")
    
    args = parser.parse_args()
    
    # Create the dataset
    if args.minimal:
        dataset_info, all_bytes = create_minimal_test_dataset(args.output_dir)
    else:
        dataset_info, all_bytes = create_comprehensive_test_dataset(args.output_dir)
    
    # Export bytes dictionary if requested
    if args.export_bytes:
        import json
        bytes_dict = export_as_bytes_dict(dataset_info)
        
        # Save metadata about the files (not the actual bytes, which would be huge)
        metadata = {
            'acquisitions': {
                acq: {
                    'file_count': len(paths),
                    'filenames': [Path(p).name for p in paths]
                }
                for acq, paths in dataset_info.items()
            },
            'total_files': sum(len(p) for p in dataset_info.values())
        }
        
        metadata_path = Path(args.output_dir) / "dataset_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"\nMetadata saved to: {metadata_path}")
        print("Note: Actual DICOM bytes are in the .dcm files")