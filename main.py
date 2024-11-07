import os
import pydicom
import pandas as pd
from pydicom.multival import MultiValue
import json

# Existing functions remain the same
def extract_relevant_fields(dicom_path, fields):
    """Extract relevant fields from a DICOM file, setting None for missing or empty fields."""
    try:
        dicom_data = pydicom.dcmread(dicom_path, stop_before_pixels=True)
        header = {}
        for field in fields:
            value = getattr(dicom_data, field, None)
            
            # Convert PersonName and MultiValue objects to strings or tuples
            if isinstance(value, pydicom.valuerep.PersonName):
                value = str(value)
            elif isinstance(value, MultiValue):
                try:
                    value = tuple(float(v) for v in value)
                except ValueError:
                    value = tuple(value)  # Convert MultiValue to tuple for hashability

            header[field] = value if value else None
        return header
    except Exception as e:
        print(f"Skipping non-DICOM file {dicom_path}: {e}")
        return None

def get_unique_dicom_combinations(dicom_folder, fields):
    """Process all possible DICOM files in a folder tree and return unique combinations of specified fields."""
    combinations_dict = {}
    
    for root, _, files in os.walk(dicom_folder):
        for filename in files:
            if filename.endswith((".dcm", ".IMA")) or '.' not in filename:
                dicom_path = os.path.join(root, filename)
                header = extract_relevant_fields(dicom_path, fields)
                
                if header is None:
                    continue
                
                header_tuple = tuple(header.items())
                
                if header_tuple in combinations_dict:
                    combinations_dict[header_tuple] += 1
                else:
                    combinations_dict[header_tuple] = 1

    data = [dict(combination, Slices=count) for combination, count in combinations_dict.items()]
    df = pd.DataFrame(data)
    return df

def get_qsm_series(dicom_folder):
    unique_fields = [
        "SeriesTime", "Modality", "PatientName", "PatientID", "AcquisitionDate", "SeriesNumber",
        "StudyDescription", "SequenceName", "ProtocolName", "SeriesDescription",
        "MagneticFieldStrength", "EchoNumbers", "EchoTime", "RepetitionTime", "SliceThickness", 
        "FlipAngle", "Rows", "Columns", "ImageType", "PixelSpacing"
    ]
    
    df = get_unique_dicom_combinations(dicom_folder, unique_fields)

    sort_fields = [col for col in ["PatientName", "AcquisitionDate", "SeriesTime", "SeriesNumber"] if col in df.columns]
    df.sort_values(by=sort_fields, inplace=True)

    df_echo = df.drop(columns=['EchoTime', 'EchoNumbers']).drop_duplicates()

    phase_series = df_echo[df_echo['ImageType'].apply(lambda x: 'P' in x)]
    magnitude_series = df_echo[df_echo['ImageType'].apply(lambda x: 'M' in x and 'P' not in x) & (df_echo['SeriesNumber'].isin(phase_series['SeriesNumber'] - 1) | df_echo['SeriesNumber'].isin(phase_series['SeriesNumber'] + 1))]
    qsm_series = pd.concat([phase_series, magnitude_series]).sort_values(by='SeriesNumber')

    qsm_run_counter = 1
    qsm_series['QSM Run'] = None

    for _, phase_row in phase_series.iterrows():
        matching_magnitude = magnitude_series[
                (magnitude_series['PatientName'] == phase_row['PatientName']) &
                (magnitude_series['AcquisitionDate'] == phase_row['AcquisitionDate']) &
                (magnitude_series['SequenceName'] == phase_row['SequenceName']) &
                (magnitude_series['ProtocolName'] == phase_row['ProtocolName']) &
                (magnitude_series['MagneticFieldStrength'] == phase_row['MagneticFieldStrength']) &
                (abs(phase_row['SeriesNumber'] - magnitude_series['SeriesNumber']) == 1)
        ]

        qsm_series.loc[qsm_series.index == phase_row.name, 'QSM Run'] = qsm_run_counter

        if not matching_magnitude.empty:
            qsm_series.loc[matching_magnitude.index, 'QSM Run'] = qsm_run_counter

        qsm_run_counter += 1

    qsm_series = qsm_series[qsm_series['QSM Run'].notna()]
    qsm_series = pd.merge(qsm_series, df, on=[col for col in df.columns if col in qsm_series.columns])

    return qsm_series

def apply_flags(qsm_series, json_spec, ref=None):
    # Load JSON specification
    flags_spec = json.loads(json_spec)["flags"]
    
    # Add a new column to hold flags
    qsm_series['flags'] = [[] for _ in range(len(qsm_series))]

    # Process each unique QSM Run
    for qsm_run in qsm_series['QSM Run'].unique():
        df = qsm_series[qsm_series['QSM Run'] == qsm_run]

        for flag in flags_spec:
            # Evaluate the data_source expression for the subset dataframe
            try:
                if eval(flag["data_source"]):
                    # Append the flag_id to each entry in the subset
                    qsm_series.loc[qsm_series['QSM Run'] == qsm_run, 'flags'] = qsm_series.loc[qsm_series['QSM Run'] == qsm_run, 'flags'].apply(lambda x: x + [flag["flag_id"]])
            except Exception as e:
                print(f"Error evaluating flag {flag['flag_id']}: {e}")

    if ref is not None:
        qsm_series['ref_flags'] = [[] for _ in range(len(qsm_series))]
        ref_spec = json.loads(json_spec)["reference_flags"]
        for qsm_run in qsm_series['QSM Run'].unique():
            df = qsm_series[qsm_series['QSM Run'] == qsm_run]
            for flag in ref_spec:
                try:
                    if eval(flag["data_source"]):
                        qsm_series.loc[qsm_series['QSM Run'] == qsm_run, 'ref_flags'] = qsm_series.loc[qsm_series['QSM Run'] == qsm_run, 'ref_flags'].apply(lambda x: x + [flag["flag_id"]])
                except Exception as e:
                    print(f"Error evaluating flag {flag['flag_id']}: {e}")

    return qsm_series

# Example usage
if __name__ == "__main__":
    dicom_folder = "/home/ashley/downloads/DICOMs/dicoms-sorted"
    qsm_series = get_qsm_series(dicom_folder)

    # remove qsm_series with `QSM Run` 1 and store as ref_qsm_series
    ref_qsm_series = qsm_series[qsm_series['QSM Run'] == 1]
    qsm_series = qsm_series[qsm_series['QSM Run'] != 1]
    print("REF")
    print(ref_qsm_series)
    # load the JSON specification
    with open("guidelines/qsm.json") as f:
        json_spec = f.read()

    # Apply flags based on JSON specs
    qsm_series = apply_flags(qsm_series, json_spec, ref=ref_qsm_series)

    print(qsm_series)

    # Save the DataFrame to a CSV file
    csv_path = "results.csv"
    qsm_series.to_csv(csv_path, index=False)
    print("Results saved to", csv_path)
