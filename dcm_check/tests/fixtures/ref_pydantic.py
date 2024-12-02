from typing import List
from pydantic import BaseModel, confloat, field_validator

class T1_MPR_Config(BaseModel):
    SeriesDescription: str
    MagneticFieldStrength: confloat(ge=2.9, le=3.1)
    RepetitionTime: confloat(ge=2300, le=2500)
    EchoTime: List[float]
    PixelSpacing: List[float]
    SliceThickness: confloat(ge=0.75, le=0.85)

    # Validators
    @field_validator("EchoTime", mode="before")
    def validate_echo_time_spacing(cls, value):
        if len(value) > 1:
            spacings = [j - i for i, j in zip(value[:-1], value[1:])]
            if not all(abs(spacings[0] - s) < 0.01 for s in spacings):
                raise ValueError("EchoTime values must be evenly spaced.")
        return value

    # Define acquisition and reference fields as class attributes
    acquisition_fields: List[str] = ["SeriesDescription"]
    reference_fields: List[str] = ["MagneticFieldStrength", "RepetitionTime", "EchoTime", "PixelSpacing", "SliceThickness"]

ACQUISITION_MODELS = {
    "T1_MPR": T1_MPR_Config,
}
