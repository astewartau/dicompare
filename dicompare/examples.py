"""
Synthetic example sessions for trying dicompare without data of your own.

``write_multisite_example`` writes two small sessions of a numerical phantom:
a reference site that runs a protocol as intended, and a second site that has
drifted from it. The tutorial notebook in ``examples/`` uses them. Every file
is synthetic; no real or patient data is involved.
"""

import os
from pathlib import Path
from typing import Dict, Optional, Sequence, Union

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

_COMMON = dict(MRAcquisitionType="3D", NumberOfAverages=1, PixelBandwidth=200, ReceiveCoilName="HeadNeck_64")
_T1 = dict(_COMMON, SeriesNumber=2, ScanningSequence=["GR", "IR"], RepetitionTime=2400, EchoTime=2.14,
           InversionTime=1000, FlipAngle=8, SliceThickness=0.8)
_QSM = dict(_COMMON, SeriesNumber=3, ScanningSequence="GR", RepetitionTime=30, FlipAngle=12, SliceThickness=1.0)
_FLAIR = dict(_COMMON, SeriesNumber=4, ScanningSequence=["SE", "IR"], RepetitionTime=5000, EchoTime=390,
              InversionTime=1800, FlipAngle=120, SliceThickness=1.0)
_QSM_ECHO_TIMES = [4.0, 10.0, 16.0, 22.0, 28.0]


def _phantom(n: int, slice_index: int, nslices: int) -> np.ndarray:
    """A head-shaped ellipsoid with two 'ventricles', scaled to 12 bits."""
    y, x = np.mgrid[-1:1:n * 1j, -1:1:n * 1j]
    z = (slice_index - (nslices - 1) / 2) / nslices * 0.4
    head = (x / 0.75) ** 2 + (y / 0.9) ** 2 + z ** 2
    img = np.where(head < 1.0, 0.55, 0.0)
    img = np.where(head < 0.8, 0.8, img)
    ventricles = ((np.abs(x) - 0.12) / 0.08) ** 2 + (y / 0.3) ** 2
    img = np.where((head < 0.8) & (ventricles < 1.0), 0.35, img)
    return (img * 4000).astype("<u2")


def _write_acquisition(
    site_dir: Path,
    protocol: str,
    params: dict,
    pixel_spacing: float,
    echo_times: Sequence[Optional[float]] = (None,),
    image_types: Sequence[str] = ("M",),
    nslices: int = 2,
    n: int = 64,
) -> None:
    """Write one acquisition: one file per image type x echo x slice."""
    out = site_dir / protocol
    out.mkdir(parents=True, exist_ok=True)
    site = site_dir.name
    for itype in image_types:
        series_uid = generate_uid(entropy_srcs=[site, protocol, itype])
        for echo, te in enumerate(echo_times, start=1):
            for k in range(nslices):
                ds = Dataset()
                ds.SOPClassUID = MRImageStorage
                ds.SOPInstanceUID = generate_uid(entropy_srcs=[site, protocol, itype, str(echo), str(k)])
                ds.StudyInstanceUID = generate_uid(entropy_srcs=[site])
                ds.SeriesInstanceUID = series_uid
                ds.Modality, ds.Manufacturer, ds.MagneticFieldStrength = "MR", "SIEMENS", 3
                ds.PatientName, ds.PatientID = "Synthetic^Phantom", f"PHANTOM-{site}"
                ds.StudyDate = ds.SeriesDate = "20260101"
                ds.SeriesTime = "090000"
                ds.ProtocolName = ds.SeriesDescription = protocol
                ds.InstanceNumber = (echo - 1) * nslices + k + 1
                ds.ImageType = ["ORIGINAL", "PRIMARY", itype]
                for key, value in params.items():
                    setattr(ds, key, value)
                if te is not None:
                    ds.EchoTime, ds.EchoNumbers = te, echo
                ds.PixelSpacing = [pixel_spacing, pixel_spacing]
                ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                ds.ImagePositionPatient = [0, 0, k * params["SliceThickness"]]
                ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
                ds.Rows = ds.Columns = n
                ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
                ds.PixelData = _phantom(n, k, nslices).tobytes()
                ds.file_meta = FileMetaDataset()
                ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
                ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                path = out / f"{itype}_echo{echo}_slice{k + 1}.dcm"
                if int(pydicom.__version__.split(".")[0]) >= 3:  # pragma: no cover - dicompare pins pydicom 2
                    pydicom.dcmwrite(path, ds, enforce_file_format=True)
                else:
                    ds.is_little_endian, ds.is_implicit_VR = True, False
                    pydicom.dcmwrite(path, ds, write_like_original=False)


def write_multisite_example(dest: Union[str, os.PathLike] = "dicompare_example_data") -> Dict[str, Path]:
    """
    Write two synthetic sessions of one protocol, for trying dicompare.

    The protocol has a 3D T1-weighted MPRAGE, a five-echo 3D GRE for QSM
    (magnitude and phase) and a 3D T2-weighted FLAIR. Each volume is a 64 x 64
    phantom with two slices per echo, so the whole set is about 600 KB.

    - ``site_A`` runs the protocol as intended.
    - ``site_B`` has drifted: its T1 has TR 2300 ms instead of 2400, TE
      2.98 ms instead of 2.14 and 1 mm voxels instead of 0.8 mm; its QSM has
      2 mm slices instead of 1 mm; it has no FLAIR; and its protocols have
      different names (``t1_mprage_sag``, ``gre_qsm_5echo``).

    Writing again to the same folder overwrites the files with identical ones.

    Args:
        dest: Folder to write into. It is created if needed.

    Returns:
        Dict[str, Path]: ``{"site_A": path, "site_B": path}``, the folder of
        each session.

    Example:
        >>> sites = write_multisite_example("example_data")
        >>> results = check_session(sites["site_B"], build_schema(load_dicom_session(sites["site_A"])))
    """
    dest = Path(dest)
    site_a, site_b = dest / "site_A", dest / "site_B"

    _write_acquisition(site_a, "T1w_MPR", _T1, pixel_spacing=0.8)
    _write_acquisition(site_a, "QSM_ME_GRE", _QSM, pixel_spacing=1.0,
                       echo_times=_QSM_ECHO_TIMES, image_types=("M", "P"))
    _write_acquisition(site_a, "T2w_FLAIR", _FLAIR, pixel_spacing=1.0)

    _write_acquisition(site_b, "t1_mprage_sag", dict(_T1, RepetitionTime=2300, EchoTime=2.98, SliceThickness=1.0),
                       pixel_spacing=1.0)
    _write_acquisition(site_b, "gre_qsm_5echo", dict(_QSM, SliceThickness=2.0), pixel_spacing=1.0,
                       echo_times=_QSM_ECHO_TIMES, image_types=("M", "P"))

    return {"site_A": site_a, "site_B": site_b}
