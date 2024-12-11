import sys
import os

def clean_string(s: str):
    forbidden_chars = "`~!@#$%^&*()_+=[]\{\}|;':,.<>?/\\ "
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

