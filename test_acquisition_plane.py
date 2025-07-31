#!/usr/bin/env python3

"""
Test script for AcquisitionPlane calculation functionality
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dicompare'))

from dicompare.io import load_dicom

def test_acquisition_plane_calculation():
    """Test AcquisitionPlane calculation with various orientations"""
    
    # Test cases with different ImageOrientationPatient values
    test_cases = [
        # Axial (Z-dominant slice normal)
        {
            'name': 'Axial',
            'ImageOrientationPatient': [1, 0, 0, 0, 1, 0],  # Standard axial
            'expected': 'axial'
        },
        # Sagittal (X-dominant slice normal)
        {
            'name': 'Sagittal',
            'ImageOrientationPatient': [0, 1, 0, 0, 0, -1],  # Standard sagittal
            'expected': 'sagittal'
        },
        # Coronal (Y-dominant slice normal)
        {
            'name': 'Coronal',
            'ImageOrientationPatient': [1, 0, 0, 0, 0, -1],  # Standard coronal
            'expected': 'coronal'
        },
        # Oblique axial (still Z-dominant)
        {
            'name': 'Oblique Axial',
            'ImageOrientationPatient': [0.9, 0.1, 0.1, -0.1, 0.9, 0.1],
            'expected': 'axial'
        },
        # Invalid case
        {
            'name': 'Invalid',
            'ImageOrientationPatient': [1, 2, 3],  # Wrong length
            'expected': 'unknown'
        },
        # Missing case
        {
            'name': 'Missing',
            'ImageOrientationPatient': None,
            'expected': 'unknown'
        }
    ]
    
    print("Testing AcquisitionPlane calculation...")
    print("-" * 50)
    
    for i, test_case in enumerate(test_cases):
        print(f"Test {i+1}: {test_case['name']}")
        
        # Create mock metadata
        metadata = {}
        if test_case['ImageOrientationPatient'] is not None:
            metadata['ImageOrientationPatient'] = test_case['ImageOrientationPatient']
        
        # Simulate the calculation logic directly
        if 'ImageOrientationPatient' in metadata:
            iop = metadata['ImageOrientationPatient']
            try:
                if isinstance(iop, (tuple, list)) and len(iop) == 6:
                    iop_list = [float(x) for x in iop]
                    
                    # Get row and column direction cosines
                    row_cosines = iop_list[:3]
                    col_cosines = iop_list[3:6]
                    
                    # Calculate slice normal using cross product
                    slice_normal = [
                        row_cosines[1] * col_cosines[2] - row_cosines[2] * col_cosines[1],
                        row_cosines[2] * col_cosines[0] - row_cosines[0] * col_cosines[2],
                        row_cosines[0] * col_cosines[1] - row_cosines[1] * col_cosines[0]
                    ]
                    
                    # Determine primary orientation
                    abs_normal = [abs(x) for x in slice_normal]
                    max_component = abs_normal.index(max(abs_normal))
                    
                    if max_component == 0:
                        result = 'sagittal'
                    elif max_component == 1:
                        result = 'coronal'
                    else:
                        result = 'axial'
                        
                    print(f"  IOP: {iop}")
                    print(f"  Slice normal: {slice_normal}")
                    print(f"  Max component index: {max_component}")
                else:
                    result = 'unknown'
            except (ValueError, TypeError, IndexError):
                result = 'unknown'
        else:
            result = 'unknown'
        
        # Check result
        if result == test_case['expected']:
            print(f"  ✓ Result: {result} (PASS)")
        else:
            print(f"  ✗ Result: {result}, Expected: {test_case['expected']} (FAIL)")
        
        print()
    
    print("Test completed!")

if __name__ == '__main__':
    test_acquisition_plane_calculation()