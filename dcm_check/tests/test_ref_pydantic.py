import pytest
from dcm_check import load_ref_pydantic, is_compliant, get_compliance_summary

@pytest.fixture
def t1_mpr_dicom_values():
    """Fixture for T1_MPR DICOM test values."""
    return {
        "SeriesDescription": "t1_mpr_sag",
        "MagneticFieldStrength": 3.0,
        "RepetitionTime": 2400,
        "EchoTime": 12,
        "PixelSpacing": [0.8, 0.8],
        "SliceThickness": 0.8
    }

@pytest.fixture
def invalid_t1_mpr_dicom_values():
    """Fixture for invalid T1_MPR DICOM values."""
    return {
        "SeriesDescription": "t2",  # Does not contain "T1"
        "MagneticFieldStrength": 2.0,  # Out of range
        "RepetitionTime": 1000,  # Too low, fails repetition vs echo rule
        "EchoTime": 700,
        "PixelSpacing": [0.9, 0.9],  # Out of allowed range
        "SliceThickness": 1.2  # Out of range
    }

def test_load_ref_pydantic_models(t1_mpr_dicom_values):
    # Path to the module file (e.g., "dcm_check/tests/ref_pydantic.py")
    module_path = "dcm_check/tests/ref_pydantic.py"

    # Load all the models from the module
    load_ref_pydantic(module_path, "T1_MPR")
    load_ref_pydantic(module_path, "T2w_SPC")
    load_ref_pydantic(module_path, "Diff_1k")

def test_load_ref_pydantic_invalid_module():
    """Test loading a Pydantic model from an invalid module."""
    module_path = "dcm_check/tests/ref_pydantic.py"
    with pytest.raises(ValueError, match="Acquisition 'FAKE' is not defined in ACQUISITION_MODELS."):
        load_ref_pydantic(module_path, "FAKE")

def test_load_ref_pydantic_no_acquisition_models():
    """Test loading a Pydantic model from a module without ACQUISITION_MODELS."""
    module_path = "dcm_check/tests/ref_pydantic_no_models.py"
    with pytest.raises(ValueError, match="No ACQUISITION_MODELS found in the module 'dcm_check/tests/ref_pydantic_no_models.py'."):
        load_ref_pydantic(module_path, "T1_MPR")

def test_t1_mpr_compliance(t1_mpr_dicom_values):
    """Test compliance for valid T1_MPR values."""
    module_path = "dcm_check/tests/ref_pydantic.py"
    t1_mpr_model = load_ref_pydantic(module_path, "T1_MPR")

    # Verify that the model was loaded correctly
    assert t1_mpr_model is not None
    assert t1_mpr_model.__name__ == "T1_MPR_Config"

    # Validate compliance
    assert is_compliant(t1_mpr_model, t1_mpr_dicom_values)

    # Test get_compliance_summary
    compliance_summary = get_compliance_summary(t1_mpr_model, t1_mpr_dicom_values)
    assert len(compliance_summary) == 0  # Should be no errors if values are valid

def test_t1_mpr_compliance_summary_invalid(invalid_t1_mpr_dicom_values):
    """Test compliance summary for invalid T1_MPR values."""
    module_path = "dcm_check/tests/ref_pydantic.py"
    t1_mpr_model = load_ref_pydantic(module_path, "T1_MPR")
    
    # Validate non-compliance
    assert not is_compliant(t1_mpr_model, invalid_t1_mpr_dicom_values)

    # Get compliance summary for errors
    compliance_summary = get_compliance_summary(t1_mpr_model, invalid_t1_mpr_dicom_values)
    assert len(compliance_summary) > 0  # Expect some errors

    # Example check for specific errors
    error_params = [error["Parameter"] for error in compliance_summary]
    assert "SeriesDescription" in error_params  # Expect failure on SeriesDescription
    assert "MagneticFieldStrength" in error_params  # Out of range error
    assert "RepetitionTime" in error_params  # Repetition vs Echo rule
    assert "PixelSpacing" in error_params  # Out of range error
    assert "SliceThickness" in error_params  # Out of range error

def test_t1_mpr_repetition_vs_echo_rule(t1_mpr_dicom_values):
    """Test that the RepetitionTime and EchoTime rule is enforced."""
    module_path = "dcm_check/tests/ref_pydantic.py"
    t1_mpr_model = load_ref_pydantic(module_path, "T1_MPR")
    
    # Modify RepetitionTime to break the 2x EchoTime rule
    t1_mpr_dicom_values["EchoTime"] = 3000  # Too low
    
    # Validate non-compliance
    assert not is_compliant(t1_mpr_model, t1_mpr_dicom_values)

    # Check compliance summary
    compliance_summary = get_compliance_summary(t1_mpr_model, t1_mpr_dicom_values)

    assert len(compliance_summary) > 0
    assert compliance_summary[0]["Parameter"] == "Model-Level Error"
    assert compliance_summary[0]["Expected"] == "RepetitionTime must be at least 2x EchoTime"
    assert compliance_summary[0]["Value"] == "N/A"

def test_diffusion_config_compliance():
    """Test DiffusionConfig compliance for a sample diffusion acquisition."""
    module_path = "dcm_check/tests/ref_pydantic.py"
    diffusion_model = load_ref_pydantic(module_path, "Diff_1k")

    valid_diffusion_values = {
        "SeriesDescription": "Diff_1k",
        "bValue": 1000,
        "NumberOfDirections": 30,
        "PixelSpacing": [1.25, 1.25],
        "SliceThickness": 1.25
    }
    
    # Validate compliance
    assert is_compliant(diffusion_model, valid_diffusion_values)

def test_diffusion_config_non_compliance():
    """Test non-compliance for DiffusionConfig."""
    module_path = "dcm_check/tests/ref_pydantic.py"
    diffusion_model = load_ref_pydantic(module_path, "Diff_1k")

    invalid_diffusion_values = {
        "SeriesDescription": "wrong",  # Wrong prefix
        "bValue": 1200, # Out of range
        "NumberOfDirections": 4,  # Too few directions
        "PixelSpacing": [1.4, 1.4],  # Out of allowed range
        "SliceThickness": 1.4  # Out of range
    }
    
    # Validate non-compliance
    assert not is_compliant(diffusion_model, invalid_diffusion_values)

    # Check compliance summary
    compliance_summary = get_compliance_summary(diffusion_model, invalid_diffusion_values)
    print(compliance_summary)
    assert len(compliance_summary) == 6
    error_params = [error["Parameter"] for error in compliance_summary]
    assert "SeriesDescription" in error_params
    assert "NumberOfDirections" in error_params
    assert "PixelSpacing" in error_params
    assert "SliceThickness" in error_params

if __name__ == "__main__":
    pytest.main(["-v", __file__])

