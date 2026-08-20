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

interface TicketVehicle {
    style?: string;
    instrument?: string;
    strike?: number;
    structure?: string;
    why?: string;
}

interface Ticket {
    side?: string;
    trigger?: string;
    sponsor?: string;
    vehicle?: TicketVehicle;
    entry?: string;
    stop?: number;
    stop_src?: string;
    target1?: number;
    target1_src?: string;
    rr?: number;
    time_stop?: string;
    invalidation?: string;
    adx?: number;
    vwap?: number;
    mtf_allowed?: string;
    h4_bias?: string;
}

interface PermissionHit {
    rule: string;
    detail: string;
    w?: number;
}

interface Candidate {
    symbol: string;
    name: string;
    ltp: number;
    cross_type: 'BULLISH' | 'BEARISH' | string;
    kind?: string;
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
    approach_score?: number;
    body_strength?: number;
    adx?: number;
    vwap?: number;
    permission?: number;
    desk_score?: number;
    board?: 'TRADE' | 'WATCH' | 'REJECT' | string;
    board_reason?: string;
    grade?: string;
    h4_bias?: string;
    mtf_allowed?: string;
    mtf_gate?: string;
    futures_state?: string;
    buildup_note?: string;
    atm_iv?: number;
    put_wall?: number;
    call_wall?: number;
    ticket?: Ticket | null;
    permission_hits?: PermissionHit[];
    permission_miss?: string[];
}

interface SuggestedStrike {
    role: string;
    strike: number;
    instrument: string;
    structure: string;
    style?: string;
    why?: string;
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
    suggested_strikes: SuggestedStrike[];
    report: string;
    ticket?: Ticket | null;
    board?: string;
    board_reason?: string;
    permission?: number;
    desk_score?: number;
    h4_bias?: string;
    mtf_allowed?: string;
    adx?: number;
}

interface Props {
    onBack: () => void;
}

