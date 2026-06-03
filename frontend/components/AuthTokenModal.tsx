'use client';

import { useState, useCallback } from 'react';

interface AuthTokenModalProps {
    isOpen: boolean;
    onClose: () => void;
    onLogin: () => void;
    onSubmitCode: (code: string) => Promise<any>;
}

export default function AuthTokenModal({ isOpen, onClose, onLogin, onSubmitCode }: AuthTokenModalProps) {
    const [rawInput, setRawInput] = useState('');
    const [step, setStep] = useState<1 | 2 | 3>(1);
    const [submitting, setSubmitting] = useState(false);
    const [success, setSuccess] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const extractedCode = extractAuthCode(rawInput.trim());
    const isUrl = rawInput.trim().startsWith('http');

    const handleOpenLogin = useCallback(() => {
        onLogin();
        setStep(2);
    }, [onLogin]);

    const handleSubmit = useCallback(async () => {
        if (!rawInput.trim()) return;

        setSubmitting(true);
        setError(null);

        try {
            await onSubmitCode(rawInput.trim());
            setSuccess(true);
            setStep(3);
            // Auto-close after 2 seconds
            setTimeout(() => {
                onClose();
                // Reset state
                setRawInput('');
                setStep(1);
                setSuccess(false);
                setError(null);
            }, 2000);
        } catch (err: any) {
            setError(err.message || 'Failed to generate token');
        } finally {
            setSubmitting(false);
        }
    }, [rawInput, onSubmitCode, onClose]);

    const handleClose = useCallback(() => {
        onClose();
        setRawInput('');
        setStep(1);
        setSuccess(false);
        setError(null);
    }, [onClose]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                onClick={handleClose}
            />

            {/* Modal */}
            <div className="relative w-full max-w-lg mx-4 bg-zinc-900 border border-zinc-700/50 rounded-2xl shadow-2xl overflow-hidden">
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white text-sm font-bold">
                            🔑
                        </div>
                        <div>
                            <h2 className="text-white font-bold text-sm">Generate Access Token</h2>
                            <p className="text-zinc-500 text-[10px] uppercase tracking-wider font-semibold">Fyers API Authentication</p>
                        </div>
                    </div>
                    <button
                        onClick={handleClose}
                        className="w-8 h-8 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white flex items-center justify-center transition-colors"
                    >
                        ✕
                    </button>
                </div>

                {/* Content */}
                <div className="px-6 py-5 space-y-5">
                    {/* Steps */}
                    <div className="space-y-3">
                        {/* Step 1 */}
                        <div className={`flex gap-3 ${step >= 1 ? 'opacity-100' : 'opacity-40'}`}>
                            <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step > 1 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-blue-500/20 text-blue-400'
                                }`}>
                                {step > 1 ? '✓' : '1'}
                            </div>
                            <div className="flex-1 pt-0.5">
                                <p className="text-white text-sm font-medium">Open Fyers Login</p>
                                <p className="text-zinc-500 text-xs mt-0.5">
                                    Click below to open the Fyers OAuth page in a new tab.
                                    Log in with your credentials.
                                </p>
                                {step === 1 && (
                                    <button
                                        onClick={handleOpenLogin}
                                        className="mt-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                                    >
                                        Open Fyers Login →
                                    </button>
                                )}
                            </div>
                        </div>

                        {/* Step 2 */}
                        <div className={`flex gap-3 ${step >= 2 ? 'opacity-100' : 'opacity-40'}`}>
                            <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step > 2 ? 'bg-emerald-500/20 text-emerald-400' : step === 2 ? 'bg-blue-500/20 text-blue-400' : 'bg-zinc-800 text-zinc-600'
                                }`}>
                                {step > 2 ? '✓' : '2'}
                            </div>
                            <div className="flex-1 pt-0.5">
                                <p className="text-white text-sm font-medium">Paste Auth Code</p>
                                <p className="text-zinc-500 text-xs mt-0.5">
                                    After login, Fyers redirects to a URL. Copy the <span className="text-zinc-300 font-mono">auth_code</span> value from the URL
                                    — or paste the <span className="text-zinc-300">entire URL</span>.
                                </p>
                                {step === 2 && (
                                    <div className="mt-3 space-y-3">
                                        {/* Example */}
                                        <div className="bg-zinc-800/60 rounded-lg p-3 border border-zinc-700/40">
                                            <p className="text-[10px] text-zinc-500 uppercase tracking-wider font-bold mb-1.5">Example redirect URL</p>
                                            <p className="text-[11px] text-zinc-400 font-mono break-all leading-relaxed">
                                                https://google.com/?s=ok&code=200&<span className="text-amber-400 font-bold">auth_code=eyJhbG...</span>&state=optiongreek
                                            </p>
                                        </div>

                                        {/* Input */}
                                        <textarea
                                            value={rawInput}
                                            onChange={(e) => { setRawInput(e.target.value); setError(null); }}
                                            placeholder="Paste auth_code or full redirect URL here..."
                                            rows={3}
                                            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-3 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 font-mono resize-none transition-colors"
                                            autoFocus
                                        />

                                        {/* Auto-detection indicator */}
                                        {rawInput.trim() && (
                                            <div className="flex items-center gap-2 text-xs">
                                                {isUrl ? (
                                                    <span className="flex items-center gap-1 text-amber-400">
                                                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                                                        URL detected — auth_code will be auto-extracted
                                                    </span>
                                                ) : (
                                                    <span className="flex items-center gap-1 text-emerald-400">
                                                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                                        Using as raw auth code
                                                    </span>
                                                )}
                                            </div>
                                        )}

                                        {/* Error */}
                                        {error && (
                                            <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-2.5 text-red-400 text-xs">
                                                <span className="font-bold">Error:</span> {error}
                                            </div>
                                        )}

                                        {/* Submit button */}
                                        <button
                                            onClick={handleSubmit}
                                            disabled={!rawInput.trim() || submitting}
                                            className="w-full px-4 py-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 disabled:from-zinc-700 disabled:to-zinc-700 disabled:cursor-not-allowed text-white text-sm font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl flex items-center justify-center gap-2"
                                        >
                                            {submitting ? (
                                                <>
                                                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                                    </svg>
                                                    Converting to Token...
                                                </>
                                            ) : (
                                                'Generate Token & Save to .env'
                                            )}
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Step 3: Success */}
                        {step === 3 && success && (
                            <div className="flex gap-3">
                                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-emerald-500/20 flex items-center justify-center text-xs font-bold text-emerald-400">
                                    ✓
                                </div>
                                <div className="flex-1 pt-0.5">
                                    <p className="text-emerald-400 text-sm font-bold">Token Generated Successfully!</p>
                                    <p className="text-zinc-500 text-xs mt-0.5">
                                        Access token saved to <span className="text-zinc-300 font-mono">.env</span> and settings reloaded.
                                        This modal will close automatically.
                                    </p>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Footer */}
                <div className="px-6 py-3 border-t border-zinc-800 bg-zinc-900/50">
                    <p className="text-[10px] text-zinc-600 text-center">
                        Token is saved to your local <span className="font-mono">.env</span> file and never sent to any external server.
                    </p>
                </div>
            </div>
        </div>
    );
}


/**
 * Extract auth_code from raw input (URL or plain code).
 * This is for the visual indicator only — the backend does the actual extraction.
 */
function extractAuthCode(input: string): string {
    if (input.startsWith('http://') || input.startsWith('https://')) {
        try {
            const url = new URL(input);
            return url.searchParams.get('auth_code') || url.searchParams.get('code') || input;
        } catch {
            return input;
        }
    }
    return input;
}
