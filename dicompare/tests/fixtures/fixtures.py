import datetime
import pytest
import json
import numpy as np
import nibabel as nib

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID, ExplicitVRLittleEndian

@pytest.fixture
def empty_nifti() -> nib.Nifti1Image:
    """Create a minimal NIfTI object with basic metadata for testing."""
    
    # Create a 10x10x10 array of random integers
    data = np.random.randint(0, 2**16, (10, 10, 10)).astype(np.uint16)
    
    # Create a NIfTI object
    nii = nib.Nifti1Image(data, np.eye(4))
    
    # Set the header metadata
    nii.header.set_xyzt_units('mm', 'sec')
    nii.header['pixdim'][4] = 1.0  # TE
    nii.header['pixdim'][0] = 3  # qform_code
    nii.header['qform_code'] = 1  # NIFTI_XFORM_SCANNER_ANAT
    nii.header['sform_code'] = 1  # NIFTI_XFORM_SCANNER_ANAT
    nii.header['intent_code'] = 0  # NIFTI_INTENT_NONE
    nii.header['intent_name'] = b''
    nii.header['intent_p1'] = 0.0
    nii.header['intent_p2'] = 0.0
    nii.header['intent_p3'] = 0.0
    nii.header['slice_code'] = 0  # NIFTI_SLICE_UNKNOWN
    nii.header['slice_duration'] = 0.0
    nii.header['toffset'] = 0.0
    nii.header['descrip'] = b''
    nii.header['aux_file'] = b''
    nii.header['qform_code'] = 1  # NIFTI_XFORM_SCANNER_ANAT
    nii.header['sform_code'] = 1  # NIFTI_XFORM_SCANNER_ANAT
    nii.header['quatern_b'] = 0.0
    nii.header['quatern_c'] = 0.0
    nii.header['quatern_d'] = 0.0
    nii.header['qoffset_x'] = 0.0
    nii.header['qoffset_y'] = 0.0
    nii.header['qoffset_z'] = 0.0
    nii.header['srow_x'] = [1, 0, 0, 0]
    nii.header['srow_y'] = [0, 1, 0, 0]
    nii.header['srow_z'] = [0, 0, 1, 0]

    return nii

@pytest.fixture
def empty_json() -> dict:
    json_sidecar = {
        "Modality": "MR",
        "MagneticFieldStrength": 7,
        "ImagingFrequency": 297.220808,
        "Manufacturer": "Siemens",
        "ManufacturersModelName": "Skyra",
        "InstitutionName": "Institution",
        "InstitutionalDepartmentName": "Department",
        "InstitutionAddress": "123 Main St",
        "DeviceSerialNumber": "12345",
        "StationName": "MRI",
        "BodyPartExamined": "BRAIN",
        "PatientPosition": "HFS",
        "ProcedureStepDescription": "MRI Brain",
        "SoftwareVersion": "syngo MR E11",
        "MRAcquisitionType": "3D",
        "SeriesDescription": "Magnitude",
        "ProtocolName": "T1w_MPRAGE",
        "ScanningSequence": "GR",
        "SequenceVariant": "SP",
        "ScanOptions": "FS",
        "SequenceName": "MPRAGE",
        "ImageType": ["ORIGINAL", "PRIMARY", "M", "ND"],
        "NonlinearGradientCorrection": True,
        "SeriesNumber": 1,
        "AcquisitionTime": "12:34:56",
        "AcquisitionNumber": 1,
        "SliceThickness": 1,
        "SAR": 0.1,
        "EchoTime": 0.0025,
        "RepetitionTime": 0.043,
        "FlipAngle": 15,
        "PartialFourier": 0.75,
        "BaseResolution": 272,
        "ShimSetting": [
            -12,
            -114,
            1191,
            625,
            1,
            24,
            298,
            -146	],
        "TxRefAmp": 229.712,
        "PhaseResolution": 1,
        "ReceiveCoilName": "HeadNeck_20",
        "ReceiveCoilActiveElements": "HEAD",
        "CoilCombinationMethod": "Sum of Squares",
        "MatrixCoilMode": "GRAPPA",
        "PercentPhaseFOV": 87.5,
        "PercentSampling": 100,
        "PhaseEncodingSteps": 179,
        "AcquisitionMatrixPE": 238,
        "ReconMatrixPE": 238,
        "ParallelReductionFactorInPlane": 2,
        "PixelBandwidth": 615,
        "DwellTime": 3e-06,
        "PhaseEncodingDirection": "i",
        "ImageOrientationPatientDICOM": [
            0.999397,
            -0.0347251,
            0,
            0.0347251,
            0.999397,
            0	],
        "ImageOrientationText": "Tra",
        "InPlanePhaseEncodingDirectionDICOM": "ROW",
    }

    return json_sidecar

