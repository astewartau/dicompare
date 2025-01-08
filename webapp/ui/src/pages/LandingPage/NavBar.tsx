import React from 'react';
import { Box, Flex, Link, Button, Heading, useColorModeValue } from '@chakra-ui/react';
import { Link as RouterLink } from 'react-router-dom';

const NavBar = () => {
    const bg = useColorModeValue('white', 'gray.800');
    const color = useColorModeValue('teal.500', 'white');

    return (
        <Box bg={bg} px={4} boxShadow="md">
            <Flex h={16} alignItems={'center'} justifyContent={'space-between'}>
                <Heading as="h1" color={color} size="4xl">
                    dicompare
                </Heading>
                <Flex alignItems={'center'}>
                    <RouterLink to="/team">
                        <Button as={Link} variant={'link'} marginRight="1rem" color="blue.500">
                            TEAM
                        </Button>
                    </RouterLink>
                    <RouterLink to="/login">
                        <Button as={Link} variant={'link'} color="blue.500">
                            LOG IN / REGISTER
                        </Button>
                    </RouterLink>
                </Flex>
            </Flex>
        </Box>
    );
};

export default NavBar;
