# dicompare

[![](img/button.png)](https://dicompare-web.vercel.app/)

dicompare is a DICOM validation tool designed to ensure compliance with study-specific imaging protocols and domain-specific guidelines while preserving data privacy. It provides multiple interfaces, including support for validation directly in the browser at [dicompare-web.vercel.app](https://dicompare-web.vercel.app/), leveraging WebAssembly (WASM), Pyodide, and the underlying pip package `dicompare`. dicompare is suitable for multi-site studies and clinical environments without requiring software installation or external data uploads.

dicompare supports DICOM session validation against templates based on:

- **Reference sessions**: JSON schema files can be generated based on a reference MRI scanning session;
- **Domain guidelines**: Flexible guidelines for specific domains (e.g. [QSM](https://doi.org/10.1002/mrm.30006), [ASL](https://doi.org/10.1002/mrm.29024), [MS/CMSC](https://doi.org/10.3174/ajnr.A7406));
- **Landmark studies**: A bundled schema library includes protocols from [HCP](https://doi.org/10.1038/s41586-018-0579-z), [ABCD](https://doi.org/10.1016/j.dcn.2018.03.001), [UK Biobank](https://doi.org/10.1038/s41586-018-0579-z), and more.

# Command-line interface (CLI) and application programming interface (API)

While you can run [dicompare](https://dicompare-web.vercel.app/) in your browser now without any installation, you may also use the underlying `dicompare` pip package if you wish to use the command-line interface (CLI) or application programming interface (API).

```bash
pip install dicompare
```

## Command-line interface (CLI)

The package provides a unified `dicompare` command with three subcommands:

- **`dicompare build`**: Generate a JSON schema from a reference DICOM session
- **`dicompare check`**: Validate DICOM sessions against a JSON schema
- **`dicompare match`**: Find best-matching schemas for input DICOM data from a library

### 1. Build a JSON schema from a reference session

```bash
dicompare build /path/to/dicom/session schema.json
```

This creates a JSON schema describing the session based on default reference fields present in the data.

### 2. Check a DICOM session against a schema

```bash
dicompare check /path/to/dicom/session schema.json
```

The tool will output an acquisition mapping summary with confidence scores, followed by a compliance report indicating deviations from the schema. Use `--auto-yes` or `-y` to skip interactive mapping prompts:

```bash
dicompare check /path/to/dicom/session schema.json --auto-yes
```

Save the compliance report to a JSON file by specifying a report path:

```bash
dicompare check /path/to/dicom/session schema.json compliance_report.json
```

### 3. Find best-matching schemas for your data

Search across a schema library to identify which protocols best match your DICOM data:

```bash
# Search the bundled schema library
dicompare match /path/to/dicom/session --library

# Search custom schema files or directories
dicompare match /path/to/dicom/session --schemas /path/to/schemas/

# Combine bundled library and custom schemas
dicompare match /path/to/dicom/session --library --schemas /path/to/custom_schema.json
```

This compares each input acquisition against every acquisition in the loaded schemas, ranking matches by compliance score. Options:

- `--library`: Include the bundled schema library (HCP, ABCD, UK Biobank, and more)
- `--schemas PATH [PATH ...]`: Path(s) to schema files or directories containing schemas
- `--top N`: Number of top matches to show per acquisition (default: 5)
- `--report PATH`: Save the match report to a JSON file

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

### Build a JSON schema

```python
from dicompare import load_dicom_session, build_schema, make_json_serializable
from dicompare.config import DEFAULT_SETTINGS_FIELDS
import json

# Load the reference session
session_df = load_dicom_session(
    session_dir="/path/to/dicom/session",
    show_progress=True
)

# Build the schema
json_schema = build_schema(session_df)

# Save the schema
serializable_schema = make_json_serializable(json_schema)
with open("schema.json", "w") as f:
    json.dump(serializable_schema, f, indent=4)
```

### Validate a session against a JSON schema

```python
from dicompare import (
    load_schema,
    load_dicom_session,
    check_acquisition_compliance,
    map_to_json_reference,
    assign_acquisition_and_run_numbers
)

# Load the JSON schema
reference_fields, json_schema, validation_rules = load_schema(json_schema_path="schema.json")

# Load the input session
in_session = load_dicom_session(
    session_dir="/path/to/dicom/session",
    show_progress=True
)

# Assign acquisition and run numbers
in_session = assign_acquisition_and_run_numbers(in_session)

# Map acquisitions to schema
session_map = map_to_json_reference(in_session, json_schema)

# Check compliance for each acquisition
compliance_summary = []
for ref_acq_name, schema_acq in json_schema["acquisitions"].items():
    if ref_acq_name not in session_map:
        continue

    input_acq_name = session_map[ref_acq_name]
    acq_validation_rules = validation_rules.get(ref_acq_name) if validation_rules else None

    results = check_acquisition_compliance(
        in_session,
        schema_acq,
        acquisition_name=input_acq_name,
        validation_rules=acq_validation_rules
    )
    compliance_summary.extend(results)

# Display results
for entry in compliance_summary:
    print(entry)
```

### Additional utilities

**Assign acquisition and run numbers:**

```python
from dicompare import assign_acquisition_and_run_numbers

session_df = assign_acquisition_and_run_numbers(session_df)
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

