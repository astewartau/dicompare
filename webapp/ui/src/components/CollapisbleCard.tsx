import React from "react";
import {
  Box,
  Heading,
  HStack,
  Button,
  Collapse,
  Divider,
  VStack,
  Text,
  useDisclosure,
} from "@chakra-ui/react";

const CollapsibleCard = ({ protocol }) => {
  const { isOpen, onToggle } = useDisclosure();

  return (
    <Box
      p={4}
      borderWidth="1px"
      borderRadius="md"
      bg="white"
      boxShadow="sm"
      width="100%"
    >
      {/* Protocol Name Header */}
      <HStack justify="space-between">
        <Heading as="h3" size="md" color="teal.500">
          {protocol.ProtocolName}
        </Heading>
        <Button size="sm" onClick={onToggle} colorScheme="teal">
          {isOpen ? "Collapse" : "Expand"}
        </Button>
      </HStack>

      {/* Collapsible Content */}
      <Collapse in={isOpen} animateOpacity>
        <Divider my={4} />
        <VStack align="start" spacing={2}>
          {protocol.dicomData.map((item, index) => (
            <HStack key={index} justify="space-between" width="100%">
              <Text fontWeight="bold" fontSize="sm" color="gray.600">
                {item.key}:
              </Text>
              <Text fontSize="sm" color="gray.800">
                {item.value}
              </Text>
            </HStack>
          ))}
        </VStack>
      </Collapse>
    </Box>
  );
};

export default CollapsibleCard;
