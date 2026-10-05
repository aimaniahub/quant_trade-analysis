'use client';

import { useState } from 'react';
import { useAuth } from '../lib/hooks/useAuth';
import AuthTokenModal from './AuthTokenModal';

export default function AuthButton({ compact = false }: { compact?: boolean }) {
    const { status, loading, error, login, submitAuthCode } = useAuth();
    const [showModal, setShowModal] = useState(false);

    if (loading) {
        return (
            <div className="h-7 w-24 rounded bg-zinc-800 animate-pulse" />
        );
    }

    if (status?.authenticated) {
        return (
            <div className="flex items-center gap-2 px-2.5 py-1 rounded border border-emerald-500/25 bg-emerald-500/10 text-emerald-400">
                <span className="relative flex h-1.5 w-1.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wider">
                    {compact ? 'FYERS' : 'Connected'}
                </span>
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-1 items-end">
            <button
                onClick={() => setShowModal(true)}
                className="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded text-[10px] font-bold uppercase tracking-wider"
            >
                Login
            </button>
            {error && (
                <span className="text-xs text-red-500 max-w-[200px] leading-tight text-right">
                    {error}
                </span>
            )}

            <AuthTokenModal
                isOpen={showModal}
                onClose={() => setShowModal(false)}
                onLogin={login}
                onSubmitCode={submitAuthCode}
            />
        </div>
    );
}
