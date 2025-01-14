import { useEffect } from 'react';
import { ChakraProvider } from '@chakra-ui/react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import LandingPage from './pages/LandingPage/LandingPage';
import GenerateTemplate from './pages/GenerateTemplate/GenerateTemplate';

const AppContent = () => {

    useEffect(() => {
    }, []);


    return (
        <>

            <Routes>
                <Route path="/" element={<LandingPage />} />
                <Route path="/generate-template" element={<GenerateTemplate />} />
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
