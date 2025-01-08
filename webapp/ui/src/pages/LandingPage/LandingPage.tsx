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
            </Flex>



        </Box>
    );
};

export default LandingPage;
