"""
Tests for acquisition and run number assignment with multi-parametric acquisitions.

This tests the core logic:
1. Acquisitions are identified by ProtocolName + parameter signatures
2. Parameter signatures include the SET of varying parameters (e.g., all echo times)
3. Files with same parameter sets = same acquisition
4. Files with different parameter sets = different acquisitions
5. Runs are temporal repetitions of the same acquisition (identified by SeriesTime)
"""

import pandas as pd
import pytest
from dicompare.session.acquisition import assign_acquisition_and_run_numbers


def test_assign_acquisition_and_run_numbers_multiparametric():
    """
    Test that multi-echo acquisitions are properly grouped and runs are detected correctly.

    Uses 5-second temporal windowing based on AcquisitionTime.

    Scenario 1: Multi-echo (5 echoes) with M+P, first run
                All echoes acquired within 1 second (same temporal bin)
    Scenario 2: Single-echo with M only (different acquisition!)
                Acquired 10 seconds later (different temporal bin)
    Scenario 3: Multi-echo (5 echoes) with M+P, second run (repeat of Scenario 1)
                Acquired 20 seconds after Scenario 1 (different temporal bin, same acquisition)
    """

    # Create mock DataFrame with all required fields
    data = []

    # Scenario 1: Multi-echo acquisition, Run 1
    # 5 echoes × 2 types (M, P) = 10 files
    # All acquired within 0.030 seconds (like real QSM data)
    echo_times_full = [7.0, 12.0, 17.0, 22.0, 27.0]
    base_acq_time_1 = 100004.327500  # 10:00:04.327500

    for i, echo_time in enumerate(echo_times_full):
        # Each echo 0.005 seconds apart (5 milliseconds)
        acq_time = base_acq_time_1 + (i * 0.005)

        for image_type in [('ORIGINAL', 'PRIMARY', 'M'), ('ORIGINAL', 'PRIMARY', 'P')]:
            data.append({
                'ProtocolName': 'MultiEcho_QSM',
                'PatientName': 'Patient001',
                'PatientID': 'P001',
                'StudyDate': '20250101',
                'SeriesTime': f'{100800 + i}.{(image_type[2] == "P") * 1}00000',  # Different SeriesTimes
                'EchoTime': echo_time,
                'ImageType': image_type,
                'RepetitionTime': 41.0,
                'FlipAngle': 15.0,
                'SeriesDescription': 'MultiEcho_QSM',
                'SeriesInstanceUID': f'1.2.3.{echo_time}.{image_type[2]}.1',
                'AcquisitionTime': f'{acq_time:.6f}',
            })

    # Scenario 2: Single-echo, M only (DIFFERENT ACQUISITION)
    # Different echo set = different acquisition
    # Acquired 10 seconds later (different temporal bin)
    data.append({
        'ProtocolName': 'MultiEcho_QSM',  # Same protocol!
        'PatientName': 'Patient001',
        'PatientID': 'P001',
        'StudyDate': '20250101',
        'SeriesTime': '100900.000000',
        'EchoTime': 12.0,  # Only one echo
        'ImageType': ('ORIGINAL', 'PRIMARY', 'M'),
        'RepetitionTime': 41.0,
        'FlipAngle': 15.0,
        'SeriesDescription': 'MultiEcho_QSM',
        'SeriesInstanceUID': '1.2.3.12.M.2',
        'AcquisitionTime': f'{100004.327500 + 10.0:.6f}',  # 10 seconds later
    })

    # Scenario 3: Multi-echo acquisition, Run 2 (repeat of Scenario 1)
    # Same echo set as Scenario 1 = same acquisition, different run
    # Acquired 20 seconds after Scenario 1 (different temporal bin)
    base_acq_time_3 = 100004.327500 + 20.0  # 20 seconds later

    for i, echo_time in enumerate(echo_times_full):
        acq_time = base_acq_time_3 + (i * 0.005)

        for image_type in [('ORIGINAL', 'PRIMARY', 'M'), ('ORIGINAL', 'PRIMARY', 'P')]:
            data.append({
                'ProtocolName': 'MultiEcho_QSM',
                'PatientName': 'Patient001',
                'PatientID': 'P001',
                'StudyDate': '20250101',
                'SeriesTime': f'{101000 + i}.{(image_type[2] == "P") * 1}00000',  # Different SeriesTimes
                'EchoTime': echo_time,
                'ImageType': image_type,
                'RepetitionTime': 41.0,
                'FlipAngle': 15.0,
                'SeriesDescription': 'MultiEcho_QSM',
                'SeriesInstanceUID': f'1.2.3.{echo_time}.{image_type[2]}.3',
                'AcquisitionTime': f'{acq_time:.6f}',
            })

    # Create DataFrame
    df = pd.DataFrame(data)

    # Run the assignment function
    result_df = assign_acquisition_and_run_numbers(df)

    # ===== ASSERTIONS =====

    # Test 1: Should have exactly 2 unique acquisitions
    # (Scenarios 1 & 3 share the same signature, Scenario 2 is different)
    n_acquisitions = result_df['Acquisition'].nunique()
    print(f"\nNumber of unique acquisitions: {n_acquisitions}")
    print(f"Unique acquisitions: {result_df['Acquisition'].unique()}")
    assert n_acquisitions == 2, f"Expected 2 acquisitions, got {n_acquisitions}"

    # Test 2: Scenarios 1 & 3 should have the SAME acquisition label
    scenario_1_acq = result_df[result_df['SeriesTime'] == '100800.000000']['Acquisition'].iloc[0]
    scenario_3_acq = result_df[result_df['SeriesTime'] == '101000.000000']['Acquisition'].iloc[0]
    print(f"\nScenario 1 acquisition: {scenario_1_acq}")
    print(f"Scenario 3 acquisition: {scenario_3_acq}")
    assert scenario_1_acq == scenario_3_acq, \
        f"Scenarios 1 & 3 should have same acquisition, got {scenario_1_acq} vs {scenario_3_acq}"

    # Test 3: Scenario 2 should have a DIFFERENT acquisition label
    scenario_2_acq = result_df[result_df['SeriesTime'] == '100900.000000']['Acquisition'].iloc[0]
    print(f"Scenario 2 acquisition: {scenario_2_acq}")
    assert scenario_2_acq != scenario_1_acq, \
        f"Scenario 2 should have different acquisition from Scenario 1, both are {scenario_1_acq}"

    # Test 4: Scenario 1 should be Run 1
    scenario_1_runs = result_df[result_df['SeriesTime'] == '100800.000000']['RunNumber'].unique()
    print(f"\nScenario 1 run numbers: {scenario_1_runs}")
    assert list(scenario_1_runs) == [1], \
        f"Scenario 1 should be Run 1, got {scenario_1_runs}"

    # Test 5: Scenario 3 should be Run 2 (second run of same acquisition)
    scenario_3_runs = result_df[result_df['SeriesTime'] == '101000.000000']['RunNumber'].unique()
    print(f"Scenario 3 run numbers: {scenario_3_runs}")
    assert list(scenario_3_runs) == [2], \
        f"Scenario 3 should be Run 2, got {scenario_3_runs}"

    # Test 6: Scenario 2 should be Run 1 (first run of its different acquisition)
    scenario_2_runs = result_df[result_df['SeriesTime'] == '100900.000000']['RunNumber'].unique()
    print(f"Scenario 2 run numbers: {scenario_2_runs}")
    assert list(scenario_2_runs) == [1], \
        f"Scenario 2 should be Run 1, got {scenario_2_runs}"

    # Test 7: All echoes within Scenario 1 should have same RunNumber
    scenario_1_group = result_df[result_df['SeriesTime'].str.startswith('10080')]
    echo_times_found = set(scenario_1_group['EchoTime'].unique())
    print(f"\nScenario 1 echo times: {sorted(echo_times_found)}")
    assert echo_times_found == set(echo_times_full), \
        f"Expected echo times {echo_times_full}, got {echo_times_found}"

    runs_per_echo = scenario_1_group['RunNumber'].nunique()
    assert runs_per_echo == 1, \
        f"All echoes in Scenario 1 should have same RunNumber, got {runs_per_echo} unique values"

    # Test 8: All echoes within Scenario 3 should have same RunNumber
    scenario_3_group = result_df[result_df['SeriesTime'].str.startswith('10100')]
    echo_times_found_3 = set(scenario_3_group['EchoTime'].unique())
    assert echo_times_found_3 == set(echo_times_full), \
        f"Expected echo times {echo_times_full}, got {echo_times_found_3}"

    runs_per_echo_3 = scenario_3_group['RunNumber'].nunique()
    assert runs_per_echo_3 == 1, \
        f"All echoes in Scenario 3 should have same RunNumber, got {runs_per_echo_3} unique values"

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    test_assign_acquisition_and_run_numbers_multiparametric()
