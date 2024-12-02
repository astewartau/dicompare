import pytest
from pydantic import ValidationError

from dcm_check.models import load_ref_dict, create_reference_model

@pytest.fixture
def sample_session():
    return {
        "acquisitions": {
            "acq-T1": {
                "fields": [
                    {"field": "EchoTime", "value": 25.0, "tolerance": 1.0},
                    {"field": "ProtocolName", "value": "T1"}
                ],
                "series": [
                    {
                        "fields": [
                            {"field": "SeriesDescription", "value": "T1-weighted"},
                            {"field": "PatientName", "contains": "Patient"}
                        ]
                    }
                ]
            }
        }
    }

@pytest.fixture
def simple_reference():
    return {
        "reference_values": {"EchoTime": 25.0},
        "fields_config": [
            {"field": "EchoTime", "value": 25.0, "tolerance": 1.0}
        ]
    }

def test_create_reference_model_exact_match(simple_reference):
    model = create_reference_model(
        simple_reference["reference_values"],
        simple_reference["fields_config"]
    )

    instance = model(EchoTime=25.0)  # Valid value
    assert instance.EchoTime == 25.0

    with pytest.raises(ValidationError):
        model(EchoTime=27.0)  # Outside tolerance

def test_create_reference_model_pattern_match():
    reference_values = {"ProtocolName": "T1*"}
    fields_config = [
        {"field": "ProtocolName", "value": "T1*"}
    ]
    model = create_reference_model(reference_values, fields_config)

    instance = model(ProtocolName="T1-weighted")  # Matches pattern
    assert instance.ProtocolName == "T1-weighted"

    with pytest.raises(ValidationError):
        model(ProtocolName="FLAIR")  # Does not match pattern

def test_create_reference_model_contains_match():
    reference_values = {}
    fields_config = [
        {"field": "PatientName", "contains": "Patient"}
    ]
    model = create_reference_model(reference_values, fields_config)

    instance = model(PatientName=["John", "Patient"])  # Contains "Patient"
    assert instance.PatientName == ["John", "Patient"]

    with pytest.raises(ValidationError):
        model(PatientName=["John", "Doe"])  # Does not contain "Patient"

def test_create_reference_model_list_match():
    reference_values = {"ImageType": ["ORIGINAL", "PRIMARY"]}
    fields_config = [
        {"field": "ImageType", "value": ["ORIGINAL", "PRIMARY"]}
    ]
    model = create_reference_model(reference_values, fields_config)

    instance = model(ImageType=["ORIGINAL", "PRIMARY"])  # Exact match
    assert instance.ImageType == ["ORIGINAL", "PRIMARY"]

    with pytest.raises(ValidationError):
        model(ImageType=("ORIGINAL"))  # Missing "PRIMARY"

def test_load_ref_dict(sample_session):
    updated_session = load_ref_dict(sample_session)
    acquisitions = updated_session["acquisitions"]
    assert "acq-T1" in acquisitions

    acquisition = acquisitions["acq-T1"]
    assert "fields" in acquisition
    assert "series" in acquisition

    # Validate series model
    series = acquisition["series"][0]
    assert "model" in series

    model = series["model"]
    instance = model(
        EchoTime=25.0,
        ProtocolName="T1",
        SeriesDescription="T1-weighted",
        PatientName=["Test", "Patient"]
    )

    assert instance.EchoTime == 25.0
    assert instance.ProtocolName == "T1"
    assert instance.SeriesDescription == "T1-weighted"
    assert instance.PatientName == ["Test", "Patient"]

    with pytest.raises(ValidationError):
        model(EchoTime=27.0)  # Outside tolerance

def test_load_ref_dict_missing_series_field(sample_session):
    sample_session["acquisitions"]["acq-T1"]["series"][0]["fields"].pop(1)
    updated_session = load_ref_dict(sample_session)
    series = updated_session["acquisitions"]["acq-T1"]["series"][0]
    model = series["model"]

    instance = model(EchoTime=25.0, ProtocolName="T1", SeriesDescription="T1-weighted")
    assert instance.SeriesDescription == "T1-weighted"
    assert "PatientName" not in instance.__fields__

def test_create_reference_model_numeric_tolerance():
    reference_values = {"FlipAngle": 15.0}
    fields_config = [
        {"field": "FlipAngle", "value": 15.0, "tolerance": 2.0}
    ]
    model = create_reference_model(reference_values, fields_config)

    instance = model(FlipAngle=14.0)  # Within tolerance
    assert instance.FlipAngle == 14.0

    with pytest.raises(ValidationError):
        model(FlipAngle=18.1)  # Outside tolerance

def test_create_reference_model_numeric_encoding():
    reference_values = {"EchoTime": 25.0}
    fields_config = [
        {"field": "EchoTime", "value": 25.0, "tolerance": 1.0}
    ]
    model = create_reference_model(reference_values, fields_config)

    # Test with EchoTime as float
    instance_float = model(EchoTime=25.0)  # Exact match as float
    assert instance_float.EchoTime == 25.0
    assert isinstance(instance_float.EchoTime, float)

    # Test with EchoTime as int
    instance_int = model(EchoTime=25)  # Within tolerance, int provided
    assert instance_int.EchoTime == 25.0  # Should normalize to float
    assert isinstance(instance_int.EchoTime, float)

    # Test with EchoTime outside tolerance
    with pytest.raises(ValidationError):
        model(EchoTime=27)  # Outside tolerance

    with pytest.raises(ValidationError):
        model(EchoTime=23)  # Outside tolerance

