import React, { useEffect, useState } from "react";
import {
  Box,
  Heading,
  Text,
  Button,
  VStack,
  Code,
  useToast,
} from "@chakra-ui/react";
import { saveAs } from "file-saver";

const Review = () => {
  const [jsonData, setJsonData] = useState(null);
  const toast = useToast();

  useEffect(() => {
    // Load the JSON file
    const fetchJson = async () => {
      try {
        const response = await fetch("/src/assets/example/generatedTemplate.json");
        const data = await response.json();
        setJsonData(data);
      } catch (error) {
        console.error("Error loading JSON file:", error);
        toast({
          title: "Error",
          description: "Unable to load the JSON file.",
          status: "error",
          duration: 3000,
          isClosable: true,
        });
      }
    };

    fetchJson();
  }, [toast]);

  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(jsonData, null, 2)], {
      type: "application/json",
    });
    saveAs(blob, "generatedTemplate.json");
  };

  return (
    <Box p={8}>
      <Heading as="h1" size="xl" color="teal.600" mb={6}>
        Review Template
      </Heading>

      {jsonData ? (
        <>
          <Text fontSize="lg" color="gray.700" mb={4}>
            Below is the generated template JSON file   <Button colorScheme="teal" onClick={handleDownload}>
              Download
            </Button>
          </Text>
          <Box
            p={4}
            borderWidth="1px"
            borderRadius="md"
            bg="black"
            overflow="auto"
            maxWidth="100%"
            maxHeight="800px"
            boxShadow="lg"
            >
            <Code
                as="pre"
                fontSize="md"
                color="green.300"
                bg="transparent"
                whiteSpace="pre-wrap"
                wordBreak="break-word"
            >
                {JSON.stringify(jsonData, null, 2)}
            </Code>
            </Box>
        </>
      ) : (
        <Text fontSize="lg" color="black.700">
          Loading JSON data...
        </Text>
      )}
    </Box>
  );
};

export default Review;
