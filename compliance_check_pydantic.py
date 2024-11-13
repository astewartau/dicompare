import pydicom
import argparse
import pandas as pd
import json
from importlib import import_module
from tabulate import tabulate
from pydantic import ValidationError, create_model
from typing import Literal
from generate_config import generate_config, get_dicom_values

def create_reference_model(reference_values):
    """Create a dynamic Pydantic model with exact constraints based on reference values using Literal."""
    model_fields = {}
    for field_name, value in reference_values.items():
        # Define each field to match the exact value from the reference using Literal
        model_fields[field_name] = (Literal[value], ...)  # Enforces exact matching
    # Dynamically create and return a Pydantic model
    ReferenceModel = create_model("ReferenceModel", **model_fields)
    return ReferenceModel


def check_compliance(reference_model, dicom_values):
    results = []

    try:
        # Instantiate the reference model with input DICOM values to trigger Pydantic validation
        model_instance = reference_model(**dicom_values)

        # If instantiation succeeds, gather results with each field passing the compliance check
        for field_name, expected_value in model_instance.dict().items():
            actual_value = dicom_values.get(field_name, "Missing")
            results.append({
                "Parameter": field_name,
                "Expected": expected_value,
                "Actual": actual_value,
                "Pass": actual_value == expected_value
            })

    except ValidationError as e:
        # Collect validation errors for fields that did not pass
        for error in e.errors():
            param = error['loc'][0]
            expected = error['ctx']['expected'] if 'expected' in error['ctx'] else error['msg']
            actual = dicom_values.get(param, "Missing")
            results.append({
                "Parameter": param,
                "Expected": expected,
                "Actual": actual,
                "Pass": False
            })

    return results, None


def main():
    parser = argparse.ArgumentParser(description="Check DICOM compliance against a reference model.")
    parser.add_argument("--ref", required=True, help="Reference DICOM file to use for compliance.")
    parser.add_argument("--type", required=True, choices=["dicom", "pydantic"], help="Reference type: 'dicom' or 'pydantic'.")
    parser.add_argument("--scan", required=False, help="Scan type when using a pydantic reference.")
    parser.add_argument("--in", dest="in_file", required=True, help="Path to the DICOM file to check.")
    parser.add_argument("--fields", nargs="*", help="Optional: List of DICOM fields to include in validation for DICOM reference.")
    parser.add_argument("--out", required=False, help="Path to save the compliance report in JSON format.")

    args = parser.parse_args()

    if args.type == "dicom":
        # Use a specific DICOM file as reference and extract reference values
        reference_model_class = generate_config(args.ref, check_fields=args.fields)
        reference_instance = reference_model_class()  # Instantiate the model to access field values
        reference_values = reference_instance.model_dump()  # Extract reference values as a dictionary

        # Create a Pydantic model that will validate input DICOM values against reference values
        reference_model = create_reference_model(reference_values)
    elif args.type == "pydantic":
        # Use a Pydantic module reference
        try:
            reference_module = import_module(args.ref)
            scan_models = getattr(reference_module, "SCAN_MODELS", None)
            if not scan_models:
                print(f"Error: No SCAN_MODELS found in the reference module '{reference_module.__name__}'.")
                return
            reference_model = scan_models.get(args.scan)
            if not reference_model:
                print(f"Error: Scan type '{args.scan}' is not defined in the reference module.")
                return
        except ModuleNotFoundError:
            print(f"Error: Reference module '{args.ref}' not found.")
            return

    # Extract values from the input DICOM file
    input_ds = pydicom.dcmread(args.in_file)
    dicom_values = get_dicom_values(input_ds)

    # Perform compliance check using dynamically created Pydantic validation model
    results, distance = check_compliance(reference_model, dicom_values)

    # Convert results for display with emojis
    display_results = [
        {
            **result,
            "Expected": str(result["Expected"]).replace("'", ""),
            "Actual": str(result["Actual"]).replace("'", ""),
            "Pass": "✅" if result["Pass"] else "❌"
        }
        for result in results
    ]

    # Display results in a formatted table
    if display_results:
        df = pd.DataFrame(display_results)
        print("\nCompliance Check Summary:")
        print(tabulate(df, headers="keys", tablefmt="simple"))

    # Save results as JSON if output path is specified
    if args.out:
        with open(args.out, 'w') as outfile:
            json.dump({"compliance_results": results, "distance": distance}, outfile, indent=4)
        print(f"\nCompliance report saved to {args.out}")

    # Print distance metric if calculated
    if distance is not None:
        print(f"\nDistance (RMSE): {distance:.4f}")
    else:
        print("\nDistance calculation not available.")

if __name__ == "__main__":
    main()
