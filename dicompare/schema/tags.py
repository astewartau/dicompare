# dicompare/tags.py

from typing import Dict, Any
from pydicom.datadict import tag_for_keyword, dictionary_description, dictionary_VR, dictionary_VM
from pydicom.multival import MultiValue

# Mapping of custom field names to standard DICOM keywords
FIELD_TO_KEYWORD_MAP = {
    "CoilType": None,  # This is derived from (0051,100F), not a standard tag
    # Add other mappings as needed
}

# Private tag definitions - these won't be in pydicom's dictionary
PRIVATE_TAGS = {
    "(0051,100F)": {
        "name": "CoilStringIdentifier",  # Siemens private
        "type": "string"
    },
    "(0043,102F)": {
        "name": "GEImageType",  # GE private
        "type": "number"
    },
    "(0021,111C)": {
        "name": "PhaseEncodingDirectionPositiveSiemens",  # Siemens XA private (enhanced DICOM)
        "type": "number"  # 0 = negative/reversed, 1 = positive/normal
    }
}

# Comprehensive VR to data type mapping
VR_TO_DATA_TYPE = {
    # String types
    'AE': 'string',  # Application Entity
    'AS': 'string',  # Age String
    'CS': 'string',  # Code String (can be multi-valued)
    'DA': 'string',  # Date
    'DT': 'string',  # Date Time
    'LO': 'string',  # Long String
    'LT': 'string',  # Long Text
    'PN': 'string',  # Person Name
    'SH': 'string',  # Short String
    'ST': 'string',  # Short Text
    'TM': 'string',  # Time
    'UC': 'string',  # Unlimited Characters
    'UI': 'string',  # Unique Identifier
    'UR': 'string',  # Universal Resource Identifier
    'UT': 'string',  # Unlimited Text
    
    # Number types
    'DS': 'number',  # Decimal String
    'FD': 'number',  # Floating Point Double
    'FL': 'number',  # Floating Point Single
    'IS': 'number',  # Integer String
    'SL': 'number',  # Signed Long
    'SS': 'number',  # Signed Short
    'UL': 'number',  # Unsigned Long
    'US': 'number',  # Unsigned Short
    'SV': 'number',  # Signed 64-bit Very Long
    'UV': 'number',  # Unsigned 64-bit Very Long
    
    # Binary types (treat as string for display)
    'OB': 'string',  # Other Byte
    'OD': 'string',  # Other Double
    'OF': 'string',  # Other Float
    'OL': 'string',  # Other Long
    'OV': 'string',  # Other 64-bit Very Long
    'OW': 'string',  # Other Word
    
    # Special types
    'AT': 'string',  # Attribute Tag
    'SQ': 'sequence',  # Sequence
    'UN': 'string',  # Unknown
}

