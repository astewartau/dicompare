import React, { useEffect } from 'react';
import { ChakraProvider } from '@chakra-ui/react';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import LandingPage from './pages/LandingPage/LandingPage';

const AppContent = () => {
    const location = useLocation();

    useEffect(() => {
    }, []);


    return (
        <>

            <Routes>
                <Route path="/" element={<LandingPage />} />
            </Routes>
        </>
    );
};

const App = () => {
    return (
        <ChakraProvider>
            <BrowserRouter>
                <AppContent />
            </BrowserRouter>
        </ChakraProvider>
    );
};

export default App;
