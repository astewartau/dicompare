import pandas as pd

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

