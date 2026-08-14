'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import LoadingBanner from './ui/LoadingBanner';

const SETTINGS_KEY = 'ma7200_scan_settings_v1';

export interface ScanSettings {
    fast_ma: number;
    slow_ma: number;
    window_days: number;
    vol_mult: number;
    max_bars_ago: number;
    history_days: number;
}

const DEFAULT_SETTINGS: ScanSettings = {
    fast_ma: 7,
    slow_ma: 200,
    window_days: 15,
    vol_mult: 1.5,
    max_bars_ago: 1,
    history_days: 40,
};

function loadSettings(): ScanSettings {
    if (typeof window === 'undefined') return { ...DEFAULT_SETTINGS };
    try {
        const raw = localStorage.getItem(SETTINGS_KEY);
        if (!raw) return { ...DEFAULT_SETTINGS };
        const parsed = JSON.parse(raw) as Partial<ScanSettings>;
        return normalizeSettings({ ...DEFAULT_SETTINGS, ...parsed });
    } catch {
        return { ...DEFAULT_SETTINGS };
    }
}

function normalizeSettings(s: ScanSettings): ScanSettings {
    let fast = Math.max(2, Math.min(100, Math.round(Number(s.fast_ma) || 7)));
    let slow = Math.max(5, Math.min(500, Math.round(Number(s.slow_ma) || 200)));
    if (slow <= fast) slow = fast + 1;
    return {
        fast_ma: fast,
        slow_ma: slow,
        window_days: Math.max(1, Math.min(90, Math.round(Number(s.window_days) || 15))),
        vol_mult: Math.max(0.5, Math.min(10, Number(s.vol_mult) || 1.5)),
        max_bars_ago: Math.max(0, Math.min(20, Math.round(Number(s.max_bars_ago) ?? 1))),
        history_days: Math.max(10, Math.min(120, Math.round(Number(s.history_days) || 40))),
    };
}

interface Candidate {
    symbol: string;
    name: string;
    ltp: number;
    cross_type: 'BULLISH' | 'BEARISH' | string;
    cross_time?: string;
    volume_ratio: number;
    trend_15m: string;
    ema7?: number;
    ema200?: number;
    bars_ago?: number;
    fresh_label?: string;
    freshness?: string;
    first_cross_in_15d?: boolean;
    crosses_in_15d?: number;
    extension_from_200_pct?: number;
    momentum_score?: number;
    body_strength?: number;
}

interface SuggestedStrike {
    role: string;
    strike: number;
    instrument: string;
    structure: string;
}

interface RuleHit {
    rule: string;
    detail: string;
}

interface AnalyzeResult {
    success: boolean;
    symbol: string;
    name: string;
    cross_type: string;
    spot: number;
    atm: number;
    result: string;
    status: string;
    decision: string;
    reason: string;
    rules_hit: RuleHit[];
    rules_miss: string[];
    hits: number;
    required_hits: number;
    primary_flow: string;
    secondary_flow?: string;
    oi_pcr: number;
    max_pain?: number;
    suggested_strikes: SuggestedStrike[];
    report: string;
}

interface Props {
    onBack: () => void;
}

