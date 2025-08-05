import pytest
import pandas as pd
from pydicom.multival import MultiValue
from dicompare.tags import get_tag_info, get_all_tags_in_dataset, _infer_type_from_tag, determine_field_type_from_values, VR_TO_DATA_TYPE


class TestTagInfo:
    """Test the get_tag_info function."""
    
    def test_standard_fields(self):
        """Test standard DICOM fields."""
        # Test standard field
        info = get_tag_info("PatientName")
        assert info["tag"] == "(0010,0010)"
        assert info["name"] == "PatientName"
        assert info["type"] == "string"
        
        # Test numeric field
        info = get_tag_info("RepetitionTime")
        assert info["tag"] == "(0018,0080)"
        assert info["type"] == "number"
        
        # Test with underscore
        info = get_tag_info("EchoTime")
        assert info["tag"] == "(0018,0081)"
        assert info["type"] == "number"
    
    def test_private_tags(self):
        """Test private tag handling."""
        # Test known private tag
        info = get_tag_info("(0051,100F)")
        assert info["name"] == "CoilStringIdentifier"
        assert info["type"] == "string"
        assert info["tag"] == "(0051,100F)"
        
        # Test GE private tag
        info = get_tag_info("(0043,102F)")
        assert info["name"] == "GEImageType"
        assert info["type"] == "number"
    
    def test_unknown_tags(self):
        """Test unknown private tag handling."""
        # Test unknown private tag
        info = get_tag_info("(0099,1234)")
        assert info["name"] == "(0099,1234)"  # Falls back to tag as name
        assert info["type"] == "string"
        assert info["tag"] == "(0099,1234)"
    
    def test_special_fields(self):
        """Test special derived fields."""
        # Test CoilType (derived field)
        info = get_tag_info("CoilType")
        assert info["tag"] is None
        assert info["name"] == "CoilType"
        assert info["type"] == "string"
    
    def test_unknown_fields(self):
        """Test handling of unknown field names."""
        info = get_tag_info("UnknownFieldName")
        assert info["tag"] is None
        assert info["name"] == "UnknownFieldName"
        assert info["type"] == "string"
    
    def test_sequence_type(self):
        """Test sequence type detection."""
        # ReferencedImageSequence should be detected as list type
        info = get_tag_info("ReferencedImageSequence")
        assert info["tag"] == "(0008,1140)"
        assert info["type"] == "sequence"


class TestTypeInference:
    """Test the _infer_type_from_tag function."""
    
    def test_numeric_vr_types(self):
        """Test numeric VR types are correctly identified."""
        # DS (Decimal String)
        tag_tuple = (0x0018, 0x0080)  # RepetitionTime
        assert _infer_type_from_tag(tag_tuple) == "number"
        
        # IS (Integer String) 
        tag_tuple = (0x0020, 0x0011)  # SeriesNumber
        assert _infer_type_from_tag(tag_tuple) == "number"
        
        # FL (Floating Point Single)
        tag_tuple = (0x0018, 0x1314)  # FlipAngle
        assert _infer_type_from_tag(tag_tuple) == "number"
    
    def test_text_vr_types(self):
        """Test text VR types are correctly identified."""
        # LO (Long String)
        tag_tuple = (0x0010, 0x0020)  # PatientID
        assert _infer_type_from_tag(tag_tuple) == "string"
        
        # PN (Person Name)
        tag_tuple = (0x0010, 0x0010)  # PatientName
        assert _infer_type_from_tag(tag_tuple) == "string"
        
        # UI (Unique Identifier)
        tag_tuple = (0x0020, 0x000E)  # SeriesInstanceUID
        assert _infer_type_from_tag(tag_tuple) == "string"
    
    def test_sequence_vr_type(self):
        """Test sequence VR type is correctly identified."""
        # SQ (Sequence)
        tag_tuple = (0x0008, 0x1140)  # ReferencedImageSequence
        assert _infer_type_from_tag(tag_tuple) == "sequence"
    
    def test_unknown_tag(self):
        """Test unknown tag defaults to text."""
        # Unknown tag
        tag_tuple = (0x9999, 0x9999)
        assert _infer_type_from_tag(tag_tuple) == "string"


class TestGetAllTags:
    """Test the get_all_tags_in_dataset function."""
    
    def test_mixed_metadata(self):
        """Test with metadata containing both field names and tag keys."""
        metadata = {
            "PatientName": "John Doe",
            "RepetitionTime": 1000,
            "(0051,100F)": "HEA;HEP",  # Private tag
            "(0099,1234)": "Unknown",   # Unknown tag
            "CoilType": "Combined"      # Derived field
        }
        
        result = get_all_tags_in_dataset(metadata)
        
        # Check standard fields
        assert "PatientName" in result
        assert result["PatientName"]["tag"] == "(0010,0010)"
        
        # Check private tag
        assert "CoilStringIdentifier" in result
        assert result["CoilStringIdentifier"]["tag"] == "(0051,100F)"
        
        # Check unknown tag
        assert "(0099,1234)" in result
        assert result["(0099,1234)"]["name"] == "(0099,1234)"
        
        # Check derived field
        assert "CoilType" in result
        assert result["CoilType"]["tag"] is None
    
    def test_empty_metadata(self):
        """Test with empty metadata."""
        metadata = {}
        result = get_all_tags_in_dataset(metadata)
        assert result == {}