def get_tag_info(field_or_tag: str) -> Dict[str, Any]:
    """
    Get tag information for a field name or tag.

    Args:
        field_or_tag: Either a field name (e.g., "PatientName") or tag (e.g., "(0010,0010)")

    Returns:
        Dictionary with 'tag', 'name', 'type', and 'fieldType' keys:
        - tag: DICOM tag (e.g., "(0018,1030)") or None for derived fields
        - name: Field name
        - type: Data type (string, number, list_string, list_number, etc.)
        - fieldType: Either "standard" (has DICOM tag) or "derived" (calculated/metadata)
    """
    # Check if it's already a tag format
    if field_or_tag.startswith("(") and "," in field_or_tag:
        # It's already a tag
        tag_str = field_or_tag
        
        # Check private tags first
        if tag_str in PRIVATE_TAGS:
            return {
                "tag": tag_str,
                "name": PRIVATE_TAGS[tag_str]["name"],
                "type": PRIVATE_TAGS[tag_str]["type"],
                "fieldType": "standard"
            }
        
        # Try to get name from pydicom
        try:
            # Convert string tag to tuple format for pydicom
            tag_parts = tag_str.strip("()").split(",")
            tag_tuple = (int(tag_parts[0], 16), int(tag_parts[1], 16))
            description = dictionary_description(tag_tuple)
            
            # Determine type based on VR
            tag_type = _infer_type_from_tag(tag_tuple)

            return {
                "tag": tag_str,
                "name": description or tag_str,  # Use tag as name if no description
                "type": tag_type,
                "fieldType": "standard"
            }
        except:
            # Unknown tag - use the tag itself as the name
            return {
                "tag": tag_str,
                "name": tag_str,
                "type": "string",  # Default to string for unknown
                "fieldType": "standard"
            }
    
    else:
        # It's a field name - need to look up the tag
        # Check custom mappings first
        if field_or_tag in FIELD_TO_KEYWORD_MAP:
            keyword = FIELD_TO_KEYWORD_MAP[field_or_tag]
            if keyword is None:
                # Special derived field without a direct tag
                return {
                    "tag": None,
                    "name": field_or_tag,
                    "type": "string",
                    "fieldType": "derived"
                }
        else:
            keyword = field_or_tag
            
        try:
            # Get tag from pydicom
            tag = tag_for_keyword(keyword)
            if tag is not None:
                # tag_for_keyword returns an integer, convert to tuple
                tag_tuple = (tag >> 16, tag & 0xFFFF)
                tag_str = f"({tag_tuple[0]:04X},{tag_tuple[1]:04X})"
                
                # Get type
                tag_type = _infer_type_from_tag(tag_tuple)

                return {
                    "tag": tag_str,
                    "name": field_or_tag,
                    "type": tag_type,
                    "fieldType": "standard"
                }
        except:
            pass
            
        # Try without underscores
        try:
            tag = tag_for_keyword(field_or_tag.replace('_', ''))
            if tag is not None:
                # tag_for_keyword returns an integer, convert to tuple
                tag_tuple = (tag >> 16, tag & 0xFFFF)
                tag_str = f"({tag_tuple[0]:04X},{tag_tuple[1]:04X})"
                tag_type = _infer_type_from_tag(tag_tuple)

                return {
                    "tag": tag_str,
                    "name": field_or_tag,
                    "type": tag_type,
                    "fieldType": "standard"
                }
        except:
            pass

        # Try without spaces (e.g., "Flip Angle" -> "FlipAngle")
        try:
            tag = tag_for_keyword(field_or_tag.replace(' ', ''))
            if tag is not None:
                # tag_for_keyword returns an integer, convert to tuple
                tag_tuple = (tag >> 16, tag & 0xFFFF)
                tag_str = f"({tag_tuple[0]:04X},{tag_tuple[1]:04X})"
                tag_type = _infer_type_from_tag(tag_tuple)

                return {
                    "tag": tag_str,
                    "name": field_or_tag,
                    "type": tag_type,
                    "fieldType": "standard"
                }
        except:
            pass
            
        # Unknown field - no tag
        return {
            "tag": None,
            "name": field_or_tag,
            "type": "string",
            "fieldType": "derived"
        }

def _infer_type_from_tag(tag_tuple: tuple) -> str:
    """Infer the type (string/number/list_string/list_number) from a DICOM tag."""
    try:
        vr = dictionary_VR(tag_tuple)
        vm = dictionary_VM(tag_tuple)
        
        # Get base type from VR
        base_type = VR_TO_DATA_TYPE.get(vr, 'string')
        
        # Special case for sequences
        if base_type == 'sequence':
            return 'sequence'
        
        # Check multiplicity
        # VM can be '1', '1-n', '2', '2-n', '3', '3-n', etc.
        if vm and vm not in ['1', '1-1']:
            # This field can have multiple values
            return f"list_{base_type}"
        else:
            return base_type
            
    except:
        return "string"  # Default

def get_all_tags_in_dataset(metadata: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Get all tags present in a dataset with their info.
    
    Returns a dictionary mapping field names to tag info.
    """
    result = {}
    
    for key in metadata.keys():
        # Skip non-tag keys (those that don't start with parenthesis)
        if key.startswith("("):
            info = get_tag_info(key)
            # Use the tag's name as the key if we found one
            result[info["name"]] = info
        else:
            # Regular field name
            info = get_tag_info(key)
            result[key] = info
            
    return result


def determine_field_type_from_values(field_name: str, values: Any) -> str:
    """
    Determine field type based on VR and actual values in the data.
    
    This function checks if values contain multi-valued data and adjusts
    the type accordingly (e.g., 'string' -> 'list_string').
    
    Args:
        field_name: DICOM field name
        values: pandas Series or list of values
        
    Returns:
        Data type string (e.g., 'string', 'number', 'list_string', 'list_number')
    """
    import pandas as pd
    
    # Get VR-based type
    tag_info = get_tag_info(field_name)
    vr_type = tag_info.get("type", "string")
    
    # If already a list type or sequence, return as-is
    if vr_type.startswith("list_") or vr_type == "sequence":
        return vr_type
    
    # Check if we have pandas Series
    if hasattr(values, 'dropna'):
        values_to_check = values.dropna()
    else:
        values_to_check = [v for v in values if v is not None]
    
    # Check if any values are lists/multi-valued
    has_multiple = False
    for v in values_to_check:
        if isinstance(v, (list, tuple, MultiValue)):
            has_multiple = True
            break
        # Also check for backslash-separated values (common in DICOM)
        if isinstance(v, str) and '\\' in v:
            has_multiple = True
            break
    
    if has_multiple and vr_type in ["string", "number"]:
        return f"list_{vr_type}"
    
    return vr_type