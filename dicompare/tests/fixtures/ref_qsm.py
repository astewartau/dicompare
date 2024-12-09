import math

from typing import ClassVar, List, Dict, Tuple
from pydantic import BaseModel, confloat, field_validator, model_validator, FieldValidationInfo

class QSM(BaseModel):
    SeriesDescription: str

    MagneticFieldStrength: float
    RepetitionTime: float
    FlipAngle: float
    EchoTime: List[float]
    SliceThickness: float
    PixelSpacing: Tuple[float, float]
    PixelBandwidth: float
    MRAcquisitionType: str

    # Define acquisition and reference fields as class-level constants
    acquisition_fields: ClassVar[List[str]] = ["SeriesDescription"]
    reference_fields: ClassVar[List[str]] = [
        "MagneticFieldStrength", "RepetitionTime", "FlipAngle", "EchoTime", "SliceThickness", "PixelSpacing", "PixelBandwidth", "MRAcquisitionType"
    ]

    # Specify field behaviors
    field_behaviors: ClassVar[Dict[str, str]] = {
        "MagneticFieldStrength": "scalar",
        "RepetitionTime": "scalar",
        "FlipAngle": "scalar",
        "EchoTime": "aggregate",
        "SliceThickness": "scalar",
        "PixelSpacing": "scalar",
        "PixelBandwidth": "scalar",
        "MRAcquisitionType": "scalar"
    }

    # While QSM can be achieved with one echo, two is the minimum number of echoes needed to separate the intrinsic transmit RF phase from the magnetic field-induced phase (see Section 3 below).
    @field_validator("EchoTime", mode="before")
    def validate_echotime_is_list(cls, value):
        if not isinstance(value, list):
            return [value]
        return value
    
    # While QSM can be achieved with one echo, two is the minimum number of echoes needed to separate the intrinsic transmit RF phase from the magnetic field-induced phase (see Section 3 below).
    @field_validator("EchoTime", mode="after")
    def validate_echo_count(cls, value):
        if len(value) < 2:
            raise ValueError("Multi-echo acquisitions are recommended.")
        elif len(value) < 3:
            raise ValueError("At least three echoes are recommended.")
        return value
    
    # The first TE (TE1) should be as short as possible
    @field_validator("EchoTime", mode="after")
    def validate_first_echo(cls, value):
        if value[0] > 10:
            raise ValueError("The first TE should be as short as possible.")
        return value
        
    # Use 3D acquisition instead of 2D acquisition to avoid potential slice-to-slice phase discontinuities in 2D phase maps.
    @field_validator("MRAcquisitionType", mode="after")
    def validate_mra_type(cls, value):
        if value != "3D":
            raise ValueError("Use 3D acquisition instead of 2D acquisition to avoid potential slice-to-slice phase discontinuities in 2D phase maps.")
        return value
    
    @model_validator(mode="after")
    def validate_repetition_time(cls, values: FieldValidationInfo):
        T1_MIN_MAX = {
            1.5: {"min": 600, "max": 1200},
            3.0: {"min": 900, "max": 1650},
            7.0: {"min": 1100, "max": 1900},
        }
        
        repetition_time = values.get("RepetitionTime")
        field_strength = values.get("MagneticFieldStrength")

        if field_strength not in T1_MIN_MAX:
            raise ValueError("Unsupported MagneticFieldStrength for TR validation.")

        t1_range = T1_MIN_MAX[field_strength]
        t1_min, t1_max = t1_range["min"], t1_range["max"]

        # Validate TR does not exceed maximum bound
        if repetition_time > 0.5 * t1_max:
            raise ValueError(
                f"RepetitionTime should be as short as possible, but it is > 0.5x the longest reasonable T1 ({t1_max} ms) at {field_strength}T"
            )

        return values

    @model_validator(mode="after")
    def validate_flip_angle(cls, value, values):
        T1_MIN_MAX = {
            1.5: {"min": 600, "max": 1200},
            3.0: {"min": 900, "max": 1650},
            7.0: {"min": 1100, "max": 1900},
        }
        tr = values.data["RepetitionTime"]
        field_strength = values.data["MagneticFieldStrength"]

        if tr is None or field_strength not in T1_MIN_MAX:
            raise ValueError("Cannot validate FlipAngle without valid RepetitionTime or MagneticFieldStrength.")

        t1_range = T1_MIN_MAX[field_strength]
        t1_min, t1_max = t1_range["min"], t1_range["max"]

        # Calculate min and max Ernst angles
        ernst_min = math.acos(math.exp(-tr / t1_max)) * (180 / math.pi)  # For the longest T1
        ernst_max = math.acos(math.exp(-tr / t1_min)) * (180 / math.pi)  # For the shortest T1

        # Validate FlipAngle is within the calculated range
        if not (ernst_min <= value <= ernst_max):
            raise ValueError(
                f"FlipAngle should be close to the Ernst angles ({ernst_min:.2f}° to {ernst_max:.2f}°) "
                f"for the T1 range at {field_strength}T ({t1_min}-{t1_max} ms)"
            )
        return value
    
    # The longest TE (the TE of the last echo) should be equal to at least the value of the tissue of interest.
    #  --> The longest TE should be at least 1.25x the greatest typical T2* value for the field strength, and no less than 0.75x the lowest typical T2* value.
    @model_validator(mode="after")
    def validate_echo_times(cls, values: FieldValidationInfo):
        tissue_values = {
            1.5: {"grey": 84.0, "white": 66.2, "caudate": 58.8, "putamen": 55.5},
            3.0: {"grey": 66.0, "white": 53.2, "caudate": 41.3, "putamen": 31.5},
            7.0: {"grey": 33.2, "white": 26.8, "caudate": 19.9, "putamen": 16.1}
        }

        magnetic_field_strength = values.data["MagneticFieldStrength"]
        TEs = values.data["EchoTime"]

        max_tissue = max(tissue_values[magnetic_field_strength].values())
        min_tissue = min(tissue_values[magnetic_field_strength].values())

        if TEs[-1] > 1.25 * max_tissue:
            raise ValueError(
                f"The longest TE should be at most 1.25x the T2* value of the tissue of interest "
                f"({max_tissue}ms @ {values.data['MagneticFieldStrength']}T in the {tissue_values[values.data['MagneticFieldStrength']]} vs your value of {value[-1]}ms)."
            )
        if TEs[-1] < 0.75 * min_tissue:
            raise ValueError(
                f"The longest TE should be at least 0.75x the T2* value of the tissue of interest "
                f"({min_tissue}ms @ {values.data['MagneticFieldStrength']}T in the {tissue_values[values.data['MagneticFieldStrength']]} vs your value of {value[-1]}ms)."
            )
        return TEs    

    # The spacing between echoes (ΔTE) should be uniform.
    @model_validator(mode="before")
    def uniform_echo_spacing(cls, values: FieldValidationInfo):
        TEs = values["EchoTime"]
        if isinstance(TEs, list) and len(TEs) > 1:
            spacings = [j - i for i, j in zip(TEs[:-1], TEs[1:])]
            if not all(abs(spacings[0] - s) < 0.01 for s in spacings):
                raise ValueError("EchoTime values must be evenly spaced.")
        return values

    # Use isotropic voxels of at most 1 mm to reduce partial volume-related estimation errors (check PixelSpacing and SliceThickness)
    @model_validator(mode="after")
    def validate_pixel_spacing(cls, values: FieldValidationInfo):
        voxel_size = list(values.data["PixelSpacing"]) + [values.data["SliceThickness"]]
        if any(v > 1 for v in voxel_size):
            raise ValueError("Use isotropic voxels of at most 1 mm to reduce partial volume-related estimation errors.")
    
    # Use the minimum readout bandwidth which generates acceptable distortions. At 3T, 220 Hz/pixel is often sufficient (two-pixel fat-water shift). Such acquisitions negate the need to use fat suppression for brain applications.
    @model_validator(mode="after")
    def validate_pixel_bandwidth(cls, values: FieldValidationInfo):
        pixel_bandwidth = values.data["PixelBandwidth"]
        field_strength = values.data["MagneticFieldStrength"]
        if field_strength == 3.0 and pixel_bandwidth > 220:
            raise ValueError("At 3T, 220 Hz/pixel is often sufficient and would negate the need for fat suppression.")
        if field_strength != 3.0:
            raise ValueError("TODO: Recommended PixelBandwidth unknown at this field strength!")
        return values
    
    # Use a monopolar gradient readout (fly-back) to avoid geometric mismatch and eddy current-related phase problems between even and odd echoes in bipolar acquisitions.80
    # TODO
    # Consider using flow compensation when targeting vessels, but note that flow compensation is often only available and effective for the first echo, while flow artifacts increase in later echoes.81 More detailed rationale and additional considerations are provided in Supporting Information IV.
    # TODO


ACQUISITION_MODELS = {
    "QSM": QSM,
}
