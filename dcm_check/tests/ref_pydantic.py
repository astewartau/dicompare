from pydantic import BaseModel, Field, field_validator, model_validator, confloat, model_validator
from pydantic_core import PydanticCustomError
from typing import List
import numpy as np

class T1_MPR_Config(BaseModel):
    SeriesDescription: str
    MagneticFieldStrength: confloat(ge=2.9, le=3.1)
    RepetitionTime: confloat(ge=2300, le=2500)
    EchoTime: float
    PixelSpacing: List[float]
    SliceThickness: confloat(ge=0.75, le=0.85)

    @field_validator("SeriesDescription")
    def validate_series_description(cls, v):
        if "t1" not in v.lower():
            raise ValueError("SeriesDescription must contain 'T1'")
        return v

    @field_validator("PixelSpacing", mode="before")
    def validate_pixel_spacing(cls, v):
        if len(v) != 2:
            raise ValueError("PixelSpacing must be a list of exactly 2 values")
        if not all(0.75 <= val <= 0.85 for val in v):
            raise ValueError("Each value in PixelSpacing must be between 0.75 and 0.85")
        return v
    
    @model_validator(mode="after")
    def check_repetition_vs_echo_time(self):
        rt, et = self.RepetitionTime, self.EchoTime
        if rt is not None and et is not None and rt < 2 * et:
            raise PydanticCustomError(
                "value_error",
                "RepetitionTime must be at least 2x EchoTime",
                {"RepetitionTime": rt, "EchoTime": et}
            )
        return self

class T2w_SPC_Config(BaseModel):
    SeriesDescription: str
    MagneticFieldStrength: confloat(ge=2.9, le=3.1)
    RepetitionTime: confloat(ge=3.1, le=3.3)
    EchoTime: confloat(ge=0.054, le=0.058)
    PixelSpacing: List[confloat(ge=0.75, le=0.85)]
    SliceThickness: confloat(ge=0.75, le=0.85)

    @field_validator("SeriesDescription")
    def validate_series_description(cls, v):
        if v != "T2w_SPC":
            raise ValueError("SeriesDescription must be 'T2w_SPC'")
        return v

    @field_validator("PixelSpacing")
    def validate_pixel_spacing(cls, v):
        if len(v) != 2:
            raise ValueError("PixelSpacing must have exactly 2 values")
        return v

class DiffusionConfig(BaseModel):
    SeriesDescription: str
    bValue: int = Field(..., ge=900, le=1100)
    NumberOfDirections: int = Field(..., ge=6)
    PixelSpacing: List[confloat(ge=1.15, le=1.35)] = [1.25, 1.25]
    SliceThickness: confloat(ge=1.15, le=1.35) = 1.25

    @field_validator("SeriesDescription")
    def validate_series_description(cls, v):
        if not v.startswith("Diff_"):
            raise ValueError("SeriesDescription must start with 'Diff_'")
        return v

    @field_validator("PixelSpacing")
    def validate_pixel_spacing(cls, v):
        if len(v) != 2:
            raise ValueError("PixelSpacing must have exactly 2 values")
        return v

# Dictionary to map acquisitions to their respective config models (without instantiation)
ACQUISITION_MODELS = {
    "T1_MPR": T1_MPR_Config,
    "T2w_SPC": T2w_SPC_Config,
    "Diff_1k": DiffusionConfig,
}

