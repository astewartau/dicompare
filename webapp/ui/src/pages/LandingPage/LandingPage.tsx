import React from 'react';
import { Box, Button, Container, Heading, Link, Text, Flex, Grid, GridItem, Image, Icon } from '@chakra-ui/react';
import { CheckCircleIcon, ExternalLinkIcon } from '@chakra-ui/icons';
import { useNavigate } from 'react-router-dom';

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
                <Flex>
                    <Link href="https://brainlife.io/team/" marginRight="2rem" color="blue.500" isExternal>
                        <ExternalLinkIcon mx="2px" />
                        <Text fontSize="xl" as="b">
                            TEAM
                        </Text>
                    </Link>
                </Flex>
            </Flex>


            <Box textAlign="center" py={5} bg="gray.50" height={20}>
                <Text>&copy; Pestillilab. All rights reserved.</Text>
            </Box>
        </Box>
    );
};

export default LandingPage;
