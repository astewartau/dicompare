import numpy as np
from pydantic import BaseModel, Field, model_validator, ValidationError
from typing import List

class GRE_ECHO(BaseModel):
    EchoTime: float

class GRE_ASPIRE(BaseModel):
    SeriesDescription: str
    series: List[GRE_ECHO]

    @model_validator(mode="after")
    def validate_echo_time_spacing(self):
        echo_times = [
            series.EchoTime for series in self.series if hasattr(series, 'EchoTime')
        ]
        if len(echo_times) < 2:
            return self

        # Ensure echo times are sorted and evenly spaced
        echo_times.sort()
        spacings = [echo_times[i] - echo_times[i - 1] for i in range(1, len(echo_times))]
        if not all(np.isclose(spacing, spacings[0]) for spacing in spacings):
            raise ValueError(
                f"Echo times are not evenly spaced: {echo_times}. Spacings: {spacings}"
            )
        return self

ACQUISITION_MODELS = {
    "GRE_ASPIRE": GRE_ASPIRE
}
