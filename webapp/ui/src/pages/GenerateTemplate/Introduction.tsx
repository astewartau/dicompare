import React from 'react';
import {
  Box,
  Heading,
  Text,
  VStack,
  FormControl,
  FormLabel,
  Input,
  Textarea,
  FormHelperText,
  Button,
} from '@chakra-ui/react';

const Introduction = ({ onNext }) => {
  return (
    <Box width="100%">
      {/* Walkthrough Heading and Description */}
      <VStack align="start" spacing={6}>
        <Heading size="xl" color="teal.600">
          Introduction
        </Heading>
        <Text fontSize="md" color="gray.700">
          Let’s start by creating a template. Please provide a name, description, and authors for the template. This will help identify and describe the purpose of the template.
        </Text>
      </VStack>

      {/* Form Section */}
      <VStack as="form" spacing={6} marginTop={8}>
        {/* Template Name */}
        <FormControl id="template-name" isRequired>
          <Text fontSize='3xl' fontWeight="bold">Template Name</Text>
          <FormHelperText fontSize='lg'>Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.</FormHelperText>
          <Input
            placeholder="Enter template name"
            focusBorderColor="teal.500"
            size='lg'
            variant='filled'
            mt={5}
          />

        </FormControl>

        {/* Template Description */}
        <FormControl id="template-description">
        <Text fontSize='3xl' fontWeight="bold">Template Description</Text>
        <FormHelperText fontSize='lg' mr='50'>
            Describe the purpose and scope of this template, e.g., "Ensures DICOM compliance for MRI imaging."
        </FormHelperText>
          <Textarea
            placeholder="Enter a short description of the template"
            focusBorderColor="teal.500"
            mt={5}
          />
        </FormControl>

        {/* Authors */}
        <FormControl id="authors">
          <Text fontSize='3xl' fontWeight="bold">Authors</Text>
          <FormHelperText fontSize='lg'>
            Specify the authors who created this template, e.g., "Dr. John Doe, Jane Smith."
          </FormHelperText>
          <Input
            placeholder="Enter authors (comma-separated)"
            focusBorderColor="teal.500"
            size='lg'
            variant='filled'
            mt={5}
          />
        </FormControl>

        Navigation Button
        <Button
          colorScheme="teal"
          width="100%"
          size="lg"
          onClick={onNext}
        >
          Next
        </Button>
      </VStack>
    </Box>
  );
};

export default Introduction;
