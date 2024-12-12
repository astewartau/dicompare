import math
from dicompare.validation import ValidationError, BaseValidationModel, validator

class QSM(BaseValidationModel):

    @validator(["ImageType", "EchoTime"], rule_message="Each EchoTime must have exactly one magnitude and phase image.")
    def validate_image_type(cls, value):  # value is a DataFrame grouped by ImageType and EchoTime
        magnitude_counts = []
        phase_counts = []

        for echo_time, group in value.groupby("EchoTime"):
            image_types = group["ImageType"]

            # Count occurrences of 'M' and 'P' in ImageType tuples
            magnitude_counts.append(sum('M' in image for image in image_types))
            phase_counts.append(sum('P' in image for image in image_types))

        if not all(m == 1 for m in magnitude_counts):
            raise ValidationError(f"Each EchoTime must have exactly one magnitude image. Found {magnitude_counts}.")
        if not all(p == 1 for p in phase_counts):
            raise ValidationError(f"Each EchoTime must have exactly one phase image. Found {phase_counts}.")

        return value
    
    @validator(["ImageType", "EchoTime"], rule_message="Each magnitude and phase image should have the same number of slices.")
    def validate_image_slices(cls, value):
        num_slices = value['Count']
        if not all(num_slices == num_slices.iloc[0]):
            raise ValidationError()
        return value

    @validator(["EchoTime"], rule_message="While QSM can be achieved with one echo, two is the minimum number of echoes needed to separate the intrinsic transmit RF phase from the magnetic field-induced phase.")
    def validate_echo_count(cls, value):
        echo_times = value["EchoTime"].dropna().unique()
        if len(echo_times) == 1:
            raise ValidationError("Found single-echo acquisition.")
        elif len(echo_times) < 3:
            raise ValidationError(f"Found {len(echo_times)} echoes, but at least 3 are recommended.")
        return value

    @validator(["EchoTime"], rule_message="The spacing between echoes (ΔTE) should be uniform.")
    def uniform_echo_spacing(cls, value):
        echo_times = value["EchoTime"].dropna().sort_values()
        spacings = echo_times.diff().iloc[1:]
        if not all(abs(spacings.iloc[0] - s) < 0.01 for s in spacings):
            raise ValidationError()
        return value

    @validator(["EchoTime"], rule_message="The first TE (TE1) should be as short as possible.")
    def validate_first_echo(cls, value):
        first_echo_time = value["EchoTime"].min()
        if first_echo_time > 10:
            raise ValidationError(f"The first TE is overly long.")
        return value

    @validator(["MRAcquisitionType"], rule_message="Use 3D acquisition instead of 2D acquisition to avoid potential slice-to-slice phase discontinuities in 2D phase maps.")
    def validate_mra_type(cls, value):
        acquisition_type = value["MRAcquisitionType"].iloc[0]  # Assuming consistent within group
        if acquisition_type != "3D":
            raise ValidationError(f"The input data is not 3D.")
        return value

    @validator(["RepetitionTime", "MagneticFieldStrength"], rule_message="RepetitionTime should be as short as possible.")
    def validate_repetition_time(cls, value):
        repetition_time = value["RepetitionTime"].iloc[0]
        field_strength = value["MagneticFieldStrength"].iloc[0]

        T1_MIN_MAX = {
            1.5: {"min": 600, "max": 1200},
            3.0: {"min": 900, "max": 1650},
            7.0: {"min": 1100, "max": 1900},
        }

        if field_strength not in T1_MIN_MAX:
            raise ValidationError("Unsupported MagneticFieldStrength for TR validation.")

        t1_min, t1_max = T1_MIN_MAX[field_strength]["min"], T1_MIN_MAX[field_strength]["max"]
        if repetition_time > 0.5 * t1_max:
            raise ValidationError(f"TR may not be as short as possible (≤0.5*T1≈{0.5*t1_max} ms).")
        return value

    @validator(["FlipAngle", "RepetitionTime", "MagneticFieldStrength"], rule_message="FlipAngle should be close to the Ernst angle.")
    def validate_flip_angle(cls, value):
        tr = value["RepetitionTime"].iloc[0]
        field_strength = value["MagneticFieldStrength"].iloc[0]
        flip_angle = value["FlipAngle"].iloc[0]

        T1_MIN_MAX = {
            1.5: {"min": 600, "max": 1200},
            3.0: {"min": 900, "max": 1650},
            7.0: {"min": 1100, "max": 1900},
        }

        if field_strength not in T1_MIN_MAX:
            raise ValidationError(f"Unsupported MagneticFieldStrength {field_strength}T for Ernst angle validation.")

        t1_min, t1_max = T1_MIN_MAX[field_strength]["min"], T1_MIN_MAX[field_strength]["max"]
        ernst_min = math.acos(math.exp(-tr / t1_max)) * (180 / math.pi)
        ernst_max = math.acos(math.exp(-tr / t1_min)) * (180 / math.pi)

        if not (ernst_min <= flip_angle <= ernst_max):
            raise ValidationError(f"FlipAngle should be between {ernst_min:.2f}° and {ernst_max:.2f}° at {field_strength}T.")
        return value

    @validator(["EchoTime", "MagneticFieldStrength"], rule_message="The longest TE (the TE of the last echo) should be equal to at least the T2* value of the tissue of interest.")
    def validate_echo_times(cls, value):
        echo_times = value["EchoTime"].dropna().sort_values()
        field_strength = value["MagneticFieldStrength"].iloc[0]

        tissue_values = {
            1.5: {"grey": 84.0, "white": 66.2, "caudate": 58.8, "putamen": 55.5},
            3.0: {"grey": 66.0, "white": 53.2, "caudate": 41.3, "putamen": 31.5},
            7.0: {"grey": 33.2, "white": 26.8, "caudate": 19.9, "putamen": 16.1},
        }

        max_tissue = max(tissue_values[field_strength].values())
        min_tissue = min(tissue_values[field_strength].values())

        if echo_times.iloc[-1] > 1.25 * max_tissue:
            raise ValidationError(f"The longest TE should be ≤1.25x the highest tissue T2* ({max_tissue} ms).")
        if echo_times.iloc[-1] < 0.75 * min_tissue:
            raise ValidationError(f"The longest TE should be ≥0.75x the lowest tissue T2* ({min_tissue} ms).")
        return value
    
    @validator(["PixelSpacing", "SliceThickness"], rule_message="Use isotropic voxels.")
    def validate_voxel_shape(cls, value):
        pixel_spacing = value["PixelSpacing"].iloc[0]
        slice_thickness = value["SliceThickness"].iloc[0]

        if not all(p == pixel_spacing[0] for p in pixel_spacing) or pixel_spacing[0] != slice_thickness:
            raise ValidationError()
        return value

    @validator(["PixelSpacing", "SliceThickness"], rule_message="Use a combined voxel size of at most 1 mm³ to reduce partial volume-related estimation errors.")
    def validate_pixel_spacing(cls, value):
        pixel_spacing = value["PixelSpacing"].iloc[0]
        slice_thickness = value["SliceThickness"].iloc[0]
        voxel_size_mm3 = math.prod(list(pixel_spacing) + [slice_thickness])

        if voxel_size_mm3 > 1:
            raise ValidationError(f"Voxel size should be ≤1 mm³. Got {voxel_size_mm3:.2f} mm³.")
        
        return value

    @validator(["PixelBandwidth", "MagneticFieldStrength"], rule_message="Use the minimum readout bandwidth which generates acceptable distortions.")
    def validate_pixel_bandwidth(cls, value):
        pixel_bandwidth = value["PixelBandwidth"].iloc[0]
        field_strength = value["MagneticFieldStrength"].iloc[0]

        if field_strength == 3.0 and pixel_bandwidth > 220:
            raise ValidationError("PixelBandwidth should be ≤220 Hz/pixel at 3T.")
        elif field_strength != 3.0:
            raise ValidationError("PixelBandwidth recommendations are not available for this field strength.")
        return value

    # Use a monopolar gradient readout (fly-back) to avoid geometric mismatch and eddy current-related phase problems between even and odd echoes in bipolar acquisitions.80
    # TODO
    # Consider using flow compensation when targeting vessels, but note that flow compensation is often only available and effective for the first echo, while flow artifacts increase in later echoes.81 More detailed rationale and additional considerations are provided in Supporting Information IV.
    # TODO

ACQUISITION_MODELS = {
    "QSM": QSM,
}
