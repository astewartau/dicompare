import {
    Box,
    Heading,
    Text,
    Flex,
    VStack,
    Button,
    HStack,
    Icon,
    Image,
} from '@chakra-ui/react';
import { useNavigate } from 'react-router-dom';
import { CheckCircleIcon, EditIcon } from '@chakra-ui/icons';

const LandingPage = () => {
    const navigate = useNavigate();

    return (
        <Box>
            {/* Header Section */}
            <Flex
                justify="space-between"
                align="center"
                padding="1rem 2rem"
                bg="teal.500"
                color="white"
                boxShadow="md"
            >
                <Heading as="h1" size="xl">
                    dicompare
                </Heading>
            </Flex>

                        {/* Introductory Section */}
            <Flex
                direction={{ base: 'column', md: 'row' }}
                padding="4rem 2rem"
                bgGradient="linear(to-r, teal.500, teal.300)"
                color="white"
            >
                <Box flex='2'>
                    <VStack align="start" spacing={6} marginRight={20}>
                        <Text fontSize="6xl" as='b'>
                            Empowering imaging research with privacy-first data validation
                        </Text>
                        <Text fontSize="lg" mr={20}>
                            Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. DICOMpare is your trusted partner in achieving high-quality, compliant medical imaging workflows.
                        </Text>e
                    </VStack>
                </Box>
                <Box
                    flex='1'
                    >
                <Image
                    src="../assets/ct-scan.png"
                    alt="MRI Visualization"
                    borderRadius="md"
                    boxShadow="lg"
                    />
                </Box>
            </Flex>



            {/* Main Content */}
            <Flex
                direction="column"
                align="center"
                justify="center"
                padding="4rem 2rem"
                bg="gray.100"
            >
                <Heading as="h2" size="lg" marginBottom="2rem" textAlign="center" color="teal.600">
                    Select to Begin
                </Heading>

                <HStack spacing={8}>
                    {/* Option 1: Generate Template */}
                    <VStack
                        spacing={4}
                        padding="2rem"
                        bg="white"
                        borderRadius="md"
                        boxShadow="lg"
                        align="center"
                        onClick={() => navigate('/generate-template')}
                        _hover={{ transform: 'scale(1.05)', transition: '0.3s' }}
                        cursor="pointer"
                    >
                        <Icon as={EditIcon} w={12} h={12} color="teal.500" />
                        <Heading as="h3" size="md" textAlign="center" color="teal.600">
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
                        boxShadow="lg"
                        align="center"
                        onClick={() => navigate('/check-compliance')}
                        _hover={{ transform: 'scale(1.05)', transition: '0.3s' }}
                        cursor="pointer"
                    >
                        <Icon as={CheckCircleIcon} w={12} h={12} color="teal.500" />
                        <Heading as="h3" size="md" textAlign="center" color="teal.600">
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
