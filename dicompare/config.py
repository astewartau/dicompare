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
    "EchoTime",  # Can vary within multi-echo acquisitions - handled by parameter set grouping
    "InversionTime",  # Can vary within MP2RAGE acquisitions - handled by parameter set grouping
    "FlipAngle",  # Can vary within some acquisitions - handled by parameter set grouping
    "NumberOfAverages",
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
    "CoilCombinationMethod",  # Siemens: Sum of Squares, Adaptive Combine
    "ReconstructionDiameter",
    "InPlanePhaseEncodingDirection",
    "ParallelReductionFactorInPlane",
    "ParallelAcquisitionTechnique",
    "AccelerationFactorPE",  # Siemens: from sPat.lAccelFactPE (GRAPPA/SENSE)

    # Timing and triggering
    "TriggerTime",
    "TriggerSourceOrType",
    "BeatRejectionFlag",
    "LowRRValue",
    "HighRRValue",

    # Safety and limits
    "dBdt",

    # Advanced sequence parameters
    "GradientEchoTrainLength",
    "SpoilingRFPhaseAngle",
    "DiffusionBValue",  # Can vary within multi-shell acquisitions - handled by parameter set grouping
    # "DiffusionGradientDirectionSequence",  # Removed - varies per diffusion direction
    "PerfusionTechnique",
    "SpectrallySelectedExcitation",
    "SaturationRecovery",
    "SpectrallySelectedSuppression",
    "TimeOfFlightContrast",
    "SteadyStatePulseSequence",
    "PartialFourierDirection",
    "MultibandFactor",
    "ImageType",  # Can vary within multi-part acquisitions (M/P) - handled by parameter set grouping

    # ASL (Arterial Spin Labeling) parameters
    "ArterialSpinLabelingType",  # PCASL, PASL, CASL
    "PostLabelDelay",  # PLD in seconds
    "LabelingDuration",  # Labeling duration in seconds
    "BolusDuration",  # PASL bolus duration
    "LabelOffset",  # Labeling plane offset in mm
]

DEFAULT_SERIES_FIELDS = [
    "SeriesDescription",
    "ImageType",
    # "DiffusionBValue",  # Excluded - handled by parameter set grouping in acquisition assignment
    #"DiffusionGradientDirectionSequence", # Too many unique values - should be handled by validation rules
    "InversionTime"
]

# Default acquisition identification fields
DEFAULT_ACQUISITION_FIELDS = ["ProtocolName"]

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
    # ASL timing parameters
    "PostLabelDelay",
    "LabelingDuration",
    "BolusDuration",
    "TagDuration",
    "TagPlaneDThickness",
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
    'NumberOfImagesInMosaic',  # Siemens mosaic: slices per volume
    'TemporalResolution', # MISSING
    'SliceTiming', # MISSING

    # Diffusion-specific
    'DiffusionBValue', # MISSING
    #'DiffusionGradientDirectionSequence', # MISSING - too many unique values, should be handled by validation rules

    # Parallel Imaging / Multiband
    'ParallelAcquisitionTechnique',
    'ParallelReductionFactorInPlane',
    'AccelerationFactorPE',  # Siemens: from sPat.lAccelFactPE (GRAPPA/SENSE)
    'PartialFourier',
    'SliceAccelerationFactor',
    'MultibandFactor',

    # Bandwidth / Readout
    'PixelBandwidth',
    'BandwidthPerPixelPhaseEncode',

    # Phase encoding
    'InPlanePhaseEncodingDirection',
    'NumberOfPhaseEncodingSteps',
    'PhaseEncodingDirectionPositive',  # Siemens: 0=negative/P-A, 1=positive/A-P
    'RectilinearPhaseEncodeReordering',  # GE: LINEAR, REVERSE_LINEAR, etc.

    # Scanner hardware
    'MagneticFieldStrength',
    'ImagingFrequency',
    'ImagedNucleus',
    'TransmitCoilName',
    'ReceiveCoilName',
    'CoilCombinationMethod',  # Siemens: Sum of Squares, Adaptive Combine (from ucCoilCombineMode)
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

    # ASL (Arterial Spin Labeling) parameters
    'ArterialSpinLabelingType',  # PCASL, PASL, CASL - inferred from CSA/sequence name
    'PostLabelDelay',  # PLD in seconds (Siemens CSA, Philips TriggerDelayTime)
    'LabelingDuration',  # Labeling duration in seconds (computed from TagDuration or NumRFBlocks*RFGap)
    'BolusDuration',  # PASL bolus duration in seconds
    'LabelOffset',  # Labeling plane offset in mm
    'InitialPostLabelDelay',  # Multi-PLD array (vessel-encoded ASL)
    'NumRFBlocks',  # Number of RF pulses in labeling train
    'RFGap',  # Gap between RF pulses in seconds
    'TagDuration',  # PCASL labeling duration (vessel-encoded)
    'TagRFFlipAngle',  # RF flip angle for labeling
    'TagRFDuration',  # Duration of each RF pulse
    'TagRFSeparation',  # Separation between RF pulses
    'MeanTagGradient',  # Mean gradient during labeling
    'TagGradientAmplitude',  # Gradient amplitude during labeling
    'MaximumT1Opt',  # Maximum T1 optimization value
    'TagPlaneDThickness',  # Labeling plane thickness in mm
    'PhiAdjust',  # Phase adjustment for labeling
    'T1',  # Blood T1 value used for quantification (seconds)
    'MeanGzx10',  # Mean gradient (scaled by 10)
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