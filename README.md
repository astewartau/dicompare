# dcm-check

`dcm-check` is a command-line tool and Python library for validating DICOM files against specified reference models. This tool supports JSON, DICOM, and Pydantic-based reference models to facilitate compliance checks for DICOM attributes.
Features

- Validate DICOM files against JSON, DICOM, or Pydantic reference models.
- Generate detailed compliance reports, including expected and actual values for each parameter.
- Output results in JSON format for further analysis or logging.

## Installation

To install `dcm-check`, clone the repository and run:

```bash
pip install .
```

`dcm-check` requires Python >=3.10.

## Usage

The tool can be used as a command-line interface (CLI) or as an API within Python scripts.

### Command-Line Usage

The CLI provides options to specify a reference model and validate a DICOM file.
Command Syntax

```bash
dcm-check --ref <reference-file> --type <json|dicom|pydantic> --acquisition <acquisition-type> --in <dicom-file> [--fields <field1 field2 ...>] [--out <output-file>]
```

**Arguments:**

- `--ref`: Path to the reference file (JSON, DICOM, or Python module).
- `--type`: Type of reference model (json, dicom, or pydantic).
- `--acquisition`: Acquisition type (e.g., T1, T2w, etc.) when using JSON or Pydantic references; inferred if not given.
- `--in`: Path to the DICOM file to validate.
- `--fields`: (Optional) List of specific DICOM fields to include in validation for DICOM reference types.
- `--out`: (Optional) Path to save the compliance report as a JSON file.

**Example Commands:**

Validate a DICOM file using a JSON reference model:

```bash
dcm-check --ref reference.json --acquisition T1 --in dicom_file.dcm
```

Validate a DICOM file using another DICOM as a reference:

```bash
dcm-check --ref reference.dcm --in dicom_file.dcm --fields EchoTime RepetitionTime
```

Validate a DICOM file using a Pydantic model in a Python module:

```bash
dcm-check --ref reference.py --acquisition T1_MPR --in dicom_file.dcm
```

**Output**

The compliance report is printed to the terminal in tabular format. You can also save it to a JSON file using the --out argument.

```
    Parameter          Expected                                       Actual       Pass
--  -----------------  ---------------------------------------------  -----------  ------
 0  EchoTime           Input should be greater than or equal to 5.74  3.0          False
 1  RepetitionTime     29.0                                           8.0          False
 2  SeriesDescription  String should match pattern '.*t1.*'           T1-weighted  False
```

Example JSON report:

```json
[
    {
        "Parameter": "EchoTime",
        "Expected": "Input should be greater than or equal to 5.74",
        "Actual": 2.96,
        "Pass": false
    },
    {
        "Parameter": "RepetitionTime",
        "Expected": "29.0",
        "Actual": 2300.0,
        "Pass": false
    }
]
```

## Python API Usage

To use `dcm-check` programmatically, import the appropriate functions from `dcm_check`:

```python
from dcm_check.dcm_check import load_ref_json, load_ref_dicom, load_ref_pydantic, get_compliance_summary, is_compliant

# Example for loading a JSON reference model and checking compliance
reference_model = load_ref_json("reference.json", "T1")
dicom_values = load_dicom("dicom_file.dcm")
compliance_summary = get_compliance_summary(reference_model, dicom_values)

# Print compliance summary
print(compliance_summary)
```

