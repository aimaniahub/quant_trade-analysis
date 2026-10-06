'use client';

import { useState } from 'react';
import { useAuth } from '../lib/hooks/useAuth';
import AuthTokenModal from './AuthTokenModal';

export default function AuthButton({ compact = false }: { compact?: boolean }) {
    const { status, loading, error, login, submitAuthCode, logout } = useAuth();
    const [showModal, setShowModal] = useState(false);

    const [showUserMenu, setShowUserMenu] = useState(false);

    if (loading) {
        return (
            <div className="h-7 w-20 sm:w-24 rounded bg-zinc-800 animate-pulse" />
        );
    }

    if (status?.authenticated) {
        const userName = status.user_info?.name || status.user_info?.display_name || 'Trader';
        const fyersId = status.user_info?.fy_id || status.app_id || '';

        return (
            <div className="relative">
                <button
                    onClick={() => setShowUserMenu(!showUserMenu)}
                    className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-2.5 py-1 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-all select-none"
                    title={`Connected as ${userName} (${fyersId}). Click to manage.`}
                >
                    <span className="relative flex h-1.5 w-1.5 shrink-0">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
                    </span>
                    <span className="text-[10px] font-semibold uppercase tracking-wider truncate max-w-[80px] sm:max-w-[120px]">
                        {compact ? 'FYERS' : userName}
                    </span>
                </button>

                {showUserMenu && (
                    <div className="absolute right-0 mt-1.5 w-48 rounded-xl bg-[#0c1017] border border-zinc-800 shadow-2xl p-2.5 z-50 animate-fadeIn text-xs">
                        <div className="pb-2 border-b border-zinc-800/80 mb-2">
                            <p className="font-bold text-white truncate">{userName}</p>
                            {fyersId && <p className="text-[10px] font-mono text-zinc-400 truncate">{fyersId}</p>}
                            <span className="inline-block mt-1 text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                ACTIVE SESSION
                            </span>
                        </div>
                        <button
                            onClick={async () => {
                                setShowUserMenu(false);
                                if (confirm('Are you sure you want to log out of Fyers?')) {
                                    await logout();
                                }
                            }}
                            className="w-full text-left px-2 py-1.5 rounded-lg text-rose-400 hover:bg-rose-500/10 hover:text-rose-300 font-medium text-xs transition-colors"
                        >
                            Disconnect / Log Out
                        </button>
                    </div>
                )}
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