class TestVRMapping:
    """Test the comprehensive VR to data type mapping."""
    
    def test_string_vr_types(self):
        """Test all string VR types."""
        string_vrs = ['AE', 'AS', 'CS', 'DA', 'DT', 'LO', 'LT', 'PN', 'SH', 'ST', 'TM', 'UC', 'UI', 'UR', 'UT']
        for vr in string_vrs:
            assert VR_TO_DATA_TYPE[vr] == 'string', f"VR {vr} should map to 'string'"
    
    def test_number_vr_types(self):
        """Test all number VR types."""
        number_vrs = ['DS', 'FD', 'FL', 'IS', 'SL', 'SS', 'UL', 'US', 'SV', 'UV']
        for vr in number_vrs:
            assert VR_TO_DATA_TYPE[vr] == 'number', f"VR {vr} should map to 'number'"
    
    def test_special_vr_types(self):
        """Test special VR types."""
        assert VR_TO_DATA_TYPE['SQ'] == 'sequence'
        assert VR_TO_DATA_TYPE['UN'] == 'string'
        assert VR_TO_DATA_TYPE['AT'] == 'string'


class TestMultiValuedFields:
    """Test handling of multi-valued fields."""
    
    def test_scanning_sequence_cs_field(self):
        """Test ScanningSequence field (CS with VM 1-n)."""
        # ScanningSequence has tag (0018,0020) with VR=CS and VM="1-n"
        tag_tuple = (0x0018, 0x0020)
        # Should detect as list_string due to VM="1-n"
        result = _infer_type_from_tag(tag_tuple)
        assert result == "list_string", "ScanningSequence should be list_string due to VM=1-n"
    
    def test_single_valued_cs_field(self):
        """Test single-valued CS field."""
        # Modality has tag (0008,0060) with VR=CS and VM="1"
        tag_tuple = (0x0008, 0x0060)
        result = _infer_type_from_tag(tag_tuple)
        assert result == "string", "Modality should be string due to VM=1"
    
    def test_multi_valued_numeric_field(self):
        """Test multi-valued numeric field."""
        # PixelSpacing has tag (0028,0030) with VR=DS and VM="2"
        tag_tuple = (0x0028, 0x0030)
        result = _infer_type_from_tag(tag_tuple)
        assert result == "list_number", "PixelSpacing should be list_number due to VM=2"


class TestFieldTypeFromValues:
    """Test determine_field_type_from_values function."""
    
    def test_single_string_values(self):
        """Test with single string values."""
        values = pd.Series(['MR', 'MR', 'MR'])
        result = determine_field_type_from_values('Modality', values)
        assert result == 'string'
    
    def test_multi_valued_string_field(self):
        """Test with multi-valued string data."""
        # Test with backslash-separated values
        values = pd.Series(['SE\IR', 'SE\IR', 'GR'])
        result = determine_field_type_from_values('ScanningSequence', values)
        assert result == 'list_string'
        
        # Test with actual list values
        values = pd.Series([['SE', 'IR'], ['SE', 'IR'], ['GR']])
        result = determine_field_type_from_values('ScanningSequence', values)
        assert result == 'list_string'
    
    def test_multi_valued_numeric_field(self):
        """Test with multi-valued numeric data."""
        # Test with list of numbers
        values = pd.Series([[0.5, 0.5], [0.5, 0.5], [0.6, 0.6]])
        result = determine_field_type_from_values('PixelSpacing', values)
        assert result == 'list_number'
    
    def test_pydicom_multivalue(self):
        """Test with pydicom MultiValue objects."""
        mv = MultiValue(float, ['0.5', '0.5'])
        values = pd.Series([mv, mv, mv])
        result = determine_field_type_from_values('PixelSpacing', values)
        assert result == 'list_number'
    
    def test_mixed_single_and_multi_values(self):
        """Test with some single and some multi values."""
        values = pd.Series(['SE', 'SE\IR', 'GR', None, 'SE\IR\EP'])
        result = determine_field_type_from_values('ScanningSequence', values)
        assert result == 'list_string'
    
    def test_unknown_field(self):
        """Test with unknown field name."""
        values = pd.Series(['test', 'test', 'test'])
        result = determine_field_type_from_values('UnknownField', values)
        assert result == 'string'