'use client';

import { useAuth } from '../lib/hooks/useAuth';

export default function AuthButton() {
    const { status, loading, error, login, autoLogin } = useAuth();

    if (loading) {
        return (
            <div className="flex items-center gap-2 px-4 py-2 border rounded-md bg-zinc-100 dark:bg-zinc-800 animate-pulse">
                <div className="w-20 h-4 bg-zinc-200 dark:bg-zinc-700 rounded"></div>
            </div>
        );
    }

    if (status?.authenticated) {
        return (
            <div className="flex flex-col items-end gap-1">
                <div className="flex items-center gap-2 px-4 py-2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 rounded-md">
                    <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    <span className="text-sm font-medium">Connected to Fyers</span>
                </div>
                {status.user_info && (
                    <span className="text-[10px] text-zinc-500 dark:text-zinc-400 px-1">
                        {status.user_info.name || status.user_info.fy_id}
                    </span>
                )}
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-2">
            <button
                onClick={login}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md transition-colors text-sm font-medium flex items-center gap-2"
            >
                Login with Fyers
            </button>
            {error && (
                <span className="text-xs text-red-500 max-w-[200px] leading-tight text-right">
                    {error}
                </span>
            )}
        </div>
    );
}
