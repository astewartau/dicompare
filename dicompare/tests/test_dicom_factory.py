"""
Test DICOM factory for creating test DICOM files with pixel data.
"""

import tempfile
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian
import pydicom._storage_sopclass_uids


def create_test_dicom_file(
    file_path: str,
    rows: int = 64,
    columns: int = 64,
    pixel_data: Optional[np.ndarray] = None,
    metadata: Optional[Dict[str, Any]] = None,
    study_instance_uid: Optional[str] = None,
    series_instance_uid: Optional[str] = None
) -> str:
    """
    Create a test DICOM file with pixel data.
    
    Args:
        file_path: Path where to save the DICOM file
        rows: Number of rows in pixel data
        columns: Number of columns in pixel data  
        pixel_data: Custom pixel data array, if None creates random data
        metadata: Additional DICOM metadata tags
        study_instance_uid: Study UID to use, generates new one if None
        series_instance_uid: Series UID to use, generates new one if None
        
    Returns:
        Path to the created DICOM file
        
    Examples:
        >>> path = create_test_dicom_file('/tmp/test.dcm', metadata={'RepetitionTime': 2000})
        >>> ds = pydicom.dcmread(path)
        >>> ds.RepetitionTime
        2000
    """
    # Create pixel data if not provided
    if pixel_data is None:
        # Create random pixel data with some structure
        pixel_data = np.random.randint(0, 1000, size=(rows, columns), dtype=np.uint16)
        
        # Add some structured patterns to make it more realistic
        # Add a bright circle in the center
        center_y, center_x = rows // 2, columns // 2
        radius = min(rows, columns) // 4
        y, x = np.ogrid[:rows, :columns]
        mask = (x - center_x) ** 2 + (y - center_y) ** 2 <= radius ** 2
        pixel_data[mask] = np.random.randint(800, 1000, size=np.sum(mask))
    
    # Ensure pixel data is correct type and shape
    if len(pixel_data.shape) != 2:
        raise ValueError("Pixel data must be 2D array")
    
    if pixel_data.shape != (rows, columns):
        raise ValueError(f"Pixel data shape {pixel_data.shape} doesn't match specified dimensions ({rows}, {columns})")
    
    # Create basic DICOM dataset
    ds = Dataset()
    
    # File Meta Information
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom._storage_sopclass_uids.MRImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()
    file_meta.ImplementationVersionName = "TEST_DICOM_1.0"
    
    ds.file_meta = file_meta
    
    # Required Patient Information
    ds.PatientName = "Test^Patient"
    ds.PatientID = "TEST001"
    ds.PatientBirthDate = "19900101"
    ds.PatientSex = "M"
    
    # Required Study Information
    ds.StudyInstanceUID = study_instance_uid or generate_uid()
    ds.StudyDate = "20230101"
    ds.StudyTime = "120000"
    ds.StudyID = "1"
    ds.AccessionNumber = "ACC001"
    
    # Required Series Information
    ds.SeriesInstanceUID = series_instance_uid or generate_uid()
    ds.SeriesDate = "20230101"
    ds.SeriesTime = "120000"
    ds.SeriesNumber = 1
    ds.Modality = "MR"
    ds.SeriesDescription = "Test Series"
    
    # Required Instance Information
    ds.SOPClassUID = pydicom._storage_sopclass_uids.MRImageStorage
    ds.SOPInstanceUID = generate_uid()
    ds.InstanceNumber = 1
    ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "ND"]
    
    # Image specific metadata
    ds.Rows = rows
    ds.Columns = columns
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0  # unsigned
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PlanarConfiguration = 0  # Even though for monochrome, some viewers expect it
    
    # Add transfer syntax info to help pydicom interpret pixel data
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    
    # MR specific metadata (common defaults)
    ds.RepetitionTime = 2000.0
    ds.EchoTime = 10.0
    ds.FlipAngle = 30.0
    ds.SliceThickness = 5.0
    ds.PixelSpacing = [1.0, 1.0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0, 0, 0]
    ds.SliceLocation = 0.0
    ds.MagneticFieldStrength = 3.0
    
    # Add display/windowing parameters for proper visualization
    ds.RescaleIntercept = 0
    ds.RescaleSlope = 1
    ds.WindowCenter = 500
    ds.WindowWidth = 1000
    
    # Add custom metadata if provided
    if metadata:
        for key, value in metadata.items():
            setattr(ds, key, value)
    
    # Add pixel data
    pixel_bytes = pixel_data.tobytes()
    
    # Ensure even byte length (though uint16 should always be even)
    if len(pixel_bytes) % 2 != 0:
        pixel_bytes = pixel_bytes + b'\x00'
    
    ds.PixelData = pixel_bytes
    
    # Ensure the transfer syntax is properly set in file meta
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    
    # Save the file
    ds.save_as(file_path, write_like_original=False)
    
    return file_path


