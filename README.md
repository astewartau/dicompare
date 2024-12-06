# ezVal

[![](img/button.png)](https://astewartau.github.io/dcm-check/)

ezVal is a browser-based DICOM validation tool designed to ensure compliance with study-specific imaging protocols and domain-specific guidelines while preserving data privacy. It supports flexible validation directly in the browser, leveraging WebAssembly (WASM), Pyodide, and the underlying pip package [`dcm-check`](#dcm-check). ezVal is suitable for multi-site studies and clinical environments without requiring software installation or external data uploads.

The tool support DICOM session validation against:

- **Session schemas**: JSON schema files that can be generated based on a reference session;
- **[UNDER CONSTRUCTION] landmark studies**: Schema files based on landmark studies such as the [HCP](https://doi.org/10.1038/s41586-018-0579-z), [ABCD](https://doi.org/10.1016/j.dcn.2018.03.001), and [UK BioBank](https://doi.org/10.1038/s41586-018-0579-z) projects;
- **[UNDER CONSTRUCTION] domain guidelines**: Flexible guidelines for domains such as [QSM](https://doi.org/10.1002/mrm.30006).

# `dcm-check`

While you can run [ezVal](https://astewartau.github.io/dcm-check/) in your browser without any installation, you may also use the underlying `dcm-check` pip package if you wish to use the command-line interface (CLI) or application programming interface (API).

```bash
pip install dcm-check
```

## Usage
### Command-Line Interface

The package provides two main entry points:

- `dcm-gen-session`: Generate JSON schemas for DICOM validation.
- `dcm-check-session`: Validate DICOM sessions against predefined schemas.

1. Generate a JSON Reference Schema

```bash
dcm-gen-session \
    --in_session_dir /path/to/dicom/session \
    --out_json_ref schema.json \
    --acquisition_fields ProtocolName SeriesDescription \
    --reference_fields EchoTime RepetitionTime
```

This will create a JSON schema describing the session based on the specified fields.

2. Validate a DICOM Session

```bash
dcm-check-session \
    --in_session /path/to/dicom/session \
    --json_ref schema.json \
    --out_json compliance_report.json
```

The tool will output a compliance summary, indicating deviations from the reference schema.

### Python API

The `dcm-check` package provides a Python API for programmatic schema generation and validation.

**Generate a schema:**

```python
from dcm_check.io import read_dicom_session

reference_fields = ["EchoTime", "RepetitionTime"]
acquisition_fields = ["ProtocolName", "SeriesDescription"]

session_data = read_dicom_session(
    session_dir="/path/to/dicom/session",
    acquisition_fields=acquisition_fields,
    reference_fields=reference_fields
)

# Save the schema as JSON
import json
with open("schema.json", "w") as f:
    json.dump(session_data, f, indent=4)
```

**Validate a session:**

```python
from dcm_check.io import read_json_session, read_dicom_session
from dcm_check.compliance import check_session_compliance

# Load the schema
acquisition_fields, reference_fields, ref_session = read_json_session(json_ref="schema.json")

# Read the input session
in_session = read_dicom_session(
    session_dir="/path/to/dicom/session",
    acquisition_fields=acquisition_fields,
    reference_fields=reference_fields
)

# Perform compliance check
compliance_summary = check_session_compliance(
    in_session=in_session,
    ref_session=ref_session,
    series_map=None  # Optional: map series if needed
)

# Print compliance summary
for entry in compliance_summary:
    print(entry)
```

