import subprocess
import json
import os
import pytest
import pydicom
import pandas as pd
from tabulate import tabulate

# Directory setup (update paths as necessary)
CLI_SCRIPT = "dcm-check"  # Adjust path if needed
DICOM_FILE = "dcm_check/tests/ref_dicom.dcm"  # Replace with actual test DICOM file path
JSON_REF = "dcm_check/tests/ref_json.json"  # Replace with actual JSON reference file path
PYDANTIC_REF = "dcm_check/tests/ref_pydantic.py"  # Python module for pydantic references
OUTPUT_JSON = "compliance_output.json"  # Output file for tests

COMPLIANT_MESSAGE = "DICOM file is compliant with the reference model."
SAVED_MESSAGE = "Compliance report saved to compliance_output.json"

def test_cli_json_reference_with_series():
    command = [
        CLI_SCRIPT,
        "--ref", JSON_REF,
        "--type", "json",
        "--acquisition", "T1",
        "--series", "Series 1",
        "--in", DICOM_FILE
    ]

    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    
    expected_output = "DICOM file is compliant with the reference model."
    
    assert result.returncode == 0
    assert expected_output in result.stdout


def test_cli_json_reference_compliant_no_series():
    command = [CLI_SCRIPT, "--ref", JSON_REF, "--type", "json", "--acquisition", "T1", "--in", DICOM_FILE]
    
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    
    assert result.returncode == 0
    assert COMPLIANT_MESSAGE in result.stdout

def test_cli_output_file_compliant_with_series():
    command = [
        CLI_SCRIPT,
        "--ref", JSON_REF,
        "--type", "json",
        "--acquisition", "T1",
        "--series", "Series 1",
        "--in", DICOM_FILE,
        "--out", OUTPUT_JSON
    ]
    
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    
    assert COMPLIANT_MESSAGE in result.stdout
    assert SAVED_MESSAGE in result.stdout

    assert os.path.isfile(OUTPUT_JSON)
    
    with open(OUTPUT_JSON) as f:
        results = json.load(f)
    
    assert isinstance(results, list)  # Validate that results are in list format
    assert len(results) == 0  # Validate that no compliance issues were found

    os.remove(OUTPUT_JSON)

def test_cli_output_file_not_compliant_with_series():
    # Modify the DICOM file to make it non-compliant
    dicom = pydicom.dcmread(DICOM_FILE)
    dicom.ImageType = ["ORIGINAL", "PRIMARY", "P", "N"]
    non_compliant_dicom = "dcm_check/tests/non_compliant_dicom.dcm"
    dicom.save_as(non_compliant_dicom)

    command = [
        CLI_SCRIPT,
        "--ref", JSON_REF,
        "--type", "json",
        "--acquisition", "T1",
        "--series", "Series 1",
        "--in", non_compliant_dicom,
        "--out", OUTPUT_JSON
    ]

    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)

    expected_output = tabulate(pd.DataFrame({ # as above
        "Acquisition": ["T1"],
        "Series": ["Series 1"],
        "Parameter": ["ImageType"],
        "Value": [['ORIGINAL', 'PRIMARY', 'P', 'N']],
        "Expected": ["Value error, ImageType must contain 'M'"]
    }), headers="keys", tablefmt="simple")
    
    assert result.returncode == 0
    assert expected_output in result.stdout

    assert os.path.isfile(OUTPUT_JSON)
    
    with open(OUTPUT_JSON) as f:
        results = json.load(f)
    
    assert isinstance(results, list)  # Validate that results are in list format
    assert len(results) == 1  # Validate that one compliance issue was found

    os.remove(OUTPUT_JSON)

    # delete the non-compliant DICOM file
    os.remove(non_compliant_dicom)

def test_cli_json_reference():
    command = [CLI_SCRIPT, "--ref", JSON_REF, "--type", "json", "--acquisition", "T1", "--in", DICOM_FILE]

    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    
    assert result.returncode == 0
    assert COMPLIANT_MESSAGE in result.stdout

def test_cli_json_reference_inferred_type():
    command = [CLI_SCRIPT, "--ref", JSON_REF, "--acquisition", "T1", "--in", DICOM_FILE]

    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    
    assert result.returncode == 0
    assert COMPLIANT_MESSAGE in result.stdout

