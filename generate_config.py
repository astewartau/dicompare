import warnings
from pydantic import BaseModel, create_model
from typing import List, Optional
import pydicom
from pydicom.multival import MultiValue
from pydicom.uid import UID
from pydicom.valuerep import PersonName, DSfloat, IS

def get_dicom_values(ds):
    """Convert the DICOM dataset to a nested dictionary, handling sequences and known DICOM-specific types."""
    dicom_dict = {}

    def process_element(element):
        # Handle sequence elements recursively
        if element.VR == 'SQ':
            return [get_dicom_values(item) for item in element]
        # Convert MultiValue to list for compatibility
        elif isinstance(element.value, MultiValue):
            return list(element.value)
        # Convert UID to string for compatibility
        elif isinstance(element.value, UID):
            return str(element.value)
        # Convert PersonName to string for compatibility
        elif isinstance(element.value, PersonName):
            return str(element.value)
        # Convert DSfloat to float for compatibility
        elif isinstance(element.value, DSfloat):
            return float(element.value)
        # Convert IS to int for compatibility
        elif isinstance(element.value, IS):
            return int(element.value)
        elif isinstance(element.value, (int, float)):
            return element.value
        else:
            return str(element.value[:50])

    for element in ds:
        dicom_dict[element.keyword] = process_element(element)
        
    return dicom_dict

def generate_config(dicom_file, check_fields=None):
    """
    Generate a Pydantic model class from a DICOM file.
    
    Parameters:
        dicom_file (str): Path to the DICOM file.
        check_fields (List[str], optional): List of DICOM fields to include in the model. 
                                            If None, all fields in the DICOM are included.
    
    Returns:
        A dynamically created Pydantic model class for the specified DICOM file.
    """
    # Load the DICOM file
    ds = pydicom.dcmread(dicom_file)
    dicom_dict = get_dicom_values(ds)

    # Filter fields if check_fields is specified
    if check_fields:
        for field in check_fields:
            if field not in dicom_dict:
                warnings.warn(f"Field '{field}' does not exist in the reference DICOM data.")
        dicom_dict = {field: dicom_dict[field] for field in check_fields if field in dicom_dict}
    
    # Create model fields with types
    model_fields = {}
    for key, value in dicom_dict.items():
        # Set field type based on value type
        field_type = type(value) if value is not None else Optional[str]
        model_fields[key] = (field_type, value)
    
    # Dynamically create a Pydantic model class
    model_name = dicom_file.split('/')[-1].split('.')[0] + "Config"
    ConfigModel = create_model(model_name, **model_fields)
    
    return ConfigModel
