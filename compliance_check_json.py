import json
import pydicom
import argparse
import sys
import pandas as pd
from tabulate import tabulate

def load_json_reference(ref_file):
    """Load JSON reference file."""
    with open(ref_file, 'r') as file:
        return json.load(file)

def check_compliance(reference, dicom_file, scan_type):
    """Check DICOM file compliance with the reference JSON for a given scan type."""
    ds = pydicom.dcmread(dicom_file)
    scan_reference = reference.get(scan_type)

    if not scan_reference:
        print(f"Scan type '{scan_type}' not found in reference.")
        sys.exit(1)

    results = []
    for param, details in scan_reference['required_parameters'].items():
        expected_value = details['value']
        tolerance = details.get('tolerance', 0)
        datatype = details['datatype']

        # Retrieve DICOM value
        actual_value = getattr(ds, param, None)
        if actual_value is None:
            results.append({
                "Parameter": param,
                "Expected": expected_value,
                "Actual": "Missing",
                "Tolerance": tolerance,
                "Status": "❌"
            })
            continue

        # Convert and compare values
        if datatype == "list[float]":
            actual_value = [float(x) for x in actual_value]
            within_tolerance = all(abs(a - e) <= tolerance for a, e in zip(actual_value, expected_value))
        elif datatype == "float":
            actual_value = float(actual_value)
            within_tolerance = abs(actual_value - expected_value) <= tolerance
        elif datatype == "int":
            actual_value = int(actual_value)
            within_tolerance = abs(actual_value - expected_value) <= tolerance
        elif datatype == "str":
            actual_value = str(actual_value)
            within_tolerance = (actual_value == expected_value)
        else:
            results.append({
                "Parameter": param,
                "Expected": expected_value,
                "Actual": "Unsupported datatype",
                "Tolerance": tolerance,
                "Status": "❌"
            })
            continue

        # Report result with tick or cross
        status = "✅" if within_tolerance else "❌"
        results.append({
            "Parameter": param,
            "Expected Value": expected_value,
            "Actual Value": actual_value,
            "Tolerance": tolerance,
            "Status": status
        })

    return results

def main():
    parser = argparse.ArgumentParser(description="Check DICOM compliance against a JSON reference.")
    parser.add_argument("--ref", required=True, help="Path to the JSON reference file.")
    parser.add_argument("--scan", required=True, help="Scan type in the reference (e.g., T1_MPR).")
    parser.add_argument("--dicom", required=True, help="Path to the DICOM file to check.")
    args = parser.parse_args()

    # Load reference JSON
    reference = load_json_reference(args.ref)

    # Perform compliance check
    results = check_compliance(reference, args.dicom, args.scan)

    # Convert results to a DataFrame and display with borders
    df = pd.DataFrame(results)
    print("\nCompliance Check Summary:")
    print(tabulate(df, headers="keys", tablefmt="simple"))

if __name__ == "__main__":
    main()
