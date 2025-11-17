#!/usr/bin/env python3
"""
Investigate why QSM data splits into two acquisitions when loaded from full dataset.
"""

import sys
import pandas as pd
from dicompare import load_dicom_session, assign_acquisition_and_run_numbers_v2
from dicompare.config import DEFAULT_SETTINGS_FIELDS

print("=" * 80)
print("QSM Split Investigation")
print("=" * 80)

# Load QSM data alone
print("\n1. Loading QSM data from /home/ashley/TEST_RUNS/qsm/...")
qsm_df = load_dicom_session("/home/ashley/TEST_RUNS/qsm/")
print(f"   Loaded {len(qsm_df)} files")

# Process QSM alone
print("\n2. Processing QSM data alone...")
qsm_processed = assign_acquisition_and_run_numbers_v2(qsm_df)
print("\n   Results:")
for acq in sorted(qsm_processed['Acquisition'].unique()):
    acq_data = qsm_processed[qsm_processed['Acquisition'] == acq]
    runs = sorted(acq_data['RunNumber'].unique())
    print(f"   - {acq}: Runs {runs}")

# Load full dataset
print("\n3. Loading full dataset from /home/ashley/TEST_RUNS/full/...")
full_df = load_dicom_session("/home/ashley/TEST_RUNS/full/")
print(f"   Loaded {len(full_df)} files")

# Process full dataset
print("\n4. Processing full dataset...")
full_processed = assign_acquisition_and_run_numbers_v2(full_df)
print("\n   Results:")
for acq in sorted(full_processed['Acquisition'].unique()):
    acq_data = full_processed[full_processed['Acquisition'] == acq]
    runs = sorted(acq_data['RunNumber'].unique())
    print(f"   - {acq}: Runs {runs}")

# Find QSM acquisitions in full dataset
print("\n5. Analyzing QSM acquisitions in full dataset...")
qsm_acqs = [acq for acq in full_processed['Acquisition'].unique()
            if 'wip925b1mmpat3eco6' in acq.lower()]

if len(qsm_acqs) < 2:
    print("   ERROR: Expected 2 QSM acquisitions in full dataset, found:", qsm_acqs)
    sys.exit(1)

print(f"   Found QSM acquisitions: {qsm_acqs}")

# Get data for each QSM acquisition
acq1_name = sorted(qsm_acqs)[0]
acq2_name = sorted(qsm_acqs)[1]

acq1_data = full_processed[full_processed['Acquisition'] == acq1_name]
acq2_data = full_processed[full_processed['Acquisition'] == acq2_name]

print(f"\n   {acq1_name}: {len(acq1_data)} files")
print(f"   {acq2_name}: {len(acq2_data)} files")

# Compare settings fields
print("\n6. Comparing settings fields between the two acquisitions...")
print("   (Looking for fields that differ and caused the split)\n")

# Get one representative file from each acquisition
acq1_sample = acq1_data.iloc[0]
acq2_sample = acq2_data.iloc[0]

differing_fields = []

for field in DEFAULT_SETTINGS_FIELDS:
    if field in acq1_sample.index and field in acq2_sample.index:
        val1 = acq1_sample[field]
        val2 = acq2_sample[field]

        # Handle NaN comparison
        if pd.isna(val1) and pd.isna(val2):
            continue
        elif pd.isna(val1) or pd.isna(val2):
            differing_fields.append((field, val1, val2))
            print(f"   ❌ {field}:")
            print(f"      {acq1_name}: {val1}")
            print(f"      {acq2_name}: {val2}")
            print()
        elif val1 != val2:
            differing_fields.append((field, val1, val2))
            print(f"   ❌ {field}:")
            print(f"      {acq1_name}: {val1}")
            print(f"      {acq2_name}: {val2}")
            print()

if not differing_fields:
    print("   ✓ No differing settings fields found!")
    print("   This suggests the split may be due to a bug in the algorithm.")
else:
    print(f"\n7. Summary: Found {len(differing_fields)} differing settings field(s):")
    for field, val1, val2 in differing_fields:
        print(f"   - {field}")

print("\n" + "=" * 80)
print("Investigation complete!")
print("=" * 80)
