# dicompare

[![](img/button.png)](https://dicompare-web.vercel.app/)

dicompare is a DICOM validation tool designed to ensure compliance with study-specific imaging protocols and domain-specific guidelines while preserving data privacy. It provides multiple interfaces, including support for validation directly in the browser at [dicompare-web.vercel.app](https://dicompare-web.vercel.app/), leveraging WebAssembly (WASM), Pyodide, and the underlying pip package `dicompare`. dicompare is suitable for multi-site studies and clinical environments without requiring software installation or external data uploads.

dicompare supports DICOM session validation against templates based on:

- **Reference sessions**: JSON schema files can be generated based on a reference MRI scanning session;
- **[TESTING] domain guidelines**: Flexible guidelines for specific domains (currently [QSM](https://doi.org/10.1002/mrm.30006));
- **[FUTURE] landmark studies**: Schema files based on landmark studies such as the [HCP](https://doi.org/10.1038/s41586-018-0579-z), [ABCD](https://doi.org/10.1016/j.dcn.2018.03.001), and [UK BioBank](https://doi.org/10.1038/s41586-018-0579-z) projects.

# Command-line interface (CLI) and application programming interface (API)

While you can run [dicompare](https://dicompare-web.vercel.app/) in your browser now without any installation, you may also use the underlying `dicompare` pip package if you wish to use the command-line interface (CLI) or application programming interface (API).

```bash
pip install dicompare
```

## Command-line interface (CLI)

The package provides the following CLI entry points:

- **`dcm-gen-session`**: Generate JSON schemas for DICOM validation from a reference session
- **`dcm-check-session`**: Validate DICOM sessions against JSON or Python schemas

### 1. Generate a JSON schema from a reference session

```bash
dcm-gen-session \
    --in_session_dir /path/to/dicom/session \
    --out_json_schema schema.json \
    --reference_fields EchoTime RepetitionTime FlipAngle
```

This creates a JSON schema describing the session based on the specified reference fields.

### 2. Validate a DICOM session

```bash
dcm-check-session \
    --in_session /path/to/dicom/session \
    --json_schema schema.json \
    --out_json compliance_report.json
```

The tool will output a compliance summary, indicating deviations from the schema.

## Python API

The `dicompare` package provides a comprehensive Python API for programmatic schema generation, validation, and DICOM processing.

### Loading DICOM data

**Load a DICOM session:**

```python
from dicompare import load_dicom_session

session_df = load_dicom_session(
    session_dir="/path/to/dicom/session",
    show_progress=True
)
```

**Load individual DICOM files:**

```python
from dicompare import load_dicom

dicom_data = load_dicom(
    dicom_paths=["/path/to/file1.dcm", "/path/to/file2.dcm"],
    show_progress=True
)
```

**Load Siemens .pro files:**

```python
from dicompare import load_pro_session

pro_session = load_pro_session(
    session_dir="/path/to/pro/files",
    show_progress=True
)
```

### Generate a JSON schema

```python
from dicompare import load_dicom_session, create_json_schema
import json

# Load the reference session
session_df = load_dicom_session(
    session_dir="/path/to/dicom/session",
    show_progress=True
)

# Create a JSON schema
reference_fields = ["EchoTime", "RepetitionTime", "FlipAngle"]
json_schema = create_json_schema(
    session_df=session_df,
    reference_fields=reference_fields
)

# Save the schema
with open("schema.json", "w") as f:
    json.dump(json_schema, f, indent=4)
```

### Validate a session against a JSON schema

```python
from dicompare import (
    load_json_schema,
    load_dicom_session,
    check_session_compliance_with_json_schema,
    map_to_json_reference
)

# Load the JSON schema
reference_fields, json_schema = load_json_schema(json_schema_path="schema.json")

# Load the input session
in_session = load_dicom_session(
    session_dir="/path/to/dicom/session",
    show_progress=True
)

# Map acquisitions to schema
session_map = map_to_json_reference(in_session, json_schema)

# Check compliance
compliance_summary = check_session_compliance_with_json_schema(
    in_session=in_session,
    ref_session=json_schema,
    session_map=session_map
)

# Display results
for entry in compliance_summary:
    print(entry)
```

### Additional utilities

**Assign acquisition and run numbers:**

```python
from dicompare import assign_acquisition_and_run_numbers

session_df = assign_acquisition_and_run_numbers(
    session_df=session_df,
    acquisition_fields=["ProtocolName"],
    reference_fields=["EchoTime", "RepetitionTime"]
)
```

**Get DICOM tag information:**

```python
from dicompare import get_tag_info, get_all_tags_in_dataset

# Get info about a specific tag
tag_info = get_tag_info("EchoTime")
print(tag_info)  # {'tag': '(0018,0081)', 'name': 'Echo Time', 'type': 'float'}

# Get all tags in a dataset
all_tags = get_all_tags_in_dataset(dicom_metadata)
```

