'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import LoadingBanner from './ui/LoadingBanner';

interface TradeGuide {
    type: string;
    strike: number;
    instrument: string;
    rationale: string;
}

interface BuildupActionable {
    strike: number;
    side: string;
    state: string;
    strength: string;
    oi_change?: number;
    fade_risk?: boolean;
}

interface BuildupSummary {
    primary_state?: string;
    bias?: string;
    conviction?: string;
    note?: string;
    strong_long_ce?: number;
    strong_long_pe?: number;
    short_covering_calls?: number;
    actionable?: BuildupActionable[];
    atm_band?: Array<{
        strike: number;
        call?: { state?: string; strength?: string };
        put?: { state?: string; strength?: string };
    }>;
}

interface StockAnalysisRow {
    symbol: string;
    spot_price: number;
    atm_strike: number;
    state: string;
    intent_score: number;
    confidence: number;
    message: string;
    time_window: string;
    tradable: boolean;
    pcr: number;
    pcr_signal?: string;
    vix: number;
    support: number;
    resistance: number;
    quant_score?: number;
    quant_bias?: string;
    quant_conviction?: string;
    quant_factors?: string[];
    /** Single source of truth for bull/bear columns */
    setup_side?: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | string;
    max_pain?: number;
    expected_move?: number;
    expected_move_pct?: number;
    iv_skew?: number;
    iv_skew_label?: string;
    gamma_wall?: number;
    pin_risk?: number;
    /** Desk-style four-state buildup */
    buildup_state?: string;
    buildup_strength?: string;
    buildup_note?: string;
    buildup_bias?: string;
    buildup?: BuildupSummary;
    oi_pcr?: number;
    volume_pcr?: number;
    atm_pcr?: number;
    band_pcr?: number;
    pcr_regime?: string;
    pcr_regime_label?: string;
    pcr_health?: string;
    call_wall?: number;
    put_wall?: number;
    call_wall_oi?: number;
    put_wall_oi?: number;
    technical?: {
        ok?: boolean;
        bias?: string;
        tech_score?: number;
        long_signal?: boolean;
        short_signal?: boolean;
        note?: string;
        blocked_reason?: string;
        intraday?: {
            ema7?: number;
            ema20?: number;
            ema_stack?: string;
            volume_ratio?: number;
            bias?: string;
            note?: string;
        };
        htf?: {
            bias?: string;
            ema20?: number;
            ema50?: number;
            ema200?: number;
            note?: string;
            timeframe?: string;
        };
    };
    premium?: {
        ok?: boolean;
        has_history?: boolean;
        premium_score?: number;
        bias?: string;
        flags?: string[];
        note?: string;
        squeeze_risk?: boolean;
        vol_expand_risk?: boolean;
        straddle?: number;
        straddle_chg_pct?: number;
    };
    tech_bias?: string;
    tech_score?: number;
    entry_long?: boolean;
    entry_short?: boolean;
    watch_long?: boolean;
    watch_short?: boolean;
    lean_bias?: string;
    vol_confirm_long?: boolean;
    vol_confirm_short?: boolean;
    atm_call_volume?: number;
    atm_put_volume?: number;
    atm_ce_rel_vol?: number;
    atm_pe_rel_vol?: number;
    ce_vol_share?: number;
    squeeze_risk?: boolean;
    vol_expand_risk?: boolean;
    score_components?: {
        option_score?: number;
        tech_score?: number;
        premium_score?: number;
        total?: number;
        flow_score?: number;
        pcr_penalty?: number;
        gamma_penalty?: number;
        max_score_cap?: number;
        raw?: number;
    };
    action?: string;
    side_preference?: string;
    max_score_cap?: number;
    verdict?: string;
    conflicted?: boolean;
    prefer_defined_risk?: boolean;
    decision_narrative?: string;
    skew_label?: string;
    strike_guidance?: {
        suggested: boolean;
        bias: string;
        trades: TradeGuide[];
        expert_note: string;
    };
    institutional_flow?: {
        intent_score: number;
        big_money_present: boolean;
        clusters: Array<{
            strike: number;
            type: string;
            strength: number;
            is_institutional: boolean;
        }>;
    };
    deep_analytics?: {
        pcr?: {
            oi_pcr?: number;
            volume_pcr?: number;
            atm_oi_pcr?: number;
            band_oi_pcr?: number;
            oi_bias?: string;
            volume_bias?: string;
            regime?: string;
            regime_label?: string;
            health?: string;
        };
        straddle?: {
            straddle?: number;
            expected_move?: number;
            expected_move_pct?: number;
            upper_1sd?: number;
            lower_1sd?: number;
        };
        iv_structure?: {
            atm_iv?: number;
            skew?: number;
            risk_reversal?: number;
            skew_label?: string;
            iv_bias?: string;
        };
        greeks_walls?: {
            gamma_wall_strike?: number;
            pin_risk?: number;
            delta_bias?: string;
            net_delta_oi?: number;
        };
        max_pain?: {
            max_pain?: number;
            distance_from_spot?: number;
            distance_pct?: number;
        };
        walls?: {
            call_wall?: number;
            put_wall?: number;
            call_wall_oi?: number;
            put_wall_oi?: number;
        };
        buildup?: BuildupSummary;
        premium_dislocation?: {
            best_gap?: {
                gap?: number;
                gap_pct?: number;
                cheap_side?: string;
                undervalued_strike?: number;
                call_strike?: number;
                put_strike?: number;
            } | null;
        };
        quant?: {
            quant_score?: number;
            bias?: string;
            conviction?: string;
            factors?: string[];
            primary_buildup?: string;
            buildup_note?: string;
        };
    };
}

interface ScanResponse {
    success: boolean;
    count: number;
    total_scanned: number;
    completed?: number;
    tradable_count: number;
    universe_requested?: number;
    completion_pct?: number;
    bullish_count?: number;
    bearish_count?: number;
    neutral_count?: number;
    top_only?: boolean;
    partial?: boolean;
    rate_limited_skips?: number;
    stocks: StockAnalysisRow[];
    error_count?: number;
    timestamp: string;
    job_id?: string;
    status?: string;
    current_symbol?: string | null;
    failed_symbols?: string[];
}

type FilterType = 'all' | 'tradable' | 'TREND' | 'INTENT' | 'ADJUSTMENT' | 'HIGH_QUANT';
type ScopeType = 'full' | 'top';

interface StockAnalysisProps {
    onBack: () => void;
}

