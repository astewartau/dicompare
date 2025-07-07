#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import pandas as pd
from dicompare.generate_schema import create_json_schema
from dicompare.data_utils import make_dataframe_hashable
import json

# Create a test DataFrame that mimics the issue
df = pd.DataFrame({
    'Acquisition': ['T1', 'T1', 'T1'],
    'PixelSpacing': [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]],
    'AcquisitionMatrix': [[0, 256, 256, 0], [0, 256, 256, 0], [0, 256, 256, 0]],
    'RepetitionTime': [2000, 2000, 2000],
    'EchoTime': [0.03, 0.03, 0.03]
})

print("Original DataFrame:")
print(df)
print("\nData types:")
print(df.dtypes)

# Test with hashable conversion
print("\n=== Testing make_dataframe_hashable ===")
hashable_df = make_dataframe_hashable(df.copy())
print("After make_dataframe_hashable:")
print(hashable_df)
print("\nData types after hashable:")
print(hashable_df.dtypes)

# Create JSON schema
print("\n=== Creating JSON Schema ===")
reference_fields = ['PixelSpacing', 'AcquisitionMatrix', 'RepetitionTime', 'EchoTime']
schema = create_json_schema(df, reference_fields)

# Check types in the schema first
print("\n=== Checking types in schema ===")
for acq_name, acq_data in schema['acquisitions'].items():
    print(f"\nAcquisition: {acq_name}")
    for field in acq_data['fields']:
        field_name = field['field']
        field_value = field['value']
        print(f"  {field_name}: {field_value} (type: {type(field_value)})")
        if isinstance(field_value, tuple):
            print(f"    Elements: {[f'{v} (type: {type(v)})' for v in field_value]}")

# Try to convert to JSON-serializable format  
def convert_to_json_serializable(obj):
    """Convert numpy/pandas types to JSON-serializable Python types"""
    if isinstance(obj, dict):
        return {k: convert_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_to_json_serializable(v) for v in obj]
    elif hasattr(obj, 'item'):  # numpy scalar
        return obj.item()
    elif hasattr(obj, 'tolist'):  # numpy array
        return obj.tolist()
    else:
        return obj

print("\n=== Converting to JSON-serializable format ===")
json_serializable_schema = convert_to_json_serializable(schema)
print(json.dumps(json_serializable_schema, indent=2))