export default function MA7200Scanner({ onBack }: Props) {
    const [candidates, setCandidates] = useState<Candidate[]>([]);
    const [tradeRows, setTradeRows] = useState<Candidate[]>([]);
    const [watchRows, setWatchRows] = useState<Candidate[]>([]);
    const [rejectRows, setRejectRows] = useState<Candidate[]>([]);
    const [tab, setTab] = useState<'TRADE' | 'WATCH' | 'REJECT'>('TRADE');
    const [selected, setSelected] = useState<Candidate | null>(null);
    const [harvest, setHarvest] = useState<{
        symbols?: number;
        history_15_fresh?: number;
        freshest_age?: number | null;
        redis?: string;
    } | null>(null);
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
        setTradeRows([]);
        setWatchRows([]);
        setRejectRows([]);
        setSelected(null);
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

                    const trade = snap.trade || [];
                    const watch = snap.watch || [];
                    const reject = snap.reject || [];
                    const cands =
                        snap.candidates ||
                        [...trade, ...watch, ...reject].filter(Boolean);
                    if (cands.length) {
                        setCandidates(cands);
                        setTradeRows(
                            trade.length
                                ? trade
                                : cands.filter((c: Candidate) => c.board === 'TRADE'),
                        );
                        setWatchRows(
                            watch.length
                                ? watch
                                : cands.filter((c: Candidate) => c.board === 'WATCH'),
                        );
                        setRejectRows(
                            reject.length
                                ? reject
                                : cands.filter((c: Candidate) => c.board === 'REJECT'),
                        );
                    }
                    if (snap.harvest) setHarvest(snap.harvest);

                    if (snap.api) {
                        setApiInfo(
                            `store desk · ok ${snap.api.ok ?? '—'} · miss ${snap.api.fail ?? 0}` +
                                (snap.harvest?.history_15_fresh != null
                                    ? ` · 15m ${snap.harvest.history_15_fresh}/${snap.harvest.symbols ?? '—'}`
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
                        const t =
                            snap.trade ||
                            cands.filter((c: Candidate) => c.board === 'TRADE');
                        const w =
                            snap.watch ||
                            cands.filter((c: Candidate) => c.board === 'WATCH');
                        setTradeRows(t);
                        setWatchRows(w);
                        setRejectRows(
                            snap.reject ||
                                cands.filter((c: Candidate) => c.board === 'REJECT'),
                        );
                        if (t[0]) {
                            setSelected(t[0]);
                            setTab('TRADE');
                        } else if (w[0]) {
                            setSelected(w[0]);
                            setTab('WATCH');
                        }
                        if (snap.status === 'failed') {
                            setError(snap.error_message || 'Scan job failed');
                        } else if (t.length === 0 && w.length === 0) {
                            const s = settingsRef.current;
                            setError(
                                `Book scanned ${snap.scanned || snap.completed || 0}/${snap.universe || limit} — no TRADE/WATCH. Waiting harvest or 4H/OC gate empty. first-in-${s.window_days}d ${s.fast_ma}/${s.slow_ma}.`,
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

    const selectRow = (c: Candidate) => {
        setSelected(c);
        setAnalyzeError(null);
        if (c.ticket || c.board) {
            setAnalysis(null);
        }
    };

    const analyzeChain = async (c: Candidate) => {
        selectRow(c);
        setAnalyzing(c.symbol);
        setAnalyzeError(null);
        setAnalysis(null);
        try {
            const data = (await api.ma7200.analyze(
                c.symbol,
                c.cross_type,
                14,
            )) as AnalyzeResult;
            setAnalysis(data);
        } catch (e: any) {
            setAnalyzeError(e?.message || 'Chain analysis failed');
        } finally {
            setAnalyzing(null);
        }
    };

    const statusColor = (s?: string) => {
        if (s === 'CONFIRMED' || s === 'TRADE' || s === 'A-SETUP' || s === 'SETUP')
            return 'text-emerald-500 border-emerald-500/40 bg-emerald-500/10';
        if (s === 'CONFLICT' || s === 'REJECT')
            return 'text-rose-500 border-rose-500/40 bg-rose-500/10';
        return 'text-amber-600 border-amber-500/40 bg-amber-500/10';
    };

    const maLabel = `${settings.fast_ma}/${settings.slow_ma}`;
    const visibleRows =
        tab === 'TRADE' ? tradeRows : tab === 'WATCH' ? watchRows : rejectRows;
    const ticket = selected?.ticket || analysis?.ticket || null;
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
                                15m first-cross · 4H allowed_side · OC/futures ticket
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
                            {loading ? 'Scoring book…' : `↻ Rescore ${maLabel}`}
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
                    label={`Scoring harvest book — ${maLabel} 15m + stored chain`}
                    progress={progress}
                    detail={
                        currentSym
                            ? `Now: ${currentSym.replace('NSE:', '').replace('-EQ', '')} · ${scanned}/${universe}`
                            : `CPU only · 4H gate · no Fyers walk`
                    }
                />

                {harvest && (
                    <div className="mb-3 inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border border-zinc-700 bg-zinc-900/80 text-zinc-400">
                        <span
                            className={`w-1.5 h-1.5 rounded-full ${
                                harvest.redis === 'ok' ? 'bg-emerald-500' : 'bg-amber-400'
                            }`}
                        />
                        Book age{' '}
                        {harvest.freshest_age != null
                            ? `${Math.round(harvest.freshest_age)}s`
                            : '—'}
                        {' · '}
                        15m {harvest.history_15_fresh ?? 0}/{harvest.symbols ?? 0}
                        {' · '}
                        {harvest.redis === 'ok' ? 'Redis' : 'Memory'}
                    </div>
                )}

                <div className="mb-4 p-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 text-[11px] text-zinc-600 dark:text-zinc-400 space-y-1">
                    <div>
                        <strong className="text-cyan-600">Desk rules:</strong> first{' '}
                        <strong>
                            {settings.fast_ma}/{settings.slow_ma}
                        </strong>{' '}
                        in <strong>{settings.window_days}d</strong>, vol ≥
                        <strong>{settings.vol_mult}×</strong>. Bar-2 only if ext ≤1.2% and P≥70.
                        4H <strong>allowed_side</strong> is a hard gate. Max pain not used. IV
                        picks outright vs debit spread.
                    </div>
                    <div>
                        Progress:{' '}
                        <span className="font-mono font-bold">
                            {scanned}/{universe || '—'}
                        </span>{' '}
                        · TRADE {tradeRows.length} · WATCH {watchRows.length} · REJECT{' '}
                        {rejectRows.length}
                        {apiInfo ? ` · ${apiInfo}` : ''}
                    </div>
                </div>

                {error && (
                    <div className="mb-4 p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-xs text-amber-700 dark:text-amber-300">
                        {error}
                    </div>
                )}

                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                    <div className="lg:col-span-3 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden">
                        <div className="px-4 py-3 border-b border-zinc-100 dark:border-zinc-800 flex flex-wrap gap-2 justify-between items-center">
                            <div className="flex gap-1">
                                {(
                                    [
                                        ['TRADE', tradeRows.length],
                                        ['WATCH', watchRows.length],
                                        ['REJECT', rejectRows.length],
                                    ] as const
                                ).map(([id, n]) => (
                                    <button
                                        key={id}
                                        onClick={() => setTab(id)}
                                        className={`px-3 py-1.5 text-[10px] font-black uppercase rounded-lg ${
                                            tab === id
                                                ? id === 'TRADE'
                                                    ? 'bg-emerald-600 text-white'
                                                    : id === 'WATCH'
                                                      ? 'bg-amber-600 text-white'
                                                      : 'bg-zinc-600 text-white'
                                                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500'
                                        }`}
                                    >
                                        {id} {n}
                                    </button>
                                ))}
                            </div>
                            <span className="text-[10px] text-zinc-400 font-bold">
                                4H gate · first {settings.window_days}d · vol ≥{settings.vol_mult}×
                            </span>
                        </div>
                        <div className="overflow-x-auto max-h-[65vh] overflow-y-auto">
                            <table className="w-full text-left text-xs">
                                <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-900/95 text-[10px] uppercase text-zinc-500">
                                    <tr>
                                        <th className="px-3 py-2">Stock</th>
                                        <th className="px-3 py-2">LTP</th>
                                        <th className="px-3 py-2">Side</th>
                                        <th className="px-3 py-2">Age</th>
                                        <th className="px-3 py-2">ADX</th>
                                        <th className="px-3 py-2">4H</th>
                                        <th className="px-3 py-2">P</th>
                                        <th className="px-3 py-2">Desk</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {!loading && visibleRows.length === 0 && (
                                        <tr>
                                            <td
                                                colSpan={8}
                                                className="px-4 py-12 text-center text-zinc-500"
                                            >
                                                {scanned > 0
                                                    ? tab === 'TRADE'
                                                        ? 'No permissioned tickets. Check WATCH (NEAR / 4H mixed / thin OC) or wait for harvest.'
                                                        : `No ${tab} rows.`
                                                    : 'Rescore the harvest book to fill the desk.'}
                                            </td>
                                        </tr>
                                    )}
                                    {visibleRows.map(c => (
                                        <tr
                                            key={`${c.symbol}-${c.kind || c.fresh_label}`}
                                            onClick={() => selectRow(c)}
                                            className={`border-t border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/40 cursor-pointer ${
                                                selected?.symbol === c.symbol
                                                    ? 'bg-cyan-500/10'
                                                    : ''
                                            }`}
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
                                                    {c.kind === 'NEAR' ? 'NEAR ' : ''}
                                                    {c.cross_type}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2.5">
                                                <span className="text-[10px] font-black text-cyan-600">
                                                    {c.fresh_label ||
                                                        (c.bars_ago === 0
                                                            ? 'just closed'
                                                            : c.bars_ago === 1
                                                              ? '1 bar'
                                                              : c.bars_ago === 2
                                                                ? '2 bars'
                                                                : `${c.bars_ago} bars`)}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2.5 font-mono text-[11px]">
                                                {c.adx ?? '—'}
                                            </td>
                                            <td className="px-3 py-2.5 text-[10px] font-bold">
                                                {c.h4_bias || c.mtf_allowed || '—'}
                                            </td>
                                            <td className="px-3 py-2.5 font-mono font-bold">
                                                {c.permission ?? '—'}
                                            </td>
                                            <td className="px-3 py-2.5 font-black">
                                                {c.desk_score ?? c.momentum_score ?? '—'}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="lg:col-span-2 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-4 min-h-[320px]">
                        <div className="text-xs font-black uppercase tracking-wider text-zinc-500">
                            Ticket
                        </div>

                        {analyzing && (
                            <LoadingBanner
                                active
                                label="Re-scoring stored chain"
                                detail={analyzing}
                            />
                        )}

                        {analyzeError && (
                            <div className="p-3 rounded-xl border border-rose-500/30 bg-rose-500/10 text-xs text-rose-600">
                                {analyzeError}
                            </div>
                        )}

                        {!selected && !analysis && !analyzing && (
                            <p className="text-sm text-zinc-500 py-8 text-center">
                                Select a row. TRADE rows already have a ticket — no extra fetch.
                            </p>
                        )}

                        {(selected || analysis) && (
                            <div className="space-y-3">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-lg font-black">
                                        {selected?.name || analysis?.name}
                                    </span>
                                    <span
                                        className={`text-[10px] font-black uppercase px-2 py-1 rounded border ${statusColor(
                                            selected?.board || analysis?.status,
                                        )}`}
                                    >
                                        {selected?.grade ||
                                            selected?.board ||
                                            analysis?.status}
                                    </span>
                                </div>
                                <div
                                    className={`p-3 rounded-xl border text-sm font-bold ${statusColor(
                                        selected?.board || analysis?.status,
                                    )}`}
                                >
                                    {selected?.board_reason ||
                                        analysis?.reason ||
                                        analysis?.decision}
                                    <div className="text-[11px] font-medium mt-1 opacity-90">
                                        4H {selected?.h4_bias || analysis?.h4_bias || '—'} ·
                                        allowed {selected?.mtf_allowed || analysis?.mtf_allowed || '—'}
                                        {' · '}ADX {selected?.adx ?? analysis?.adx ?? '—'}
                                        {' · '}P {selected?.permission ?? analysis?.permission ?? '—'}
                                    </div>
                                </div>

                                {ticket ? (
                                    <div className="space-y-2 text-[11px]">
                                        <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 space-y-1.5">
                                            <div className="text-[10px] font-black uppercase text-emerald-600">
                                                {ticket.side} · {ticket.vehicle?.style}
                                            </div>
                                            <div className="text-sm font-black font-mono">
                                                {ticket.vehicle?.structure}
                                            </div>
                                            <div className="text-zinc-500">
                                                {ticket.vehicle?.why}
                                            </div>
                                            <div>Entry: {ticket.entry}</div>
                                            <div>
                                                Stop: <strong>{ticket.stop}</strong> ({ticket.stop_src})
                                            </div>
                                            <div>
                                                Target: <strong>{ticket.target1}</strong> (
                                                {ticket.target1_src})
                                            </div>
                                            <div>R:R {ticket.rr ?? '—'} · {ticket.time_stop}</div>
                                            <div className="text-zinc-500">{ticket.invalidation}</div>
                                        </div>
                                    </div>
                                ) : (
                                    <p className="text-[11px] text-zinc-500">
                                        No ticket — {selected?.board_reason || 'not permissioned'}.
                                        4H opposite the cross is a hard block even with a strong
                                        chain.
                                    </p>
                                )}

                                {(selected?.permission_hits?.length ||
                                    analysis?.rules_hit?.length) && (
                                    <ul className="space-y-1">
                                        {(selected?.permission_hits || analysis?.rules_hit || []).map(
                                            (r, i) => (
                                                <li
                                                    key={i}
                                                    className="text-[10px] text-zinc-600 dark:text-zinc-400"
                                                >
                                                    ✓ <strong>{r.rule}</strong> — {r.detail}
                                                </li>
                                            ),
                                        )}
                                    </ul>
                                )}
                                {selected?.permission_miss &&
                                    selected.permission_miss.length > 0 && (
                                        <ul className="space-y-1">
                                            {selected.permission_miss.slice(0, 4).map((m, i) => (
                                                <li
                                                    key={i}
                                                    className="text-[10px] text-zinc-500"
                                                >
                                                    · {m}
                                                </li>
                                            ))}
                                        </ul>
                                    )}

                                <button
                                    onClick={() => selected && analyzeChain(selected)}
                                    disabled={!selected || analyzing === selected?.symbol}
                                    className="w-full px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-white text-[10px] font-black uppercase rounded-lg disabled:opacity-50"
                                >
                                    Re-score this name
                                </button>

                                {analysis?.report && (
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
