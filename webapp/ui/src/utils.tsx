import axios from 'axios';
import { setJWTInAxios } from './axios.instance';
import { jwtDecode } from 'jwt-decode';

export function hasJWT() {
    return !!getJWT();
}

export function getJWT() {
    return localStorage.getItem('jwt');
}

export function retrieveJWTFromHeader() {
}

export function getFullName() {
    const token = getJWT();
    if (!token) return null;
    const decoded = jwtDecode(token);
    return decoded.profile.fullname;
}

export function getID() {
    const token = getJWT();
    if (!token) return null;
    const decoded = jwtDecode(token);
    return decoded.id;
}


