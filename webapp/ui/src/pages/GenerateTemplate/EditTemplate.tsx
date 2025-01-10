import React, { useState } from "react";
import {
  Box,
  Heading,
  Text,
  VStack,
  Collapse,
  Button,
  HStack,
  Divider,
  useDisclosure,
} from "@chakra-ui/react";

import CollapsibleCard from "../../components/CollapisbleCard";

const EditTemplate = () => {
  const mockProtocols = [
    {
      ProtocolName: "QSM_p2_1mmIso_TE20",
      dicomData: [
        { key: "Series Description", value: "QSM_p2_1mmIso_TE20" },
        { key: "Modality", value: "MRI" },
        { key: "Patient ID", value: "12345" },
      ],
    },
    {
      ProtocolName: "T1w_MPRAGE",
      dicomData: [
        { key: "Series Description", value: "T1-weighted anatomical" },
        { key: "Modality", value: "MRI" },
        { key: "Patient ID", value: "67890" },
      ],
    },
    {
      ProtocolName: "fMRI_Task",
      dicomData: [
        { key: "Series Description", value: "Functional task imaging" },
        { key: "Modality", value: "fMRI" },
        { key: "Patient ID", value: "54321" },
      ],
    },
  ];

  return (
    <Box p={8}>
      {/* Heading */}
      <Heading as="h1" size="2xl" color="teal.600" mb={6}>
        Edit Template
      </Heading>

      {/* Description */}
      <Text fontSize="xl" mb={8} color="gray.700">
        Modify the protocols and their associated DICOM data in the template.
      </Text>

      {/* Collapsible Cards */}
      <VStack spacing={6} align="stretch">
        {mockProtocols.map((protocol, index) => (
          <CollapsibleCard key={index} protocol={protocol} />
        ))}
      </VStack>
    </Box>
  );
};



export default EditTemplate;
