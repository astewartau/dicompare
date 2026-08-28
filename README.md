# dicompare

[![](img/button.png)](https://dicompare.neurodesk.org/)

**dicompare** is an open-source, vendor-independent tool for automated validation and comparison of MRI acquisition protocols using DICOM metadata. It enables researchers to determine whether imaging protocols implemented at different sites are truly equivalent, similar, or meaningfully different — a task that is currently manual, error-prone, and often infeasible in large, multi-site studies.

dicompare is a collaboration between the [Neurodesk](https://www.neurodesk.org/) and [Brainlife](https://brainlife.io/) groups.

This repository contains the core Python package, which provides a command-line interface (CLI) and Python API for building, validating, and matching protocol schemas.

For the visual web and desktop application, see [**dicompare-web**](https://github.com/astewartau/dicompare-web) or use the live app at [dicompare.neurodesk.org](https://dicompare.neurodesk.org/) or [brainlife.io/dicompare](https://brainlife.io/dicompare).

---

## What dicompare Does

dicompare performs structured comparisons of DICOM files to evaluate whether imaging protocols match a target reference or schema. It works directly with DICOM metadata and does not depend on scanner manufacturer formats or proprietary exam card systems.

dicompare supports validation against:

- **Reference sessions** — JSON schema files generated from a reference MRI scanning session
- **Domain guidelines** — Flexible guidelines for specific domains (e.g. [QSM](https://doi.org/10.1002/mrm.30006), [ASL](https://doi.org/10.1002/mrm.29024), [MS/CMSC](https://doi.org/10.3174/ajnr.A7406))
- **Landmark studies** — A bundled schema library with protocols from [HCP](https://doi.org/10.1038/s41586-018-0579-z), [ABCD](https://doi.org/10.1016/j.dcn.2018.03.001), [UK Biobank](https://doi.org/10.1038/s41586-018-0579-z), and more

---

## Installation

```bash
pip install dicompare
```

Alternatively, use the [web app](https://dicompare.neurodesk.org/) or [desktop app](https://github.com/astewartau/dicompare-web/releases) for a visual interface with no installation required.

## Command-line interface (CLI)

The package provides a unified `dicompare` command with four subcommands:

- **`dicompare build`**: Generate a JSON schema from a reference DICOM session
- **`dicompare check`**: Validate DICOM sessions against a JSON schema
- **`dicompare match`**: Find best-matching schemas for input DICOM data from a library
- **`dicompare lint`**: Check a schema for problems before sharing or submitting it

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

### 4. Lint a schema

```bash
dicompare lint schema.json
```

Checks a schema against the dicompare metaschema and best practices:

- field constraints are compared against the **canonical field registry**
  (console display strings like `A >> P`, raw vendor codes, and
  out-of-vocabulary values will never match real DICOM data)
- exact matches on continuous physical parameters (e.g. `EchoTime`) are
  flagged as brittle
- rule structure is verified (valid Python, unique rule/test ids, no reads of
  undeclared fields)
- **every rule test case is executed** through the same validation path used
  in production — including the check that a schema's own example values pass
  its own rules

Errors exit non-zero (suitable as a CI gate — the
[dicompare-web](https://github.com/astewartau/dicompare-web) schema-submission
workflow runs this on every community submission); warnings are informational.
Use `--format json` or `--format markdown` for machine-readable output.

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

**Load vendor protocol files:**

Every supported protocol format has a matching importer family
(`load_<source>_file`, `load_<source>_file_schema_format`, and where
applicable `load_<source>_session`):

```python
from dicompare import (
    load_pro_file,         # Siemens .pro (raw MrPhoenixProtocol)
    load_exar_file,        # Siemens .exar1 exports
    load_printprot_file,   # Siemens "MR print protocol" (XML/TXT console export)
    load_examcard_file,    # Philips ExamCard
    load_lxprotocol_file,  # GE LxProtocol
)

protocols = load_printprot_file("AxonDiameterProtocol.txt")
```

All importers translate vendor-specific values (raw enum codes, console
display strings, unit conventions) to the canonical DICOM vocabulary via the
field registry, so a schema built from any source validates cleanly against
real DICOM data. Diffusion gradient files (`.dvs`, `.bvec`/`.bval`) can be
attached to derive shell descriptors (`DiffusionBValues`,
`DirectionsPerShell`, ...).

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

### The canonical field registry

`dicompare.fields` is the single source of truth for per-field knowledge:
canonical DICOM keywords, tags, value types, units, allowed vocabularies,
suggested tolerances, and vendor encodings (e.g. Siemens `ucCoilCombineMode`
code `2` means `"Adaptive Combine"`). The protocol importers, the schema
lint, and the [dicompare-web](https://github.com/astewartau/dicompare-web)
schema editor all consume it, so field semantics cannot drift between them.

```python
from dicompare import get_field, check_value, validate_fields

get_field("InPlanePhaseEncodingDirection").vocabulary   # ('ROW', 'COL')
check_value("CoilCombinationMethod", 2)                  # -> [".. not in the canonical vocabulary .."]
validate_fields({"InPlanePhaseEncodingDirection": "A >> P"})  # flags display strings
```

Export the registry as JSON (consumed by the web schema editor) with
`python -m dicompare.fields`.

### Lint a schema programmatically

```python
import json
from dicompare import lint_schema, format_findings

schema = json.load(open("schema.json"))
findings = lint_schema(schema)
print(format_findings(findings, "markdown"))
errors = [f for f in findings if f.severity == "error"]
```

### Writing validation rules

Schema rules are Python snippets executed in a sandbox. The preferred
interface is the `ctx` object, which provides typed field access and
collected severities:

```python
# Inside a rule's "implementation":
for row in ctx.rows:
    bvals = row["DiffusionBValues"]        # plain list, no parsing needed
    if len([b for b in bvals if b > 0]) < 2:
        ctx.error("At least two non-zero b-value shells are required")
    elif len(bvals) < 4:
        ctx.warn("Four or more b-values are recommended")
```

`ctx.error(...)` findings fail validation; `ctx.warn(...)` findings surface
as warnings. The legacy interface (a pandas DataFrame named `value`, with
`ValidationError` / `ValidationWarning` raised explicitly) remains fully
supported. Every rule should ship `testCases` — `dicompare lint` executes
them through the production validation path.

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

## Links

- [dicompare Web & Desktop App](https://github.com/astewartau/dicompare-web) — Visual interface for building, viewing, and validating protocol schemas
- [Live App (Neurodesk)](https://dicompare.neurodesk.org/)
- [Live App (Brainlife)](https://brainlife.io/dicompare)
- [Report Issues](https://github.com/astewartau/dicompare-pip/issues)
