#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from dicompare.tests.fixtures.fixtures import create_empty_dicom
from dicompare.io import _process_dicom_element
from pydicom.multival import MultiValue

# Create test DICOM dataset with string values (as they might come from other sources)
ds = create_empty_dicom()

# Add fields with string values (like what might come from JSON or other sources)
ds.RepetitionTime = "8.0"
ds.EchoTime = "3.0"
ds.PixelSpacing = ["0.5", "0.5"]  # Strings in list
ds.AcquisitionMatrix = ["256", "0", "0", "256"]  # Strings in list

print("=== DICOM Element Types (with string inputs) ===")
for element in ds:
    if element.keyword in ['PixelSpacing', 'AcquisitionMatrix', 'RepetitionTime', 'EchoTime']:
        print(f"\n{element.keyword}:")
        print(f"  Raw value: {element.value}")
        print(f"  Type: {type(element.value)}")
        if hasattr(element.value, '__iter__') and not isinstance(element.value, str):
            print(f"  Element types: {[type(v) for v in element.value]}")
        
        # Process the element
        processed = _process_dicom_element(element)
        print(f"  Processed: {processed}")
        print(f"  Processed type: {type(processed)}")
        if isinstance(processed, tuple):
            print(f"  Processed element types: {[type(v) for v in processed]}")
            
print("\n=== Testing MultiValue with strings ===")
from pydicom.multival import MultiValue
mv = MultiValue(str, ["1.0", "2.0"])
print(f"MultiValue: {mv}")
print(f"Type: {type(mv)}")
print(f"Element types: {[type(v) for v in mv]}")

# Create a fake element to test
class FakeElement:
    def __init__(self, keyword, value):
        self.keyword = keyword
        self.value = value

fake_element = FakeElement("PixelSpacing", mv)
processed = _process_dicom_element(fake_element)
print(f"Processed: {processed}")
print(f"Processed type: {type(processed)}")
if isinstance(processed, tuple):
    print(f"Processed element types: {[type(v) for v in processed]}")