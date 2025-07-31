#!/usr/bin/env python3

"""
Test script for AcquisitionPlane with a real DICOM file
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dicompare'))

from dicompare.io import load_dicom

def test_real_dicom():
    """Test AcquisitionPlane calculation with real DICOM"""
    
    dicom_path = 'dicompare/tests/fixtures/ref_dicom.dcm'
    
    if not os.path.exists(dicom_path):
        print(f"DICOM test file not found at {dicom_path}")
        return
    
    try:
        print(f"Testing with real DICOM file: {dicom_path}")
        print("-" * 50)
        
        # Load the DICOM
        metadata = load_dicom(dicom_path)
        
        # Check if AcquisitionPlane was calculated
        if 'AcquisitionPlane' in metadata:
            print(f"✓ AcquisitionPlane field present: {metadata['AcquisitionPlane']}")
        else:
            print("✗ AcquisitionPlane field missing")
            
        # Display relevant fields for debugging
        relevant_fields = ['ImageOrientationPatient', 'AcquisitionPlane', 'Manufacturer', 'ProtocolName']
        for field in relevant_fields:
            if field in metadata:
                print(f"  {field}: {metadata[field]}")
            else:
                print(f"  {field}: <not present>")
                
    except Exception as e:
        print(f"Error loading DICOM: {e}")

if __name__ == '__main__':
    test_real_dicom()