def create_test_dicom_series(
    base_dir: str,
    acquisition_name: str,
    num_slices: int = 3,
    rows: int = 64,
    columns: int = 64,
    metadata_base: Optional[Dict[str, Any]] = None,
    varying_fields: Optional[Dict[str, list]] = None
) -> Tuple[list, Dict[str, bytes]]:
    """
    Create a series of test DICOM files.
    
    Args:
        base_dir: Base directory for DICOM files
        acquisition_name: Name of the acquisition
        num_slices: Number of slices to create
        rows: Image height
        columns: Image width  
        metadata_base: Base metadata for all slices
        varying_fields: Fields that vary across slices
        
    Returns:
        Tuple of (file_paths, dicom_bytes_dict)
        
    Examples:
        >>> paths, bytes_dict = create_test_dicom_series(
        ...     '/tmp', 'T1_MPRAGE', 
        ...     varying_fields={'InstanceNumber': [1, 2, 3]}
        ... )
        >>> len(paths)
        3
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    
    file_paths = []
    dicom_bytes = {}
    
    # Generate shared UIDs for this series - all slices will belong to same study and series
    study_uid = generate_uid()
    # Check if series UID is provided in metadata_base, otherwise generate one
    if metadata_base and 'SeriesInstanceUID' in metadata_base:
        series_uid = metadata_base['SeriesInstanceUID']
    else:
        series_uid = generate_uid()
    
    # Set up base metadata
    base_metadata = {
        'SeriesDescription': acquisition_name,
        'ProtocolName': acquisition_name,
    }
    if metadata_base:
        base_metadata.update(metadata_base)
    
    # Create each slice
    for i in range(num_slices):
        # Create slice-specific metadata
        slice_metadata = base_metadata.copy()
        slice_metadata['InstanceNumber'] = i + 1
        slice_metadata['SliceLocation'] = i * 5.0  # 5mm spacing
        slice_metadata['ImagePositionPatient'] = [0, 0, i * 5.0]
        
        # Add varying fields if specified
        if varying_fields:
            for field, values in varying_fields.items():
                if i < len(values):
                    slice_metadata[field] = values[i]
        
        # Create unique pixel data for each slice
        pixel_data = np.random.randint(0, 1000, size=(rows, columns), dtype=np.uint16)
        
        # Add slice-specific pattern
        pixel_data[i*5:(i+1)*5, :] = 800 + i * 50  # Horizontal bands
        
        # Create file
        file_path = base_dir / f"{acquisition_name}_slice_{i+1:03d}.dcm"
        
        # Use series UID from slice metadata if it was set via varying_fields, otherwise use shared series UID
        slice_series_uid = slice_metadata.get('SeriesInstanceUID', series_uid)
        
        create_test_dicom_file(
            str(file_path), 
            rows, 
            columns, 
            pixel_data, 
            slice_metadata,
            study_instance_uid=study_uid,
            series_instance_uid=slice_series_uid
        )
        
        file_paths.append(str(file_path))
        
        # Read file back as bytes for testing
        with open(file_path, 'rb') as f:
            dicom_bytes[str(file_path)] = f.read()
    
    return file_paths, dicom_bytes


def create_multi_echo_series(
    base_dir: str,
    acquisition_name: str,
    echo_times: list = [0.01, 0.02, 0.03],
    num_slices_per_echo: int = 2,
    rows: int = 64,
    columns: int = 64
) -> Tuple[list, Dict[str, bytes]]:
    """
    Create a multi-echo DICOM series.
    
    Args:
        base_dir: Base directory
        acquisition_name: Acquisition name
        echo_times: List of echo times
        num_slices_per_echo: Number of slices per echo time
        rows: Image height
        columns: Image width
        
    Returns:
        Tuple of (file_paths, dicom_bytes_dict)
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    
    all_paths = []
    all_bytes = {}
    
    for echo_idx, echo_time in enumerate(echo_times):
        # Create series UID for this echo time
        series_uid = generate_uid()
        
        varying_fields = {
            'EchoTime': [echo_time] * num_slices_per_echo,
            'SeriesInstanceUID': [series_uid] * num_slices_per_echo,
            'SeriesNumber': [echo_idx + 1] * num_slices_per_echo
        }
        
        metadata_base = {
            'SeriesDescription': f"{acquisition_name}_Echo{echo_idx+1}",
            'ProtocolName': acquisition_name,
        }
        
        paths, bytes_dict = create_test_dicom_series(
            base_dir / f"echo_{echo_idx+1}",
            f"{acquisition_name}_echo{echo_idx+1}",
            num_slices_per_echo,
            rows, columns,
            metadata_base,
            varying_fields
        )
        
        all_paths.extend(paths)
        all_bytes.update(bytes_dict)
    
    return all_paths, all_bytes


