import pandas as pd
import sys
import os

def json_to_dataframe(json_data: dict):
    """
    Convert a JSON-like dictionary structure into a DataFrame.
    """
    rows = []

    for acq_name, acquisition in json_data.get("acquisitions", {}).items():
        acq_fields = {field["field"]: field.get("value", None) for field in acquisition.get("fields", [])}

        if not acquisition.get("series"):
            rows.append({"Acquisition": acq_name, "Series": None, **acq_fields})
        else:
            for series in acquisition["series"]:
                series_fields = {field["field"]: field.get("value", None) for field in series.get("fields", [])}
                rows.append({"Acquisition": acq_name, "Series": series["name"], **acq_fields, **series_fields})

    return pd.DataFrame(rows)

def clean_string(s: str):
    forbidden_chars = "`~!@#$%^&*()_+-=[]\{\}|;':,.<>?/\\ "
    for char in forbidden_chars:
        s = s.replace(char, "").lower()
    return s

def infer_type_from_extension(ref_path):
    """Infer the reference type based on the file extension."""
    _, ext = os.path.splitext(ref_path.lower())
    if ext == ".json":
        return "json"
    elif ext in [".dcm", ".IMA"]:
        return "dicom"
    elif ext == ".py":
        return "pydantic"
    else:
        print("Error: Could not determine the reference type. Please specify '--type'.", file=sys.stderr)
        sys.exit(1)