def test_cli_dicom_reference():
    command = [CLI_SCRIPT, "--ref", DICOM_FILE, "--type", "dicom", "--in", DICOM_FILE, "--fields", "SAR", "FlipAngle"]

    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0
    assert COMPLIANT_MESSAGE in result.stdout

def test_cli_dicom_reference_inferred_type():
    command = [CLI_SCRIPT, "--ref", DICOM_FILE, "--in", DICOM_FILE, "--fields", "SAR", "FlipAngle"]
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0
    assert COMPLIANT_MESSAGE in result.stdout

def test_cli_dicom_reference_non_compliant():
    # Modify the DICOM file to make it non-compliant
    dicom = pydicom.dcmread(DICOM_FILE)
    dicom.FlipAngle = 45
    non_compliant_dicom = "dcm_check/tests/non_compliant_dicom.dcm"
    dicom.save_as(non_compliant_dicom)

    command = [CLI_SCRIPT, "--ref", DICOM_FILE, "--type", "dicom", "--in", non_compliant_dicom, "--fields", "SAR", "FlipAngle"]
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)

    expected_output = tabulate(pd.DataFrame({
        "Parameter": ["FlipAngle"],
        "Value": [45],
        "Expected": [15]
    }), headers="keys", tablefmt="simple")

    # delete the non-compliant DICOM file
    os.remove(non_compliant_dicom)

    assert result.returncode == 0
    assert expected_output in result.stdout

def test_cli_pydantic_reference():
    command = [CLI_SCRIPT, "--ref", PYDANTIC_REF, "--type", "pydantic", "--acquisition", "T1_MPR", "--in", DICOM_FILE]
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)

    expected_output = tabulate(pd.DataFrame({
        "Acquisition": ["T1_MPR", "T1_MPR", "T1_MPR", "T1_MPR"],
        "Parameter": ["MagneticFieldStrength", "RepetitionTime", "PixelSpacing", "SliceThickness"],
        "Value": ["N/A", 8.0, ['0.5', '0.5'], 1.0],
        "Expected": ["Field required", "Input should be greater than or equal to 2300", "Value error, Each value in PixelSpacing must be between 0.75 and 0.85", "Input should be less than or equal to 0.85"]
    }), headers="keys", tablefmt="simple")

    assert result.returncode == 0
    assert expected_output in result.stdout  # Validate that output includes compliance info

def test_cli_pydantic_reference_inferred_type():
    command = [CLI_SCRIPT, "--ref", PYDANTIC_REF, "--acquisition", "T1_MPR", "--in", DICOM_FILE]
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)

    expected_output = tabulate(pd.DataFrame({
        "Acquisition": ["T1_MPR", "T1_MPR", "T1_MPR", "T1_MPR"],
        "Parameter": ["MagneticFieldStrength", "RepetitionTime", "PixelSpacing", "SliceThickness"],
        "Value": ["N/A", 8.0, ['0.5', '0.5'], 1.0],
        "Expected": ["Field required", "Input should be greater than or equal to 2300", "Value error, Each value in PixelSpacing must be between 0.75 and 0.85", "Input should be less than or equal to 0.85"]
    }), headers="keys", tablefmt="simple")

    assert result.returncode == 0
    assert expected_output in result.stdout  # Validate that output includes compliance info

@pytest.mark.parametrize("ref_type,acquisition", [("json", "T1"), ("pydantic", "T1_MPR"), ("dicom", DICOM_FILE)])
def test_cli_output_file_creation(ref_type, acquisition):
    ref_path = JSON_REF if ref_type == "json" else PYDANTIC_REF if ref_type == "pydantic" else DICOM_FILE
    subprocess.run(
        [CLI_SCRIPT, "--ref", ref_path, "--type", ref_type, "--acquisition", acquisition, "--in", DICOM_FILE, "--out", OUTPUT_JSON],
        check=True
    )
    assert os.path.isfile(OUTPUT_JSON)
    with open(OUTPUT_JSON) as f:
        results = json.load(f)
    assert isinstance(results, list)  # Assuming compliance results are in list form
    os.remove(OUTPUT_JSON)

if __name__ == "__main__":
    pytest.main([__file__])

