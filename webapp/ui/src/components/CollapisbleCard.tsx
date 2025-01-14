import React, { useState } from "react";
import {
  Box,
  Heading,
  HStack,
  Button,
  Collapse,
  Divider,
  VStack,
  Text,
  Input,
  IconButton,
  useDisclosure,
} from "@chakra-ui/react";
import Select from "react-select";
import { CloseIcon } from "@chakra-ui/icons";

const CollapsibleCard = ({ protocol, validFields }) => {
  const { isOpen, onToggle } = useDisclosure();
  const [selectedField, setSelectedField] = useState(null);
  const [inputType, setInputType] = useState("Value");
  const [newFieldValue, setNewFieldValue] = useState("");
  const [rangeValue, setRangeValue] = useState({ min: "", max: "" });
  const [toleranceValue, setToleranceValue] = useState({ value: "", tolerance: "" });
  const [containsValue, setContainsValue] = useState("");
  const [dicomData, setDicomData] = useState(protocol.dicomData);

  const handleAddField = () => {
    if (selectedField) {
      let value;
      if (inputType === "Value") {
        value = newFieldValue;
      } else if (inputType === "Range") {
        value = `Range: ${rangeValue.min} - ${rangeValue.max}`;
      } else if (inputType === "Value and Tolerance") {
        value = `Value: ${toleranceValue.value}, Tolerance: ±${toleranceValue.tolerance}`;
      } else if (inputType === "Contains") {
        value = `Contains: ${containsValue}`;
      }

      if (value) {
        setDicomData([
          ...dicomData,
          { key: selectedField.value, value },
        ]);
        setSelectedField(null);
        setNewFieldValue("");
        setRangeValue({ min: "", max: "" });
        setToleranceValue({ value: "", tolerance: "" });
        setContainsValue("");
        setInputType("Value");
      }
    }
  };

  const handleRemoveField = (index) => {
    setDicomData(dicomData.filter((_, i) => i !== index));
  };

  const handleClearInputs = () => {
    setSelectedField(null);
    setNewFieldValue("");
    setRangeValue({ min: "", max: "" });
    setToleranceValue({ value: "", tolerance: "" });
    setContainsValue("");
    setInputType("Value");
  };

  const fieldOptions = validFields.map((field) => ({
    value: field,
    label: field,
  }));

  const inputTypeOptions = [
    { value: "Value", label: "Value" },
    { value: "Range", label: "Range" },
    { value: "Value and Tolerance", label: "Value and Tolerance" },
    { value: "Contains", label: "Contains" },
  ];

  return (
    <Box
      p={4}
      borderWidth="1px"
      borderRadius="md"
      bg="white"
      boxShadow="sm"
      width="100%"
      maxWidth="100%" // Prevents growing beyond 600px
      minWidth="100%" // Prevents shrinking below 400px
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

        {/* Display Existing DICOM Data */}
        <VStack align="start" spacing={2} maxHeight={200} overflowY="auto">
          {dicomData.map((item, index) => (
            <HStack key={index} justify="space-between" width="100%">
              <HStack>
                <Text fontWeight="bold" fontSize="md" color="gray.600">
                  {item.key}:
                </Text>
                <Text fontSize="md" color="gray.800">
                  {item.value}
                </Text>
              </HStack>
              <IconButton
                icon={<CloseIcon />}
                size="xs"
                colorScheme="red"
                onClick={() => handleRemoveField(index)}
              />
            </HStack>
          ))}
        </VStack>

        {/* Add New Field Section */}
        <Divider my={4} />
        <VStack align="start" spacing={4} width="100%">
          <Select
            options={fieldOptions}
            value={selectedField}
            onChange={(selectedOption) => setSelectedField(selectedOption)}
            placeholder="Search or select field"
            isSearchable
            styles={{
              container: (provided) => ({
                ...provided,
                width: "100%", // Full width for the container
                zIndex: 9999, // Ensure the dropdown is above other elements
              }),
              control: (provided) => ({
                ...provided,
                width: "100%", // Full width for the control (input and dropdown)
              }),
              menu: (provided) => ({
                ...provided,
                zIndex: 9999, // Ensure the menu renders above other elements
              }),
              menuPortal: (provided) => ({
                ...provided,
                zIndex: 9999, // Ensure the menu portal renders above any parent container
              }),
            }}
            menuPortalTarget={document.body} // Renders the dropdown in a portal outside parent containers
          />
          <Select
            options={inputTypeOptions}
            value={inputTypeOptions.find((option) => option.value === inputType)}
            onChange={(selectedOption) => setInputType(selectedOption.value)}
            placeholder="Select input type"
            isSearchable
            width="80%"
            styles={{
              container: (provided) => ({
                ...provided,
                width: "100%", // Full width for the container
              }),
              control: (provided) => ({
                ...provided,
                width: "100%", // Full width for the control (input and dropdown)
              }),
              menu: (provided) => ({
                ...provided,
                zIndex: 9999, // Ensure the menu renders above other elements
              }),
              menuPortal: (provided) => ({
                ...provided,
                zIndex: 9999, // Ensure the menu portal renders above any parent container
              }),
            }}
            menuPortalTarget={document.body} // Renders the dropdown in a portal outside parent containers
          />
          <HStack width="100%">
          {inputType === "Value" && (
          <Input
            placeholder="Enter value"
            value={newFieldValue}
            onChange={(e) => setNewFieldValue(e.target.value)}
            width="100%"
          />
        )}

        {inputType === "Range" && (
          <HStack width="100%">
            <Input
              placeholder="Min value"
              value={rangeValue.min}
              onChange={(e) => setRangeValue({ ...rangeValue, min: e.target.value })}
              width="48%" // Maintain consistent input widths
            />
            <Input
              placeholder="Max value"
              value={rangeValue.max}
              onChange={(e) => setRangeValue({ ...rangeValue, max: e.target.value })}
              width="48%" // Keep consistent with the first input
            />
          </HStack>
        )}

        {inputType === "Value and Tolerance" && (
          <HStack width="100%">
            <Input
              placeholder="Value"
              value={toleranceValue.value}
              onChange={(e) => setToleranceValue({ ...toleranceValue, value: e.target.value })}
              width="48%" // Consistent input widths
            />
            <Input
              placeholder="Tolerance"
              value={toleranceValue.tolerance}
              onChange={(e) => setToleranceValue({ ...toleranceValue, tolerance: e.target.value })}
              width="48%" // Consistent with the above input
            />
          </HStack>
        )}

        {inputType === "Contains" && (
          <Input
            placeholder="Enter substring"
            value={containsValue}
            onChange={(e) => setContainsValue(e.target.value)}
            width="100%" // Ensure full width
          />
        )}

          </HStack>
          <HStack spacing={4} width="100%">
            <Button colorScheme="teal" size="sm" onClick={handleAddField}>
              Add Field
            </Button>
            <Button colorScheme="gray" size="sm" onClick={handleClearInputs}>
              Clear
            </Button>
          </HStack>
        </VStack>
      </Collapse>
    </Box>
  );
};

export default CollapsibleCard;
