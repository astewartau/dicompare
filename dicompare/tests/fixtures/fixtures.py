import datetime
import pytest
import numpy as np

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID, ExplicitVRLittleEndian

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

