import React from "react";
import VerticalStepper from "../../components/Stepper";
import Introduction from "./Introduction";
import NavigationBar from "../../components/NavigationBar";
import { Box, Flex } from "@chakra-ui/react";
import DICOMAnalysis from "./DicomAnalysis";
import EditTemplate from "./EditTemplate";

const GenerateTemplate = () => {
  const steps = [
    { title: "Introduction", component: <Introduction onNext={() => {}} /> },
    { title: "Dicom Analysis", component: <DICOMAnalysis onNext={() => {}} /> },
    { title: "Edit Template", component: <EditTemplate onNext={() => {}} /> },
  ];

  return (
    <>
      {/* Navigation Bar */}
      <Box position="sticky" top="0" zIndex="100">
        <NavigationBar />
      </Box>
        <VerticalStepper steps={steps} />
    </>
  );
};

export default GenerateTemplate;
