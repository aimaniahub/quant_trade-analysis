'use client';

import { useState, useCallback, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../lib/api';

interface AuthTokenModalProps {
    isOpen: boolean;
    onClose: () => void;
    onLogin: () => void;
    onSubmitCode: (code: string) => Promise<any>;
}

const DEFAULT_LOGIN_URL =
    'https://api-t1.fyers.in/api/v3/generate-authcode?client_id=WG88Q43SI6-100&redirect_uri=https%3A%2F%2Fgoogle.com&response_type=code&state=optiongreek';

export default function AuthTokenModal({ isOpen, onClose, onLogin, onSubmitCode }: AuthTokenModalProps) {
    const [rawInput, setRawInput] = useState('');
    const [step, setStep] = useState<1 | 2 | 3>(1);
    const [submitting, setSubmitting] = useState(false);
    const [success, setSuccess] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [mounted, setMounted] = useState(false);
    const [loginUrl, setLoginUrl] = useState<string>(DEFAULT_LOGIN_URL);
    const [loadingUrl, setLoadingUrl] = useState(false);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        setMounted(true);
    }, []);

    // Fetch dynamic login URL from backend on modal open
    useEffect(() => {
        if (!isOpen) return;

        let isCancelled = false;
        setLoadingUrl(true);

        api.auth
            .getLoginUrl()
            .then((res) => {
                if (!isCancelled && res?.login_url) {
                    setLoginUrl(res.login_url);
                }
            })
            .catch((err) => {
                console.warn('Could not fetch dynamic login URL from backend, using fallback:', err);
            })
            .finally(() => {
                if (!isCancelled) setLoadingUrl(false);
            });

        return () => {
            isCancelled = true;
        };
    }, [isOpen]);

    const isUrl = rawInput.trim().startsWith('http');

    const handleOpenLogin = useCallback(() => {
        try {
            onLogin();
        } catch {
            // onLogin might fail if window.open was blocked; native anchor handles primary navigation
        }
        setStep(2);
    }, [onLogin]);

    const handleCopyUrl = useCallback(async () => {
        try {
            await navigator.clipboard.writeText(loginUrl);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            // clipboard write failed
        }
    }, [loginUrl]);

    const handlePasteClipboard = useCallback(async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text && text.trim()) {
                setRawInput(text.trim());
                setError(null);
            }
        } catch {
            // permission denied or not supported
        }
    }, []);

    const handleSubmit = useCallback(async () => {
        if (!rawInput.trim()) return;

        setSubmitting(true);
        setError(null);

        try {
            await onSubmitCode(rawInput.trim());
            setSuccess(true);
            setStep(3);
            setTimeout(() => {
                onClose();
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

    // Keyboard Escape support
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && isOpen) {
                handleClose();
            }
        };
        if (isOpen) {
            window.addEventListener('keydown', handleKeyDown);
        }
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, handleClose]);

    // Prevent background scrolling when modal is open
    useEffect(() => {
        if (isOpen) {
            const originalOverflow = document.body.style.overflow;
            document.body.style.overflow = 'hidden';
            return () => {
                document.body.style.overflow = originalOverflow;
            };
        }
    }, [isOpen]);

    if (!isOpen || !mounted) return null;

    const modalContent = (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-4 overflow-y-auto">
            {/* Backdrop */}
            <div
                className="fixed inset-0 bg-black/80 backdrop-blur-sm transition-opacity"
                onClick={handleClose}
                aria-hidden="true"
            />

            {/* Modal Dialog */}
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="modal-title"
                className="relative w-full max-w-lg my-auto bg-[#0d1117] border border-zinc-700/80 rounded-2xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col z-10 animate-fadeIn"
            >
                {/* Header */}
                <div className="shrink-0 flex items-center justify-between px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-800 bg-zinc-900/60">
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white text-sm font-bold shadow-md shadow-blue-500/20">
                            🔑
                        </div>
                        <div>
                            <h2 id="modal-title" className="text-white font-bold text-sm">Generate Access Token</h2>
                            <p className="text-zinc-400 text-[10px] uppercase tracking-wider font-semibold font-mono">Fyers API Authentication</p>
                        </div>
                    </div>
                    <button
                        onClick={handleClose}
                        className="w-8 h-8 rounded-lg bg-zinc-800/80 hover:bg-zinc-700 text-zinc-400 hover:text-white flex items-center justify-center transition-colors text-sm font-bold"
                        aria-label="Close dialog"
                    >
                        ✕
                    </button>
                </div>

                {/* Content */}
                <div className="px-4 sm:px-6 py-4 sm:py-5 space-y-4 sm:space-y-5 overflow-y-auto touch-scroll">
                    {/* Steps */}
                    <div className="space-y-4">
                        {/* Step 1 */}
                        <div className={`flex gap-3 ${step >= 1 ? 'opacity-100' : 'opacity-40'}`}>
                            <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                                step > 1
                                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                                    : 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
                            }`}>
                                {step > 1 ? '✓' : '1'}
                            </div>
                            <div className="flex-1 pt-0.5">
                                <div className="flex items-center justify-between">
                                    <p className="text-white text-sm font-semibold">Open Fyers Login</p>
                                    {step > 1 && (
                                        <button
                                            onClick={() => setStep(1)}
                                            className="text-[11px] text-zinc-400 hover:text-white underline font-mono"
                                        >
                                            Step 1
                                        </button>
                                    )}
                                </div>
                                <p className="text-zinc-400 text-xs mt-0.5 leading-relaxed">
                                    Click below to open the Fyers OAuth authentication page in a new tab.
                                    Log in with your Fyers credentials.
                                </p>

                                {/* Step 1 Actions */}
                                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                                    <a
                                        href={loginUrl}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        onClick={handleOpenLogin}
                                        className="px-4 py-2 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg shadow-blue-500/20 hover:shadow-cyan-500/30 flex items-center gap-1.5 cursor-pointer select-none"
                                    >
                                        <span>{step === 1 ? 'Open Fyers Login' : 'Re-open Fyers Login'}</span>
                                        <span>↗</span>
                                    </a>

                                    <button
                                        type="button"
                                        onClick={handleCopyUrl}
                                        className="px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white text-xs font-medium rounded-lg border border-zinc-700 transition-colors flex items-center gap-1.5"
                                        title="Copy Fyers OAuth URL to paste into any browser"
                                    >
                                        <span>{copied ? '✓ Copied' : '📋 Copy URL'}</span>
                                    </button>

                                    {step === 1 && (
                                        <button
                                            type="button"
                                            onClick={() => setStep(2)}
                                            className="px-3 py-2 text-zinc-400 hover:text-zinc-200 text-xs font-semibold underline transition-colors"
                                        >
                                            Already logged in? Go to Step 2 →
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* Step 2 */}
                        <div className={`flex gap-3 ${step >= 2 ? 'opacity-100' : 'opacity-50'}`}>
                            <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                                step > 2
                                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                                    : step === 2
                                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
                                    : 'bg-zinc-800 text-zinc-500 border border-zinc-700'
                            }`}>
                                {step > 2 ? '✓' : '2'}
                            </div>
                            <div className="flex-1 pt-0.5">
                                <p className="text-white text-sm font-semibold">Paste Auth Code</p>
                                <p className="text-zinc-400 text-xs mt-0.5 leading-relaxed">
                                    After login, Fyers redirects to a URL. Copy the <span className="text-zinc-200 font-mono bg-zinc-800 px-1 py-0.5 rounded">auth_code</span> value from the URL
                                    — or paste the <span className="text-zinc-200 font-medium">entire redirect URL</span>.
                                </p>

                                {step >= 2 && (
                                    <div className="mt-3 space-y-3">
                                        {/* Quick launcher in Step 2 so user is never stuck */}
                                        <div className="flex items-center justify-between bg-zinc-900/90 rounded-lg px-3 py-2 border border-zinc-800 text-xs">
                                            <span className="text-zinc-400 text-[11px]">Didn't get redirected yet?</span>
                                            <a
                                                href={loginUrl}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="text-cyan-400 hover:text-cyan-300 font-semibold flex items-center gap-1 text-[11px] underline"
                                            >
                                                Launch Fyers Login Page ↗
                                            </a>
                                        </div>

                                        {/* Example */}
                                        <div className="bg-zinc-900/70 rounded-lg p-3 border border-zinc-800">
                                            <p className="text-[10px] text-zinc-400 uppercase tracking-wider font-bold mb-1.5">Example redirect URL</p>
                                            <p className="text-[11px] text-zinc-400 font-mono break-all leading-relaxed">
                                                https://google.com/?s=ok&code=200&<span className="text-amber-400 font-bold">auth_code=eyJhbG...</span>&state=optiongreek
                                            </p>
                                        </div>

                                        {/* Input Header & Paste Button */}
                                        <div className="flex items-center justify-between text-xs">
                                            <label className="text-zinc-300 font-semibold text-[11px]">Redirect URL or auth_code:</label>
                                            <button
                                                type="button"
                                                onClick={handlePasteClipboard}
                                                className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-cyan-400 hover:text-cyan-300 text-[11px] font-mono flex items-center gap-1 border border-zinc-700 transition-colors"
                                                title="Paste directly from clipboard"
                                            >
                                                📋 Paste
                                            </button>
                                        </div>

                                        {/* Input */}
                                        <textarea
                                            value={rawInput}
                                            onChange={(e) => { setRawInput(e.target.value); setError(null); }}
                                            placeholder="Paste auth_code or full redirect URL here..."
                                            rows={3}
                                            className="w-full bg-zinc-950/90 border border-zinc-700/80 rounded-lg px-3.5 py-2.5 text-xs sm:text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/60 focus:ring-1 focus:ring-cyan-500/30 font-mono resize-none transition-colors"
                                            autoFocus
                                        />

                                        {/* Auto-detection indicator */}
                                        {rawInput.trim() && (
                                            <div className="flex items-center gap-2 text-xs">
                                                {isUrl ? (
                                                    <span className="flex items-center gap-1.5 text-amber-400 font-mono text-[11px]">
                                                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                                                        URL detected — auth_code will be auto-extracted
                                                    </span>
                                                ) : (
                                                    <span className="flex items-center gap-1.5 text-emerald-400 font-mono text-[11px]">
                                                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                                        Using as raw auth code
                                                    </span>
                                                )}
                                            </div>
                                        )}

                                        {/* Error */}
                                        {error && (
                                            <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-3.5 py-2.5 text-red-400 text-xs">
                                                <p><span className="font-bold">Error:</span> {error}</p>
                                                <p className="mt-1 text-[11px] text-zinc-400">
                                                    Note: Fyers auth codes expire after 3–5 minutes. If it expired, click <a href={loginUrl} target="_blank" rel="noopener noreferrer" className="text-cyan-400 underline">Open Fyers Login ↗</a> to get a fresh code.
                                                </p>
                                            </div>
                                        )}

                                        {/* Submit button */}
                                        <button
                                            onClick={handleSubmit}
                                            disabled={!rawInput.trim() || submitting}
                                            className="w-full px-4 py-2.5 sm:py-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 disabled:from-zinc-800 disabled:to-zinc-800 disabled:text-zinc-500 disabled:cursor-not-allowed text-white text-xs sm:text-sm font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg shadow-emerald-600/20 flex items-center justify-center gap-2 cursor-pointer"
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
                            <div className="flex gap-3 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl">
                                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-emerald-500/20 flex items-center justify-center text-xs font-bold text-emerald-400">
                                    ✓
                                </div>
                                <div className="flex-1 pt-0.5">
                                    <p className="text-emerald-400 text-sm font-bold">Token Generated Successfully!</p>
                                    <p className="text-zinc-400 text-xs mt-0.5">
                                        Access token saved to <span className="text-zinc-200 font-mono">.env</span> and settings reloaded.
                                        This modal will close automatically.
                                    </p>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Footer */}
                <div className="shrink-0 px-4 sm:px-6 py-3 border-t border-zinc-800 bg-zinc-950/60 flex items-center justify-between text-[10px] text-zinc-500 font-mono">
                    <span>Token is stored securely in your backend session</span>
                    <button
                        onClick={handleClose}
                        className="text-zinc-400 hover:text-white underline cursor-pointer"
                    >
                        Dismiss
                    </button>
                </div>
            </div>
        </div>
    );

    return createPortal(modalContent, document.body);
}
