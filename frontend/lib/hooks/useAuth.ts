'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

export interface AuthStatus {
    authenticated: boolean;
    has_token: boolean;
    is_valid: boolean;
    user_info: any;
    app_id: string | null;
}

export function useAuth() {
    const [status, setStatus] = useState<AuthStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const checkStatus = useCallback(async () => {
        try {
            setLoading(true);
            const data = await api.auth.getStatus();
            setStatus(data);
            setError(null);
        } catch (err: any) {
            setError(err.message || 'Failed to check auth status');
            setStatus(null);
        } finally {
            setLoading(false);
        }
    }, []);

    const login = useCallback(async () => {
        try {
            const { login_url } = await api.auth.getLoginUrl();
            if (login_url) {
                window.location.href = login_url;
            }
        } catch (err: any) {
            setError(err.message || 'Failed to get login URL');
        }
    }, []);

    const autoLogin = useCallback(async () => {
        try {
            setLoading(true);
            await api.auth.autoLogin();
            await checkStatus();
        } catch (err: any) {
            setError(err.message || 'Auto-login failed. Please sign in manually.');
        } finally {
            setLoading(false);
        }
    }, [checkStatus]);

    useEffect(() => {
        checkStatus();
    }, [checkStatus]);

    return {
        status,
        loading,
        error,
        login,
        autoLogin,
        refresh: checkStatus
    };
}
