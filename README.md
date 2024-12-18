# dicompare

[![](img/button.png)](https://astewartau.github.io/dicompare/)

dicompare is a DICOM validation tool designed to ensure compliance with study-specific imaging protocols and domain-specific guidelines while preserving data privacy. It provides multiple interfaces, including support for validation directly in the browser, leveraging WebAssembly (WASM), Pyodide, and the underlying pip package [`dicompare`](#dicompare). dicompare is suitable for multi-site studies and clinical environments without requiring software installation or external data uploads.

dicompare supports DICOM session validation against templates based on:

- **Reference sessions**: JSON schema files can be generated based on a reference MRI scanning session;
- **[TESTING] domain guidelines**: Flexible guidelines for specific domains (currently [QSM](https://doi.org/10.1002/mrm.30006));
- **[FUTURE] landmark studies**: Schema files based on landmark studies such as the [HCP](https://doi.org/10.1038/s41586-018-0579-z), [ABCD](https://doi.org/10.1016/j.dcn.2018.03.001), and [UK BioBank](https://doi.org/10.1038/s41586-018-0579-z) projects.

# Command-line interface (CLI) and application programming interface (API)

While you can run [dicompare](https://astewartau.github.io/dicompare/) in your browser now without any installation, you may also use the underlying `dicompare` pip package if you wish to use the command-line interface (CLI) or application programming interface (API).

```bash
pip install dicompare
```

## Command-line interface (CLI)

The package provides the following CLI entry points:

- `dcm-gen-session`: Generate JSON schemas for DICOM validation.
- `dcm-check-session`: Validate DICOM sessions against predefined schemas.

1. Generate a session template

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
dicompare-session \
    --in_session /path/to/dicom/session \
    --json_ref schema.json \
    --out_json compliance_report.json
```

The tool will output a compliance summary, indicating deviations from the session template.

## Python API

The `dicompare` package provides a Python API for programmatic schema generation and validation.

**Generate a schema:**

```python
from dicompare.io import read_dicom_session

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
from dicompare.io import read_json_session, read_dicom_session
from dicompare.compliance import check_session_compliance

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

