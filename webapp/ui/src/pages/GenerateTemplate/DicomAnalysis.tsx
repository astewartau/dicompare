import React, { useState, useEffect } from "react";
import {
  Box,
  Heading,
  Text,
  Button,
  VStack,
  Progress,
  Input,
  HStack,
  Checkbox,
} from "@chakra-ui/react";

const DICOMAnalysis = () => {
  const [fileCount, setFileCount] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [sessions, setSessions] = useState([]);
  const [processingComplete, setProcessingComplete] = useState(false);

  const mockSessions = [
    {
      ProtocolName: "QSM_p2_1mmIso_TE20",
      SeriesDescription: "QSM_p2_1mmIso_TE20",
      TotalFiles: "100 files",
    },
    {
      ProtocolName: "T1w_MPRAGE",
      SeriesDescription: "T1-weighted anatomical",
      TotalFiles: "75 files",
    },
    {
      ProtocolName: "fMRI_Task",
      SeriesDescription: "Functional task imaging",
      TotalFiles: "120 files",
    },
    {
      ProtocolName: "DTI_64dir",
      SeriesDescription: "Diffusion tensor imaging",
      TotalFiles: "80 files",
    },
    {
      ProtocolName: "ASL",
      SeriesDescription: "Arterial spin labeling",
      TotalFiles: "50 files",
    },
  ];

  const handleFileUpload = (event) => {
    const files = event.target.files;
    const dcmFiles = Array.from(files).filter((file) =>
      file.name.endsWith(".dcm")
    );

    setFileCount(dcmFiles.length);
    setProcessing(true);
    setProgress(0);
    setProcessingComplete(false);
  };

  const startProcessing = () => {
    let progressInterval = 0;
    const interval = setInterval(() => {
      progressInterval += 1;
      setProgress(progressInterval * 3.33); // Update progress every second for 30 seconds
      if (progressInterval === 30) {
        clearInterval(interval);
        setProcessing(false);
        setProcessingComplete(true);
        setSessions(mockSessions);
      }
    }, 1000);
  };

  useEffect(() => {
    if (processing) {
      startProcessing();
    }
  }, [processing]);

  return (
    <Box p={6} maxW="container.md" mx="auto">
      {/* Main Heading */}
      <Heading as="h1" size="xl" color="teal.600" mb={4}>
        DICOM Analysis
      </Heading>

      {/* Description */}
      <Text fontSize="lg" mb={6} color="gray.700">
        Analyze your DICOM files locally with privacy-first processing.
      </Text>

      {!processingComplete ? (
        <>
          {/* Subheading */}
          <Heading as="h2" size="md" mb={2} color="teal.500">
            Choose Session DICOMS
          </Heading>
          <Text fontSize="sm" color="gray.600" mb={4}>
            Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do
            eiusmod tempor incididunt ut labore.
          </Text>

          {/* File Upload */}
          <VStack spacing={4} align="start">
            <HStack>
              <Input
                type="file"
                accept=".dcm"
                multiple
                display="none"
                id="file-upload"
                onChange={handleFileUpload}
              />
              <Button as="label" htmlFor="file-upload" colorScheme="teal">
                Browse
              </Button>
              <Text fontSize="sm" color="gray.600">
                {fileCount > 0
                  ? `${fileCount} DICOM files selected`
                  : "No files selected"}
              </Text>
            </HStack>

            {/* Progress Bar */}
            {processing && (
              <Box width="100%">
                <Text fontSize="md" as="b" mb={2} color="gray.700">
                  Processing locally...
                </Text>
                <Progress value={progress} size="sm" colorScheme="teal" />
                <Text fontSize="sm" mt={2} color="teal.600">
                  {Math.round(progress)}% Complete
                </Text>
              </Box>
            )}
          </VStack>
        </>
      ) : (
        <>
          {/* Sessions Found */}
          <Heading as="h2" size="md" mb={2} color="teal.500">
            Sessions Found
          </Heading>
          <Text fontSize="sm" color="gray.600" mb={4}>
            Below are the sessions found in the uploaded DICOM files. Select the
            ones you wish to analyze.
          </Text>

          {/* Sessions List */}
          <VStack align="stretch" spacing={4}>
            {sessions.map((session, index) => (
              <Box
                key={index}
                p={4}
                borderWidth="1px"
                borderRadius="md"
                bg="gray.50"
                boxShadow="sm"
              >
                <HStack>
                  <Checkbox colorScheme="teal" size="lg" />
                  <Text fontSize="md" fontWeight="bold">
                    {session.ProtocolName}
                  </Text>
                </HStack>
                <VStack align="start" mt={2} pl={6}>
                  <Text fontSize="sm">
                    <b>Series Description:</b> {session.SeriesDescription}
                  </Text>
                  <Text fontSize="sm">
                    <b>Total Files:</b> {session.TotalFiles}
                  </Text>
                </VStack>
              </Box>
            ))}
          </VStack>
        </>
      )}
    </Box>
  );
};

export default DICOMAnalysis;
