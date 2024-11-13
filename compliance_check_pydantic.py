import pydicom
import argparse
import pandas as pd
from importlib import import_module
from tabulate import tabulate
from pydantic import ValidationError

def get_dicom_values(ds):
    """Convert the DICOM dataset to a dictionary for Pydantic validation."""
    dicom_dict = {}
    for element in ds:
        if element.VR != 'SQ':  # Exclude sequences for simplicity
            dicom_dict[element.keyword] = element.value
        else:
            dicom_dict[element.keyword] = "Sequence"  # Placeholder for sequences
    return dicom_dict

def check_compliance(scan_type, dicom_file, reference_module):
    scan_models = getattr(reference_module, "SCAN_MODELS", None)
    if not scan_models:
        print(f"Error: No SCAN_MODELS found in the reference module '{reference_module.__name__}'.")
        return None

    model_class = scan_models.get(scan_type)
    if not model_class:
        print(f"Error: Scan type '{scan_type}' is not defined in the reference module.")
        return None

    ds = pydicom.dcmread(dicom_file)
    dicom_values = get_dicom_values(ds)

    results = []
    reference_values = {}
    numeric_actual_values = {}

    try:
        # Pass the DICOM values directly into the model instance to trigger validation
        model_instance = model_class(**dicom_values)

        # Collect expected and actual values for reporting
        for field_name, result in model_instance.dict().items():
            val = dicom_values.get(field_name)

            # Collect numeric reference and actual values for optional distance calculation
            if isinstance(result, (int, float, list)) and isinstance(val, (int, float, list)):
                reference_values[field_name] = result
                numeric_actual_values[field_name] = val

            # Append results for each field
            if val == result:
                results.append({
                    "Parameter": field_name,
                    "Outcome": result,
                    "Value": val,
                    "Pass": "✅"
                })
            else:
                results.append({
                    "Parameter": field_name,
                    "Outcome": result,
                    "Value": val if val is not None else "Missing",
                    "Pass": "❌"
                })

    except ValidationError as e:
        # Process validation errors from Pydantic
        for error in e.errors():
            param = error['loc'][0]
            results.append({
                "Parameter": param,
                "Outcome": error['msg'],
                "Value": dicom_values.get(param, "Missing"),
                "Pass": "❌"
            })

    # Optional distance calculation
    distance = None
    if hasattr(reference_module, "calculate_distance"):
        distance = reference_module.calculate_distance(reference_values, numeric_actual_values)

    return results, distance


def main():
    parser = argparse.ArgumentParser(description="Check DICOM compliance against a reference module.")
    parser.add_argument("--ref", required=True, help="Reference module to use (e.g., hcp_reference).")
    parser.add_argument("--scan", required=True, help="Scan type in the reference module.")
    parser.add_argument("--dicom", required=True, help="Path to the DICOM file to check.")
    args = parser.parse_args()

    try:
        reference_module = import_module(args.ref)
    except ModuleNotFoundError:
        print(f"Error: Reference module '{args.ref}' not found.")
        return

    results, distance = check_compliance(args.scan, args.dicom, reference_module)

    # Display results in a formatted table
    if results:
        df = pd.DataFrame(results)
        print("\nCompliance Check Summary:")
        print(tabulate(df, headers="keys", tablefmt="simple"))

    # Print distance metric if calculated
    if distance is not None:
        print(f"\nDistance (RMSE): {distance:.4f}")
    else:
        print("\nDistance calculation not available.")

if __name__ == "__main__":
    main()