export default function MA7200Scanner({ onBack }: Props) {
    const [candidates, setCandidates] = useState<Candidate[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [scanned, setScanned] = useState(0);
    const [universe, setUniverse] = useState(0);
    const [progress, setProgress] = useState(0);
    const [currentSym, setCurrentSym] = useState<string | null>(null);
    const [source, setSource] = useState<'full' | 'top'>('full');
    const [apiInfo, setApiInfo] = useState('');

    const [settings, setSettings] = useState<ScanSettings>(DEFAULT_SETTINGS);
    const [draft, setDraft] = useState<ScanSettings>(DEFAULT_SETTINGS);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [settingsReady, setSettingsReady] = useState(false);
    const [saveFlash, setSaveFlash] = useState(false);

    const [analyzing, setAnalyzing] = useState<string | null>(null);
    const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null);
    const [analyzeError, setAnalyzeError] = useState<string | null>(null);

    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const runIdRef = useRef(0);
    const settingsRef = useRef(settings);
    settingsRef.current = settings;

    // Load saved settings once on mount
    useEffect(() => {
        const s = loadSettings();
        setSettings(s);
        setDraft(s);
        setSettingsReady(true);
    }, []);

    const stopPoll = useCallback(() => {
        if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    }, []);

    const runScan = useCallback(async () => {
        if (!settingsReady) return;
        const myRun = ++runIdRef.current;
        const active = settingsRef.current;
        stopPoll();
        setLoading(true);
        setError(null);
        setAnalysis(null);
        setCandidates([]);
        setScanned(0);
        setProgress(0);
        setCurrentSym(null);

        try {
            const limit = source === 'top' ? 40 : 200;
            const started: any = await api.ma7200.startScan(limit, 12, source, active);
            if (myRun !== runIdRef.current) return;
            if (!started.job_id) throw new Error('No job id from scan/start');

            const jid = started.job_id as string;
            setUniverse(started.total || limit);

            const pollOnce = async () => {
                if (myRun !== runIdRef.current) return;
                try {
                    const snap: any = await api.ma7200.getScanJob(jid);
                    if (myRun !== runIdRef.current) return;

                    setProgress(Number(snap.completion_pct || 0));
                    setScanned(snap.completed || snap.scanned || 0);
                    setUniverse(snap.universe || snap.total || limit);
                    setCurrentSym(snap.current_symbol || null);

                    const cands = snap.candidates || [];
                    if (cands.length) setCandidates(cands);

                    if (snap.api) {
                        setApiInfo(
                            `direct API · ok ${snap.api.ok ?? '—'} · fail ${snap.api.fail ?? 0}` +
                                (snap.api.in_cooldown
                                    ? ` · cooldown ${snap.api.cooldown_remaining}s`
                                    : ''),
                        );
                    }

                    const done =
                        snap.status === 'completed' ||
                        snap.status === 'failed' ||
                        snap.status === 'cancelled';

                    if (done) {
                        stopPoll();
                        setLoading(false);
                        setProgress(100);
                        setCurrentSym(null);
                        setCandidates(cands);
                        if (snap.status === 'failed') {
                            setError(snap.error_message || 'Scan job failed');
                        } else if (cands.length === 0) {
                            const s = settingsRef.current;
                            setError(
                                `Scanned ${snap.scanned || snap.completed || 0}/${snap.universe || limit} — no first-in-${s.window_days}d ${s.fast_ma}/${s.slow_ma} cross aged ≤${s.max_bars_ago + 1} bars (vol ≥${s.vol_mult}×).`,
                            );
                        }
                    }
                } catch (e: any) {
                    if (myRun !== runIdRef.current) return;
                    stopPoll();
                    setLoading(false);
                    setError(e?.message || 'Poll failed');
                }
            };

            await pollOnce();
            if (myRun !== runIdRef.current) return;
            pollRef.current = setInterval(pollOnce, 1500);
        } catch (e: any) {
            if (myRun !== runIdRef.current) return;
            setLoading(false);
            setError(e?.message || 'Failed to start scan');
        }
    }, [source, stopPoll, settingsReady]);

    // Auto-scan when source changes or settings become ready (not while editing draft)
    useEffect(() => {
        if (!settingsReady) return;
        runScan();
        return () => {
            runIdRef.current += 1;
            stopPoll();
        };
    }, [runScan, stopPoll, settingsReady]);

    const saveSettings = () => {
        const next = normalizeSettings(draft);
        if (next.slow_ma <= next.fast_ma) {
            setError('Slow MA must be greater than Fast MA');
            return;
        }
        try {
            localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
        } catch {
            /* ignore */
        }
        setSettings(next);
        setDraft(next);
        setSaveFlash(true);
        setTimeout(() => setSaveFlash(false), 1500);
        setSettingsOpen(false);
        // settingsRef updates on next render; force scan with next via ref then runScan
        settingsRef.current = next;
        // bump scan after state settles
        setTimeout(() => runScan(), 0);
    };

    const resetDefaults = () => {
        setDraft({ ...DEFAULT_SETTINGS });
    };

    const analyzeChain = async (c: Candidate) => {
        setAnalyzing(c.symbol);
        setAnalyzeError(null);
        setAnalysis(null);
        try {
            const data = (await api.ma7200.analyze(
                c.symbol,
                c.cross_type,
            )) as AnalyzeResult;
            setAnalysis(data);
        } catch (e: any) {
            setAnalyzeError(e?.message || 'Chain analysis failed');
        } finally {
            setAnalyzing(null);
        }
    };

    const statusColor = (s?: string) => {
        if (s === 'CONFIRMED') return 'text-emerald-500 border-emerald-500/40 bg-emerald-500/10';
        if (s === 'CONFLICT') return 'text-rose-500 border-rose-500/40 bg-rose-500/10';
        return 'text-amber-600 border-amber-500/40 bg-amber-500/10';
    };

    const maLabel = `${settings.fast_ma}/${settings.slow_ma}`;
    const draftDirty =
        JSON.stringify(normalizeSettings(draft)) !== JSON.stringify(settings);

    const fieldClass =
        'w-full px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-xs font-mono font-bold focus:outline-none focus:ring-2 focus:ring-cyan-500/40';
    const labelClass = 'text-[10px] font-black uppercase tracking-wider text-zinc-500';

    return (
        <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8">
            <div className="max-w-6xl mx-auto">
                <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                    <div className="flex items-center gap-3">
                        <button
                            onClick={onBack}
                            className="p-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg"
                        >
                            ←
                        </button>
                        <div>
                            <h1 className="text-2xl font-black italic tracking-tighter uppercase">
                                {maLabel} MA Cross<span className="text-cyan-500">.</span>
                            </h1>
                            <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest">
                                Direct Fyers 15m API · then option chain confirms
                            </p>
                        </div>
                    </div>
                    <div className="flex flex-wrap gap-2 items-center">
                        <button
                            onClick={() => setSource('full')}
                            className={`px-3 py-2 text-[10px] font-bold uppercase rounded-lg ${
                                source === 'full'
                                    ? 'bg-cyan-600 text-white'
                                    : 'bg-zinc-200 dark:bg-zinc-800 text-zinc-500'
                            }`}
                        >
                            All F&O (~184)
                        </button>
                        <button
                            onClick={() => setSource('top')}
                            className={`px-3 py-2 text-[10px] font-bold uppercase rounded-lg ${
                                source === 'top'
                                    ? 'bg-cyan-600 text-white'
                                    : 'bg-zinc-200 dark:bg-zinc-800 text-zinc-500'
                            }`}
                        >
                            Top liquid
                        </button>
                        <button
                            onClick={() => {
                                setDraft(settings);
                                setSettingsOpen(o => !o);
                            }}
                            className={`px-3 py-2 text-[10px] font-bold uppercase rounded-lg border ${
                                settingsOpen
                                    ? 'bg-zinc-800 text-white border-zinc-800 dark:bg-zinc-100 dark:text-zinc-900'
                                    : 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300'
                            }`}
                            title="Filter settings"
                        >
                            ⚙ Settings
                        </button>
                        <button
                            onClick={runScan}
                            disabled={loading || !settingsReady}
                            className="px-4 py-2 bg-cyan-600 hover:bg-cyan-700 text-white text-xs font-bold uppercase rounded-lg disabled:opacity-50"
                        >
                            {loading ? 'Direct API scan…' : `↻ Scan ${maLabel}`}
                        </button>
                    </div>
                </header>

                {/* Settings panel */}
                {settingsOpen && (
                    <div className="mb-4 p-4 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm">
                        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                            <div>
                                <div className="text-xs font-black uppercase tracking-wider text-zinc-500">
                                    Filter settings
                                </div>
                                <p className="text-[11px] text-zinc-500 mt-0.5">
                                    Edit days / MA / volume · <strong>Save</strong> applies filters
                                    and re-scans. Stored in this browser.
                                </p>
                            </div>
                            {saveFlash && (
                                <span className="text-[10px] font-black uppercase text-emerald-600">
                                    Saved ✓
                                </span>
                            )}
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                            <label className="space-y-1">
                                <span className={labelClass}>Fast MA</span>
                                <input
                                    type="number"
                                    min={2}
                                    max={100}
                                    value={draft.fast_ma}
                                    onChange={e =>
                                        setDraft(d => ({
                                            ...d,
                                            fast_ma: Number(e.target.value),
                                        }))
                                    }
                                    className={fieldClass}
                                />
                            </label>
                            <label className="space-y-1">
                                <span className={labelClass}>Slow MA</span>
                                <input
                                    type="number"
                                    min={5}
                                    max={500}
                                    value={draft.slow_ma}
                                    onChange={e =>
                                        setDraft(d => ({
                                            ...d,
                                            slow_ma: Number(e.target.value),
                                        }))
                                    }
                                    className={fieldClass}
                                />
                            </label>
                            <label className="space-y-1">
                                <span className={labelClass}>Window days</span>
                                <input
                                    type="number"
                                    min={1}
                                    max={90}
                                    value={draft.window_days}
                                    onChange={e =>
                                        setDraft(d => ({
                                            ...d,
                                            window_days: Number(e.target.value),
                                        }))
                                    }
                                    className={fieldClass}
                                    title="First cross must be unique in this many calendar days"
                                />
                            </label>
                            <label className="space-y-1">
                                <span className={labelClass}>Vol mult ×</span>
                                <input
                                    type="number"
                                    min={0.5}
                                    max={10}
                                    step={0.1}
                                    value={draft.vol_mult}
                                    onChange={e =>
                                        setDraft(d => ({
                                            ...d,
                                            vol_mult: Number(e.target.value),
                                        }))
                                    }
                                    className={fieldClass}
                                    title="Volume ≥ this × prior 10-bar average"
                                />
                            </label>
                            <label className="space-y-1">
                                <span className={labelClass}>Max age (bars)</span>
                                <input
                                    type="number"
                                    min={0}
                                    max={20}
                                    value={draft.max_bars_ago}
                                    onChange={e =>
                                        setDraft(d => ({
                                            ...d,
                                            max_bars_ago: Number(e.target.value),
                                        }))
                                    }
                                    className={fieldClass}
                                    title="0 = latest bar only; 1 = last 2 bars"
                                />
                            </label>
                            <label className="space-y-1">
                                <span className={labelClass}>History days</span>
                                <input
                                    type="number"
                                    min={10}
                                    max={120}
                                    value={draft.history_days}
                                    onChange={e =>
                                        setDraft(d => ({
                                            ...d,
                                            history_days: Number(e.target.value),
                                        }))
                                    }
                                    className={fieldClass}
                                    title="Fyers history fetch window (auto-bumped for slow MA)"
                                />
                            </label>
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                            <button
                                onClick={saveSettings}
                                disabled={loading}
                                className="px-4 py-2 bg-cyan-600 hover:bg-cyan-700 text-white text-xs font-black uppercase rounded-lg disabled:opacity-50"
                            >
                                Save & scan
                            </button>
                            <button
                                onClick={resetDefaults}
                                disabled={loading}
                                className="px-3 py-2 bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 text-[10px] font-bold uppercase rounded-lg"
                            >
                                Reset defaults
                            </button>
                            <button
                                onClick={() => {
                                    setDraft(settings);
                                    setSettingsOpen(false);
                                }}
                                className="px-3 py-2 text-[10px] font-bold uppercase text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                            >
                                Cancel
                            </button>
                            {draftDirty && (
                                <span className="text-[10px] font-bold text-amber-600">
                                    Unsaved changes
                                </span>
                            )}
                            <span className="text-[10px] text-zinc-400 ml-auto font-mono">
                                Preview: first {draft.fast_ma}/{draft.slow_ma} in {draft.window_days}
                                d · age ≤{Number(draft.max_bars_ago) + 1} bars · vol ≥
                                {draft.vol_mult}×
                            </span>
                        </div>
                    </div>
                )}

                <LoadingBanner
                    active={loading}
                    label={`Direct Fyers history API — ${maLabel} 15m per stock`}
                    progress={progress}
                    detail={
                        currentSym
                            ? `Now: ${currentSym.replace('NSE:', '').replace('-EQ', '')} · ${scanned}/${universe}`
                            : `Paced ~0.5s/call · full list ~1.5–2 min`
                    }
                />

                <div className="mb-4 p-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 text-[11px] text-zinc-600 dark:text-zinc-400 space-y-1">
                    <div>
                        <strong className="text-cyan-600">Active filters:</strong> first{' '}
                        <strong>
                            {settings.fast_ma}/{settings.slow_ma} EMA
                        </strong>{' '}
                        cross in <strong>{settings.window_days} days</strong>, age ≤{' '}
                        <strong>{settings.max_bars_ago + 1} closed 15m candles</strong>, volume ≥
                        <strong>{settings.vol_mult}×</strong>. Sideways re-crosses hidden.
                    </div>
                    <div>
                        Direct Fyers 15m history per stock. Progress:{' '}
                        <span className="font-mono font-bold">
                            {scanned}/{universe || '—'}
                        </span>{' '}
                        · momentum names: <span className="font-bold">{candidates.length}</span>
                        {apiInfo ? ` · ${apiInfo}` : ''}
                        {currentSym
                            ? ` · ${currentSym.replace('NSE:', '').replace('-EQ', '')}`
                            : ''}
                    </div>
                </div>

                {error && (
                    <div className="mb-4 p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-xs text-amber-700 dark:text-amber-300">
                        {error}
                    </div>
                )}

                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                    <div className="lg:col-span-3 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden">
                        <div className="px-4 py-3 border-b border-zinc-100 dark:border-zinc-800 flex justify-between">
                            <span className="text-xs font-black uppercase tracking-wider text-zinc-500">
                                Step 1 · Momentum first-cross board
                            </span>
                            <span className="text-[10px] text-zinc-400 font-bold">
                                First in {settings.window_days}d · age ≤
                                {settings.max_bars_ago + 1} · vol ≥{settings.vol_mult}×
                            </span>
                        </div>
                        <div className="overflow-x-auto max-h-[65vh] overflow-y-auto">
                            <table className="w-full text-left text-xs">
                                <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-900/95 text-[10px] uppercase text-zinc-500">
                                    <tr>
                                        <th className="px-3 py-2">Stock</th>
                                        <th className="px-3 py-2">LTP</th>
                                        <th className="px-3 py-2">Cross</th>
                                        <th className="px-3 py-2">Age</th>
                                        <th className="px-3 py-2">
                                            {settings.window_days}d
                                        </th>
                                        <th className="px-3 py-2">Vol</th>
                                        <th className="px-3 py-2">Score</th>
                                        <th className="px-3 py-2">Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {!loading && candidates.length === 0 && (
                                        <tr>
                                            <td
                                                colSpan={8}
                                                className="px-4 py-12 text-center text-zinc-500"
                                            >
                                                {scanned > 0
                                                    ? `No first-in-${settings.window_days}d ${maLabel} cross aged ≤${settings.max_bars_ago + 1} bars (momentum filter). Try ⚙ Settings.`
                                                    : 'Start a scan — direct API walks F&O names.'}
                                            </td>
                                        </tr>
                                    )}
                                    {candidates.map(c => (
                                        <tr
                                            key={c.symbol}
                                            className="border-t border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
                                        >
                                            <td className="px-3 py-2.5 font-black">{c.name}</td>
                                            <td className="px-3 py-2.5 font-mono">
                                                {c.ltp?.toLocaleString('en-IN', {
                                                    maximumFractionDigits: 2,
                                                })}
                                            </td>
                                            <td className="px-3 py-2.5">
                                                <span
                                                    className={`font-black text-[10px] uppercase px-1.5 py-0.5 rounded ${
                                                        c.cross_type === 'BULLISH'
                                                            ? 'bg-emerald-500/15 text-emerald-600'
                                                            : 'bg-rose-500/15 text-rose-600'
                                                    }`}
                                                >
                                                    {c.cross_type}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2.5">
                                                <span className="text-[10px] font-black text-cyan-600">
                                                    {c.fresh_label ||
                                                        (c.bars_ago === 0
                                                            ? '1 bar'
                                                            : c.bars_ago === 1
                                                              ? '2 bars'
                                                              : `${c.bars_ago} bars`)}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2.5 text-[10px] font-bold text-emerald-600">
                                                {c.first_cross_in_15d !== false
                                                    ? 'First ✓'
                                                    : '—'}
                                            </td>
                                            <td className="px-3 py-2.5 font-mono font-bold">
                                                {c.volume_ratio}×
                                            </td>
                                            <td className="px-3 py-2.5 font-black">
                                                {c.momentum_score ?? '—'}
                                            </td>
                                            <td className="px-3 py-2.5">
                                                <button
                                                    onClick={() => analyzeChain(c)}
                                                    disabled={analyzing === c.symbol || loading}
                                                    className="px-2.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-[10px] font-black uppercase rounded-lg disabled:opacity-50 whitespace-nowrap"
                                                >
                                                    {analyzing === c.symbol
                                                        ? '…'
                                                        : 'Analyze Chain'}
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="lg:col-span-2 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-4 min-h-[320px]">
                        <div className="text-xs font-black uppercase tracking-wider text-zinc-500">
                            Step 2–3 · Chain confirmation
                        </div>

                        {analyzing && (
                            <LoadingBanner
                                active
                                label="Fetching live option chain"
                                detail={analyzing}
                            />
                        )}

                        {analyzeError && (
                            <div className="p-3 rounded-xl border border-rose-500/30 bg-rose-500/10 text-xs text-rose-600">
                                {analyzeError}
                            </div>
                        )}

                        {!analysis && !analyzing && !analyzeError && (
                            <p className="text-sm text-zinc-500 py-8 text-center">
                                Wait for scan, then <strong>Analyze Chain</strong> on a candidate.
                            </p>
                        )}

                        {analysis && (
                            <div className="space-y-3">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-lg font-black">{analysis.name}</span>
                                    <span
                                        className={`text-[10px] font-black uppercase px-2 py-1 rounded border ${statusColor(
                                            analysis.status,
                                        )}`}
                                    >
                                        {analysis.status}
                                    </span>
                                </div>
                                <div
                                    className={`p-3 rounded-xl border text-sm font-bold ${statusColor(
                                        analysis.status,
                                    )}`}
                                >
                                    {analysis.decision}
                                    <div className="text-[11px] font-medium mt-1 opacity-90">
                                        {analysis.reason}
                                    </div>
                                </div>
                                <div className="text-[11px] space-y-1">
                                    <div>Primary: {analysis.primary_flow}</div>
                                    {analysis.secondary_flow && (
                                        <div>Secondary: {analysis.secondary_flow}</div>
                                    )}
                                    <div>OI PCR: {analysis.oi_pcr?.toFixed?.(2)}</div>
                                </div>
                                {analysis.rules_hit?.length > 0 && (
                                    <ul className="space-y-1">
                                        {analysis.rules_hit.map((r, i) => (
                                            <li
                                                key={i}
                                                className="text-[10px] text-zinc-600 dark:text-zinc-400"
                                            >
                                                ✓ <strong>{r.rule}</strong> — {r.detail}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                {analysis.status === 'CONFIRMED' &&
                                    analysis.suggested_strikes?.length > 0 && (
                                        <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5">
                                            <div className="text-[10px] font-black uppercase text-emerald-600 mb-2">
                                                Suggested strikes
                                            </div>
                                            {analysis.suggested_strikes.map((s, i) => (
                                                <div
                                                    key={i}
                                                    className="text-xs flex justify-between"
                                                >
                                                    <span className="text-zinc-500">{s.role}</span>
                                                    <span className="font-black font-mono">
                                                        {s.structure}
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                {analysis.report && (
                                    <pre className="text-[10px] p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-100 dark:border-zinc-800 whitespace-pre-wrap font-mono">
                                        {analysis.report}
                                    </pre>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