class DicomTestFactory:
    """Factory class for creating test DICOM files with common configurations."""
    
    def __init__(self, temp_dir: Optional[str] = None):
        """Initialize factory with temporary directory."""
        if temp_dir is None:
            self.temp_dir = tempfile.mkdtemp()
        else:
            self.temp_dir = temp_dir
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)
    
    def create_t1_mprage(self, num_slices: int = 3) -> Tuple[list, Dict[str, bytes]]:
        """Create T1 MPRAGE series."""
        metadata = {
            'RepetitionTime': 2000.0,
            'EchoTime': 2.46,
            'FlipAngle': 9.0,
            'SliceThickness': 1.0,
            'AcquisitionMatrix': [0, 64, 64, 0],  # Frequency\\Phase\\Phase\\Frequency
            'PixelSpacing': [0.9, 0.9]
        }
        
        return create_test_dicom_series(
            self.temp_dir, 'T1_MPRAGE', num_slices,
            metadata_base=metadata
        )
    
    def create_t2_flair(self, num_slices: int = 2) -> Tuple[list, Dict[str, bytes]]:
        """Create T2 FLAIR series."""
        metadata = {
            'RepetitionTime': 9000.0,
            'EchoTime': 85.0,
            'FlipAngle': 150.0,
            'SliceThickness': 3.0,
            'AcquisitionMatrix': [0, 64, 64, 0],  # Frequency\\Phase\\Phase\\Frequency
            'PixelSpacing': [0.7, 0.7]
        }
        
        return create_test_dicom_series(
            self.temp_dir, 'T2_FLAIR', num_slices,
            metadata_base=metadata
        )
    
    def create_bold_fmri(self, num_echo_times: int = 3) -> Tuple[list, Dict[str, bytes]]:
        """Create multi-echo BOLD fMRI series."""
        echo_times = [0.03, 0.06, 0.09][:num_echo_times]
        
        return create_multi_echo_series(
            self.temp_dir, 'BOLD_fMRI', echo_times, 
            num_slices_per_echo=2
        )
    
    def cleanup(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)


# For backwards compatibility
TestDicomFactory = DicomTestFactory

# Example usage for tests
if __name__ == "__main__":
    # Create a test factory
    factory = DicomTestFactory()
    
    # Create some test series
    t1_paths, t1_bytes = factory.create_t1_mprage()
    print(f"Created T1 MPRAGE: {len(t1_paths)} files")
    
    t2_paths, t2_bytes = factory.create_t2_flair()  
    print(f"Created T2 FLAIR: {len(t2_paths)} files")
    
    bold_paths, bold_bytes = factory.create_bold_fmri()
    print(f"Created BOLD fMRI: {len(bold_paths)} files")
    
    # Test reading one
    import pydicom
    ds = pydicom.dcmread(t1_paths[0])
    print(f"T1 RepetitionTime: {ds.RepetitionTime}")
    print(f"T1 pixel array shape: {ds.pixel_array.shape}")
    
    # Cleanup
    factory.cleanup()