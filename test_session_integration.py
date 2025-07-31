#!/usr/bin/env python3

"""
Test script for AcquisitionPlane in DICOM session loading
"""

import sys
import os
import tempfile
import shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dicompare'))

from dicompare.io import load_dicom_session

def test_session_integration():
    """Test AcquisitionPlane field in session DataFrame"""
    
    # Create temporary directory with test DICOM
    test_dicom_path = 'dicompare/tests/fixtures/ref_dicom.dcm'
    
    if not os.path.exists(test_dicom_path):
        print(f"Test DICOM file not found at {test_dicom_path}")
        return
    
    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Copy test DICOM to temp directory
        temp_dicom = os.path.join(temp_dir, 'test.dcm')
        shutil.copy(test_dicom_path, temp_dicom)
        
        try:
            print("Testing AcquisitionPlane in DICOM session loading...")
            print("-" * 50)
            
            # Load DICOM session
            session_df = load_dicom_session(temp_dir, show_progress=False)
            
            print(f"Session DataFrame shape: {session_df.shape}")
            print(f"Columns in DataFrame: {list(session_df.columns)}")
            
            # Check if AcquisitionPlane column exists
            if 'AcquisitionPlane' in session_df.columns:
                print(f"✓ AcquisitionPlane column present")
                print(f"  Values: {session_df['AcquisitionPlane'].unique()}")
            else:
                print("✗ AcquisitionPlane column missing")
                
            # Show a few relevant columns
            relevant_cols = ['AcquisitionPlane', 'ImageOrientationPatient', 'ProtocolName']
            available_cols = [col for col in relevant_cols if col in session_df.columns]
            
            if available_cols:
                print("\nSample data:")
                print(session_df[available_cols].head())
                
        except Exception as e:
            print(f"Error loading session: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    test_session_integration()