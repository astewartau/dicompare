import { Toast } from '@chakra-ui/react';
import axios from 'axios';
import { getJWT, hasJWT } from './utils';

const axiosInstance = axios.create({
    headers: { 'Content-Type': 'application/json; charset=UTF-8' },
});

export function setJWTInAxios(jwt: string | undefined) {
    axiosInstance.interceptors.request.use((config) => {
        if (!jwt) return config;
        config.headers.Authorization = `Bearer ${jwt}`;
        return config;
    });
}

axiosInstance.interceptors.request.use((config) => {
    if (hasJWT()) {
        config.headers.Authorization = `Bearer ${getJWT()}`;
    }
    return config;
});

export default axiosInstance;
