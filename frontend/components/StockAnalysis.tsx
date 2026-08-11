'use client';

import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { useApiQuery } from '../lib/hooks/useApiQuery';

interface TradeGuide {
    type: string;
    strike: number;
    instrument: string;
    rationale: string;
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
    max_pain?: number;
    expected_move?: number;
    expected_move_pct?: number;
    iv_skew?: number;
    iv_skew_label?: string;
    gamma_wall?: number;
    pin_risk?: number;
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
        pcr?: { oi_pcr?: number; volume_pcr?: number; oi_bias?: string; volume_bias?: string };
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
        };
    };
}

interface ScanResponse {
    success: boolean;
    count: number;
    total_scanned: number;
    tradable_count: number;
    universe_requested?: number;
    top_only?: boolean;
    stocks: StockAnalysisRow[];
    error_count?: number;
    timestamp: string;
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

    const limit = scope === 'full' ? 180 : 40;

    const { data, isLoading, error, isFetching, refetch } = useApiQuery<ScanResponse>(
        ['market', 'stocks-scan', scope, limit],
        () =>
            api.market.scanStocks(limit, false, scope === 'top', 10, true) as Promise<ScanResponse>,
        {
            staleTime: 60_000,
        },
    );

    useEffect(() => {
        const active = isLoading || isFetching;
        if (active) {
            setProgress(5);
            const id = setInterval(() => {
                setProgress(prev => (prev >= 92 ? prev : prev + 3));
            }, 400);
            return () => clearInterval(id);
        }
        setProgress(100);
        return undefined;
    }, [isLoading, isFetching]);

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

    /** Unbiased side label: prefer quant vote; fall back to strike guidance */
    const sideOf = (s: StockAnalysisRow): 'BULLISH' | 'BEARISH' | 'NEUTRAL' => {
        const q = s.quant_bias;
        if (q === 'BULLISH' || q === 'BEARISH') return q;
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
                    <div className="h-2 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-blue-600 transition-all"
                            style={{ width: `${progress}%` }}
                        />
                    </div>
                    <p className="text-xs text-zinc-500 font-bold uppercase tracking-widest">
                        Deep-scanning F&O option chains with quant math… {progress}%
                    </p>
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
                                {data?.count || 0} analyzed · {data?.tradable_count || 0} tradable ·{' '}
                                universe {data?.universe_requested || limit}
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

                {(isLoading || isFetching) && (
                    <div className="mb-4">
                        <div className="h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-gradient-to-r from-blue-600 to-emerald-500 transition-all"
                                style={{ width: `${progress}%` }}
                            />
                        </div>
                        <p className="text-[10px] text-zinc-500 mt-1 font-bold uppercase tracking-wider">
                            Fetching option chains + computing max pain, IV skew, gamma walls…
                        </p>
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
                            value: summary.bull,
                            cls: 'text-emerald-500',
                        },
                        {
                            label: 'Bearish',
                            value: summary.bear,
                            cls: 'text-rose-500',
                        },
                        {
                            label: 'Neutral',
                            value: summary.neutral,
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
                    Unbiased majority-vote engine · equal CE/PE rules · ties stay{' '}
                    <span className="font-bold">NEUTRAL</span> (never forced bearish/bullish)
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
                        title="Bullish Setups"
                        subtitle={`${bullStocks.length} names · CE-side majority`}
                        tone="bull"
                        stocks={bullStocks}
                        selected={selected}
                        onSelect={setSelected}
                        extractStockName={extractStockName}
                        stateColors={stateColors}
                    />
                    <SideColumn
                        title="Bearish Setups"
                        subtitle={`${bearStocks.length} names · PE-side majority`}
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
                    <span>Option Quant Engine · Max Pain · IV Skew · Gamma Wall · PCR</span>
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
                                <div className="mt-2 flex flex-wrap gap-2 text-[9px] text-zinc-500">
                                    <span>PCR {stock.pcr?.toFixed?.(2) ?? '—'}</span>
                                    <span>Skew {stock.iv_skew?.toFixed?.(1) ?? '—'}</span>
                                    <span>Pin {stock.pin_risk?.toFixed?.(0) ?? '—'}%</span>
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

    const metrics = [
        { label: 'Quant Score', value: stock.quant_score?.toFixed?.(1) ?? '—', sub: stock.quant_conviction },
        { label: 'Bias', value: stock.quant_bias || '—', sub: stock.state },
        { label: 'Max Pain', value: stock.max_pain ?? deep?.max_pain?.max_pain ?? '—', sub: deep?.max_pain?.distance_pct != null ? `${deep.max_pain.distance_pct}% from spot` : undefined },
        { label: '1σ Move', value: stock.expected_move != null ? `₹${stock.expected_move}` : '—', sub: stock.expected_move_pct != null ? `${stock.expected_move_pct}%` : undefined },
        { label: 'IV Skew', value: stock.iv_skew?.toFixed?.(1) ?? deep?.iv_structure?.skew?.toFixed?.(1) ?? '—', sub: stock.iv_skew_label || deep?.iv_structure?.skew_label },
        { label: 'ATM IV', value: deep?.iv_structure?.atm_iv?.toFixed?.(1) ?? '—', sub: deep?.iv_structure?.iv_bias },
        { label: 'Gamma Wall', value: stock.gamma_wall ?? deep?.greeks_walls?.gamma_wall_strike ?? '—', sub: deep?.greeks_walls?.delta_bias },
        { label: 'Pin Risk', value: `${stock.pin_risk?.toFixed?.(0) ?? deep?.greeks_walls?.pin_risk?.toFixed?.(0) ?? '—'}%`, sub: 'OI × γ concentration' },
        { label: 'PCR (OI)', value: stock.pcr?.toFixed?.(2) ?? deep?.pcr?.oi_pcr?.toFixed?.(2) ?? '—', sub: stock.pcr_signal || deep?.pcr?.oi_bias },
        { label: 'PCR (Vol)', value: deep?.pcr?.volume_pcr?.toFixed?.(2) ?? '—', sub: deep?.pcr?.volume_bias },
        { label: 'Support', value: stock.support ?? '—', sub: 'Max put OI' },
        { label: 'Resistance', value: stock.resistance ?? '—', sub: 'Max call OI' },
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
                </div>
                <div className="text-right">
                    <div className={`text-2xl font-black ${biasColor(stock.quant_bias)}`}>
                        {stock.quant_score?.toFixed?.(0) ?? '—'}
                    </div>
                    <div className="text-[10px] font-bold uppercase text-zinc-500">
                        Quant · {stock.quant_conviction || '—'} · {stock.quant_bias || '—'}
                    </div>
                </div>
            </div>

            <p className="text-xs text-zinc-600 dark:text-zinc-400 border-t border-zinc-100 dark:border-zinc-800 pt-3">
                {stock.message}
            </p>

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

            {/* Strike guidance */}
            {stock.strike_guidance?.suggested && (
                <div className="p-3 rounded-xl border border-zinc-200 dark:border-zinc-700">
                    <div className="flex justify-between mb-2">
                        <span
                            className={`text-[10px] font-black uppercase ${
                                stock.strike_guidance.bias === 'BULLISH'
                                    ? 'text-emerald-500'
                                    : 'text-rose-500'
                            }`}
                        >
                            {stock.strike_guidance.bias} Setup
                        </span>
                        <span className="text-[9px] text-zinc-400 font-bold">BUY ONLY</span>
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
