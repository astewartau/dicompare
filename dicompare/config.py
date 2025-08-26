"""
Configuration constants for dicompare.

This module contains default field lists, constants, and configuration
values used throughout the dicompare package.
"""

# Default reference fields for DICOM acquisition comparison
DEFAULT_SETTINGS_FIELDS = [
    # Core acquisition parameters
    "ScanOptions",
    "MRAcquisitionType", 
    # "SequenceName",  # Removed - varies per diffusion direction in multi-shell sequences
    "AngioFlag",
    "SliceThickness",
    "AcquisitionMatrix",
    "RepetitionTime",
    # "InversionTime",  # Removed - varies between inversion points in MP2RAGE sequences
    "NumberOfAverages",
    "ImagingFrequency",
    "ImagedNucleus",
    "MagneticFieldStrength",
    "NumberOfPhaseEncodingSteps",
    "EchoTrainLength",
    "PercentSampling",
    "PercentPhaseFieldOfView",
    "PixelBandwidth",
    
    # Coil and hardware parameters
    "ReceiveCoilName",
    "TransmitCoilName",
    # "FlipAngle",  # Removed - varies between inversion points in MP2RAGE sequences
    "ReconstructionDiameter",
    "InPlanePhaseEncodingDirection",
    "ParallelReductionFactorInPlane",
    "ParallelAcquisitionTechnique",
    
    # Timing and triggering
    "TriggerTime",
    "TriggerSourceOrType",
    "BeatRejectionFlag",
    "LowRRValue",
    "HighRRValue",
    
    # Safety and limits
    "SAR",
    "dBdt",
    
    # Advanced sequence parameters
    "GradientEchoTrainLength",
    "SpoilingRFPhaseAngle",
    # "DiffusionBValue",  # Removed - varies per b-shell in multi-shell sequences
    # "DiffusionGradientDirectionSequence",  # Removed - varies per diffusion direction
    "PerfusionTechnique",
    "SpectrallySelectedExcitation",
    "SaturationRecovery",
    "SpectrallySelectedSuppression",
    "TimeOfFlightContrast",
    "SteadyStatePulseSequence",
    "PartialFourierDirection",
    "MultibandFactor"
]

DEFAULT_SERIES_FIELDS = [
    "SeriesInstanceUID",
    "SeriesDescription",
    "SeriesNumber",
    "SeriesDate",
    "SeriesTime",
    "ImageType",
    "EchoTime",
    "DiffusionBValue",
    "DiffusionGradientDirectionSequence",
    "InversionTime"
]

# Default acquisition identification fields
DEFAULT_ACQUISITION_FIELDS = ["ProtocolName"]

# Default run grouping fields for identifying separate runs
DEFAULT_RUN_GROUP_FIELDS = ["PatientName", "PatientID", "ProtocolName", "StudyDate"]

# Fields that should not contain zero values (used in DICOM processing)
NONZERO_FIELDS = [
    "EchoTime",
    "FlipAngle", 
    "SliceThickness",
    "RepetitionTime",
    "InversionTime",
    "NumberOfAverages",
    "ImagingFrequency",
    "MagneticFieldStrength",
    "NumberOfPhaseEncodingSteps",
    "EchoTrainLength",
    "PercentSampling",
    "PercentPhaseFieldOfView",
    "PixelBandwidth",
]

# Maximum difference score for field matching
MAX_DIFF_SCORE = 10

# Comprehensive DICOM field list for web interface
# Used by both schema generation and compliance checking components
DEFAULT_DICOM_FIELDS = [
    # Core Identifiers
    'SeriesDescription',
    'SequenceName',
    'SequenceVariant',
    'ScanningSequence',
    'ImageType', # MISSING

    'Manufacturer',
    'ManufacturerModelName',
    'SoftwareVersion',

    # Geometry
    'MRAcquisitionType',
    'SliceThickness', 
    'PixelSpacing', 
    'Rows',
    'Columns',
    'Slices',
    'AcquisitionMatrix',
    'ReconstructionDiameter',

    # Timing / Contrast
    'RepetitionTime',
    'EchoTime',
    'InversionTime',
    'FlipAngle',
    'EchoTrainLength',
    'GradientEchoTrainLength', # MISSING
    'NumberOfTemporalPositions',
    'TemporalResolution', # MISSING
    'SliceTiming', # MISSING

    # Diffusion-specific
    'DiffusionBValue', # MISSING
    'DiffusionGradientDirectionSequence', # MISSING

    # Parallel Imaging / Multiband
    'ParallelAcquisitionTechnique',
    'ParallelReductionFactorInPlane',
    'PartialFourier',
    'SliceAccelerationFactor',
    'MultibandFactor',

    # Bandwidth / Readout
    'PixelBandwidth',
    'BandwidthPerPixelPhaseEncode',

    # Phase encoding
    'InPlanePhaseEncodingDirection',
    'NumberOfPhaseEncodingSteps',

    # Scanner hardware
    'MagneticFieldStrength',
    'ImagingFrequency',
    'ImagedNucleus',
    'TransmitCoilName',
    'ReceiveCoilName',
    'SAR', # MISSING
    'dBdt',
    'NumberOfAverages',
    'CoilType',

    # Coverage / FOV %
    'PercentSampling',
    'PercentPhaseFieldOfView',

    # Scan options
    'ScanOptions', # MISSING
    'AngioFlag',

    # Triggering / gating (mostly fMRI / cardiac)
    'TriggerTime',
    'TriggerSourceOrType',
    'BeatRejectionFlag', # MISSING
    'LowRRValue', # MISSING
    'HighRRValue', # MISSING

    # Advanced / niche
    'SpoilingRFPhaseAngle',
    'PerfusionTechnique', # MISSING
    'SpectrallySelectedExcitation', # MISSING
    'SaturationRecovery', # MISSING
    'SpectrallySelectedSuppression', # MISSING
    'TimeOfFlightContrast',
    'SteadyStatePulseSequence', # MISSING
    'PartialFourierDirection',
]

# Enhanced to regular DICOM field mapping
ENHANCED_TO_REGULAR_MAPPING = {
    "EffectiveEchoTime": "EchoTime",
    "FrameType": "ImageType", 
    "FrameAcquisitionNumber": "AcquisitionNumber",
    "FrameAcquisitionDateTime": "AcquisitionDateTime",
    "FrameAcquisitionDuration": "AcquisitionDuration",
    "FrameReferenceDateTime": "ReferenceDateTime",
}