def create_empty_dicom() -> Dataset:
    """Create a minimal DICOM object with basic metadata for testing."""
    
    # Create the main DICOM dataset
    ds = Dataset()
    dt = datetime.datetime.now()
    ds.ContentDate = dt.strftime("%Y%m%d")
    ds.ContentTime = dt.strftime("%H%M%S.%f")  # long format with micro seconds
    
    # Set a few required attributes to make it valid
    ds.PatientName = "Test^Patient"
    ds.PatientID = "123456"
    ds.StudyInstanceUID = "1.2.3.4.5.6.7.8.9.0"
    ds.SeriesInstanceUID = "1.2.3.4.5.6.7.8.9.1"
    ds.SOPInstanceUID = "1.2.3.4.5.6.7.8.9.2"
    ds.Modality = "MR"
    ds.SeriesNumber = "1"
    ds.InstanceNumber = "1"
    
    # Create file meta information
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = UID("1.2.840.10008.5.1.4.1.1.2")
    file_meta.MediaStorageSOPInstanceUID = UID("1.2.3")
    file_meta.ImplementationClassUID = UID("1.2.3.4")
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    
    # Attach file meta to dataset
    ds.file_meta = file_meta
    
    return ds


@pytest.fixture
def t1() -> Dataset:
    """Create a DICOM object with T1-weighted MRI metadata for testing."""

    ref_dicom = create_empty_dicom()
    
    # Set example attributes for T1-weighted MRI
    ref_dicom.SeriesDescription = "T1-weighted"
    ref_dicom.ProtocolName = "T1"
    ref_dicom.ScanningSequence = "GR"
    ref_dicom.SequenceVariant = "SP"
    ref_dicom.ScanOptions = "FS"
    ref_dicom.MRAcquisitionType = "3D"
    ref_dicom.RepetitionTime = "8.0"
    ref_dicom.EchoTime = "3.0"
    ref_dicom.InversionTime = "400.0"
    ref_dicom.FlipAngle = "15"
    ref_dicom.SAR = "0.1"
    ref_dicom.SliceThickness = "1.0"
    ref_dicom.SpacingBetweenSlices = "1.0"
    ref_dicom.PixelSpacing = ["0.5", "0.5"]
    ref_dicom.Rows = 256
    ref_dicom.Columns = 256
    ref_dicom.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    ref_dicom.ImagePositionPatient = ["-128", "-128", "0"]
    ref_dicom.Laterality = "R"
    ref_dicom.PatientPosition = "HFS"
    ref_dicom.BodyPartExamined = "BRAIN"
    ref_dicom.PatientOrientation = ["A", "P", "R", "L"]
    ref_dicom.AcquisitionMatrix = [256, 0, 0, 256]
    ref_dicom.InPlanePhaseEncodingDirection = "ROW"
    ref_dicom.EchoTrainLength = 1
    ref_dicom.PercentPhaseFieldOfView = "100"
    ref_dicom.AcquisitionContrast = "UNKNOWN"
    ref_dicom.PixelBandwidth = "200"
    ref_dicom.DeviceSerialNumber = "12345"
    ref_dicom.ImageType = ["ORIGINAL", "PRIMARY", "M", "ND"]

    # Set PixelData to a 10x10 array of random integers
    ref_dicom.Rows = 10
    ref_dicom.Columns = 10
    ref_dicom.BitsAllocated = 16
    ref_dicom.BitsStored = 16
    ref_dicom.HighBit = 15
    ref_dicom.PixelRepresentation = 0
    ref_dicom.PixelData = np.random.randint(0, 2**16, (10, 10)).astype(np.uint16).tobytes()

    return ref_dicom

