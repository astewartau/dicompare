import React, { useEffect, useState } from "react";
import {
  Box,
  Heading,
  Text,
  VStack,
} from "@chakra-ui/react";

import CollapsibleCard from "../../components/CollapisbleCard";

const EditTemplate = () => {
  const [validFields, setValidFields] = useState([]);
  const mockProtocols = [
    {
      ProtocolName: "QSM_p2_1mmIso_TE20",
      dicomData: [
        { key: "Series Description", value: "QSM_p2_1mmIso_TE20" },
        { key: "Modality", value: "MRI" },
        { key: "Patient ID", value: "12345" },
        { key: "Study Date", value: "2023-01-01" },
        { key: "Institution Name", value: "Medical Imaging Center" },
      ],
    },
    {
      ProtocolName: "T1w_MPRAGE",
      dicomData: [
        { key: "Series Description", value: "T1-weighted anatomical" },
        { key: "Modality", value: "MRI" },
        { key: "Patient ID", value: "67890" },
        { key: "Study Date", value: "2023-02-15" },
        { key: "Institution Name", value: "NeuroScan Institute" },
      ],
    },
    {
      ProtocolName: "fMRI_Task",
      dicomData: [
        { key: "Series Description", value: "Functional task imaging" },
        { key: "Modality", value: "fMRI" },
        { key: "Patient ID", value: "54321" },
        { key: "Study Date", value: "2023-03-10" },
        { key: "Institution Name", value: "Brain Research Lab" },
      ],
    },
    {
      ProtocolName: "DTI_64Directions",
      dicomData: [
        { key: "Series Description", value: "Diffusion Tensor Imaging - 64 directions" },
        { key: "Modality", value: "DTI" },
        { key: "Patient ID", value: "11223" },
        { key: "Study Date", value: "2023-04-05" },
        { key: "Institution Name", value: "Advanced Imaging Center" },
      ],
    },
    {
      ProtocolName: "T2w_FLAIR",
      dicomData: [
        { key: "Series Description", value: "T2-weighted Fluid-Attenuated Inversion Recovery" },
        { key: "Modality", value: "MRI" },
        { key: "Patient ID", value: "33445" },
        { key: "Study Date", value: "2023-05-20" },
        { key: "Institution Name", value: "Imaging Diagnostics Facility" },
      ],
    },
    {
      ProtocolName: "ASL_Perfusion",
      dicomData: [
        { key: "Series Description", value: "Arterial Spin Labeling Perfusion Imaging" },
        { key: "Modality", value: "MRI" },
        { key: "Patient ID", value: "77889" },
        { key: "Study Date", value: "2023-06-12" },
        { key: "Institution Name", value: "Perfusion Imaging Lab" },
      ],
    },
    {
      ProtocolName: "MRA_CircleOfWillis",
      dicomData: [
        { key: "Series Description", value: "Magnetic Resonance Angiography - Circle of Willis" },
        { key: "Modality", value: "MRA" },
        { key: "Patient ID", value: "99112" },
        { key: "Study Date", value: "2023-07-08" },
        { key: "Institution Name", value: "Vascular Imaging Center" },
      ],
    },
    {
      ProtocolName: "Cardiac_Cine",
      dicomData: [
        { key: "Series Description", value: "Cardiac Cine Imaging" },
        { key: "Modality", value: "MRI" },
        { key: "Patient ID", value: "66778" },
        { key: "Study Date", value: "2023-08-18" },
        { key: "Institution Name", value: "Cardiac Imaging Lab" },
      ],
    },
    {
      ProtocolName: "PET_CT_FDG",
      dicomData: [
        { key: "Series Description", value: "Positron Emission Tomography with FDG tracer" },
        { key: "Modality", value: "PET/CT" },
        { key: "Patient ID", value: "44567" },
        { key: "Study Date", value: "2023-09-21" },
        { key: "Institution Name", value: "Oncology Imaging Center" },
      ],
    },
  ];


  useEffect(() => {
    const fetchFields = async () => {
      try {
        const response = await fetch(
          "https://raw.githubusercontent.com/astewartau/dicompare/v0.1.12/valid_fields.json"
        );
        const fields = await response.json();
        setValidFields(fields);
      } catch (error) {
        console.error("Failed to fetch valid fields", error);
      }
    };

    fetchFields();
  }, []);

  return (
    <Box p={8}>
      {/* Heading */}
      <Heading as="h1" size="2xl" color="teal.600" mb={6}>
        Generate Template
      </Heading>

      {/* Description */}
      <Text fontSize="xl" mb={8} color="gray.700">
        Modify the protocols and their associated DICOM data in the template.
      </Text>

      {/* Collapsible Cards */}
      <VStack spacing={6} width={"200%"}>
        {mockProtocols.map((protocol, index) => (
          <CollapsibleCard key={index} protocol={protocol} validFields={validFields} />
        ))}
      </VStack>
    </Box>
  );
};

export default EditTemplate;
