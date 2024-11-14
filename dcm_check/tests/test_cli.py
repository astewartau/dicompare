import subprocess
import json
import os
import pytest
import pydicom

# Directory setup (update paths as necessary)
CLI_SCRIPT = "dcm-check"  # Adjust path if needed
DICOM_FILE = "dcm_check/tests/ref_dicom.dcm"  # Replace with actual test DICOM file path
JSON_REF = "dcm_check/tests/ref_json.json"  # Replace with actual JSON reference file path
PYDANTIC_REF = "dcm_check/tests/ref_pydantic.py"  # Python module for pydantic references
OUTPUT_JSON = "compliance_output.json"  # Output file for tests

# Test with JSON Reference
def test_cli_json_reference():
    command = [CLI_SCRIPT, "--ref", JSON_REF, "--type", "json", "--scan", "T1", "--in", DICOM_FILE]

    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    
    # Define the expected output as a single string
    expected_output = (
        "    Parameter          Expected                              Actual       Pass\n"
        "--  -----------------  ------------------------------------  -----------  ------\n"
        " 0  SeriesDescription  String should match pattern '.*t1.*'  T1-weighted  False\n"
    )
    
    # Assert that the command executed successfully
    assert result.returncode == 0
    
    # Assert that the output contains the exact expected string
    assert expected_output in result.stdout


# Test with JSON Reference
def test_cli_json_reference_inferred_type():
    command = [CLI_SCRIPT, "--ref", JSON_REF, "--scan", "T1", "--in", DICOM_FILE]

    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    
    # Define the expected output as a single string
    expected_output = (
        "    Parameter          Expected                              Actual       Pass\n"
        "--  -----------------  ------------------------------------  -----------  ------\n"
        " 0  SeriesDescription  String should match pattern '.*t1.*'  T1-weighted  False\n"
    )

    # Assert that the command executed successfully
    assert result.returncode == 0
    
    # Assert that the output contains the exact expected string
    assert expected_output in result.stdout

# Test with DICOM Reference
def test_cli_dicom_reference():
    result = subprocess.run(
        [CLI_SCRIPT, "--ref", DICOM_FILE, "--type", "dicom", "--in", DICOM_FILE, "--fields", "SAR", "FlipAngle"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "DICOM file is compliant with the reference model." in result.stdout

# Test with DICOM Reference
def test_cli_dicom_reference_inferred_type():
    result = subprocess.run(
        [CLI_SCRIPT, "--ref", DICOM_FILE, "--in", DICOM_FILE, "--fields", "SAR", "FlipAngle"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "DICOM file is compliant with the reference model." in result.stdout

# Test with DICOM Reference
def test_cli_dicom_reference_non_compliant():
    # Modify the DICOM file to make it non-compliant
    dicom = pydicom.dcmread(DICOM_FILE)
    dicom.FlipAngle = 45
    non_compliant_dicom = "dcm_check/tests/non_compliant_dicom.dcm"
    dicom.save_as(non_compliant_dicom)

    result = subprocess.run(
        [CLI_SCRIPT, "--ref", DICOM_FILE, "--type", "dicom", "--in", non_compliant_dicom, "--fields", "SAR", "FlipAngle"],
        capture_output=True,
        text=True
    )

    expected_output = (
        "    Parameter      Expected    Actual  Pass\n"
        "--  -----------  ----------  --------  ------\n"
        " 0  FlipAngle            15        45  False\n"
    )

    # delete the non-compliant DICOM file
    os.remove(non_compliant_dicom)

    assert result.returncode == 0
    assert expected_output in result.stdout

# Test with Pydantic Reference
def test_cli_pydantic_reference():
    result = subprocess.run(
        [CLI_SCRIPT, "--ref", PYDANTIC_REF, "--type", "pydantic", "--scan", "T1_MPR", "--in", DICOM_FILE],
        capture_output=True,
        text=True
    )
    expected_output = (
        "    Parameter              Expected                                                               Actual          Pass\n"
        "--  ---------------------  ---------------------------------------------------------------------  --------------  ------\n"
        " 0  MagneticFieldStrength  Field required                                                         N/A             False\n"
        " 1  RepetitionTime         Input should be greater than or equal to 2300                          8.0             False\n"
        " 2  PixelSpacing           Value error, Each value in PixelSpacing must be between 0.75 and 0.85  ['0.5', '0.5']  False\n"
        " 3  SliceThickness         Input should be less than or equal to 0.85                             1.0             False\n"
    )
    assert result.returncode == 0
    assert expected_output in result.stdout  # Validate that output includes compliance info


# Test with Pydantic Reference
def test_cli_pydantic_reference_inferred_type():
    result = subprocess.run(
        [CLI_SCRIPT, "--ref", PYDANTIC_REF, "--scan", "T1_MPR", "--in", DICOM_FILE],
        capture_output=True,
        text=True
    )
    expected_output = (
        "    Parameter              Expected                                                               Actual          Pass\n"
        "--  ---------------------  ---------------------------------------------------------------------  --------------  ------\n"
        " 0  MagneticFieldStrength  Field required                                                         N/A             False\n"
        " 1  RepetitionTime         Input should be greater than or equal to 2300                          8.0             False\n"
        " 2  PixelSpacing           Value error, Each value in PixelSpacing must be between 0.75 and 0.85  ['0.5', '0.5']  False\n"
        " 3  SliceThickness         Input should be less than or equal to 0.85                             1.0             False\n"
    )
    assert result.returncode == 0
    assert expected_output in result.stdout  # Validate that output includes compliance info

# Test JSON Output File Creation
@pytest.mark.parametrize("ref_type,scan", [("json", "T1"), ("pydantic", "T1_MPR"), ("dicom", DICOM_FILE)])
def test_cli_output_file_creation(ref_type, scan):
    ref_path = JSON_REF if ref_type == "json" else PYDANTIC_REF if ref_type == "pydantic" else DICOM_FILE
    subprocess.run(
        [CLI_SCRIPT, "--ref", ref_path, "--type", ref_type, "--scan", scan, "--in", DICOM_FILE, "--out", OUTPUT_JSON],
        check=True
    )
    assert os.path.isfile(OUTPUT_JSON)
    with open(OUTPUT_JSON) as f:
        results = json.load(f)
    assert isinstance(results, list)  # Assuming compliance results are in list form
    os.remove(OUTPUT_JSON)

if __name__ == "__main__":
    pytest.main([__file__])

