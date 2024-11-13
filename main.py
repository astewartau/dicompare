import os
import pydicom
import pandas as pd
from pydicom.multival import MultiValue
import json
from guidelines.qsm.qsm import identify_qsm_runs

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

def read_dicoms(dicom_folder, fields):
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

def apply_flags(df, json_data, ref=None):
    # Extract the flags specification
    flags_spec = json_data["rules"]

    # Initialize `rules` and `failed_matches` as empty lists
    df['rules'] = [[] for _ in range(len(df))]
    if ref is not None:
        df['failed_matches'] = [[] for _ in range(len(df))]

    for index, row in df.iterrows():
        # Local variable to represent the current row
        row_data = row.to_dict()
        for rule in flags_spec:
            # Execute the condition as code within Python, using row_data to check each condition
            try:
                # Define the condition explicitly
                condition = rule["data_source"]

                # Check if the condition is True for the current row
                result = eval(condition, {"df": df, "row": row_data})
                if result:
                    df.at[index, 'rules'].append(rule["rule_id"])
            except Exception as e:
                print(f"Error evaluating flag {rule['rule_id']}: {e}")

    # Apply reference rules if a reference DataFrame is provided
    if ref is not None:
        if "reference_rules" in json_data:
            df['reference_rules'] = [[] for _ in range(len(df))]
            ref_spec = json_data["reference_rules"]
            for index, row in df.iterrows():
                for rule in ref_spec:
                    try:
                        if eval(rule["data_source"]):
                            df.at[index, 'reference_rules'].append(rule["rule_id"])
                    except Exception as e:
                        print(f"Error evaluating flag {rule['rule_id']}: {e}")
                        
    if "reference_required_matches" in json_data and ref is not None:
        ref_nomatch_spec = json_data["reference_required_matches"]

        # Check that the number of rows in df and ref are the same
        if len(df) != len(ref):
            df['failed_matches'] = [ref_nomatch_spec for _ in range(len(df))]
            return df
        
        # Save the original order of df and ref by creating a temporary index
        df['original_order'] = range(len(df))
        ref['original_order'] = range(len(ref))
        
        for field in ref_nomatch_spec:
            # Sort both df and ref by the current field without reassigning
            df_sorted = df.sort_values(by=field).reset_index(drop=True)
            ref_sorted = ref.sort_values(by=field).reset_index(drop=True)

            # Perform the row-wise comparison for the current field
            for index, (row_df, row_ref) in enumerate(zip(df_sorted.iterrows(), ref_sorted.iterrows())):
                row_df_data, row_ref_data = row_df[1], row_ref[1]  # Extract row data
                if row_df_data[field] != row_ref_data[field]:
                    df.at[df_sorted.index[index], 'failed_matches'].append(field)
        
        # Restore the original order based on the temporary index and drop it afterward
        df = df.sort_values(by='original_order').drop(columns='original_order').reset_index(drop=True)
        ref = ref.sort_values(by='original_order').drop(columns='original_order').reset_index(drop=True)

    # Fill any remaining NaNs in `rules`, `failed_matches`, and `reference_rules` with empty lists
    df['rules'] = df['rules'].apply(lambda x: x if isinstance(x, list) else [])
    if 'failed_matches' in df.columns:
        df['failed_matches'] = df['failed_matches'].apply(lambda x: x if isinstance(x, list) else [])
    if 'reference_rules' in df.columns:
        df['reference_rules'] = df['reference_rules'].apply(lambda x: x if isinstance(x, list) else [])

    return df
    

if __name__ == "__main__":
    with open("guidelines/qsm/qsm.json") as f:
        json_data = json.load(f)

    #dicom_folder = "/home/ashley/downloads/DICOMs/dicoms-sorted"
    dicom_folder = "/home/ashley/downloads/DICOMs/dwi-dicoms"
    dicom_series = read_dicoms(dicom_folder, json_data["series_fields"])

    print(dicom_series)

    # Save the DataFrame to a CSV file
    csv_path = "results.csv"
    dicom_series.to_csv(csv_path, index=False)
    print("Results saved to", csv_path)
    exit()
    dicom_series = identify_qsm_runs(dicom_series)

    # remove qsm_series with `QSM Run` 1 and store as ref_qsm_series
    ref_series = dicom_series[dicom_series['QSM Run'] == 1]
    new_series = dicom_series[dicom_series['QSM Run'] != 1]

    # Create an empty list to hold processed DataFrames
    processed_segments = []

    # Apply flags in-place based on JSON specs for each QSM Run and collect results
    for i in range(1, new_series['QSM Run'].max() + 1):
        mask = new_series['QSM Run'] == i
        # Apply flags on a copy of the masked segment
        flagged_segment = apply_flags(new_series.loc[mask].copy(), json_data, ref_series)
        # Append the processed segment to the list
        processed_segments.append(flagged_segment)

    # Concatenate all processed segments back into new_series
    new_series = pd.concat(processed_segments).reset_index(drop=True)

    print("REF", ref_series)
    print("NEW", new_series)

