import React from 'react';
import * as ReactDOM from 'react-dom/client';
import App from './App.tsx';
import './index.css';
import { ChakraProvider, extendTheme } from '@chakra-ui/react';
import { MultiSelectTheme } from 'chakra-multiselect';

const theme = extendTheme({
    components: {
        MultiSelect: MultiSelectTheme,
    },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <ChakraProvider theme={theme}>
            <App />
        </ChakraProvider>
    </React.StrictMode>
);
