#!/usr/bin/env python3

import pandas as pd

def identify_qsm_runs(df):
    sort_fields = [col for col in ["PatientName", "AcquisitionDate", "SeriesTime", "SeriesNumber"] if col in df.columns]
    df.sort_values(by=sort_fields, inplace=True)

    df_noecho = df.drop(columns=['EchoTime', 'EchoNumbers']).drop_duplicates()
    
    phase_series = df_noecho[df_noecho['ImageType'].apply(lambda x: 'P' in x)]
    magnitude_series = df_noecho[df_noecho['ImageType'].apply(lambda x: 'M' in x and 'P' not in x) & (df_noecho['SeriesNumber'].isin(phase_series['SeriesNumber'] - 1) | df_noecho['SeriesNumber'].isin(phase_series['SeriesNumber'] + 1))]
    qsm_df = pd.concat([phase_series, magnitude_series]).sort_values(by='SeriesNumber')

    qsm_run_counter = 1
    qsm_df['QSM Run'] = None

    for _, phase_row in phase_series.iterrows():
        matching_magnitude = magnitude_series[
                (magnitude_series['PatientName'] == phase_row['PatientName']) &
                (magnitude_series['AcquisitionDate'] == phase_row['AcquisitionDate']) &
                (magnitude_series['SequenceName'] == phase_row['SequenceName']) &
                (magnitude_series['ProtocolName'] == phase_row['ProtocolName']) &
                (magnitude_series['MagneticFieldStrength'] == phase_row['MagneticFieldStrength']) &
                (abs(phase_row['SeriesNumber'] - magnitude_series['SeriesNumber']) == 1)
        ]

        qsm_df.loc[qsm_df.index == phase_row.name, 'QSM Run'] = qsm_run_counter

        if not matching_magnitude.empty:
            qsm_df.loc[matching_magnitude.index, 'QSM Run'] = qsm_run_counter

        qsm_run_counter += 1

    qsm_df = qsm_df[qsm_df['QSM Run'].notna()]
    qsm_df = pd.merge(qsm_df, df, on=[col for col in df.columns if col in qsm_df.columns])

    qsm_df.sort_values(by=["QSM Run", "EchoTime"], inplace=True)

    return qsm_df

