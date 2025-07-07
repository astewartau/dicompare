#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import pandas as pd
from dicompare.generate_schema import create_json_schema
from dicompare.data_utils import make_dataframe_hashable
from dicompare.io import load_dicom
from dicompare.tests.fixtures.fixtures import create_empty_dicom
import json
import tempfile

# Create a test DICOM file with string values in MultiValue fields
ds = create_empty_dicom()
ds.RepetitionTime = "8.0"
ds.EchoTime = "3.0"
ds.PixelSpacing = ["1.0", "1.0"]  # String values in MultiValue
ds.AcquisitionMatrix = ["0", "256", "256", "0"]  # String values in MultiValue

# Save to temporary file
with tempfile.NamedTemporaryFile(suffix='.dcm', delete=False) as temp_file:
    ds.save_as(temp_file.name)
    temp_path = temp_file.name

print("=== Loading DICOM file ===")
metadata = load_dicom(temp_path)

print("Key fields in metadata:")
for field in ['PixelSpacing', 'AcquisitionMatrix', 'RepetitionTime', 'EchoTime']:
    if field in metadata:
        value = metadata[field]
        print(f"  {field}: {value} (type: {type(value)})")
        if isinstance(value, tuple):
            print(f"    Element types: {[type(v) for v in value]}")

print("\n=== Creating DataFrame ===")
df = pd.DataFrame([metadata])
print("DataFrame types:")
print(df.dtypes)

print("\n=== Creating JSON Schema ===")
reference_fields = ['PixelSpacing', 'AcquisitionMatrix', 'RepetitionTime', 'EchoTime']
schema = create_json_schema(df, reference_fields)

print("\nSchema field types:")
for acq_name, acq_data in schema['acquisitions'].items():
    print(f"\nAcquisition: {acq_name}")
    for field in acq_data['fields']:
        field_name = field['field']
        field_value = field['value']
        print(f"  {field_name}: {field_value} (type: {type(field_value)})")
        if isinstance(field_value, tuple):
            print(f"    Element types: {[type(v) for v in field_value]}")

# Clean up
os.unlink(temp_path)