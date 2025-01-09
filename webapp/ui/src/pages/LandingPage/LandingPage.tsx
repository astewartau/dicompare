import { Box, Heading, Text, Flex, VStack, Button, HStack, Icon } from '@chakra-ui/react';
import { useNavigate } from 'react-router-dom';
import { CheckCircleIcon, EditIcon } from '@chakra-ui/icons';

const LandingPage = () => {
    const navigate = useNavigate();

    return (
        <Box>
            {/* Header Section */}
            <Flex justify="space-between" align="center" padding="1rem 2rem" bg="white">
                <Heading as="h1" size="xl">
                    <Text as="span" color="teal.500">
                        dicompare
                    </Text>
                </Heading>
            </Flex>

            {/* Main Content */}
            <Flex
                direction="column"
                align="center"
                justify="center"
                padding="2rem"
                bg="gray.50"
                height="100vh"
            >
                <Heading as="h2" size="lg" marginBottom="1rem" textAlign="center">
                    Welcome to DICOMpare
                </Heading>
                <Text fontSize="lg" color="gray.600" textAlign="center" marginBottom="2rem">
                    Choose one of the options below to get started:
                </Text>

                <HStack spacing={8}>
                    {/* Option 1: Generate Template */}
                    <VStack
                        spacing={4}
                        padding="2rem"
                        bg="white"
                        borderRadius="md"
                        boxShadow="md"
                        align="center"
                        onClick={() => navigate('/generate-template')}
                        _hover={{ transform: 'scale(1.05)', transition: '0.2s' }}
                        cursor="pointer"
                    >
                        <Icon as={EditIcon} w={12} h={12} color="teal.500" />
                        <Heading as="h3" size="md" textAlign="center">
                            Generate Template
                        </Heading>
                        <Text fontSize="sm" color="gray.500" textAlign="center">
                            Create a new DICOM template quickly and efficiently.
                        </Text>
                        <Button colorScheme="teal" size="sm">
                            Choose
                        </Button>
                    </VStack>

                    {/* Option 2: Check Compliance */}
                    <VStack
                        spacing={4}
                        padding="2rem"
                        bg="white"
                        borderRadius="md"
                        boxShadow="md"
                        align="center"
                        onClick={() => navigate('/check-compliance')}
                        _hover={{ transform: 'scale(1.05)', transition: '0.2s' }}
                        cursor="pointer"
                    >
                        <Icon as={CheckCircleIcon} w={12} h={12} color="teal.500" />
                        <Heading as="h3" size="md" textAlign="center">
                            Check Compliance
                        </Heading>
                        <Text fontSize="sm" color="gray.500" textAlign="center">
                            Validate your DICOM files to ensure compliance with standards.
                        </Text>
                        <Button colorScheme="teal" size="sm">
                            Choose
                        </Button>
                    </VStack>
                </HStack>
            </Flex>
        </Box>
    );
};

export default LandingPage;
