import datetime

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

