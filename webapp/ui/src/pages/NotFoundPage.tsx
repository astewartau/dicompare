import { Box, Button, Heading } from '@chakra-ui/react';
import { useNavigate } from 'react-router-dom';

function NotFoundPage() {
    const navigate = useNavigate();
    const handleRedirect = () => {
        navigate('/');
    };

    return (
        <Box w="100%">
            <Box w="100%" h="100%" display="flex" justifyContent="center" alignItems="center" flexDirection="column">
                <Heading mb={6} size="2xl">
                    Page not found
                </Heading>
                <Button size="lg" colorScheme="secondary" onClick={handleRedirect}>
                    Return to main page
                </Button>
            </Box>
        </Box>
    );
}

export default NotFoundPage;