export default function StockAnalysis({ onBack }: StockAnalysisProps) {
    const [filter, setFilter] = useState<FilterType>('all');
    const [scope, setScope] = useState<ScopeType>('full');
    const [selected, setSelected] = useState<string | null>(null);
    const [progress, setProgress] = useState(0);
    const [search, setSearch] = useState('');
    const [data, setData] = useState<ScanResponse | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isFetching, setIsFetching] = useState(false);
    const [error, setError] = useState<Error | null>(null);
    const [jobId, setJobId] = useState<string | null>(null);
    const [currentSymbol, setCurrentSymbol] = useState<string | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const runIdRef = useRef(0);

    const limit = scope === 'full' ? 200 : 40;
    const isError = !!error;

    const stopPolling = useCallback(() => {
        if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    }, []);

    const applyJobSnapshot = useCallback((snap: any, opts?: { mergeBase?: ScanResponse | null }) => {
        let stocks: StockAnalysisRow[] = snap.stocks || [];
        // Client-side safety merge when retry job streams only new rows early
        if (opts?.mergeBase?.stocks?.length && stocks.length) {
            const map = new Map<string, StockAnalysisRow>();
            for (const r of opts.mergeBase.stocks) {
                if (r.symbol) map.set(r.symbol, r);
            }
            for (const r of stocks) {
                if (r.symbol) map.set(r.symbol, r);
            }
            stocks = Array.from(map.values());
        } else if (opts?.mergeBase?.stocks?.length && !stocks.length) {
            stocks = opts.mergeBase.stocks;
        }

        setProgress(Number(snap.completion_pct ?? 0));
        setCurrentSymbol(snap.current_symbol || null);

        const bull = stocks.filter(s => (s.setup_side || s.quant_bias) === 'BULLISH').length;
        const bear = stocks.filter(s => (s.setup_side || s.quant_bias) === 'BEARISH').length;
        const neut = stocks.filter(
            s => (s.setup_side || s.quant_bias) !== 'BULLISH' && (s.setup_side || s.quant_bias) !== 'BEARISH',
        ).length;

        // Stream partial rows while job runs so UI is never empty forever
        if (stocks.length > 0 || snap.status === 'completed' || snap.status === 'failed') {
            const universe =
                snap.universe_requested ??
                opts?.mergeBase?.universe_requested ??
                snap.total;
            setData({
                success: true,
                count: snap.count ?? stocks.length,
                total_scanned: snap.total_scanned ?? (snap.completed || 0) + (snap.failed || 0),
                completed: snap.completed ?? stocks.length,
                tradable_count: snap.tradable_count ?? stocks.filter((s: any) => s.tradable).length,
                universe_requested: universe,
                completion_pct: snap.completion_pct,
                bullish_count: snap.bullish_count ?? bull,
                bearish_count: snap.bearish_count ?? bear,
                neutral_count: snap.neutral_count ?? neut,
                top_only: scope === 'top',
                partial:
                    snap.partial ||
                    (snap.status === 'completed' &&
                        stocks.length < (universe || stocks.length + 1)),
                rate_limited_skips: snap.rate_limited_skips,
                stocks,
                error_count: snap.error_count,
                timestamp: snap.timestamp || new Date().toISOString(),
                job_id: snap.job_id,
                status: snap.status,
                current_symbol: snap.current_symbol,
                failed_symbols: snap.failed_symbols,
            });
        }
    }, [scope]);

    const startScan = useCallback(async (opts?: { retryJobId?: string }) => {
        const myRun = ++runIdRef.current;
        stopPolling();
        setIsFetching(true);
        setError(null);
        // Capture previous grid for client merge during retry
        const mergeBase = opts?.retryJobId ? data : null;
        if (!data) setIsLoading(true);
        setProgress(p => (p > 0 && data ? p : 2));
        setCurrentSymbol(null);

        try {
            let started: any;
            if (opts?.retryJobId) {
                started = await api.market.retryFailedStockScan(opts.retryJobId);
                if (!started.job_id) {
                    // nothing to retry
                    setIsFetching(false);
                    setIsLoading(false);
                    return;
                }
            } else {
                started = await api.market.startStockScan(
                    limit,
                    false,
                    scope === 'top',
                    10,
                    true,
                );
            }
            if (myRun !== runIdRef.current) return;

            const jid = started.job_id as string;
            setJobId(jid);

            const pollOnce = async () => {
                if (myRun !== runIdRef.current) return;
                try {
                    const snap = await api.market.getStockScanJob(jid, true);
                    if (myRun !== runIdRef.current) return;
                    applyJobSnapshot(snap, {
                        mergeBase: opts?.retryJobId ? mergeBase : null,
                    });
                    const done =
                        snap.status === 'completed' ||
                        snap.status === 'failed' ||
                        snap.status === 'cancelled';
                    if (done) {
                        stopPolling();
                        setIsLoading(false);
                        setIsFetching(false);
                        if (snap.status === 'failed') {
                            setError(new Error(snap.error_message || 'Scan job failed'));
                        }
                    }
                } catch (e: any) {
                    if (myRun !== runIdRef.current) return;
                    stopPolling();
                    setIsLoading(false);
                    setIsFetching(false);
                    setError(e instanceof Error ? e : new Error(e?.message || 'Poll failed'));
                }
            };

            await pollOnce();
            if (myRun !== runIdRef.current) return;
            // Keep polling until terminal state
            pollRef.current = setInterval(pollOnce, 1500);
        } catch (e: any) {
            if (myRun !== runIdRef.current) return;
            setIsLoading(false);
            setIsFetching(false);
            setError(e instanceof Error ? e : new Error(e?.message || 'Failed to start scan'));
        }
    }, [applyJobSnapshot, data, limit, scope, stopPolling]);

    // Start scan when scope changes / mount
    useEffect(() => {
        startScan();
        return () => {
            runIdRef.current += 1;
            stopPolling();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [scope, limit]);

    const refetch = useCallback(() => startScan(), [startScan]);
    const retryFailed = useCallback(() => {
        if (jobId) startScan({ retryJobId: jobId });
        else startScan();
    }, [jobId, startScan]);

    const stateColors: Record<string, string> = {
        TREND: 'bg-blue-500',
        RANGE: 'bg-amber-500',
        INTENT: 'bg-emerald-500',
        ADJUSTMENT: 'bg-purple-500',
        'NO-TRADE': 'bg-zinc-600',
    };

    const stateBorderColors: Record<string, string> = {
        TREND: 'border-blue-500/30',
        RANGE: 'border-amber-500/30',
        INTENT: 'border-emerald-500/30',
        ADJUSTMENT: 'border-purple-500/30',
        'NO-TRADE': 'border-zinc-600/30',
    };

    const biasColor = (b?: string) =>
        b === 'BULLISH'
            ? 'text-emerald-500'
            : b === 'BEARISH'
              ? 'text-rose-500'
              : 'text-zinc-400';

    /** Single consistent side for columns + detail panel */
    const sideOf = (s: StockAnalysisRow): 'BULLISH' | 'BEARISH' | 'NEUTRAL' => {
        const side = s.setup_side || s.quant_bias;
        if (side === 'BULLISH' || side === 'BEARISH') return side;
        const g = s.strike_guidance?.bias;
        if (g === 'BULLISH' || g === 'BEARISH') return g;
        return 'NEUTRAL';
    };

    const filteredStocks = useMemo(() => {
        let rows = data?.stocks || [];
        if (search.trim()) {
            const q = search.trim().toUpperCase();
            rows = rows.filter(
                s =>
                    s.symbol?.toUpperCase().includes(q) ||
                    s.symbol?.replace('NSE:', '').replace('-EQ', '').includes(q),
            );
        }
        if (filter === 'tradable') rows = rows.filter(s => s.tradable);
        else if (filter === 'HIGH_QUANT')
            rows = rows.filter(s => (s.quant_score || 0) >= 60);
        else if (filter !== 'all') rows = rows.filter(s => s.state === filter);
        // Sort by quant only (no side preference)
        return [...rows].sort(
            (a, b) => (b.quant_score || 0) - (a.quant_score || 0),
        );
    }, [data?.stocks, filter, search]);

    const bullStocks = useMemo(
        () => filteredStocks.filter(s => sideOf(s) === 'BULLISH'),
        [filteredStocks],
    );
    const bearStocks = useMemo(
        () => filteredStocks.filter(s => sideOf(s) === 'BEARISH'),
        [filteredStocks],
    );
    const neutralStocks = useMemo(
        () => filteredStocks.filter(s => sideOf(s) === 'NEUTRAL'),
        [filteredStocks],
    );

    const selectedStock =
        filteredStocks.find(s => s.symbol === selected) ||
        bullStocks[0] ||
        bearStocks[0] ||
        neutralStocks[0] ||
        null;

    useEffect(() => {
        if (!selected && selectedStock) {
            setSelected(selectedStock.symbol);
        }
    }, [filteredStocks, selected, selectedStock]);

    const extractStockName = (symbol: string) =>
        symbol?.replace('NSE:', '').replace('-EQ', '') || '—';

    const summary = useMemo(() => {
        const rows = data?.stocks || [];
        const avgQuant =
            rows.length > 0
                ? rows.reduce((a, r) => a + (r.quant_score || 0), 0) / rows.length
                : 0;
        const bull = rows.filter(r => sideOf(r) === 'BULLISH').length;
        const bear = rows.filter(r => sideOf(r) === 'BEARISH').length;
        const neutral = rows.filter(r => sideOf(r) === 'NEUTRAL').length;
        return {
            avgQuant: Math.round(avgQuant),
            bull,
            bear,
            neutral,
            highQuant: rows.filter(r => (r.quant_score || 0) >= 70).length,
        };
    }, [data?.stocks]);

    if (isLoading && !data) {
        return (
            <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8">
                <div className="max-w-7xl mx-auto space-y-6">
                    <div className="animate-pulse h-10 w-72 bg-zinc-200 dark:bg-zinc-800 rounded" />
                    <LoadingBanner
                        active
                        label={
                            scope === 'full'
                                ? 'Starting full F&O quant job…'
                                : 'Starting top-liquid quant job…'
                        }
                        progress={progress}
                        detail={
                            currentSymbol
                                ? `Analyzing ${currentSymbol} · server job ${jobId || '…'}`
                                : 'Real progress from backend job (not fake timer)'
                        }
                    />
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {[...Array(6)].map((_, i) => (
                            <div
                                key={i}
                                className="h-40 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl animate-pulse"
                            />
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8">
            <div className="max-w-7xl mx-auto">
                <header className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4 mb-6">
                    <div className="flex items-center gap-3">
                        <button
                            onClick={onBack}
                            className="p-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
                        >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M10 19l-7-7m0 0l7-7m-7 7h18"
                                />
                            </svg>
                        </button>
                        <div>
                            <h1 className="text-2xl font-black italic tracking-tighter uppercase">
                                F&O Stock Quant<span className="text-blue-600">.</span>
                            </h1>
                            <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest">
                                {data?.completed ?? data?.count ?? 0}/
                                {data?.universe_requested || limit} complete
                                {data?.completion_pct != null
                                    ? ` (${data.completion_pct}%)`
                                    : ''}{' '}
                                · {data?.tradable_count || 0} tradable
                                {data?.partial ? ' · partial (rate limits)' : ''}
                                {data?.error_count ? ` · ${data.error_count} errors` : ''}
                            </p>
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <div className="flex rounded-lg overflow-hidden border border-zinc-200 dark:border-zinc-700">
                            <button
                                onClick={() => setScope('full')}
                                className={`px-3 py-2 text-[10px] font-bold uppercase ${
                                    scope === 'full'
                                        ? 'bg-blue-600 text-white'
                                        : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500'
                                }`}
                            >
                                Full F&O
                            </button>
                            <button
                                onClick={() => setScope('top')}
                                className={`px-3 py-2 text-[10px] font-bold uppercase ${
                                    scope === 'top'
                                        ? 'bg-blue-600 text-white'
                                        : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500'
                                }`}
                            >
                                Top Liquid
                            </button>
                        </div>
                        <input
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            placeholder="Search symbol…"
                            className="px-3 py-2 text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 w-36"
                        />
                        <button
                            onClick={() => refetch()}
                            disabled={isFetching}
                            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg disabled:opacity-50"
                        >
                            {isFetching ? 'Scanning…' : '🔄 Deep Scan'}
                        </button>
                    </div>
                </header>

                <LoadingBanner
                    active={isLoading || isFetching}
                    label={
                        scope === 'full'
                            ? 'Deep-scanning full F&O universe'
                            : 'Scanning top liquid F&O'
                    }
                    progress={progress}
                    detail={
                        currentSymbol
                            ? `Now: ${currentSymbol.replace('NSE:', '').replace('-EQ', '')} · ${data?.completed ?? 0}/${data?.universe_requested ?? limit} done`
                            : isFetching && data?.stocks?.length
                              ? `Live job… ${data.completed ?? data.count} analyzed so far (previous rows still visible)`
                              : 'Background job · option chains · max pain · IV skew · gamma walls · quant votes'
                    }
                />
                {data?.partial && !isFetching && (
                    <div className="mb-4 p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-[11px] text-amber-700 dark:text-amber-300 font-medium flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                        <span>
                            Partial scan: {data.completed ?? data.count} of {data.universe_requested}{' '}
                            stocks completed
                            {data.rate_limited_skips
                                ? ` (${data.rate_limited_skips} skipped by Fyers rate limit)`
                                : ''}
                            {data.failed_symbols?.length
                                ? ` · ${data.failed_symbols.length} failed`
                                : ''}
                            .
                        </span>
                        <button
                            type="button"
                            onClick={retryFailed}
                            disabled={isFetching}
                            className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-[10px] font-black uppercase tracking-wider disabled:opacity-50 shrink-0"
                        >
                            Retry failed only
                        </button>
                    </div>
                )}
                {error && (
                    <div className="mb-4 p-3 rounded-xl border border-rose-500/30 bg-rose-500/10 text-[11px] text-rose-600 dark:text-rose-300 font-medium">
                        {error.message}
                        <button
                            type="button"
                            onClick={() => refetch()}
                            className="ml-3 underline font-bold"
                        >
                            Retry full scan
                        </button>
                    </div>
                )}

                {/* Universe summary — balanced bull/bear counts */}
                <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-6">
                    {[
                        { label: 'Analyzed', value: data?.count ?? 0, cls: '' },
                        { label: 'Tradable', value: data?.tradable_count ?? 0, cls: '' },
                        { label: 'Avg Quant', value: summary.avgQuant, cls: '' },
                        {
                            label: 'Bullish',
                            value: data?.bullish_count ?? summary.bull,
                            cls: 'text-emerald-500',
                        },
                        {
                            label: 'Bearish',
                            value: data?.bearish_count ?? summary.bear,
                            cls: 'text-rose-500',
                        },
                        {
                            label: 'Neutral',
                            value: data?.neutral_count ?? summary.neutral,
                            cls: 'text-zinc-400',
                        },
                    ].map(c => (
                        <div
                            key={c.label}
                            className="p-3 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800"
                        >
                            <div className="text-[9px] font-bold text-zinc-500 uppercase">{c.label}</div>
                            <div className={`text-lg font-black ${c.cls}`}>{c.value}</div>
                        </div>
                    ))}
                </div>
                <p className="text-[10px] text-zinc-500 mb-4 font-medium">
                    Priority: <span className="font-bold">HTF gate → PCR structure → Buildup → Gamma/MaxPain → Skew → 15m</span>
                    {' '}· conflict defaults to <span className="font-bold">WAIT</span> (never forced BUY)
                </p>

                {error && (
                    <div className="p-4 bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 rounded-xl mb-6 text-sm text-rose-600">
                        {error.message}
                    </div>
                )}

                {/* Filters */}
                <div className="flex gap-2 mb-4 overflow-x-auto pb-2">
                    {(
                        [
                            ['all', 'All'],
                            ['tradable', 'Tradable'],
                            ['HIGH_QUANT', 'Quant ≥ 60'],
                            ['TREND', 'Trend'],
                            ['INTENT', 'Intent'],
                            ['ADJUSTMENT', 'Adjustment'],
                        ] as const
                    ).map(([key, label]) => (
                        <button
                            key={key}
                            onClick={() => setFilter(key)}
                            className={`px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-lg whitespace-nowrap ${
                                filter === key
                                    ? 'bg-blue-600 text-white'
                                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500'
                            }`}
                        >
                            {label}
                        </button>
                    ))}
                </div>

                {/* Two equal columns: Bullish | Bearish */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
                    <SideColumn
                        title="Bullish Lean"
                        subtitle={`${bullStocks.length} names · flow lean (incl. WATCH) · action may be WAIT`}
                        tone="bull"
                        stocks={bullStocks}
                        selected={selected}
                        onSelect={setSelected}
                        extractStockName={extractStockName}
                        stateColors={stateColors}
                    />
                    <SideColumn
                        title="Bearish Lean"
                        subtitle={`${bearStocks.length} names · flow lean (incl. WATCH) · action may be WAIT`}
                        tone="bear"
                        stocks={bearStocks}
                        selected={selected}
                        onSelect={setSelected}
                        extractStockName={extractStockName}
                        stateColors={stateColors}
                    />
                </div>

                {neutralStocks.length > 0 && (
                    <div className="mb-4 p-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
                        <div className="text-[10px] font-black uppercase text-zinc-500 mb-2">
                            Neutral / No majority ({neutralStocks.length}) — not forced into either side
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {neutralStocks.map(s => (
                                <button
                                    key={s.symbol}
                                    onClick={() => setSelected(s.symbol)}
                                    className={`text-[10px] px-2 py-1 rounded-lg font-bold border ${
                                        selected === s.symbol
                                            ? 'border-blue-500 bg-blue-500/10'
                                            : 'border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800'
                                    }`}
                                >
                                    {extractStockName(s.symbol)}{' '}
                                    <span className="text-zinc-400">
                                        Q{s.quant_score?.toFixed?.(0) ?? '—'}
                                    </span>
                                </button>
                            ))}
                        </div>
                    </div>
                )}

                {/* Deep panel */}
                <div>
                    {selectedStock ? (
                        <DeepPanel stock={selectedStock} biasColor={biasColor} />
                    ) : (
                        <div className="p-8 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-500 text-sm">
                            Select a stock from Bullish or Bearish column for full math analytics.
                        </div>
                    )}
                </div>

                <footer className="mt-10 pt-6 border-t border-zinc-200 dark:border-zinc-800 flex justify-between text-[10px] font-bold text-zinc-400 uppercase tracking-widest">
                    <span>
                        Updated:{' '}
                        {data?.timestamp
                            ? new Date(data.timestamp).toLocaleTimeString()
                            : '—'}
                    </span>
                    <span>Buildup · PCR triad · Walls · Max Pain · Gamma · Quant</span>
                </footer>
            </div>
        </div>
    );
}

function SideColumn({
    title,
    subtitle,
    tone,
    stocks,
    selected,
    onSelect,
    extractStockName,
    stateColors,
}: {
    title: string;
    subtitle: string;
    tone: 'bull' | 'bear';
    stocks: StockAnalysisRow[];
    selected: string | null;
    onSelect: (symbol: string) => void;
    extractStockName: (s: string) => string;
    stateColors: Record<string, string>;
}) {
    const border =
        tone === 'bull'
            ? 'border-emerald-500/30'
            : 'border-rose-500/30';
    const header =
        tone === 'bull'
            ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
            : 'bg-rose-500/10 text-rose-600 dark:text-rose-400';
    const accent =
        tone === 'bull' ? 'border-emerald-500 bg-emerald-500/5' : 'border-rose-500 bg-rose-500/5';

    return (
        <div className={`rounded-2xl border-2 ${border} bg-white dark:bg-zinc-900 overflow-hidden`}>
            <div className={`px-4 py-3 ${header}`}>
                <div className="text-sm font-black uppercase tracking-wider">{title}</div>
                <div className="text-[10px] font-bold opacity-80">{subtitle}</div>
            </div>
            <div className="p-2 space-y-2 max-h-[42vh] overflow-y-auto">
                {stocks.length === 0 ? (
                    <div className="text-center text-zinc-500 text-xs py-8">
                        No {tone === 'bull' ? 'bullish' : 'bearish'} majority setups in this filter.
                    </div>
                ) : (
                    stocks.map(stock => {
                        const active = selected === stock.symbol;
                        return (
                            <button
                                key={stock.symbol}
                                onClick={() => onSelect(stock.symbol)}
                                className={`w-full text-left p-3 rounded-xl border-2 transition-all ${
                                    active
                                        ? accent
                                        : 'border-zinc-100 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-600'
                                }`}
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <div>
                                        <div className="font-black text-sm">
                                            {extractStockName(stock.symbol)}
                                        </div>
                                        <div className="text-[11px] text-zinc-500">
                                            ₹
                                            {stock.spot_price?.toLocaleString('en-IN', {
                                                maximumFractionDigits: 2,
                                            }) || '—'}
                                        </div>
                                    </div>
                                    <div className="flex flex-col items-end gap-1">
                                        <span
                                            className={`px-1.5 py-0.5 text-[9px] font-black rounded text-white ${stateColors[stock.state] || 'bg-zinc-600'}`}
                                        >
                                            {stock.state}
                                        </span>
                                        <span
                                            className={`text-[10px] font-black ${
                                                tone === 'bull' ? 'text-emerald-500' : 'text-rose-500'
                                            }`}
                                        >
                                            Q {stock.quant_score?.toFixed?.(0) ?? '—'}
                                        </span>
                                    </div>
                                </div>
                                {(stock.buildup_state || stock.buildup?.primary_state) && (
                                    <div className="mt-1.5 flex flex-wrap gap-1">
                                        <BuildupBadge
                                            state={stock.buildup_state || stock.buildup?.primary_state}
                                            strength={stock.buildup_strength || stock.buildup?.conviction}
                                        />
                                        {stock.action && stock.action !== 'WAIT' ? (
                                            <span
                                                className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded ${
                                                    stock.action === 'SELL'
                                                        ? 'bg-rose-600 text-white'
                                                        : 'bg-emerald-600 text-white'
                                                }`}
                                            >
                                                {stock.action === 'BUY_CAUTIOUS' ? 'CAUTIOUS' : stock.action}
                                            </span>
                                        ) : (
                                            <span className="text-[9px] font-black uppercase px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 border border-amber-500/30">
                                                {stock.watch_long || stock.watch_short ? 'WATCH' : 'WAIT'}
                                            </span>
                                        )}
                                        {stock.vol_confirm_long && (
                                            <span className="text-[9px] font-black uppercase px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-600 border border-cyan-500/30">
                                                CE vol
                                            </span>
                                        )}
                                        {stock.vol_confirm_short && (
                                            <span className="text-[9px] font-black uppercase px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-600 border border-violet-500/30">
                                                PE vol
                                            </span>
                                        )}
                                        {stock.conflicted && (
                                            <span className="text-[9px] font-black uppercase px-1.5 py-0.5 rounded bg-zinc-500/20 text-zinc-500">
                                                Conflict
                                            </span>
                                        )}
                                    </div>
                                )}
                                <div className="mt-2 flex flex-wrap gap-2 text-[9px] text-zinc-500">
                                    <span>OI PCR {(stock.oi_pcr ?? stock.pcr)?.toFixed?.(2) ?? '—'}</span>
                                    <span>
                                        ATM CE vol{' '}
                                        {stock.atm_ce_rel_vol != null
                                            ? `${stock.atm_ce_rel_vol}×`
                                            : '—'}
                                    </span>
                                    <span>
                                        Stock vol{' '}
                                        {stock.technical?.intraday?.volume_ratio != null
                                            ? `${stock.technical.intraday.volume_ratio}×`
                                            : '—'}
                                    </span>
                                    <span>P-wall {stock.put_wall ?? stock.support ?? '—'}</span>
                                    {stock.strike_guidance?.suggested && (
                                        <span className="font-bold">
                                            {stock.strike_guidance.trades?.[0]?.instrument}{' '}
                                            {stock.strike_guidance.trades?.[0]?.strike}
                                        </span>
                                    )}
                                </div>
                            </button>
                        );
                    })
                )}
            </div>
        </div>
    );
}

function BuildupBadge({
    state,
    strength,
}: {
    state?: string;
    strength?: string;
}) {
    if (!state) return null;
    const s = state.toLowerCase();
    let cls = 'bg-zinc-500/15 text-zinc-500 border-zinc-500/30';
    if (s.includes('long buildup')) cls = 'bg-emerald-500/15 text-emerald-600 border-emerald-500/30';
    else if (s.includes('short buildup')) cls = 'bg-rose-500/15 text-rose-600 border-rose-500/30';
    else if (s.includes('short covering')) cls = 'bg-amber-500/15 text-amber-600 border-amber-500/30';
    else if (s.includes('unwinding')) cls = 'bg-orange-500/15 text-orange-600 border-orange-500/30';
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[9px] font-black uppercase tracking-wide ${cls}`}>
            {state}
            {strength ? <span className="opacity-70">· {strength}</span> : null}
        </span>
    );
}

function DeepPanel({
    stock,
    biasColor,
}: {
    stock: StockAnalysisRow;
    biasColor: (b?: string) => string;
}) {
    const deep = stock.deep_analytics;
    const name = stock.symbol?.replace('NSE:', '').replace('-EQ', '') || '—';
    const bestGap = deep?.premium_dislocation?.best_gap;
    const buildup = stock.buildup || deep?.buildup;
    const bState = stock.buildup_state || buildup?.primary_state;
    const bNote = stock.buildup_note || buildup?.note;
    const bStrength = stock.buildup_strength || buildup?.conviction;

    // One consistent side everywhere in this panel
    const setupSide =
        stock.setup_side === 'BULLISH' || stock.setup_side === 'BEARISH'
            ? stock.setup_side
            : stock.buildup_bias === 'BULLISH' || stock.buildup_bias === 'BEARISH'
              ? stock.buildup_bias
              : stock.quant_bias === 'BULLISH' || stock.quant_bias === 'BEARISH'
                ? stock.quant_bias
                : stock.strike_guidance?.bias === 'BULLISH' ||
                    stock.strike_guidance?.bias === 'BEARISH'
                  ? stock.strike_guidance.bias
                  : 'NEUTRAL';

    const oiPcr = stock.oi_pcr ?? deep?.pcr?.oi_pcr ?? stock.pcr;
    const volPcr = stock.volume_pcr ?? deep?.pcr?.volume_pcr;
    const atmPcr = stock.atm_pcr ?? deep?.pcr?.atm_oi_pcr;
    const bandPcr = stock.band_pcr ?? deep?.pcr?.band_oi_pcr;
    const putWall = stock.put_wall ?? deep?.walls?.put_wall ?? stock.support;
    const callWall = stock.call_wall ?? deep?.walls?.call_wall ?? stock.resistance;

    const metrics = [
        { label: 'Quant Score', value: stock.quant_score?.toFixed?.(1) ?? '—', sub: stock.quant_conviction },
        { label: 'Setup Side', value: setupSide, sub: `State: ${stock.state}` },
        { label: 'Buildup', value: bState ?? '—', sub: bStrength },
        { label: 'Max Pain', value: stock.max_pain ?? deep?.max_pain?.max_pain ?? '—', sub: deep?.max_pain?.distance_pct != null ? `${deep.max_pain.distance_pct}% from spot` : undefined },
        { label: '1σ Move', value: stock.expected_move != null ? `₹${stock.expected_move}` : '—', sub: stock.expected_move_pct != null ? `${stock.expected_move_pct}%` : undefined },
        { label: 'IV Skew', value: stock.iv_skew?.toFixed?.(1) ?? deep?.iv_structure?.skew?.toFixed?.(1) ?? '—', sub: stock.iv_skew_label || deep?.iv_structure?.skew_label },
        { label: 'Gamma Wall', value: stock.gamma_wall ?? deep?.greeks_walls?.gamma_wall_strike ?? '—', sub: deep?.greeks_walls?.delta_bias },
        { label: 'Pin Risk', value: `${stock.pin_risk?.toFixed?.(0) ?? deep?.greeks_walls?.pin_risk?.toFixed?.(0) ?? '—'}%`, sub: 'OI × γ concentration' },
        { label: 'OI PCR', value: oiPcr?.toFixed?.(2) ?? '—', sub: stock.pcr_regime_label || deep?.pcr?.regime_label || stock.pcr_signal },
        { label: 'Vol PCR', value: volPcr?.toFixed?.(2) ?? '—', sub: deep?.pcr?.volume_bias },
        { label: 'ATM PCR', value: atmPcr?.toFixed?.(2) ?? '—', sub: `Band ±5: ${bandPcr?.toFixed?.(2) ?? '—'}` },
        { label: 'Put Wall', value: putWall ?? '—', sub: stock.put_wall_oi ? `OI ${Number(stock.put_wall_oi).toLocaleString('en-IN')}` : 'Support' },
        { label: 'Call Wall', value: callWall ?? '—', sub: stock.call_wall_oi ? `OI ${Number(stock.call_wall_oi).toLocaleString('en-IN')}` : 'Resistance' },
    ];

    return (
        <div className="p-5 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 space-y-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 className="text-xl font-black tracking-tight">{name}</h2>
                    <p className="text-sm text-zinc-500">
                        Spot ₹
                        {stock.spot_price?.toLocaleString('en-IN', {
                            maximumFractionDigits: 2,
                        })}{' '}
                        · ATM {stock.atm_strike}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                        <BuildupBadge state={bState} strength={bStrength} />
                        {bState === 'Short Covering' && (
                            <span className="text-[9px] font-bold uppercase text-amber-600 bg-amber-500/10 px-2 py-0.5 rounded-md border border-amber-500/30">
                                Fade risk
                            </span>
                        )}
                    </div>
                </div>
                <div className="text-right">
                    <div className={`text-2xl font-black ${biasColor(setupSide)}`}>
                        {stock.quant_score?.toFixed?.(0) ?? '—'}
                    </div>
                    <div className="text-[10px] font-bold uppercase text-zinc-500">
                        Quant · {stock.quant_conviction || '—'} ·{' '}
                        <span className={biasColor(setupSide)}>{setupSide}</span>
                    </div>
                </div>
            </div>

            <div
                className={`text-[10px] font-black uppercase tracking-wider px-2 py-1 rounded-lg inline-block ${
                    setupSide === 'BULLISH'
                        ? 'bg-emerald-500/15 text-emerald-600'
                        : setupSide === 'BEARISH'
                          ? 'bg-rose-500/15 text-rose-600'
                          : 'bg-zinc-500/15 text-zinc-500'
                }`}
            >
                Column: {setupSide}
                {stock.strike_guidance?.bias &&
                    stock.strike_guidance.bias !== setupSide &&
                    ` · guidance aligned to ${setupSide}`}
            </div>

            {bNote && (
                <div className="p-3 rounded-xl border border-blue-500/20 bg-blue-500/5 text-xs text-zinc-700 dark:text-zinc-300">
                    <span className="text-[9px] font-black uppercase text-blue-600 block mb-1">
                        Buildup narrative
                    </span>
                    {bNote}
                </div>
            )}

            {/* Hardened action (Fix Report) */}
            <div className="flex flex-wrap gap-2 items-center">
                <span
                    className={`text-[11px] font-black uppercase px-3 py-1.5 rounded-lg ${
                        stock.action === 'BUY'
                            ? 'bg-emerald-600 text-white'
                            : stock.action === 'BUY_CAUTIOUS'
                              ? 'bg-emerald-500/20 text-emerald-600 border border-emerald-500/40'
                              : stock.action === 'SELL'
                                ? 'bg-rose-600 text-white'
                                : 'bg-amber-500/15 text-amber-700 border border-amber-500/40'
                    }`}
                >
                    {stock.action || 'WAIT'}
                </span>
                <span className="text-[10px] font-bold text-zinc-500 uppercase">
                    {stock.quant_conviction || '—'}
                    {stock.side_preference ? ` · ${stock.side_preference}` : ''}
                    {stock.max_score_cap != null ? ` · cap ${stock.max_score_cap}` : ''}
                </span>
                {stock.conflicted && (
                    <span className="text-[9px] font-black uppercase px-2 py-1 rounded bg-rose-500/10 text-rose-600 border border-rose-500/30">
                        Conflicted
                    </span>
                )}
                {stock.prefer_defined_risk && (
                    <span className="text-[9px] font-black uppercase px-2 py-1 rounded bg-blue-500/10 text-blue-600 border border-blue-500/30">
                        Defined-risk only
                    </span>
                )}
                {stock.skew_label === 'FLAT' && (
                    <span className="text-[9px] font-black uppercase px-2 py-1 rounded bg-zinc-500/10 text-zinc-500 border border-zinc-500/30">
                        No vol edge
                    </span>
                )}
                {stock.squeeze_risk && (
                    <span className="text-[9px] font-black uppercase px-2 py-1 rounded-lg bg-amber-500 text-black">
                        Squeeze
                    </span>
                )}
            </div>

            {stock.verdict && (
                <div className="p-3 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/40">
                    <div className="text-[9px] font-black uppercase text-zinc-500 mb-1">
                        Desk verdict
                    </div>
                    <pre className="text-[10px] text-zinc-600 dark:text-zinc-300 whitespace-pre-wrap font-sans leading-relaxed">
                        {stock.verdict}
                    </pre>
                </div>
            )}

            {/* Volume quality */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {[
                    {
                        l: 'ATM CE vol',
                        v:
                            stock.atm_ce_rel_vol != null
                                ? `${stock.atm_ce_rel_vol}× med`
                                : '—',
                        s: stock.atm_call_volume
                            ? `raw ${Number(stock.atm_call_volume).toLocaleString('en-IN')}`
                            : undefined,
                    },
                    {
                        l: 'ATM PE vol',
                        v:
                            stock.atm_pe_rel_vol != null
                                ? `${stock.atm_pe_rel_vol}× med`
                                : '—',
                        s: stock.atm_put_volume
                            ? `raw ${Number(stock.atm_put_volume).toLocaleString('en-IN')}`
                            : undefined,
                    },
                    {
                        l: 'CE vol share',
                        v:
                            stock.ce_vol_share != null
                                ? `${(stock.ce_vol_share * 100).toFixed(0)}%`
                                : '—',
                        s: stock.vol_confirm_long ? 'confirms long' : undefined,
                    },
                    {
                        l: 'Stock vol',
                        v:
                            stock.technical?.intraday?.volume_ratio != null
                                ? `${stock.technical.intraday.volume_ratio}×`
                                : '—',
                        s: 'underlying vs 20',
                    },
                ].map(x => (
                    <div
                        key={x.l}
                        className="p-2 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-100 dark:border-zinc-800"
                    >
                        <div className="text-[9px] font-bold text-zinc-500 uppercase">{x.l}</div>
                        <div className="text-sm font-black">{x.v}</div>
                        {x.s && <div className="text-[9px] text-zinc-400">{x.s}</div>}
                    </div>
                ))}
            </div>

            {/* Score breakdown */}
            {stock.score_components && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    {[
                        { l: 'Flow', v: stock.score_components.flow_score ?? stock.score_components.option_score },
                        { l: 'Tech 15m', v: stock.score_components.tech_score },
                        { l: 'Premium', v: stock.score_components.premium_score },
                        { l: 'Final (capped)', v: stock.score_components.total ?? stock.quant_score },
                    ].map(x => (
                        <div
                            key={x.l}
                            className="p-2 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-100 dark:border-zinc-800 text-center"
                        >
                            <div className="text-[9px] font-bold text-zinc-500 uppercase">{x.l}</div>
                            <div className="text-base font-black">{x.v ?? '—'}</div>
                        </div>
                    ))}
                </div>
            )}
            {(stock.score_components?.pcr_penalty != null ||
                stock.score_components?.gamma_penalty != null) && (
                <p className="text-[10px] text-zinc-500">
                    Penalties: PCR −{stock.score_components?.pcr_penalty ?? 0}
                    {' · '}Gamma −{stock.score_components?.gamma_penalty ?? 0}
                    {stock.score_components?.raw != null &&
                        ` · raw ${stock.score_components.raw} → capped`}
                </p>
            )}

            {/* Technical stack */}
            {(stock.technical?.ok || stock.technical?.intraday) && (
                <div className="p-3 rounded-xl border border-zinc-200 dark:border-zinc-700 space-y-2">
                    <div className="text-[10px] font-black uppercase text-zinc-500">
                        Technical stack · 15m 7/20 + HTF gate
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
                        <div>
                            <div className="text-zinc-500">15m stack</div>
                            <div className="font-black">
                                {stock.technical?.intraday?.ema_stack || '—'}
                            </div>
                            <div className="text-zinc-400">
                                7={stock.technical?.intraday?.ema7 ?? '—'} / 20=
                                {stock.technical?.intraday?.ema20 ?? '—'}
                            </div>
                        </div>
                        <div>
                            <div className="text-zinc-500">Volume</div>
                            <div className="font-black">
                                {stock.technical?.intraday?.volume_ratio != null
                                    ? `${stock.technical.intraday.volume_ratio}×`
                                    : '—'}
                            </div>
                        </div>
                        <div>
                            <div className="text-zinc-500">
                                HTF {stock.technical?.htf?.timeframe || ''}
                            </div>
                            <div className="font-black">{stock.technical?.htf?.bias || '—'}</div>
                            <div className="text-zinc-400 truncate">
                                {stock.technical?.htf?.note || ''}
                            </div>
                        </div>
                        <div>
                            <div className="text-zinc-500">Signals</div>
                            <div className="font-black">
                                {stock.technical?.long_signal
                                    ? 'LONG'
                                    : stock.technical?.short_signal
                                      ? 'SHORT'
                                      : 'WAIT'}
                            </div>
                            {stock.technical?.blocked_reason && (
                                <div className="text-amber-600 text-[9px]">
                                    {stock.technical.blocked_reason}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Premium behaviour */}
            {stock.premium && (
                <div className="p-3 rounded-xl border border-purple-500/20 bg-purple-500/5 space-y-1">
                    <div className="text-[10px] font-black uppercase text-purple-600">
                        Premium behaviour
                        {stock.premium.has_history ? '' : ' · seeding snapshot'}
                    </div>
                    <div className="text-xs text-zinc-700 dark:text-zinc-300">
                        {stock.premium.note || '—'}
                        {stock.premium.straddle_chg_pct != null && stock.premium.has_history && (
                            <span className="ml-2 text-zinc-500">
                                straddle {stock.premium.straddle_chg_pct > 0 ? '+' : ''}
                                {stock.premium.straddle_chg_pct}%
                            </span>
                        )}
                    </div>
                    {stock.premium.flags && stock.premium.flags.length > 0 && (
                        <ul className="text-[10px] text-zinc-500 space-y-0.5">
                            {stock.premium.flags.map((f, i) => (
                                <li key={`${stock.symbol}-pf-${i}`}>▸ {f}</li>
                            ))}
                        </ul>
                    )}
                </div>
            )}

            <p className="text-xs text-zinc-600 dark:text-zinc-400 border-t border-zinc-100 dark:border-zinc-800 pt-3">
                {stock.message}
            </p>

            {/* PCR triad */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {[
                    { l: 'OI PCR', v: oiPcr?.toFixed?.(2), s: stock.pcr_regime || deep?.pcr?.regime },
                    { l: 'Volume PCR', v: volPcr?.toFixed?.(2), s: deep?.pcr?.volume_bias },
                    { l: 'ATM PCR', v: atmPcr?.toFixed?.(2), s: 'structural ATM' },
                    { l: 'Band PCR', v: bandPcr?.toFixed?.(2), s: '±5 strikes' },
                ].map(x => (
                    <div
                        key={x.l}
                        className="p-2.5 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-100 dark:border-zinc-800"
                    >
                        <div className="text-[9px] font-bold text-zinc-500 uppercase">{x.l}</div>
                        <div className="text-lg font-black">{x.v ?? '—'}</div>
                        {x.s && <div className="text-[9px] text-zinc-400 truncate">{x.s}</div>}
                    </div>
                ))}
            </div>
            {(stock.pcr_regime_label || deep?.pcr?.regime_label) && (
                <p className="text-[10px] text-zinc-500 font-medium">
                    PCR regime: {stock.pcr_regime_label || deep?.pcr?.regime_label}
                    {stock.pcr_health || deep?.pcr?.health
                        ? ` · health ${stock.pcr_health || deep?.pcr?.health}`
                        : ''}
                </p>
            )}

            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {metrics.map(m => (
                    <div
                        key={m.label}
                        className="p-2.5 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-100 dark:border-zinc-800"
                    >
                        <div className="text-[9px] font-bold text-zinc-500 uppercase">{m.label}</div>
                        <div className="text-sm font-black truncate">{m.value}</div>
                        {m.sub && (
                            <div className="text-[9px] text-zinc-400 truncate">{m.sub}</div>
                        )}
                    </div>
                ))}
            </div>

            {/* ATM band CE/PE buildup */}
            {buildup?.atm_band && buildup.atm_band.length > 0 && (
                <div>
                    <div className="text-[10px] font-bold uppercase text-zinc-500 mb-2">
                        ATM ±3 Buildup Map
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-[10px]">
                            <thead>
                                <tr className="text-zinc-500 uppercase text-left">
                                    <th className="py-1 pr-2">Strike</th>
                                    <th className="py-1 pr-2">CE</th>
                                    <th className="py-1">PE</th>
                                </tr>
                            </thead>
                            <tbody>
                                {buildup.atm_band.map((row, i) => (
                                    <tr
                                        key={`${stock.symbol}-band-${row.strike}-${i}`}
                                        className="border-t border-zinc-100 dark:border-zinc-800"
                                    >
                                        <td className="py-1.5 pr-2 font-mono font-bold">{row.strike}</td>
                                        <td className="py-1.5 pr-2">
                                            <BuildupBadge
                                                state={row.call?.state}
                                                strength={row.call?.strength}
                                            />
                                        </td>
                                        <td className="py-1.5">
                                            <BuildupBadge
                                                state={row.put?.state}
                                                strength={row.put?.strength}
                                            />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Actionable legs */}
            {buildup?.actionable && buildup.actionable.length > 0 && (
                <div>
                    <div className="text-[10px] font-bold uppercase text-zinc-500 mb-2">
                        Actionable legs (Strong / band)
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {buildup.actionable.slice(0, 8).map((a, i) => (
                            <span
                                key={`${stock.symbol}-act-${i}`}
                                className="text-[10px] px-2 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 font-mono border border-zinc-200 dark:border-zinc-700"
                            >
                                {a.strike} {a.side} · {a.state}
                                {a.strength ? ` (${a.strength})` : ''}
                                {a.fade_risk ? ' ⚠ fade' : ''}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* Expected move band */}
            {deep?.straddle?.upper_1sd != null && deep?.straddle?.lower_1sd != null && (
                <div className="p-3 rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40">
                    <div className="text-[10px] font-bold uppercase text-zinc-500 mb-1">
                        ATM Straddle Expected Range (≈1σ)
                    </div>
                    <div className="text-sm font-mono font-bold">
                        {deep.straddle.lower_1sd} — {deep.straddle.upper_1sd}
                        <span className="text-zinc-500 text-xs font-sans ml-2">
                            straddle ₹{deep.straddle.straddle}
                        </span>
                    </div>
                </div>
            )}

            {/* Premium dislocation */}
            {bestGap && (
                <div className="p-3 rounded-xl border border-amber-500/20 bg-amber-500/5">
                    <div className="text-[10px] font-bold uppercase text-amber-600 mb-1">
                        Premium Dislocation (VAT-style)
                    </div>
                    <div className="text-xs">
                        Cheap <strong>{bestGap.cheap_side}</strong> @{' '}
                        {bestGap.undervalued_strike} · gap ₹{bestGap.gap} ({bestGap.gap_pct}%) · CE{' '}
                        {bestGap.call_strike} vs PE {bestGap.put_strike}
                    </div>
                </div>
            )}

            {/* Factors */}
            {(stock.quant_factors?.length || deep?.quant?.factors?.length) && (
                <div>
                    <div className="text-[10px] font-bold uppercase text-zinc-500 mb-2">
                        Quant Factors
                    </div>
                    <ul className="space-y-1">
                        {(stock.quant_factors || deep?.quant?.factors || []).map((f, i) => (
                            <li
                                key={`${stock.symbol}-f-${i}`}
                                className="text-[11px] text-zinc-600 dark:text-zinc-400 flex gap-2"
                            >
                                <span className="text-blue-500">▸</span>
                                {f}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Institutional clusters */}
            {stock.institutional_flow?.clusters && stock.institutional_flow.clusters.length > 0 && (
                <div>
                    <div className="text-[10px] font-bold uppercase text-zinc-500 mb-2">
                        Flow Clusters
                        {stock.institutional_flow.big_money_present && (
                            <span className="ml-2 text-emerald-500">Big Money</span>
                        )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {stock.institutional_flow.clusters.map((c, i) => (
                            <span
                                key={`${stock.symbol}-c-${i}`}
                                className="text-[10px] px-2 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 font-mono"
                            >
                                {c.strike} {c.type.replace('_', ' ')} ×{c.strength}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* Strike guidance — only when action allows */}
            {stock.strike_guidance?.suggested &&
                (stock.action === 'BUY' ||
                    stock.action === 'BUY_CAUTIOUS' ||
                    stock.action === 'SELL') && (
                <div className="p-3 rounded-xl border border-zinc-200 dark:border-zinc-700">
                    <div className="flex justify-between mb-2">
                        <span
                            className={`text-[10px] font-black uppercase ${
                                setupSide === 'BULLISH'
                                    ? 'text-emerald-500'
                                    : 'text-rose-500'
                            }`}
                        >
                            {setupSide} Setup · {stock.action}
                        </span>
                        <span className="text-[9px] text-zinc-400 font-bold">
                            {stock.prefer_defined_risk ? 'DEFINED-RISK' : 'DIRECTIONAL'}
                        </span>
                    </div>
                    <div className="space-y-2">
                        {stock.strike_guidance.trades.map((t, i) => (
                            <div
                                key={`${stock.symbol}-t-${i}`}
                                className="flex justify-between text-xs p-2 rounded-lg bg-zinc-50 dark:bg-zinc-800/50"
                            >
                                <span className="font-black">
                                    {t.strike} {t.instrument}
                                </span>
                                <span className="text-zinc-500 text-[10px]">{t.type}</span>
                            </div>
                        ))}
                    </div>
                    {stock.strike_guidance.expert_note && (
                        <p className="text-[10px] text-zinc-500 mt-2 italic">
                            {stock.strike_guidance.expert_note}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}
