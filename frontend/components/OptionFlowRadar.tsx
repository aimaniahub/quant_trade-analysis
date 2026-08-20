'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../lib/api';
import LoadingBanner from './ui/LoadingBanner';

// ─────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────

interface SignalInfo {
    signal: string;       // STRONG_BULLISH | STRONG_BEARISH | BULLISH | BEARISH | EXHAUSTION | ACCUMULATION | NEUTRAL
    label: string;
    icon: string;
    color: string;
    direction?: string;   // BULLISH | BEARISH | NEUTRAL (stock-side implication)
}

interface ConvictionInfo {
    level: string;        // HIGH | MEDIUM | LOW
    icon: string;
    label: string;
}

interface GreekQuality {
    score: number;
    max?: number;
    abs_delta?: number;
    notes?: string[];
}

interface GreekInterpretation {
    delta_bias: string;
    delta_label: string;
    delta_value: number;
    gamma_risk: string;
    gamma_value: number;
    theta_risk: string;
    theta_label: string;
    theta_value: number;
    vega_sensitivity: string;
    vega_value: number;
}

interface FlaggedContract {
    timestamp: string;
    symbol: string;
    name: string;
    expiry: string;
    strike: number;
    type: 'CE' | 'PE';
    ltp: number;
    ltp_change_pct: number;
    oi: number;
    oi_change_pct: number;
    volume: number;
    vol_3day_avg: number;
    vol_spike_ratio: number;
    iv: number | null;
    delta: number | null;
    gamma: number | null;
    theta: number | null;
    vega: number | null;
    greek_interpretation: GreekInterpretation | null;
    spot: number;
    spot_change_pct: number;
    vwap_dev_pct: number;
    above_ema20: boolean;
    atm_dist_pct: number;
    lis: number;
    signal: SignalInfo;
    direction?: string;
    conviction: ConvictionInfo;
    unusual_flags: string[];
    grade?: string;
    actionable?: boolean;
    watch_only?: boolean;
    alert_box?: boolean;
    unusual_score?: number;
    composite_score?: number;
    desk_score?: number;
    desk_align?: string;
    desk_thesis?: string;
    rsi15?: number | null;
    rsi60?: number | null;
    rsi_event?: string;
    rsi_div?: string | null;
    rsi_div_event?: string | null;
    rsi_div_fresh?: boolean;
    rsi_div_bars_ago?: number | null;
    rsi_div_rsi_gap?: number | null;
    rsi_div_price_l1?: number | null;
    rsi_div_price_l2?: number | null;
    rsi_div_rsi_l1?: number | null;
    rsi_div_rsi_l2?: number | null;
    oc_permission?: number;
    mtf_allowed?: string;
    h4_bias?: string;
    greek_quality?: GreekQuality;
    oi_added?: number;
    layers_passed?: number;
    layers?: Record<string, boolean>;
    vol_spike_source?: string;
    idea_status?: string;
    process_locked?: boolean;
    process_direction?: string;
    location_score?: number;
    location_tags?: string[];
    process_composite?: number;
    process_recipe?: string;
    idea?: ProcessIdea;
    levels_map?: Record<string, any>;
}


interface ProcessIdea {
    status: string;
    symbol: string;
    name: string;
    direction: string;
    side: string;
    strike: number;
    opt_type: string;
    label: string;
    signal?: string;
    thesis?: string;
    recipe?: { id?: string; name?: string; ok?: boolean };
    location_score?: number;
    location_tags?: string[];
    composite?: number;
    prominence?: number;
    lis?: number;
    grade?: string;
    spot?: number;
    locked_at?: string | null;
    hold_seconds?: number;
    invalidation?: number | null;
    stop?: number | null;
    target?: number | null;
    target_2?: number | null;
    target_label?: string | null;
    target_2_label?: string | null;
    entry?: number | null;
    entry_label?: string | null;
    exec_action?: string | null;
    reward_risk?: number | null;
    trade_opt_type?: string | null;
    trade_strike?: number | null;
    entry_zone?: { from?: number; to?: number; reason?: string } | null;
    cluster_health?: string | null;
    exit_warnings?: string[];
    entry_quality?: { score?: number; label?: string; dist_pct?: number } | null;
    locked_cluster?: { strike?: number; type?: string; oi?: number; state?: string } | null;
    cluster_plan?: {
        side?: string;
        entry_zone?: { from?: number; to?: number; reason?: string } | null;
        supporting_cluster?: { strike?: number; type?: string; oi?: number; state?: string } | null;
        primary_target?: { level?: number; reason?: string } | null;
        secondary_target?: number | null;
        stop_reference?: number | null;
        exit_warnings?: string[];
        cluster_health?: string;
        entry_quality?: { score?: number; label?: string } | null;
    } | null;
    execution?: {
        action?: string;
        action_label?: string;
        entry_role?: string;
        instrument?: { opt_type?: string; strike?: number; role?: string; note?: string };
        take_now?: boolean;
        reward_risk?: number;
        magnet_source?: string;
        support_dying?: boolean;
        tech_confirm?: string[];
        note?: string;
        cluster_health?: string;
        exit_warnings?: string[];
        entry_zone?: { from?: number; to?: number; reason?: string } | null;
    } | null;
    tag_roles?: { entry_tags?: string[]; context_tags?: string[] } | null;
    vetoes?: string[];
    persist?: { ready?: boolean; same?: number; n?: number; age_seconds?: number };
    futures?: { state?: string; label?: string };
    zone?: { labels?: string[]; mid?: number } | null;
    pivot_side?: string;
    camarilla_regime?: string;
    wall_side?: string;
    instrument_hint?: { strike?: number; opt_type?: string } | null;
    structure?: { put_wall?: number; call_wall?: number; max_pain?: number; pcr_regime?: string };
    day?: { p?: number; s1?: number; r1?: number; pdh?: number; pdl?: number; atr?: number };
    session?: { vwap?: number; orh?: number; orl?: number };
    kill_reason?: string | null;
    kill_frame?: string | null;
    downgrade_reason?: string | null;
    downgrade_frame?: string | null;
    campaign?: string;
    hq_pullback?: boolean;
    vwap_agree?: boolean;
    vwap_side?: string;
    vwap_dev_pct?: number;
    align_score?: number;
    align_label?: string;
    allowed_side?: string;
    mtf?: {
        daily_bias?: string;
        h4_bias?: string;
        h1_bias?: string;
        m15_bias?: string;
        align_score?: number;
        align_label?: string;
        allowed_side?: string;
        campaign?: string;
        hq_pullback?: boolean;
        turning?: boolean;
        m15_trigger?: boolean;
        momentum_now?: string;
    };
}

interface ScanResult {
    success: boolean;
    scanned: number;
    total_flagged: number;
    flagged: FlaggedContract[];
    watch?: FlaggedContract[];
    alert_box?: FlaggedContract[];
    ideas?: ProcessIdea[];
    ideas_confirmed?: ProcessIdea[];
    ideas_bullish?: ProcessIdea[];
    ideas_bearish?: ProcessIdea[];
    ideas_pullbacks?: ProcessIdea[];
    ideas_watch?: ProcessIdea[];
    ideas_conflict?: ProcessIdea[];
    idea_counts?: {
        active?: number;
        watch?: number;
        conflict?: number;
        confirmed?: number;
        pullbacks?: number;
        bullish?: number;
        bearish?: number;
    };
    grade_counts?: Record<string, number>;
    engine?: string;
    errors: string[];
    retry_attempted?: number;
    retry_recovered?: number;
    failed_remaining?: string[];
    timestamp: string;
    market_hours: boolean;
}

interface SymbolFlow {
    success: boolean;
    symbol: string;
    name: string;
    underlying: {
        ltp: number;
        change_pct: number;
        vwap: number;
        ema20: number;
        vwap_dev_pct: number;
        above_ema20: boolean;
    };
    chain: any[];
    spot_price: number;
    pcr: number | null;
    india_vix: number | null;
    atm_strike: number | null;
    expiries: string[];
    flagged_contracts: FlaggedContract[];
    candles_5min: Array<{
        timestamp: number;
        datetime: string;
        open: number;
        high: number;
        low: number;
        close: number;
        volume: number;
    }>;
    idea?: ProcessIdea | null;
    levels?: Record<string, any>;
    partial?: boolean;
    warning?: string;
}

interface BacktestResult {
    success: boolean;
    symbol: string;
    strike: number;
    option_type: string;
    signal_timestamp: string;
    ref_price: number;
    forward_returns: Record<string, number>;
}

interface WatchlistItem {
    symbol: string;
    name: string;
}

// ─────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────

// LIS Score ring
function LISRing({ lis }: { lis: number }) {
    const r = 20;
    const circ = 2 * Math.PI * r;
    const pct = Math.min(lis / 100, 1);
    const dash = pct * circ;
    const color = lis >= 70 ? '#10b981' : lis >= 40 ? '#f59e0b' : '#6b7280';

    return (
        <div className="relative flex items-center justify-center" style={{ width: 52, height: 52 }}>
            <svg width={52} height={52} className="-rotate-90" style={{ position: 'absolute' }}>
                <circle cx={26} cy={26} r={r} strokeWidth={4} fill="none" stroke="#1f2937" />
                <circle
                    cx={26} cy={26} r={r}
                    strokeWidth={4} fill="none"
                    stroke={color}
                    strokeDasharray={`${dash} ${circ}`}
                    strokeLinecap="round"
                    style={{ transition: 'stroke-dasharray 0.6s ease' }}
                />
            </svg>
            <span className="text-xs font-black" style={{ color, position: 'relative', zIndex: 1 }}>
                {Math.round(lis)}
            </span>
        </div>
    );
}

// Signal badge — label + stock-side direction from CE/PE matrix
function SignalBadge({ signal }: { signal: SignalInfo }) {
    const bg: Record<string, string> = {
        emerald: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
        amber: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
        rose: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
        blue: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
        zinc: 'bg-zinc-500/15 text-zinc-400 border-zinc-700',
    };
    const cls = bg[signal.color] || bg.zinc;
    const dir = signal.direction && signal.direction !== 'NEUTRAL' ? signal.direction : null;
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-bold ${cls}`}>
            {signal.icon} {signal.label}
            {dir ? (
                <span className="opacity-80 font-black">· {dir === 'BULLISH' ? '↑' : '↓'}</span>
            ) : null}
        </span>
    );
}

// Vol Spike Badge – shows volume vs 3-day average
function VolSpikeBadge({ ratio, vol3dayAvg }: { ratio: number; vol3dayAvg: number }) {
    const pct = ratio;
    const color =
        pct >= 5 ? 'text-rose-400 bg-rose-500/10 border-rose-500/30' :
        pct >= 3 ? 'text-amber-400 bg-amber-500/10 border-amber-500/30' :
        pct >= 1.5 ? 'text-blue-400 bg-blue-500/10 border-blue-500/30' :
        'text-zinc-500 bg-zinc-800 border-zinc-700';
    const label = vol3dayAvg > 0
        ? `${pct.toFixed(1)}× avg`
        : 'N/A avg';
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[9px] font-black ${color}`}>
            📊 {label}
        </span>
    );
}

// Greek Display – compact Δ/Γ/Θ/V inline
function GreekDisplay({ g }: { g: GreekInterpretation | null }) {
    if (!g) return <span className="text-zinc-600 text-[9px]">—</span>;

    const deltaColor =
        g.delta_bias === 'DEEP_ITM' ? 'text-emerald-400' :
        g.delta_bias === 'ATM' ? 'text-blue-400' :
        g.delta_bias === 'OTM' ? 'text-amber-400' : 'text-zinc-500';

    const gammaColor =
        g.gamma_risk === 'HIGH' ? 'text-rose-400' :
        g.gamma_risk === 'MEDIUM' ? 'text-amber-400' : 'text-zinc-500';

    const thetaColor =
        g.theta_risk === 'HIGH' ? 'text-rose-400' :
        g.theta_risk === 'MEDIUM' ? 'text-amber-400' : 'text-zinc-500';

    const vegaColor =
        g.vega_sensitivity === 'HIGH' ? 'text-purple-400' :
        g.vega_sensitivity === 'MEDIUM' ? 'text-violet-400' : 'text-zinc-500';

    return (
        <div className="flex flex-col gap-0.5 text-[9px] font-mono">
            <div className="flex gap-1.5">
                <span className={deltaColor} title={`Delta: ${g.delta_value} (${g.delta_label})`}>
                    Δ{g.delta_value > 0 ? '+' : ''}{g.delta_value.toFixed(2)}
                </span>
                <span className={gammaColor} title={`Gamma: ${g.gamma_value} (${g.gamma_risk} risk)`}>
                    Γ{g.gamma_value.toFixed(4)}
                </span>
            </div>
            <div className="flex gap-1.5">
                <span className={thetaColor} title={`Theta: ${g.theta_label}`}>
                    Θ{g.theta_value.toFixed(1)}
                </span>
                <span className={vegaColor} title={`Vega: ${g.vega_value} (${g.vega_sensitivity} sensitivity)`}>
                    V{g.vega_value.toFixed(1)}
                </span>
            </div>
        </div>
    );
}

// Greek Detail Card – full breakdown for Stock Flow Detail
function GreekDetailCard({ g, optType }: { g: GreekInterpretation; optType: string }) {
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {/* Delta */}
            <div className="p-3 bg-zinc-900/60 rounded-xl border border-zinc-800">
                <div className="flex items-center justify-between mb-1">
                    <span className="text-[9px] text-zinc-500 uppercase font-bold">Delta (Δ)</span>
                    <span className={`text-[9px] font-black px-1.5 py-0.5 rounded ${
                        g.delta_bias === 'DEEP_ITM' ? 'bg-emerald-500/20 text-emerald-400' :
                        g.delta_bias === 'ATM' ? 'bg-blue-500/20 text-blue-400' :
                        'bg-amber-500/20 text-amber-400'
                    }`}>{g.delta_label}</span>
                </div>
                <p className="text-xl font-black text-zinc-100">{g.delta_value > 0 ? '+' : ''}{g.delta_value.toFixed(3)}</p>
                <p className="text-[9px] text-zinc-500 mt-0.5">
                    {optType === 'CE' ? 'Bullish sensitivity' : 'Bearish sensitivity'} to spot move
                </p>
                <div className="mt-1.5 h-1 bg-zinc-800 rounded-full overflow-hidden">
                    <div
                        className="h-full bg-emerald-500/60 rounded-full"
                        style={{ width: `${Math.abs(g.delta_value) * 100}%` }}
                    />
                </div>
            </div>
            {/* Gamma */}
            <div className="p-3 bg-zinc-900/60 rounded-xl border border-zinc-800">
                <div className="flex items-center justify-between mb-1">
                    <span className="text-[9px] text-zinc-500 uppercase font-bold">Gamma (Γ)</span>
                    <span className={`text-[9px] font-black px-1.5 py-0.5 rounded ${
                        g.gamma_risk === 'HIGH' ? 'bg-rose-500/20 text-rose-400' :
                        g.gamma_risk === 'MEDIUM' ? 'bg-amber-500/20 text-amber-400' :
                        'bg-zinc-700 text-zinc-400'
                    }`}>{g.gamma_risk}</span>
                </div>
                <p className="text-xl font-black text-zinc-100">{g.gamma_value.toFixed(5)}</p>
                <p className="text-[9px] text-zinc-500 mt-0.5">Rate of delta change per ₹1 move</p>
                <p className="text-[9px] mt-1 text-zinc-600">
                    High gamma = explosive move potential near expiry
                </p>
            </div>
            {/* Theta */}
            <div className="p-3 bg-zinc-900/60 rounded-xl border border-zinc-800">
                <div className="flex items-center justify-between mb-1">
                    <span className="text-[9px] text-zinc-500 uppercase font-bold">Theta (Θ)</span>
                    <span className={`text-[9px] font-black px-1.5 py-0.5 rounded ${
                        g.theta_risk === 'HIGH' ? 'bg-rose-500/20 text-rose-400' :
                        g.theta_risk === 'MEDIUM' ? 'bg-amber-500/20 text-amber-400' :
                        'bg-zinc-700 text-zinc-400'
                    }`}>{g.theta_risk} decay</span>
                </div>
                <p className="text-xl font-black text-rose-400">{g.theta_label}</p>
                <p className="text-[9px] text-zinc-500 mt-0.5">Daily time decay cost (buyer pays)</p>
                <p className="text-[9px] mt-1 text-zinc-600">
                    Option loses ₹{Math.abs(g.theta_value).toFixed(2)} value each day from time
                </p>
            </div>
            {/* Vega */}
            <div className="p-3 bg-zinc-900/60 rounded-xl border border-zinc-800">
                <div className="flex items-center justify-between mb-1">
                    <span className="text-[9px] text-zinc-500 uppercase font-bold">Vega (V)</span>
                    <span className={`text-[9px] font-black px-1.5 py-0.5 rounded ${
                        g.vega_sensitivity === 'HIGH' ? 'bg-purple-500/20 text-purple-400' :
                        g.vega_sensitivity === 'MEDIUM' ? 'bg-violet-500/20 text-violet-400' :
                        'bg-zinc-700 text-zinc-400'
                    }`}>{g.vega_sensitivity}</span>
                </div>
                <p className="text-xl font-black text-purple-400">+{g.vega_value.toFixed(2)}</p>
                <p className="text-[9px] text-zinc-500 mt-0.5">₹ gain per +1% IV change</p>
                <p className="text-[9px] mt-1 text-zinc-600">
                    High vega = IV expansion pays well (pre-event)
                </p>
            </div>
        </div>
    );
}

// Sparkline mini-chart using SVG
function SparkLine({ candles, height = 32, width = 100 }: { candles: SymbolFlow['candles_5min']; height?: number; width?: number }) {
    if (!candles || candles.length < 2) return null;
    const closes = candles.map(c => c.close);
    const mn = Math.min(...closes);
    const mx = Math.max(...closes);
    const range = mx - mn || 1;
    const pts = closes.map((v, i) => {
        const x = (i / (closes.length - 1)) * width;
        const y = height - ((v - mn) / range) * height;
        return `${x},${y}`;
    }).join(' ');

    const last = closes[closes.length - 1];
    const first = closes[0];
    const isUp = last >= first;

    return (
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
            <polyline
                points={pts}
                fill="none"
                stroke={isUp ? '#10b981' : '#f43f5e'}
                strokeWidth={1.5}
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    );
}

// Safe expiry text formatter
function formatExpiryText(e: any): string {
    if (!e) return 'N/A';
    if (typeof e === 'object') {
        return e.expiry || e.date || JSON.stringify(e);
    }
    return String(e);
}

// ─────────────────────────────────────────────────────────────────
// Mini Candlestick chart (inline SVG, no library dep)
// ─────────────────────────────────────────────────────────────────

function CandleChart({ candles, markers, height = 240 }: {
    candles: SymbolFlow['candles_5min'];
    markers?: Array<{ timestamp: number; lis: number; type: string }>;
    height?: number;
}) {
    const width = 700;
    const pad = { top: 16, right: 16, bottom: 32, left: 60 };
    const chartW = width - pad.left - pad.right;
    const chartH = height - pad.top - pad.bottom;

    if (!candles || candles.length < 2) {
        return (
            <div className="flex items-center justify-center" style={{ height }}>
                <p className="text-xs text-zinc-500">No candle data</p>
            </div>
        );
    }

    const last60 = candles.slice(-80);
    const highs = last60.map(c => c.high);
    const lows = last60.map(c => c.low);
    const priceMin = Math.min(...lows);
    const priceMax = Math.max(...highs);
    const priceRange = priceMax - priceMin || 1;

    const candleW = Math.max(4, (chartW / last60.length) - 1);

    const py = (price: number) => pad.top + chartH - ((price - priceMin) / priceRange) * chartH;
    const px = (i: number) => pad.left + (i + 0.5) * (chartW / last60.length);

    // Volume bars
    const volMax = Math.max(...last60.map(c => c.volume), 1);

    // Y-axis ticks
    const yTicks = 5;
    const yTickValues = Array.from({ length: yTicks }, (_, i) =>
        priceMin + (priceRange / (yTicks - 1)) * i
    );

    return (
        <svg
            viewBox={`0 0 ${width} ${height}`}
            className="w-full"
            style={{ height }}
        >
            {/* Grid lines */}
            {yTickValues.map((v, i) => (
                <g key={i}>
                    <line
                        x1={pad.left} y1={py(v)}
                        x2={pad.left + chartW} y2={py(v)}
                        stroke="#1f2937" strokeWidth={0.5}
                    />
                    <text x={pad.left - 4} y={py(v) + 4} textAnchor="end"
                        fill="#6b7280" fontSize={9}>
                        {v >= 1000 ? `${(v / 1000).toFixed(1)}K` : v.toFixed(0)}
                    </text>
                </g>
            ))}

            {/* Volume bars (bottom 20%) */}
            {last60.map((c, i) => {
                const volH = (c.volume / volMax) * (chartH * 0.2);
                const isUp = c.close >= c.open;
                return (
                    <rect
                        key={`vol-${i}`}
                        x={px(i) - candleW / 2}
                        y={pad.top + chartH - volH}
                        width={candleW}
                        height={volH}
                        fill={isUp ? '#10b98120' : '#f43f5e20'}
                    />
                );
            })}

            {/* Candle wicks + bodies */}
            {last60.map((c, i) => {
                const isUp = c.close >= c.open;
                const color = isUp ? '#10b981' : '#f43f5e';
                const bodyTop = py(Math.max(c.open, c.close));
                const bodyBot = py(Math.min(c.open, c.close));
                const bodyH = Math.max(bodyBot - bodyTop, 1);
                const cx = px(i);
                return (
                    <g key={`c-${i}`}>
                        {/* Wick */}
                        <line
                            x1={cx} y1={py(c.high)}
                            x2={cx} y2={py(c.low)}
                            stroke={color} strokeWidth={1}
                        />
                        {/* Body */}
                        <rect
                            x={cx - candleW / 2}
                            y={bodyTop}
                            width={candleW}
                            height={bodyH}
                            fill={color}
                            opacity={0.85}
                        />
                    </g>
                );
            })}

            {/* Marker lines for flagged events */}
            {markers?.map((m, i) => {
                const idx = last60.findIndex(c => Math.abs(c.timestamp - m.timestamp) < 300);
                if (idx < 0) return null;
                const x = px(idx);
                const lisColor = m.lis >= 70 ? '#10b981' : m.lis >= 40 ? '#f59e0b' : '#6b7280';
                return (
                    <g key={`mk-${i}`}>
                        <line
                            x1={x} y1={pad.top}
                            x2={x} y2={pad.top + chartH}
                            stroke={lisColor} strokeWidth={1.5}
                            strokeDasharray="4 3"
                            opacity={0.8}
                        />
                        <circle cx={x} cy={pad.top + 6} r={4} fill={lisColor} opacity={0.9} />
                    </g>
                );
            })}

            {/* X-axis time labels */}
            {last60.filter((_, i) => i % Math.ceil(last60.length / 6) === 0).map((c, i, arr) => {
                const realIdx = last60.findIndex(x => x.timestamp === c.timestamp);
                const x = px(realIdx);
                const time = new Date(c.timestamp * 1000).toLocaleTimeString('en-IN', {
                    hour: '2-digit', minute: '2-digit',
                });
                return (
                    <text key={`xt-${i}`}
                        x={x} y={pad.top + chartH + 16}
                        textAnchor="middle" fill="#6b7280" fontSize={9}
                    >
                        {time}
                    </text>
                );
            })}
        </svg>
    );
}

// ─────────────────────────────────────────────────────────────────
// Option Chain mini-table
// ─────────────────────────────────────────────────────────────────

function OIBar({ value, max, type }: { value: number; max: number; type: 'call' | 'put' }) {
    const pct = max > 0 ? (value / max) * 100 : 0;
    return (
        <div className="flex items-center gap-1" style={{ width: '100%' }}>
            {type === 'put' && (
                <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                    <div className="h-full bg-rose-500/60 rounded-full" style={{ width: `${pct}%` }} />
                </div>
            )}
            <span className="text-[10px] text-zinc-400 min-w-[48px] text-center tabular-nums">
                {value >= 1e6 ? `${(value / 1e6).toFixed(1)}M` : value >= 1000 ? `${(value / 1000).toFixed(0)}K` : value}
            </span>
            {type === 'call' && (
                <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500/60 rounded-full" style={{ width: `${pct}%` }} />
                </div>
            )}
        </div>
    );
}

function OptionChainWidget({ chain, atm, spot }: { chain: any[]; atm: number | null; spot: number }) {
    if (!chain?.length) return <p className="text-xs text-zinc-500 py-4 text-center">No option chain data</p>;

    const maxCallOI = Math.max(...chain.map(r => r.call?.oi || 0), 1);
    const maxPutOI  = Math.max(...chain.map(r => r.put?.oi || 0), 1);

    // Show ATM ±5 strikes
    const atmIdx = chain.findIndex(r => r.strike_price === atm) ?? Math.floor(chain.length / 2);
    const visible = chain.slice(Math.max(0, atmIdx - 5), atmIdx + 6);

    return (
        <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
                <thead>
                    <tr className="text-zinc-500 uppercase border-b border-zinc-800">
                        <th className="py-1 text-left pl-2">OI</th>
                        <th className="py-1 text-center">Vol</th>
                        <th className="py-1 text-center">LTP</th>
                        <th className="py-1 text-center font-black text-zinc-300">Strike</th>
                        <th className="py-1 text-center">LTP</th>
                        <th className="py-1 text-center">Vol</th>
                        <th className="py-1 text-right pr-2">OI</th>
                    </tr>
                    <tr className="text-[9px] text-zinc-600">
                        <td colSpan={3} className="text-center pb-1 text-emerald-500/70">— CALL —</td>
                        <td />
                        <td colSpan={3} className="text-center pb-1 text-rose-500/70">— PUT —</td>
                    </tr>
                </thead>
                <tbody>
                    {visible.map((row: any) => {
                        const isATM = row.strike_price === atm;
                        const callOI = row.call?.oi || 0;
                        const putOI  = row.put?.oi || 0;
                        return (
                            <tr
                                key={row.strike_price}
                                className={`border-b border-zinc-800/50 ${isATM ? 'bg-blue-500/10' : 'hover:bg-zinc-800/30'}`}
                            >
                                {/* Call OI bar */}
                                <td className="py-1 pl-2">
                                    <OIBar value={callOI} max={maxCallOI} type="call" />
                                </td>
                                <td className="py-1 text-center text-zinc-400">
                                    {(row.call?.volume || 0) >= 1000 ? `${((row.call?.volume || 0) / 1000).toFixed(0)}K` : row.call?.volume || 0}
                                </td>
                                <td className={`py-1 text-center font-semibold ${(row.call?.chg_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {row.call?.ltp?.toFixed(1) || '—'}
                                </td>
                                {/* Strike */}
                                <td className={`py-1 text-center font-black text-xs ${isATM ? 'text-blue-400' : 'text-zinc-300'}`}>
                                    {row.strike_price}
                                    {isATM && <span className="ml-1 text-[8px] bg-blue-500/20 text-blue-400 px-1 rounded">ATM</span>}
                                </td>
                                {/* Put */}
                                <td className={`py-1 text-center font-semibold ${(row.put?.chg_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {row.put?.ltp?.toFixed(1) || '—'}
                                </td>
                                <td className="py-1 text-center text-zinc-400">
                                    {(row.put?.volume || 0) >= 1000 ? `${((row.put?.volume || 0) / 1000).toFixed(0)}K` : row.put?.volume || 0}
                                </td>
                                <td className="py-1 pr-2">
                                    <OIBar value={putOI} max={maxPutOI} type="put" />
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────
// Backtest Panel
// ─────────────────────────────────────────────────────────────────

function BacktestPanel({ contract, onClose }: { contract: FlaggedContract; onClose: () => void }) {
    const [result, setResult] = useState<BacktestResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setLoading(true);
        api.radar.backtest({
            symbol: contract.symbol,
            strike: contract.strike,
            option_type: contract.type,
            signal_timestamp: contract.timestamp,
            forward_minutes: [15, 30, 60],
        })
            .then(r => setResult(r))
            .catch(e => setError(e.message))
            .finally(() => setLoading(false));
    }, [contract.symbol, contract.strike, contract.type, contract.timestamp]);

    const retColor = (v: number | undefined) => {
        if (v === undefined) return 'text-zinc-500';
        return v > 0 ? 'text-emerald-400' : v < 0 ? 'text-rose-400' : 'text-zinc-400';
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="bg-[#0f1117] border border-zinc-700 rounded-2xl p-6 w-full max-w-md shadow-2xl">
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-black text-white uppercase tracking-wider">
                        📊 Signal Forward Returns
                    </h3>
                    <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                <div className="mb-4 p-3 bg-zinc-900 rounded-xl">
                    <p className="text-xs text-zinc-400">
                        <span className="text-white font-bold">{contract.name}</span> {contract.strike} {contract.type}
                        {' '}&bull; Signal LIS: <span className="text-emerald-400 font-bold">{contract.lis}</span>
                    </p>
                    <p className="text-[10px] text-zinc-500 mt-0.5">
                        Flagged at {new Date(contract.timestamp).toLocaleTimeString()}
                    </p>
                </div>

                {loading ? (
                    <div className="flex items-center justify-center py-8">
                        <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                        <span className="ml-3 text-sm text-zinc-400">Computing forward returns...</span>
                    </div>
                ) : error ? (
                    <p className="text-sm text-rose-400 py-4 text-center">{error}</p>
                ) : result ? (
                    <div className="space-y-3">
                        <p className="text-[10px] text-zinc-500 mb-2">
                            Reference price: <span className="text-white font-bold">₹{result.ref_price?.toFixed(2)}</span>
                        </p>
                        {Object.entries(result.forward_returns || {}).map(([label, ret]) => (
                            <div key={label} className="flex items-center justify-between p-3 bg-zinc-900 rounded-xl">
                                <span className="text-xs text-zinc-400 font-bold uppercase">{label}</span>
                                <div className="text-right">
                                    <p className={`text-lg font-black ${retColor(ret)}`}>
                                        {ret > 0 ? '+' : ''}{ret?.toFixed(3)}%
                                    </p>
                                </div>
                            </div>
                        ))}
                        {Object.keys(result.forward_returns || {}).length === 0 && (
                            <p className="text-xs text-zinc-500 text-center py-4">
                                Forward candle data not available — signal may be from current candle.
                            </p>
                        )}
                    </div>
                ) : null}
            </div>
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────
// Main Component
// ─────────────────────────────────────────────────────────────────

interface Props {
    onBack: () => void;
}

type TabType = 'process' | 'live' | 'alerts' | 'watch' | 'flow' | 'backtest_list';

function fmtPx(v?: number | null) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 1 });
}

function ideaTone(idea: ProcessIdea): 'bull' | 'bear' | 'none' {
    const d = (idea.direction || idea.side || '').toUpperCase();
    if (idea.status === 'CONFLICT') return 'none';
    if (d === 'BULLISH' || d === 'LONG') return 'bull';
    if (d === 'BEARISH' || d === 'SHORT') return 'bear';
    return 'none';
}

function ideaRank(idea: ProcessIdea): number {
    return Number(idea.prominence ?? idea.composite ?? 0);
}

function tickerName(idea: ProcessIdea): string {
    return idea.name || String(idea.symbol || '').split(':').pop()?.replace('-EQ', '').replace('-INDEX', '') || '—';
}

function topN(rows: ProcessIdea[], n = 3): ProcessIdea[] {
    return [...rows].sort((a, b) => ideaRank(b) - ideaRank(a)).slice(0, n);
}

function dedupeIdeas(rows: ProcessIdea[]): ProcessIdea[] {
    const seen = new Map<string, ProcessIdea>();
    for (const row of rows) {
        const key = String(row.symbol || row.name || '');
        if (!key) continue;
        const prev = seen.get(key);
        if (!prev || ideaRank(row) >= ideaRank(prev)) seen.set(key, row);
    }
    return [...seen.values()];
}

function ideaToContract(idea: ProcessIdea): FlaggedContract {
    const opt = (idea.trade_opt_type || idea.execution?.instrument?.opt_type || idea.opt_type || 'CE') as 'CE' | 'PE';
    const tone = ideaTone(idea);
    return {
        timestamp: idea.locked_at || new Date().toISOString(),
        symbol: idea.symbol,
        name: tickerName(idea),
        expiry: '',
        strike: Number(idea.trade_strike ?? idea.execution?.instrument?.strike ?? idea.strike ?? 0),
        type: opt,
        ltp: 0,
        ltp_change_pct: 0,
        oi: 0,
        oi_change_pct: 0,
        volume: 0,
        vol_3day_avg: 0,
        vol_spike_ratio: 0,
        iv: null,
        delta: null,
        gamma: null,
        theta: null,
        vega: null,
        greek_interpretation: null,
        spot: idea.spot || 0,
        spot_change_pct: 0,
        vwap_dev_pct: 0,
        above_ema20: true,
        atm_dist_pct: 0,
        lis: idea.lis || 0,
        signal: {
            signal: idea.signal || (tone === 'bull' ? 'BULLISH' : tone === 'bear' ? 'BEARISH' : 'NEUTRAL'),
            label: idea.label || '',
            icon: '',
            color: '',
            direction: idea.direction,
        },
        direction: idea.direction,
        conviction: { level: idea.status === 'ACTIVE' ? 'HIGH' : 'MEDIUM', icon: '🔒', label: idea.status },
        unusual_flags: idea.location_tags || [],
        process_locked: idea.status === 'ACTIVE',
        process_direction: idea.direction,
        idea,
    };
}

function processSignal(idea: ProcessIdea): {
    text: string;
    tone: 'bull' | 'bear' | 'none';
    hint: string;
} {
    const d = (idea.direction || idea.side || '').toUpperCase();
    if (idea.status === 'CONFLICT') {
        return { text: 'NO TRADE', tone: 'none', hint: 'Both sides printing — stand aside' };
    }
    if (d === 'BULLISH' || d === 'LONG') {
        return {
            text: 'BULLISH SIGNAL',
            tone: 'bull',
            hint: idea.label || idea.recipe?.name || 'Long process',
        };
    }
    if (d === 'BEARISH' || d === 'SHORT') {
        return {
            text: 'BEARISH SIGNAL',
            tone: 'bear',
            hint: idea.label || idea.recipe?.name || 'Short process',
        };
    }
    return { text: 'NO SIGNAL', tone: 'none', hint: idea.label || 'Waiting for direction' };
}

function ProcessMiniCard({
    idea,
    onOpen,
    selected,
}: {
    idea: ProcessIdea;
    onOpen: (idea: ProcessIdea) => void;
    selected?: boolean;
}) {
    const sig = processSignal(idea);
    const long = sig.tone === 'bull';
    const locked = idea.status === 'ACTIVE';
    const zone =
        idea.entry_zone?.from != null && idea.entry_zone?.to != null
            ? `${fmtPx(idea.entry_zone.from)}–${fmtPx(idea.entry_zone.to)}`
            : fmtPx(idea.entry ?? idea.spot);
    const buyStrike = fmtPx(idea.trade_strike ?? idea.execution?.instrument?.strike ?? idea.strike);
    const buyType = idea.trade_opt_type || idea.execution?.instrument?.opt_type || idea.opt_type || '—';
    const health = idea.cluster_health || idea.execution?.cluster_health;
    return (
        <button
            type="button"
            data-symbol={idea.symbol}
            onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onOpen(idea);
            }}
            className={`w-full text-left p-3 rounded-xl border transition-colors ${
                selected
                    ? 'ring-2 ring-cyan-400/70 border-cyan-400/50 bg-cyan-500/10'
                    : locked && long
                      ? 'bg-emerald-500/8 border-emerald-500/35 hover:border-emerald-400/60'
                      : locked && sig.tone === 'bear'
                        ? 'bg-rose-500/8 border-rose-500/35 hover:border-rose-400/60'
                        : idea.status === 'CONFLICT'
                          ? 'bg-amber-500/8 border-amber-500/30 hover:border-amber-400/50'
                          : 'bg-[#0b1018] border-zinc-800 hover:border-zinc-600'
            }`}
        >
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <p className="text-[15px] font-black text-white truncate">{tickerName(idea)}</p>
                    <p className="text-[10px] text-zinc-500 truncate">{idea.symbol}</p>
                </div>
                <span
                    className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-black ${
                        sig.tone === 'bull'
                            ? 'bg-emerald-500 text-emerald-950'
                            : sig.tone === 'bear'
                              ? 'bg-rose-500 text-rose-950'
                              : 'bg-zinc-700 text-zinc-200'
                    }`}
                >
                    {sig.tone === 'bull' ? 'BULLISH' : sig.tone === 'bear' ? 'BEARISH' : 'FLAT'}
                </span>
            </div>
            <div className="flex flex-wrap items-center gap-1 mt-2">
                <span className="px-1.5 py-0.5 rounded border border-cyan-500/30 text-cyan-300 text-[9px] font-black">
                    {locked ? 'LOCKED' : idea.status}
                </span>
                {idea.hq_pullback && (
                    <span className="px-1.5 py-0.5 rounded bg-amber-400 text-amber-950 text-[9px] font-black">
                        PULLBACK
                    </span>
                )}
                {idea.session?.vwap != null && (
                    <span
                        className={`px-1.5 py-0.5 rounded text-[9px] font-black ${
                            idea.vwap_agree
                                ? 'bg-cyan-500/20 text-cyan-300'
                                : 'bg-zinc-800 text-zinc-400'
                        }`}
                    >
                        VWAP {idea.vwap_side || (idea.spot >= (idea.session.vwap || 0) ? 'ABOVE' : 'BELOW')}
                    </span>
                )}
                <span className="text-[10px] font-black text-zinc-200">
                    Buy {buyStrike} <span className={buyType === 'CE' ? 'text-emerald-400' : 'text-rose-400'}>{buyType}</span>
                </span>
            </div>
            <div className="grid grid-cols-3 gap-1.5 mt-2 text-[10px]">
                <div>
                    <p className="text-zinc-500 font-bold uppercase">Zone</p>
                    <p className="text-zinc-100 font-black truncate">{zone}</p>
                </div>
                <div>
                    <p className="text-zinc-500 font-bold uppercase">Target</p>
                    <p className="text-emerald-300 font-black truncate">{fmtPx(idea.target)}</p>
                </div>
                <div>
                    <p className="text-zinc-500 font-bold uppercase">Stop</p>
                    <p className="text-rose-300 font-black truncate">{fmtPx(idea.stop ?? idea.invalidation)}</p>
                </div>
            </div>
            <div className="flex items-center justify-between mt-2">
                <div className="flex gap-1">
                    {[
                        ['D', idea.mtf?.daily_bias],
                        ['4H', idea.mtf?.h4_bias],
                        ['1H', idea.mtf?.h1_bias],
                        ['15', idea.mtf?.m15_bias],
                    ].map(([tf, bias]) => (
                        <span
                            key={String(tf)}
                            className={`px-1 py-0.5 rounded text-[8px] font-black ${
                                bias === 'BULLISH'
                                    ? 'bg-emerald-500/15 text-emerald-300'
                                    : bias === 'BEARISH'
                                      ? 'bg-rose-500/15 text-rose-300'
                                      : 'bg-zinc-800 text-zinc-600'
                            }`}
                        >
                            {tf}
                        </span>
                    ))}
                </div>
                <span className={`text-[9px] font-black ${
                    health === 'HEALTHY' ? 'text-emerald-400' : health === 'WEAKENING' || health === 'CHAOS' ? 'text-rose-400' : 'text-zinc-500'
                }`}>
                    {idea.execution?.action_label || idea.exec_action || health || 'Plan'}
                </span>
            </div>
        </button>
    );
}

function ProcessCategory({
    title,
    hint,
    accent,
    items,
    empty,
    selectedSymbol,
    onOpen,
}: {
    title: string;
    hint: string;
    accent: string;
    items: ProcessIdea[];
    empty: string;
    selectedSymbol?: string | null;
    onOpen: (idea: ProcessIdea) => void;
}) {
    return (
        <section className={`rounded-2xl border bg-[#0e1420] p-3 ${accent}`}>
            <div className="flex items-end justify-between gap-2 mb-3">
                <div>
                    <h3 className="text-[11px] font-black uppercase tracking-widest">{title}</h3>
                    <p className="text-[10px] text-zinc-500 mt-0.5">{hint}</p>
                </div>
                <span className="text-[10px] font-black text-zinc-500">TOP {Math.min(items.length, 3)} / 3</span>
            </div>
            {items.length === 0 ? (
                <div className="rounded-xl border border-dashed border-zinc-800 px-3 py-8 text-center">
                    <p className="text-[11px] text-zinc-500">{empty}</p>
                </div>
            ) : (
                <div className="space-y-2">
                    {items.slice(0, 3).map((idea) => (
                        <ProcessMiniCard
                            key={`${title}-${idea.symbol}`}
                            idea={idea}
                            selected={selectedSymbol === idea.symbol}
                            onOpen={onOpen}
                        />
                    ))}
                </div>
            )}
        </section>
    );
}

function ProcessIdeaCard({
    idea,
    onOpen,
}: {
    idea: ProcessIdea;
    onOpen: (idea: ProcessIdea) => void;
}) {
    const sig = processSignal(idea);
    const long = sig.tone === 'bull';
    const locked = idea.status === 'ACTIVE';
    return (
        <button
            type="button"
            onClick={() => onOpen(idea)}
            className={`w-full text-left p-4 rounded-xl border transition-colors ${
                locked
                    ? long
                        ? 'bg-emerald-500/8 border-emerald-500/40'
                        : sig.tone === 'bear'
                          ? 'bg-rose-500/8 border-rose-500/40'
                          : 'bg-[#0e1420] border-zinc-800'
                    : idea.status === 'CONFLICT'
                      ? 'bg-amber-500/8 border-amber-500/30'
                      : 'bg-[#0e1420] border-zinc-800'
            }`}
        >
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span
                            className={`px-2.5 py-1 rounded-lg text-xs font-black tracking-wide ${
                                sig.tone === 'bull'
                                    ? 'bg-emerald-500 text-emerald-950'
                                    : sig.tone === 'bear'
                                      ? 'bg-rose-500 text-rose-950'
                                      : 'bg-zinc-700 text-zinc-200'
                            }`}
                        >
                            {sig.text}
                        </span>
                        <span className="text-lg font-black text-white">{idea.name}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-black border border-cyan-500/40 text-cyan-300">
                            {locked ? 'LOCKED' : idea.status}
                        </span>
                        {idea.hq_pullback && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-black bg-amber-400 text-amber-950">
                                HIGH-QUALITY PULLBACK
                            </span>
                        )}
                        {idea.session?.vwap != null && (
                            <span
                                className={`px-2 py-0.5 rounded text-[10px] font-black ${
                                    idea.vwap_agree
                                        ? 'border border-cyan-500/40 text-cyan-300'
                                        : 'border border-zinc-700 text-zinc-400'
                                }`}
                            >
                                VWAP {idea.vwap_side || (idea.spot >= (idea.session.vwap || 0) ? 'ABOVE' : 'BELOW')}
                            </span>
                        )}
                        {idea.campaign && idea.campaign !== 'WATCH' && !idea.hq_pullback && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-black border border-zinc-600 text-zinc-300">
                                {idea.campaign}
                            </span>
                        )}
                        {idea.recipe?.name && (
                            <span className="text-[10px] font-bold text-zinc-400 uppercase">
                                {idea.recipe.name}
                            </span>
                        )}
                    </div>
                    <p className="text-[12px] font-bold mt-1.5 text-zinc-200">{sig.hint}</p>
                    {idea.thesis && (
                        <p className="text-[11px] text-zinc-500 mt-0.5">{idea.thesis}</p>
                    )}
                    <div className="flex flex-wrap gap-1.5 mt-2 text-[10px] font-black">
                        {[
                            ['D', idea.mtf?.daily_bias],
                            ['4H', idea.mtf?.h4_bias],
                            ['1H', idea.mtf?.h1_bias],
                            ['15m', idea.mtf?.m15_bias],
                        ].map(([tf, bias]) => (
                            <span
                                key={String(tf)}
                                className={`px-1.5 py-0.5 rounded border ${
                                    bias === 'BULLISH'
                                        ? 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10'
                                        : bias === 'BEARISH'
                                          ? 'border-rose-500/40 text-rose-300 bg-rose-500/10'
                                          : 'border-zinc-700 text-zinc-500'
                                }`}
                            >
                                {tf} {bias || '—'}
                            </span>
                        ))}
                        {idea.mtf?.m15_trigger && (
                            <span className="px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                                15m TRIGGER
                            </span>
                        )}
                        {idea.mtf?.turning && (
                            <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">
                                1H TURNING
                            </span>
                        )}
                        {idea.align_score != null && (
                            <span className="px-1.5 py-0.5 rounded text-zinc-400">
                                align {idea.align_score > 0 ? '+' : ''}{idea.align_score}
                            </span>
                        )}
                    </div>
                    {(idea.kill_frame || idea.downgrade_frame) && (
                        <p className="text-[10px] text-rose-400 mt-1 font-bold">
                            {idea.kill_frame
                                ? `Killed by ${idea.kill_frame}: ${idea.kill_reason}`
                                : `Downgraded by ${idea.downgrade_frame}: ${idea.downgrade_reason}`}
                        </p>
                    )}
                </div>
                <div className="text-right shrink-0">
                    <p className="text-[9px] font-bold uppercase text-zinc-500">Buy this</p>
                    <p className="text-xl font-black text-white">
                        {fmtPx(idea.trade_strike ?? idea.execution?.instrument?.strike ?? idea.strike)}{' '}
                        <span className={(idea.trade_opt_type || idea.execution?.instrument?.opt_type || idea.opt_type) === 'CE' ? 'text-emerald-400' : 'text-rose-400'}>
                            {idea.trade_opt_type || idea.execution?.instrument?.opt_type || idea.opt_type}
                        </span>
                    </p>
                    <p className={`text-[11px] font-black ${long ? 'text-emerald-400' : sig.tone === 'bear' ? 'text-rose-400' : 'text-zinc-500'}`}>
                        {long ? 'BUY CE / LONG' : sig.tone === 'bear' ? 'BUY PE / SHORT' : 'FLAT'}
                    </p>
                    <p className="text-[10px] text-zinc-500">
                        {locked && idea.hold_seconds != null ? `held ${Math.round(idea.hold_seconds / 60)}m` : `loc ${idea.location_score ?? '—'}`}
                    </p>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-3">
                <div className="p-2 rounded-lg bg-zinc-900/70 border border-zinc-800">
                    <p className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Direction (why)</p>
                    <p className="text-[11px] font-bold text-zinc-200 mt-0.5">{idea.label || sig.hint}</p>
                    <p className="text-[10px] text-zinc-500">
                        Fuel {idea.strike}{idea.opt_type} · does not pick entry
                    </p>
                </div>
                <div className={`p-2 rounded-lg border ${
                    idea.exec_action === 'AT_ENTRY'
                        ? 'bg-emerald-500/10 border-emerald-500/40'
                        : idea.exec_action === 'CLUSTER_BROKEN' || idea.exec_action === 'STAND_ASIDE' || idea.exec_action === 'STOPPED'
                          ? 'bg-rose-500/10 border-rose-500/40'
                          : idea.exec_action === 'TRAIL_EXIT' || idea.exec_action === 'CHASE' || idea.exec_action === 'WAIT_FOR_LEVEL'
                            ? 'bg-amber-500/10 border-amber-500/30'
                            : idea.exec_action === 'EXTEND'
                              ? 'bg-cyan-500/10 border-cyan-500/30'
                              : 'bg-zinc-900/70 border-zinc-800'
                }`}>
                    <p className="text-[9px] font-black uppercase tracking-widest text-zinc-500">Execution (when / where)</p>
                    <p className="text-[11px] font-black text-zinc-100 mt-0.5">
                        {idea.execution?.action_label || idea.exec_action || 'Plan pending'}
                    </p>
                    {idea.reward_risk != null && (
                        <p className="text-[10px] text-cyan-300">R:R {idea.reward_risk}</p>
                    )}
                    <p className="text-[10px] text-zinc-500">
                        Magnet: {idea.execution?.magnet_source === 'OI_CLUSTER' ? 'OI cluster' : idea.execution?.magnet_source || 'tech backup'}
                        {idea.execution?.tech_confirm?.length ? ` · confirm ${idea.execution.tech_confirm.join('+')}` : ''}
                    </p>
                    {(idea.cluster_health || idea.execution?.cluster_health) && (
                        <p className={`text-[10px] font-black mt-0.5 ${
                            (idea.cluster_health || idea.execution?.cluster_health) === 'HEALTHY'
                                ? 'text-emerald-400'
                                : (idea.cluster_health || idea.execution?.cluster_health) === 'WEAKENING' || (idea.cluster_health || idea.execution?.cluster_health) === 'CHAOS'
                                  ? 'text-rose-400'
                                  : 'text-zinc-400'
                        }`}>
                            Cluster {(idea.cluster_health || idea.execution?.cluster_health)}
                            {idea.entry_quality?.label ? ` · entry ${idea.entry_quality.label}` : ''}
                        </p>
                    )}
                    {(idea.exit_warnings || idea.execution?.exit_warnings || []).slice(0, 2).map((w) => (
                        <p key={w} className="text-[10px] font-black text-rose-400">{w}</p>
                    ))}
                </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-2 text-[10px]">
                <div>
                    <p className="text-zinc-500 uppercase font-bold">
                        {long ? 'Entry zone / demand' : 'Entry zone / supply'}
                    </p>
                    <p className="text-zinc-200 font-black">
                        {idea.entry_zone?.from != null && idea.entry_zone?.to != null
                            ? `${fmtPx(idea.entry_zone.from)}–${fmtPx(idea.entry_zone.to)}`
                            : `${idea.entry_label ? `${idea.entry_label} ` : ''}${fmtPx(idea.entry ?? idea.spot)}`}
                    </p>
                    <p className="text-[9px] text-zinc-500 truncate">
                        {idea.entry_zone?.reason
                            || idea.entry_label
                            || (long ? 'Near put cluster' : 'Near call cluster')}
                    </p>
                </div>
                <div>
                    <p className="text-zinc-500 uppercase font-bold">Stop / inv</p>
                    <p className="text-rose-300 font-black">{fmtPx(idea.stop ?? idea.invalidation)}</p>
                </div>
                <div>
                    <p className="text-zinc-500 uppercase font-bold">Target</p>
                    <p className="text-emerald-300 font-black">
                        {idea.target_label ? `${idea.target_label} ` : ''}
                        {fmtPx(idea.target)}
                    </p>
                    {idea.target_2 != null && (
                        <p className="text-[9px] text-zinc-500">
                            T2 {idea.target_2_label ? `${idea.target_2_label} ` : ''}{fmtPx(idea.target_2)}
                        </p>
                    )}
                </div>
                <div>
                    <p className="text-zinc-500 uppercase font-bold">{long ? 'Support wall' : 'Resist wall'}</p>
                    <p className="text-cyan-300 font-black truncate">
                        {long
                            ? `Put ${fmtPx(idea.structure?.put_wall)}`
                            : `Call ${fmtPx(idea.structure?.call_wall)}`}
                    </p>
                    <p className="text-[9px] text-zinc-500">
                        {long
                            ? `Call (tgt) ${fmtPx(idea.structure?.call_wall)}`
                            : `Put (tgt) ${fmtPx(idea.structure?.put_wall)}`}
                    </p>
                </div>
                <div>
                    <p className="text-zinc-500 uppercase font-bold">Fuel print</p>
                    <p className="text-zinc-200 font-black truncate">{idea.strike}{idea.opt_type}</p>
                </div>
            </div>
            {(idea.tag_roles?.entry_tags?.length || idea.location_tags?.length) ? (
                <div className="flex flex-wrap gap-1 mt-2">
                    {(idea.tag_roles?.entry_tags || idea.location_tags || []).slice(0, 6).map(t => (
                        <span key={t} className="px-1.5 py-0.5 rounded bg-zinc-900 border border-zinc-700 text-[9px] font-bold text-zinc-400">
                            {t}
                        </span>
                    ))}
                    {idea.futures?.label && (
                        <span className="px-1.5 py-0.5 rounded bg-blue-500/10 border border-blue-500/30 text-[9px] font-bold text-blue-300">
                            {idea.futures.label}
                        </span>
                    )}
                </div>
            ) : null}
        </button>
    );
}

function GradeBadge({ grade }: { grade?: string }) {
    const g = grade || '—';
    const cls =
        g === 'A+'
            ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
            : g === 'A'
              ? 'bg-blue-500/20 text-blue-300 border-blue-500/40'
              : g === 'B'
                ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                : 'bg-zinc-800 text-zinc-500 border-zinc-700';
    return (
        <span className={`px-1.5 py-0.5 rounded border text-[10px] font-black ${cls}`}>
            {g}
        </span>
    );
}

const RADAR_BOARD_KEY = 'optiongreek:radar:last_board';

function loadCachedBoard(): ScanResult | null {
    if (typeof window === 'undefined') return null;
    try {
        const raw = sessionStorage.getItem(RADAR_BOARD_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || (!parsed.flagged?.length && !parsed.ideas?.length && !parsed.watch?.length)) {
            return null;
        }
        return parsed as ScanResult;
    } catch {
        return null;
    }
}

function saveCachedBoard(data: ScanResult) {
    try {
        sessionStorage.setItem(RADAR_BOARD_KEY, JSON.stringify(data));
    } catch {
        /* quota — ignore */
    }
}

export default function OptionFlowRadar({ onBack }: Props) {
    const [tab, setTab] = useState<TabType>('process');

    // Scan state — seed from this-tab cache so Back/Radar never paints empty
    const [scanData, setScanData] = useState<ScanResult | null>(() => loadCachedBoard());
    const [scanLoading, setScanLoading] = useState(false);
    const [scanError, setScanError] = useState<string | null>(null);
    const [scanProgress, setScanProgress] = useState(0);
    const [scanCurrent, setScanCurrent] = useState<string | null>(null);
    const [scanUniverse, setScanUniverse] = useState(0);
    const [scanDoneCount, setScanDoneCount] = useState(0);
    const [scanLog, setScanLog] = useState<Array<{ sym?: string; status?: string; ms?: number; err?: string | null }>>([]);
    const [scanLastMs, setScanLastMs] = useState(0);
    const [scanLastError, setScanLastError] = useState<string | null>(null);
    const scanPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const scanRunRef = useRef(0);
    const scanLoadingRef = useRef(false);

    // Filters
    const [minLis, setMinLis] = useState(0);
    const [optTypeFilter, setOptTypeFilter] = useState<'CE' | 'PE' | ''>('');
    const [sortBy, setSortBy] = useState<'desk_score' | 'lis' | 'oi_change_pct' | 'volume' | 'composite_score' | 'unusual_score'>('desk_score');

    // Selected contract for detail
    const [selectedContract, setSelectedContract] = useState<FlaggedContract | null>(null);
    const flowReqRef = useRef(0);

    // Symbol flow detail
    const [flowData, setFlowData] = useState<SymbolFlow | null>(null);
    const [flowLoading, setFlowLoading] = useState(false);
    const [flowError, setFlowError] = useState<string | null>(null);

    // Backtest modal
    const [backtestTarget, setBacktestTarget] = useState<FlaggedContract | null>(null);

    // Auto-refresh
    const [autoRefresh, setAutoRefresh] = useState(true);
    const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
    const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Alerts (LIS > 70)
    const [alerts, setAlerts] = useState<FlaggedContract[]>([]);
    const alertedRefs = useRef<Set<string>>(new Set());

    // ── Scan (background job + poll) ─────────────────────────────

    const stopScanPoll = useCallback(() => {
        if (scanPollRef.current) {
            clearInterval(scanPollRef.current);
            scanPollRef.current = null;
        }
    }, []);

    const applyRadarAlerts = useCallback((flagged: FlaggedContract[] | undefined) => {
        if (!flagged?.length) return;
        const newAlerts: FlaggedContract[] = [];
        // Locked process trades first; otherwise Grade A / A+
        flagged
            .filter(c => c.process_locked || c.grade === 'A+' || c.grade === 'A' || (c.actionable && c.lis >= 65))
            .forEach(c => {
                const key = `${c.symbol}-${c.strike}-${c.type}-${(c.timestamp || '').slice(0, 16)}`;
                if (!alertedRefs.current.has(key)) {
                    alertedRefs.current.add(key);
                    newAlerts.push(c);
                }
            });
        if (newAlerts.length) {
            setAlerts(prev => [...newAlerts, ...prev].slice(0, 20));
        }
    }, []);

    const commitScanPayload = useCallback((snap: any) => {
        const flagged = snap.flagged || [];
        const watch = snap.watch || [];
        const alertBox = snap.alert_box || [];
        const next: ScanResult = {
            success: true,
            engine: snap.engine || 'v4-process',
            scanned: snap.scanned ?? snap.completed ?? 0,
            total_flagged: snap.total_flagged ?? flagged.length,
            flagged,
            watch,
            alert_box: alertBox,
            ideas: snap.ideas || [],
            ideas_confirmed: snap.ideas_confirmed || [],
            ideas_bullish: snap.ideas_bullish || [],
            ideas_bearish: snap.ideas_bearish || [],
            ideas_pullbacks: snap.ideas_pullbacks || [],
            ideas_watch: snap.ideas_watch || [],
            ideas_conflict: snap.ideas_conflict || [],
            idea_counts: snap.idea_counts,
            grade_counts: snap.grade_counts,
            errors: snap.errors || [],
            retry_attempted: snap.retry_attempted || 0,
            retry_recovered: snap.retry_recovered || 0,
            failed_remaining: snap.failed_remaining || [],
            timestamp: snap.timestamp || new Date().toISOString(),
            market_hours: snap.market_hours ?? true,
        };
        setScanData((prev) => {
            // Never replace a painted board with an empty snapshot
            const incoming =
                flagged.length +
                watch.length +
                alertBox.length +
                (next.ideas?.length || 0);
            const had =
                (prev?.flagged?.length || 0) +
                (prev?.watch?.length || 0) +
                (prev?.ideas?.length || 0);
            if (prev && incoming === 0 && had > 0) return prev;
            saveCachedBoard(next);
            return next;
        });
    }, []);

    const runScan = useCallback(async (silent = false) => {
        // One FNO pass at a time. Auto-refresh must not start a second job.
        if (scanLoadingRef.current && scanPollRef.current) return;
        const myRun = ++scanRunRef.current;
        stopScanPoll();
        scanLoadingRef.current = true;
        setScanLoading(true);
        setScanError(null);
        if (!silent) setScanProgress(2);
        setScanCurrent(null);

        try {
            const started: any = await api.radar.startScan(
                0,
                undefined,
                14,
            );
            if (myRun !== scanRunRef.current) return;
            const jid = started.job_id as string | null;
            setScanUniverse(Number(started.total || 0));
            setScanDoneCount(Number(started.completed || 0));
            if (started.completion_pct != null) {
                setScanProgress(Number(started.completion_pct));
            }
            if (!jid) {
                // Another pass is already fetching the full list.
                // Keep this board; wait for /radar/last to publish once.
                const waitLast = async () => {
                    if (myRun !== scanRunRef.current) return;
                    try {
                        const last: any = await api.radar.getLastScan();
                        if (myRun !== scanRunRef.current) return;
                        if (last?.scan_running) {
                            setScanCurrent('waiting for in-flight FNO pass');
                            return;
                        }
                        stopScanPoll();
                        scanLoadingRef.current = false;
                        setScanLoading(false);
                        setLastRefresh(new Date());
                        if (last?.has_data) commitScanPayload(last);
                    } catch (e: any) {
                        if (myRun !== scanRunRef.current) return;
                        stopScanPoll();
                        scanLoadingRef.current = false;
                        setScanLoading(false);
                        setScanError(e?.message || 'Radar wait failed');
                    }
                };
                await waitLast();
                if (myRun !== scanRunRef.current) return;
                if (scanLoadingRef.current) {
                    scanPollRef.current = setInterval(waitLast, 2000);
                }
                return;
            }

            const pollOnce = async () => {
                if (myRun !== scanRunRef.current) return;
                try {
                    const snap: any = await api.radar.getScanJob(jid);
                    if (myRun !== scanRunRef.current) return;
                    const requested = Number(snap.universe_requested || snap.total || 0);
                    const scanned = Number(snap.scanned ?? snap.completed ?? 0);
                    setScanUniverse(requested);
                    setScanDoneCount(scanned);
                    setScanProgress(Number(snap.completion_pct ?? 0));
                    setScanCurrent(snap.current_symbol || null);
                    if (Array.isArray(snap.log)) setScanLog(snap.log);
                    if (snap.last_ms != null) setScanLastMs(Number(snap.last_ms) || 0);
                    setScanLastError(snap.last_error || null);
                    const done =
                        snap.status === 'completed' ||
                        snap.status === 'failed' ||
                        snap.status === 'cancelled';
                    // Progress only while running. Paint the board once, after
                    // every FNO name in this job has been fetched.
                    if (done) {
                        stopScanPoll();
                        scanLoadingRef.current = false;
                        setScanLoading(false);
                        setLastRefresh(new Date());
                        const fullPass = requested <= 0 || scanned >= requested;
                        if (snap.status === 'completed' && fullPass && !snap.partial) {
                            commitScanPayload(snap);
                            applyRadarAlerts(snap.flagged || []);
                        } else if (snap.status === 'failed') {
                            setScanError(snap.error_message || 'Radar job failed');
                        } else {
                            setScanError(
                                'Scan finished before every FNO name was fetched. Previous board kept.',
                            );
                        }
                    }
                } catch (e: any) {
                    if (myRun !== scanRunRef.current) return;
                    stopScanPoll();
                    scanLoadingRef.current = false;
                    setScanLoading(false);
                    setScanError(e?.message || 'Radar poll failed');
                }
            };

            await pollOnce();
            if (myRun !== scanRunRef.current) return;
            scanPollRef.current = setInterval(pollOnce, 1500);
        } catch (e: any) {
            if (myRun !== scanRunRef.current) return;
            scanLoadingRef.current = false;
            setScanError(e.message || 'Scan failed');
            setScanLoading(false);
        }
    }, [applyRadarAlerts, commitScanPayload, stopScanPoll]);

    const applyIdeaBoard = useCallback((board: any) => {
        if (!board || scanLoadingRef.current) return;
        const ideas = board.active || board.ideas || [];
        const confirmed = board.confirmed || board.ideas_confirmed || [];
        const bullish = board.bullish || board.ideas_bullish || [];
        const bearish = board.bearish || board.ideas_bearish || [];
        const pullbacks = board.pullbacks || board.ideas_pullbacks || [];
        const watch = board.watch || board.ideas_watch || [];
        const conflict = board.conflict || board.ideas_conflict || [];
        const counts = board.counts || board.idea_counts;
        setScanData((prev) => ({
            success: true,
            scanned: prev?.scanned ?? 0,
            total_flagged: prev?.total_flagged ?? (prev?.flagged?.length ?? 0),
            flagged: prev?.flagged || [],
            watch: prev?.watch || [],
            alert_box: prev?.alert_box || [],
            ideas,
            ideas_confirmed: confirmed,
            ideas_bullish: bullish,
            ideas_bearish: bearish,
            ideas_pullbacks: pullbacks,
            ideas_watch: watch,
            ideas_conflict: conflict,
            idea_counts: counts,
            grade_counts: prev?.grade_counts,
            errors: prev?.errors || [],
            timestamp: board.timestamp || prev?.timestamp || new Date().toISOString(),
            market_hours: prev?.market_hours ?? true,
            engine: board.engine || prev?.engine || 'v4-process',
        }));
    }, []);

    // Paint last completed board immediately so a new scan does not blank the UI
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const last: any = await api.radar.getLastScan();
                if (cancelled || !last) return;
                const hasRows =
                    (last.flagged || []).length ||
                    (last.watch || []).length ||
                    (last.alert_box || []).length ||
                    (last.ideas || []).length ||
                    (last.ideas_watch || []).length;
                if (last.has_data || hasRows) {
                    commitScanPayload(last);
                }
                if (last.scan_running) {
                    scanLoadingRef.current = true;
                    setScanLoading(true);
                }
            } catch {
                /* first visit — wait for scan */
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [commitScanPayload]);

    // Process idea book is independent of a full radar scan — keep the board live
    useEffect(() => {
        let cancelled = false;
        const pull = async () => {
            if (scanLoadingRef.current) return;
            try {
                const board: any = await api.radar.getIdeas(12);
                if (!cancelled && !scanLoadingRef.current && board?.success !== false) {
                    applyIdeaBoard(board);
                }
            } catch {
                /* idea book empty until first scan */
            }
        };
        pull();
        const timer = setInterval(pull, 30_000);
        return () => {
            cancelled = true;
            clearInterval(timer);
        };
    }, [applyIdeaBoard]);

    const [bookMeta, setBookMeta] = useState<{
        symbols?: number;
        chain_fresh?: number;
        history_15_fresh?: number;
        freshest_age?: number | null;
        redis?: string;
        harvest?: { running?: boolean; scanned?: number; total?: number; phase?: string };
    } | null>(null);

    // Poll last board + ideas + harvest meta. UI never starts a 90s Fyers walk.
    useEffect(() => {
        let cancelled = false;
        const pullBook = async () => {
            try {
                const last: any = await api.radar.getLastScan();
                if (cancelled) return;
                const hasRows =
                    (last?.flagged || []).length ||
                    (last?.watch || []).length ||
                    (last?.alert_box || []).length ||
                    (last?.ideas || []).length;
                if (last?.has_data || hasRows) {
                    commitScanPayload(last);
                    setLastRefresh(new Date());
                    if (last.scan_running) {
                        scanLoadingRef.current = true;
                        setScanLoading(true);
                    } else {
                        scanLoadingRef.current = false;
                        setScanLoading(false);
                    }
                }
            } catch {
                /* board empty until first harvest */
            }
            try {
                const st: any = await api.market.getStoreStatus();
                if (!cancelled && st) setBookMeta(st);
            } catch {
                /* store status optional */
            }
        };
        pullBook();
        if (!autoRefresh) return () => { cancelled = true; };
        refreshTimerRef.current = setInterval(pullBook, 15_000);
        return () => {
            cancelled = true;
            if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
        };
    }, [autoRefresh, commitScanPayload]);

    // ── Symbol flow ───────────────────────────────────────────────

    const loadFlow = async (symbol: string) => {
        const req = ++flowReqRef.current;
        setFlowLoading(true);
        setFlowError(null);
        setFlowData(null);
        try {
            const data: SymbolFlow = await api.radar.getSymbolFlow(symbol, 14);
            if (req !== flowReqRef.current) return;
            setFlowData(data);
            if (data.warning) setFlowError(data.warning);
        } catch (e: any) {
            if (req !== flowReqRef.current) return;
            setFlowError(e?.message || 'Failed to load symbol flow');
        } finally {
            if (req === flowReqRef.current) setFlowLoading(false);
        }
    };

    const handleSelectContract = (contract: FlaggedContract) => {
        setSelectedContract(contract);
        loadFlow(contract.symbol);
    };

    const openProcessIdea = (idea: ProcessIdea) => {
        if (!idea?.symbol) return;
        setSelectedContract(ideaToContract(idea));
        setTab('flow');
        loadFlow(idea.symbol);
    };

    // ── Derived data ─────────────────────────────────────────────

    const sortRows = (rows: FlaggedContract[]) =>
        [...rows].sort((a, b) => {
            if (sortBy === 'desk_score')
                return (b.desk_score ?? b.composite_score ?? b.lis) - (a.desk_score ?? a.composite_score ?? a.lis);
            if (sortBy === 'lis') return b.lis - a.lis;
            if (sortBy === 'oi_change_pct') return Math.abs(b.oi_change_pct) - Math.abs(a.oi_change_pct);
            if (sortBy === 'unusual_score') return (b.unusual_score || 0) - (a.unusual_score || 0);
            if (sortBy === 'composite_score')
                return (b.composite_score || b.lis) - (a.composite_score || a.lis);
            return b.volume - a.volume;
        });

    const applyClientFilters = (rows: FlaggedContract[]) =>
        rows.filter((c) => {
            if (minLis > 0 && (c.lis ?? 0) < minLis) return false;
            if (optTypeFilter && c.type !== optTypeFilter) return false;
            return true;
        });
    const sortedContracts = sortRows(applyClientFilters(scanData?.flagged ?? []));
    const alertBoxRows = sortRows(applyClientFilters(scanData?.alert_box ?? []));
    const watchRows = sortRows(applyClientFilters(scanData?.watch ?? []));

    const chartMarkers = flowData?.flagged_contracts.map(c => ({
        timestamp: new Date(c.timestamp).getTime() / 1000,
        lis: c.lis,
        type: c.type,
    }));

    // ── LIS stats ─────────────────────────────────────────────────

    const processPool = dedupeIdeas([
        ...(scanData?.ideas || []),
        ...(scanData?.ideas_confirmed || []),
        ...(scanData?.ideas_bullish || []),
        ...(scanData?.ideas_bearish || []),
        ...(scanData?.ideas_pullbacks || []),
    ]);
    const processWatch = dedupeIdeas(scanData?.ideas_watch || []);
    const processConflict = dedupeIdeas(scanData?.ideas_conflict || []);
    const pureLocked = processPool.filter(i => i.status === 'ACTIVE' && !i.hq_pullback);
    const processBullish = topN(
        scanData?.ideas_bullish?.length
            ? scanData.ideas_bullish
            : pureLocked.filter(i => ideaTone(i) === 'bull'),
    );
    const processBearish = topN(
        scanData?.ideas_bearish?.length
            ? scanData.ideas_bearish
            : pureLocked.filter(i => ideaTone(i) === 'bear'),
    );
    const processPullbacks = topN(scanData?.ideas_pullbacks?.length ? scanData.ideas_pullbacks : processPool.filter(i => i.hq_pullback));
    const processWatchTop = topN(processWatch);
    const processConflictTop = topN(processConflict);
    const processBulls = (scanData?.idea_counts?.bullish ?? processPool.filter(i => ideaTone(i) === 'bull').length);
    const processBears = (scanData?.idea_counts?.bearish ?? processPool.filter(i => ideaTone(i) === 'bear').length);

    const highConviction = sortedContracts.filter(
        c => c.grade === 'A+' || c.grade === 'A' || c.lis >= 70,
    ).length;
    const callCount = sortedContracts.filter(c => c.type === 'CE').length;
    const putCount = sortedContracts.filter(c => c.type === 'PE').length;
    const gradeCounts = scanData?.grade_counts;

    // ── UI helpers ────────────────────────────────────────────────

    const lisColor = (lis: number) =>
        lis >= 70 ? 'text-emerald-400' : lis >= 40 ? 'text-amber-400' : 'text-zinc-500';

    const oiColor = (pct: number) =>
        pct > 20 ? 'text-emerald-400' : pct > 5 ? 'text-blue-400' : pct < -5 ? 'text-rose-400' : 'text-zinc-400';

    const formatOI = (v: number) =>
        v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : String(v);

    const formatNum = (v: number) =>
        v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v);

    // ─────────────────────────────────────────────────────────────
    // Render
    // ─────────────────────────────────────────────────────────────

    return (
        <div className="min-h-screen bg-[#080b11] text-zinc-100">

            {/* ── Alert Banner (LIS > 70) ── */}
            {alerts.length > 0 && (
                <div className="fixed top-4 right-4 z-40 space-y-2 max-w-xs">
                    {alerts.slice(0, 3).map((a, i) => (
                        <div
                            key={i}
                            className="flex items-center gap-3 px-4 py-3 bg-emerald-900/90 border border-emerald-500/50 rounded-xl shadow-lg backdrop-blur-sm animate-pulse-once"
                            onClick={() => setAlerts(prev => prev.filter((_, idx) => idx !== i))}
                        >
                            <span className="text-lg">🔔</span>
                            <div>
                                <p className="text-xs font-black text-emerald-300">HIGH CONVICTION SIGNAL</p>
                                <p className="text-[10px] text-emerald-400">
                                    {a.name} {a.strike} {a.type} — LIS {Math.round(a.lis)}
                                </p>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* ── Backtest Modal ── */}
            {backtestTarget && (
                <BacktestPanel
                    contract={backtestTarget}
                    onClose={() => setBacktestTarget(null)}
                />
            )}

            {/* ── Header ── */}
            <header className="border-b border-zinc-800 bg-[#0c1018]/95 backdrop-blur-sm sticky top-0 z-30">
                <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center gap-4">
                    <button
                        onClick={onBack}
                        className="p-2 hover:bg-zinc-800 rounded-lg transition-colors text-zinc-400 hover:text-white"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                        </svg>
                    </button>

                    <div>
                        <h1 className="text-lg font-black tracking-tight text-white uppercase">
                            🎯 Option Flow Radar{' '}
                            <span className="text-cyan-500 text-xs not-italic font-black">v4</span>
                        </h1>
                        <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-widest">
                            Flow + RSI 15/1H + OC permission + 4H · ranked by desk score
                        </p>
                    </div>

                    <div className="ml-auto flex items-center gap-3">
                        {/* Market status */}
                        <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-bold border ${
                            scanData?.market_hours
                                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                                : 'bg-zinc-800 border-zinc-700 text-zinc-500'
                        }`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${scanData?.market_hours ? 'bg-emerald-500 animate-pulse' : 'bg-zinc-600'}`} />
                            {scanData?.market_hours ? 'Market Open' : 'Market Closed'}
                        </div>

                        {/* Auto refresh toggle */}
                        <button
                            onClick={() => setAutoRefresh(!autoRefresh)}
                            className={`px-3 py-1.5 rounded-full text-[10px] font-bold border transition-all ${
                                autoRefresh
                                    ? 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                                    : 'bg-zinc-800 border-zinc-700 text-zinc-500'
                            }`}
                        >
                            {autoRefresh ? '🔄 Auto' : '⏸ Paused'}
                        </button>

                        <button
                            onClick={() => runScan()}
                            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-[10px] font-black uppercase rounded-full transition-all"
                        >
                            {scanLoading ? 'Harvesting…' : '↻ Refresh book'}
                        </button>

                        {lastRefresh && (
                            <span className="text-[9px] text-zinc-600">
                                {lastRefresh.toLocaleTimeString()}
                            </span>
                        )}
                    </div>
                </div>

                {bookMeta && (
                    <div className="max-w-screen-2xl mx-auto px-4 pb-2">
                        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border border-zinc-700 bg-zinc-900/80 text-zinc-400">
                            <span className={`w-1.5 h-1.5 rounded-full ${bookMeta.harvest?.running ? 'bg-amber-400 animate-pulse' : 'bg-emerald-500'}`} />
                            Book age {bookMeta.freshest_age != null ? `${Math.round(bookMeta.freshest_age)}s` : '—'}
                            {' · '}
                            {bookMeta.chain_fresh ?? 0}/{bookMeta.symbols ?? 0} chains
                            {' · '}
                            15m {bookMeta.history_15_fresh ?? 0}/{bookMeta.symbols ?? 0}
                            {' · '}
                            {bookMeta.redis === 'ok' ? 'Redis' : 'Memory'}
                            {bookMeta.harvest?.running
                                ? ` · warming ${bookMeta.harvest.scanned ?? 0}/${bookMeta.harvest.total ?? 0} ${bookMeta.harvest.phase || ''}`
                                : ''}
                        </div>
                    </div>
                )}

                {/* Tab bar */}
                <div className="max-w-screen-2xl mx-auto px-4 flex gap-1 pb-0 flex-wrap">
                    {[
                        { id: 'process', label: `🔒 Process (${scanData?.idea_counts?.active ?? scanData?.ideas?.length ?? 0})` },
                        { id: 'live', label: `📡 Tape A/A+ (${sortedContracts.length})` },
                        { id: 'alerts', label: `🚨 Alert Box (${alertBoxRows.length})` },
                        { id: 'watch', label: `👁 Watch B (${watchRows.length})` },
                        { id: 'flow', label: '📊 Stock Flow Detail' },
                        { id: 'backtest_list', label: '🧪 Signal Log' },
                    ].map(t => (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id as TabType)}
                            className={`px-4 py-2 text-xs font-bold uppercase transition-all border-b-2 ${
                                tab === t.id
                                    ? 'border-blue-500 text-blue-400'
                                    : 'border-transparent text-zinc-500 hover:text-zinc-300'
                            }`}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
            </header>

            <main className="max-w-screen-2xl mx-auto px-4 py-4">
                <LoadingBanner
                    active={scanLoading}
                    label={
                        scanUniverse
                            ? `Scanning FNO ${scanDoneCount}/${scanUniverse}`
                            : scanData
                              ? 'Starting full FNO job'
                              : 'Scanning full FNO universe'
                    }
                    progress={scanProgress}
                    detail={
                        scanLoading
                            ? [
                                  scanLog.some((r) => r.status === 'wait' || r.status === 'retry' || r.status === 'retry_start')
                                      ? 'Waiting on quota — staying on this name until the chain arrives'
                                      : null,
                                  scanCurrent
                                      ? `Now ${String(scanCurrent).replace('NSE:', '').replace('-EQ', '').replace('-INDEX', '')}`
                                      : null,
                                  scanLastMs ? `${scanLastMs}ms` : null,
                                  scanLastError ? `last ${scanLastError}` : null,
                                  'previous board held',
                              ]
                                  .filter(Boolean)
                                  .join(' · ')
                            : 'Job finished · waited for missing chains · board swapped once'
                    }
                />
                {scanLoading && scanLog.length > 0 && (
                    <div className="mb-4 flex flex-wrap gap-1.5">
                        {scanLog.slice(-20).map((row, i) => (
                            <span
                                key={`${row.sym}-${i}`}
                                className={`px-1.5 py-0.5 rounded text-[9px] font-black border ${
                                    row.status === 'hit' || row.status === 'retry_hit'
                                        ? 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10'
                                        : row.status === 'wait' || row.status === 'retry' || row.status === 'retry_start'
                                          ? 'border-amber-500/40 text-amber-300 bg-amber-500/10'
                                          : row.status === 'err' || row.status === 'timeout' || (row.status || '').startsWith('no_chain')
                                            ? 'border-rose-500/40 text-rose-300 bg-rose-500/10'
                                            : 'border-zinc-700 text-zinc-500 bg-zinc-900/60'
                                }`}
                                title={row.err || `${row.status || ''} ${row.ms || 0}ms`}
                            >
                                {row.sym}
                                {row.status === 'wait' ? ' …' : ''}
                                {row.status === 'retry' || row.status === 'retry_start' ? ' ↻' : ''}
                                {row.status === 'retry_hit' ? ' ✓' : ''}
                                {row.ms != null ? ` ${row.ms}ms` : ''}
                            </span>
                        ))}
                    </div>
                )}
                {!scanLoading && ((scanData?.retry_attempted || 0) > 0 || (scanData?.failed_remaining || []).length > 0) && (
                    <div className="mb-4 px-3 py-2 rounded-xl border border-zinc-800 bg-[#0e1420] text-[11px] text-zinc-400">
                        <span className="font-black text-zinc-200">Chain wait</span>
                        {' · '}
                        recovered {scanData?.retry_recovered ?? 0}/{scanData?.retry_attempted ?? 0}
                        {(scanData?.failed_remaining || []).length > 0 && (
                            <span className="text-rose-300">
                                {' · still missing '}
                                {(scanData?.failed_remaining || [])
                                    .slice(0, 8)
                                    .map((s) => String(s).replace('NSE:', '').replace('-EQ', '').replace('-INDEX', ''))
                                    .join(' ')}
                                {(scanData?.failed_remaining || []).length > 8
                                    ? ` +${(scanData?.failed_remaining || []).length - 8}`
                                    : ''}
                            </span>
                        )}
                    </div>
                )}

                {/* ══════════════════════════════════════════════
                    TAB: LIVE MONITOR
                ══════════════════════════════════════════════ */}
                {tab === 'process' && (
                    <div className="space-y-4">
                        <div className="p-4 rounded-2xl border border-zinc-800 bg-[#0e1420]">
                            <div className="flex flex-wrap items-end justify-between gap-3">
                                <div>
                                    <p className="text-[10px] font-black uppercase tracking-widest text-zinc-500">
                                        Process board
                                    </p>
                                    <p className="text-xl font-black text-white mt-0.5">
                                        Top 3 in each category
                                    </p>
                                    <p className="text-[11px] text-zinc-500 mt-0.5">
                                        Click a stock to open that same symbol.
                                        {scanLoading
                                            ? ` · scanning ${scanDoneCount}/${scanUniverse || '…'} FNO — categories stay put until the job finishes`
                                            : ''}
                                    </p>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    <span className="px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-300 text-xs font-black">
                                        BULL {processBulls}
                                    </span>
                                    <span className="px-3 py-1.5 rounded-lg bg-rose-500/15 text-rose-300 text-xs font-black">
                                        BEAR {processBears}
                                    </span>
                                    <span className="px-3 py-1.5 rounded-lg bg-amber-500/15 text-amber-300 text-xs font-black">
                                        PB {scanData?.idea_counts?.pullbacks ?? processPullbacks.length}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                            {[
                                { label: 'Pure bullish', value: scanData?.idea_counts?.bullish ?? processBulls, color: 'text-emerald-400' },
                                { label: 'Pure bearish', value: scanData?.idea_counts?.bearish ?? processBears, color: 'text-rose-400' },
                                { label: 'HQ pullback', value: scanData?.idea_counts?.pullbacks ?? processPullbacks.length, color: 'text-amber-400' },
                                { label: 'Watch', value: scanData?.idea_counts?.watch ?? processWatch.length, color: 'text-zinc-300' },
                                { label: 'Conflict', value: scanData?.idea_counts?.conflict ?? processConflict.length, color: 'text-orange-400' },
                            ].map(s => (
                                <div key={s.label} className="bg-[#0e1420] border border-zinc-800 rounded-xl p-3 text-center">
                                    <p className={`text-2xl font-black ${s.color}`}>{s.value}</p>
                                    <p className="text-[9px] font-bold text-zinc-600 uppercase mt-0.5">{s.label}</p>
                                </div>
                            ))}
                        </div>

                        <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                            <ProcessCategory
                                title="Pure bullish"
                                hint="Spot above VWAP · CE/PE fuel · not 4H short"
                                accent="border-emerald-500/25"
                                items={processBullish}
                                empty="No locked long ideas yet"
                                selectedSymbol={selectedContract?.symbol}
                                onOpen={openProcessIdea}
                            />
                            <ProcessCategory
                                title="Pure bearish"
                                hint="Spot below VWAP · PE/CE fuel · not 4H long"
                                accent="border-rose-500/25"
                                items={processBearish}
                                empty="No locked short ideas yet"
                                selectedSymbol={selectedContract?.symbol}
                                onOpen={openProcessIdea}
                            />
                            <ProcessCategory
                                title="HQ pullback"
                                hint="4H trend intact · 1H turning into the dip / rally"
                                accent="border-amber-500/25"
                                items={processPullbacks}
                                empty="No high-quality pullbacks"
                                selectedSymbol={selectedContract?.symbol}
                                onOpen={openProcessIdea}
                            />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <ProcessCategory
                                title="Watch"
                                hint="Building — not locked"
                                accent="border-zinc-800"
                                items={processWatchTop}
                                empty="Nothing on watch"
                                selectedSymbol={selectedContract?.symbol}
                                onOpen={openProcessIdea}
                            />
                            <ProcessCategory
                                title="Conflict"
                                hint="Both sides printing — stand aside"
                                accent="border-orange-500/20"
                                items={processConflictTop}
                                empty="No conflicts"
                                selectedSymbol={selectedContract?.symbol}
                                onOpen={openProcessIdea}
                            />
                        </div>
                    </div>
                )}

                {tab === 'live' && (
                    <div className="space-y-4">

                        {/* Stats row */}
                        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                            {[
                                { label: 'Symbols Scanned', value: scanData?.scanned ?? '—', color: 'text-zinc-300' },
                                { label: 'Grade A / A+', value: scanData?.total_flagged ?? sortedContracts.length, color: 'text-emerald-400' },
                                { label: 'Alert Box', value: alertBoxRows.length, color: 'text-rose-400' },
                                { label: 'Watch (B)', value: watchRows.length, color: 'text-amber-400' },
                                {
                                    label: 'A+ / A / B',
                                    value: gradeCounts
                                        ? `${gradeCounts['A+'] || 0}/${gradeCounts.A || 0}/${gradeCounts.B || 0}`
                                        : '—',
                                    color: 'text-cyan-400',
                                },
                                { label: 'CE / PE (A board)', value: `${callCount}/${putCount}`, color: 'text-blue-400' },
                            ].map(s => (
                                <div key={s.label} className="bg-[#0e1420] border border-zinc-800 rounded-xl p-3 text-center">
                                    <p className={`text-2xl font-black ${s.color}`}>{s.value}</p>
                                    <p className="text-[9px] font-bold text-zinc-600 uppercase mt-0.5">{s.label}</p>
                                </div>
                            ))}
                        </div>

                        <div className="p-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 text-[11px] text-zinc-400">
                            <strong className="text-cyan-400">v3 multi-layer:</strong> CE/PE flow matrix → vol ≥1.5× &amp; OI ≥8% →
                            ATM ≤7% + Greek quality → underlying context → <strong>Grade A+/A</strong> on this board.
                            Unusual size goes to <strong>Alert Box</strong> (does not auto-trade). Grade B is Watch only.
                        </div>

                        {/* Filters */}
                        <div className="flex flex-wrap items-center gap-3 p-3 bg-[#0e1420] border border-zinc-800 rounded-xl">
                            <span className="text-[10px] font-bold text-zinc-500 uppercase">Filters:</span>

                            {/* Min LIS */}
                            <div className="flex items-center gap-2">
                                <label className="text-[10px] text-zinc-500 uppercase">Min LIS</label>
                                <select
                                    value={minLis}
                                    onChange={e => setMinLis(Number(e.target.value))}
                                    className="bg-zinc-900 border border-zinc-700 text-zinc-300 text-xs rounded-lg px-2 py-1"
                                >
                                    <option value={0}>All (0+)</option>
                                    <option value={30}>30+</option>
                                    <option value={50}>50+</option>
                                    <option value={70}>70+ (High)</option>
                                </select>
                            </div>

                            {/* Type */}
                            <div className="flex items-center gap-2">
                                <label className="text-[10px] text-zinc-500 uppercase">Type</label>
                                <div className="flex gap-1">
                                    {(['', 'CE', 'PE'] as const).map(t => (
                                        <button
                                            key={t}
                                            onClick={() => setOptTypeFilter(t)}
                                            className={`px-2 py-1 text-[10px] font-bold rounded-lg transition-all ${
                                                optTypeFilter === t
                                                    ? 'bg-blue-600 text-white'
                                                    : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                                            }`}
                                        >
                                            {t || 'All'}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Sort */}
                            <div className="flex items-center gap-2 ml-auto">
                                <label className="text-[10px] text-zinc-500 uppercase">Sort by</label>
                                <select
                                    value={sortBy}
                                    onChange={e => setSortBy(e.target.value as typeof sortBy)}
                                    className="bg-zinc-900 border border-zinc-700 text-zinc-300 text-xs rounded-lg px-2 py-1"
                                >
                                    <option value="desk_score">Desk (all params)</option>
                                    <option value="composite_score">Composite</option>
                                    <option value="lis">LIS Score</option>
                                    <option value="unusual_score">Unusual Score</option>
                                    <option value="oi_change_pct">OI Change %</option>
                                    <option value="volume">Volume</option>
                                </select>
                            </div>
                        </div>

                        {/* Error */}
                        {scanError && (
                            <div className="p-4 bg-rose-900/20 border border-rose-800 rounded-xl text-sm text-rose-400">
                                ⚠️ {scanError}
                                <button onClick={() => runScan()} className="ml-4 text-xs underline hover:no-underline">Retry</button>
                            </div>
                        )}

                        {/* Main table — stay visible while a new scan updates scores */}
                        {sortedContracts.length > 0 && (
                            <div className="bg-[#0e1420] border border-zinc-800 rounded-xl overflow-hidden">
                                <div className="overflow-x-auto">
                                    <table className="w-full">
                                        <thead>
                                            <tr className="border-b border-zinc-800 text-[10px] text-zinc-500 uppercase">
                                                <th className="py-2 pl-4 text-left">Time</th>
                                                <th className="py-2 text-left">Symbol</th>
                                                <th className="py-2 text-center">Strike</th>
                                                <th className="py-2 text-center">Type</th>
                                                <th className="py-2 text-center">Grade</th>
                                                <th className="py-2 text-right">OI Chg%</th>
                                                <th className="py-2 text-right">Vol×</th>
                                                <th className="py-2 text-right">GQ</th>
                                                <th className="py-2 text-right">Spot Chg%</th>
                                                <th className="py-2 text-center">Signal</th>
                                                <th className="py-2 text-center">LIS</th>
                                                <th className="py-2 text-center">Desk</th>
                                                <th className="py-2 text-center">RSI 15/1H</th>
                                                <th className="py-2 text-center">OC P</th>
                                                <th className="py-2 text-center">Action</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {sortedContracts.map((c, i) => (
                                                <tr
                                                    key={`${c.symbol}-${c.strike}-${c.type}-${i}`}
                                                    onClick={() => { handleSelectContract(c); setTab('flow'); }}
                                                    className={`border-b border-zinc-800/50 cursor-pointer transition-colors hover:bg-zinc-800/30 ${
                                                        selectedContract?.symbol === c.symbol && selectedContract?.strike === c.strike
                                                            ? 'bg-blue-500/5'
                                                            : ''
                                                    }`}
                                                >
                                                    <td className="py-2.5 pl-4 text-[10px] text-zinc-500 font-mono">
                                                        {new Date(c.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                    </td>
                                                    <td className="py-2.5">
                                                        <div>
                                                            <p className="text-sm font-black text-white flex items-center gap-1.5">
                                                                {c.name}
                                                                {c.process_locked && (
                                                                    <span className="px-1.5 py-0.5 rounded text-[9px] font-black bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
                                                                        LOCKED
                                                                    </span>
                                                                )}
                                                            </p>
                                                            <p className="text-[9px] text-zinc-500">
                                                                Exp: {formatExpiryText(c.expiry)} • ATM dist: {c.atm_dist_pct?.toFixed(1)}%
                                                                {c.location_score != null ? ` • loc ${c.location_score}` : ''}
                                                                {c.h4_bias ? ` • 4H ${c.h4_bias}` : ''}
                                                            </p>
                                                            {c.desk_align && c.desk_align !== 'FLOW' && (
                                                                <span className={`inline-block mt-0.5 px-1.5 py-0.5 rounded text-[9px] font-black ${
                                                                    c.desk_align === 'STACK'
                                                                        ? 'bg-emerald-500/20 text-emerald-300'
                                                                        : c.desk_align === 'VETO' || c.desk_align === 'FIGHT'
                                                                          ? 'bg-rose-500/20 text-rose-300'
                                                                          : 'bg-zinc-700 text-zinc-300'
                                                                }`}>
                                                                    {c.desk_thesis || c.desk_align}
                                                                </span>
                                                            )}
                                                        </div>
                                                    </td>
                                                    <td className="py-2.5 text-center font-bold text-zinc-200 text-sm">
                                                        {c.strike}
                                                    </td>
                                                    <td className="py-2.5 text-center">
                                                        <span className={`px-2 py-0.5 rounded text-xs font-black ${
                                                            c.type === 'CE'
                                                                ? 'bg-emerald-500/15 text-emerald-400'
                                                                : 'bg-rose-500/15 text-rose-400'
                                                        }`}>
                                                            {c.type}
                                                        </span>
                                                    </td>
                                                    <td className="py-2.5 text-center">
                                                        <GradeBadge grade={c.grade} />
                                                    </td>
                                                    <td className={`py-2.5 text-right text-sm font-bold tabular-nums ${oiColor(c.oi_change_pct)}`}>
                                                        {c.oi_change_pct > 0 ? '+' : ''}{c.oi_change_pct?.toFixed(1)}%
                                                    </td>
                                                    <td className="py-2.5 text-right text-xs text-zinc-300 tabular-nums">
                                                        {(c.vol_spike_ratio ?? 0).toFixed(1)}×
                                                    </td>
                                                    <td className="py-2.5 text-right text-xs font-mono text-purple-300">
                                                        {c.greek_quality?.score != null
                                                            ? `${c.greek_quality.score}/20`
                                                            : '—'}
                                                    </td>
                                                    <td className={`py-2.5 text-right text-xs font-bold ${c.spot_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                        {c.spot_change_pct >= 0 ? '+' : ''}{c.spot_change_pct?.toFixed(2)}%
                                                    </td>
                                                    <td className="py-2.5 text-center">
                                                        <SignalBadge signal={c.signal} />
                                                    </td>
                                                    <td className="py-2.5 text-center">
                                                        <LISRing lis={c.lis} />
                                                    </td>
                                                    <td className="py-2.5 text-center">
                                                        <span className="text-sm font-black text-cyan-300 tabular-nums">
                                                            {c.desk_score != null ? c.desk_score : '—'}
                                                        </span>
                                                    </td>
                                                    <td className="py-2.5 text-center font-mono text-[11px] text-zinc-300">
                                                        {c.rsi15 != null ? c.rsi15 : '—'}
                                                        <span className="text-zinc-600"> / </span>
                                                        {c.rsi60 != null ? c.rsi60 : '—'}
                                                        {c.rsi_event && c.rsi_event !== 'NONE' && c.rsi_event !== 'MID' && (
                                                            <div className="text-[8px] text-fuchsia-400 font-bold">
                                                                {c.rsi_event}
                                                            </div>
                                                        )}
                                                        {c.rsi_div && (
                                                            <div
                                                                className={`text-[8px] font-black ${
                                                                    c.rsi_div === 'BULL_DIV'
                                                                        ? 'text-emerald-400'
                                                                        : 'text-rose-400'
                                                                }`}
                                                                title={[
                                                                    c.rsi_div_event,
                                                                    c.rsi_div_price_l1 != null && c.rsi_div_price_l2 != null
                                                                        ? `15m price ${c.rsi_div_price_l1}→${c.rsi_div_price_l2}`
                                                                        : null,
                                                                    c.rsi_div_rsi_l1 != null && c.rsi_div_rsi_l2 != null
                                                                        ? `RSI ${c.rsi_div_rsi_l1}→${c.rsi_div_rsi_l2}`
                                                                        : null,
                                                                    c.rsi_div_bars_ago != null ? `${c.rsi_div_bars_ago} bars ago` : null,
                                                                ]
                                                                    .filter(Boolean)
                                                                    .join(' · ')}
                                                            >
                                                                {c.rsi_div === 'BULL_DIV' ? 'BULL DIV' : 'BEAR DIV'}
                                                                {c.rsi_div_fresh ? ' FRESH' : ''}
                                                            </div>
                                                        )}
                                                    </td>
                                                    <td className="py-2.5 text-center text-xs font-bold text-amber-300 tabular-nums">
                                                        {c.oc_permission != null ? c.oc_permission : '—'}
                                                    </td>
                                                    <td className="py-2.5 text-center">
                                                        <button
                                                            onClick={e => { e.stopPropagation(); setBacktestTarget(c); }}
                                                            className="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white text-[9px] font-bold uppercase rounded transition-colors"
                                                        >
                                                            Backtest
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        )}

                        {sortedContracts.length === 0 && !scanError && (
                            <div className="flex flex-col items-center justify-center py-16 text-center">
                                <p className="text-4xl mb-3">🔍</p>
                                <p className="text-sm font-bold text-zinc-400">No Grade A/A+ signals</p>
                                <p className="text-xs text-zinc-600 mt-1">
                                    {watchRows.length || alertBoxRows.length
                                        ? `Check Alert Box (${alertBoxRows.length}) or Watch (${watchRows.length}) — multi-layer filter is strict by design.`
                                        : minLis > 0
                                          ? `Try lowering Min LIS below ${minLis}`
                                          : 'No multi-layer confirmed flow right now (or market closed).'}
                                </p>
                            </div>
                        )}
                    </div>
                )}

                {/* ══════════════════════════════════════════════
                    TAB: ALERT BOX (unusual / big player)
                ══════════════════════════════════════════════ */}
                {tab === 'alerts' && (
                    <div className="space-y-4">
                        <div className="p-3 rounded-xl border border-rose-500/30 bg-rose-500/5 text-[11px] text-zinc-400">
                            <strong className="text-rose-400">Alert Box</strong> — unusual / institutional-size footprint.
                            Sorted by Unusual Score. Does <strong>not</strong> auto-promote to trade; review manually.
                        </div>
                        {alertBoxRows.length === 0 ? (
                            <div className="py-16 text-center text-zinc-500 text-sm">No unusual alerts this scan.</div>
                        ) : (
                            <div className="bg-[#0e1420] border border-zinc-800 rounded-xl overflow-x-auto">
                                <table className="w-full text-xs">
                                    <thead>
                                        <tr className="border-b border-zinc-800 text-[10px] text-zinc-500 uppercase">
                                            <th className="py-2 pl-4 text-left">Symbol</th>
                                            <th className="py-2 text-center">Strike</th>
                                            <th className="py-2 text-center">Grade</th>
                                            <th className="py-2 text-right">Unusual</th>
                                            <th className="py-2 text-right">OI add</th>
                                            <th className="py-2 text-right">Vol×</th>
                                            <th className="py-2 text-center">Signal</th>
                                            <th className="py-2 text-center">LIS</th>
                                            <th className="py-2 text-left">Why</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {alertBoxRows.map((c, i) => (
                                            <tr
                                                key={`ab-${c.symbol}-${c.strike}-${c.type}-${i}`}
                                                onClick={() => { handleSelectContract(c); setTab('flow'); }}
                                                className="border-b border-zinc-800/50 cursor-pointer hover:bg-zinc-800/30"
                                            >
                                                <td className="py-2.5 pl-4 font-black text-white">{c.name}</td>
                                                <td className="py-2.5 text-center font-bold">{c.strike} {c.type}</td>
                                                <td className="py-2.5 text-center"><GradeBadge grade={c.grade} /></td>
                                                <td className="py-2.5 text-right font-black text-rose-400">{c.unusual_score ?? '—'}</td>
                                                <td className="py-2.5 text-right font-mono text-zinc-300">{formatNum(c.oi_added || 0)}</td>
                                                <td className="py-2.5 text-right">{(c.vol_spike_ratio ?? 0).toFixed(1)}×</td>
                                                <td className="py-2.5 text-center"><SignalBadge signal={c.signal} /></td>
                                                <td className="py-2.5 text-center font-black text-emerald-400">{Math.round(c.lis)}</td>
                                                <td className="py-2.5 text-[10px] text-zinc-500 max-w-[220px]">
                                                    {(c.unusual_flags || []).slice(0, 3).join(' · ')}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {/* ══════════════════════════════════════════════
                    TAB: WATCH (Grade B)
                ══════════════════════════════════════════════ */}
                {tab === 'watch' && (
                    <div className="space-y-4">
                        <div className="p-3 rounded-xl border border-amber-500/30 bg-amber-500/5 text-[11px] text-zinc-400">
                            <strong className="text-amber-400">Watch list</strong> — Grade B: decent flow missing 1–2 confirmation layers.
                            Not high-conviction; monitor only.
                        </div>
                        {watchRows.length === 0 ? (
                            <div className="py-16 text-center text-zinc-500 text-sm">No Grade B watches this scan.</div>
                        ) : (
                            <div className="bg-[#0e1420] border border-zinc-800 rounded-xl overflow-x-auto">
                                <table className="w-full text-xs">
                                    <thead>
                                        <tr className="border-b border-zinc-800 text-[10px] text-zinc-500 uppercase">
                                            <th className="py-2 pl-4 text-left">Symbol</th>
                                            <th className="py-2 text-center">Strike</th>
                                            <th className="py-2 text-center">Layers</th>
                                            <th className="py-2 text-right">GQ</th>
                                            <th className="py-2 text-center">Signal</th>
                                            <th className="py-2 text-center">LIS</th>
                                            <th className="py-2 text-left">Missing</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {watchRows.map((c, i) => {
                                            const layers = c.layers || {};
                                            const missing = Object.entries(layers)
                                                .filter(([, v]) => !v)
                                                .map(([k]) => k)
                                                .join(', ');
                                            return (
                                                <tr
                                                    key={`w-${c.symbol}-${c.strike}-${c.type}-${i}`}
                                                    onClick={() => { handleSelectContract(c); setTab('flow'); }}
                                                    className="border-b border-zinc-800/50 cursor-pointer hover:bg-zinc-800/30"
                                                >
                                                    <td className="py-2.5 pl-4 font-black text-white">{c.name}</td>
                                                    <td className="py-2.5 text-center font-bold">{c.strike} {c.type}</td>
                                                    <td className="py-2.5 text-center font-mono text-amber-300">
                                                        {c.layers_passed ?? '—'}/6
                                                    </td>
                                                    <td className="py-2.5 text-right text-purple-300">
                                                        {c.greek_quality?.score != null ? `${c.greek_quality.score}/20` : '—'}
                                                    </td>
                                                    <td className="py-2.5 text-center"><SignalBadge signal={c.signal} /></td>
                                                    <td className="py-2.5 text-center font-black">{Math.round(c.lis)}</td>
                                                    <td className="py-2.5 text-[10px] text-zinc-500">{missing || '—'}</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {/* ══════════════════════════════════════════════
                    TAB: STOCK FLOW DETAIL
                ══════════════════════════════════════════════ */}
                {tab === 'flow' && (
                    <div className="space-y-4">
                        {!selectedContract ? (
                            <div className="flex flex-col items-center justify-center py-16 text-center">
                                <p className="text-4xl mb-3">👆</p>
                                <p className="text-sm font-bold text-zinc-400">Select a contract from Live Monitor</p>
                                <p className="text-xs text-zinc-600 mt-1">Click any row in the Live Monitor tab to view its detailed flow</p>
                                <button onClick={() => setTab('live')} className="mt-4 px-4 py-2 bg-blue-600 text-white text-xs font-bold rounded-lg">
                                    Go to Live Monitor →
                                </button>
                            </div>
                        ) : (
                            <>
                                {flowError && (
                                    <div className="p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-[11px] text-amber-200">
                                        {flowError}
                                        <button
                                            type="button"
                                            onClick={() => selectedContract && loadFlow(selectedContract.symbol)}
                                            className="ml-3 underline"
                                        >
                                            Retry
                                        </button>
                                    </div>
                                )}
                                {/* Selected contract header */}
                                <div className="flex items-start gap-4 p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                                    <LISRing lis={selectedContract.lis} />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-3 flex-wrap">
                                            <h2 className="text-xl font-black text-white">
                                                {selectedContract.name}
                                            </h2>
                                            <span className="text-[11px] font-bold text-zinc-500 truncate">
                                                {selectedContract.symbol}
                                            </span>
                                            <span className={`px-2 py-0.5 rounded text-sm font-black ${
                                                selectedContract.type === 'CE'
                                                    ? 'bg-emerald-500/15 text-emerald-400'
                                                    : 'bg-rose-500/15 text-rose-400'
                                            }`}>
                                                {selectedContract.strike} {selectedContract.type}
                                            </span>
                                            <SignalBadge signal={selectedContract.signal} />
                                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                                                selectedContract.conviction.level === 'HIGH'
                                                    ? 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10'
                                                    : selectedContract.conviction.level === 'MEDIUM'
                                                    ? 'border-amber-500/40 text-amber-400 bg-amber-500/10'
                                                    : 'border-zinc-700 text-zinc-500'
                                            }`}>
                                                {selectedContract.conviction.icon} {selectedContract.conviction.label}
                                            </span>
                                        </div>
                                        <div className="flex flex-wrap gap-4 mt-2 text-xs">
                                            <span className="text-zinc-400">
                                                Spot: <span className="text-white font-bold">₹{selectedContract.spot?.toLocaleString('en-IN')}</span>
                                                <span className={`ml-1 ${selectedContract.spot_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                    ({selectedContract.spot_change_pct >= 0 ? '+' : ''}{selectedContract.spot_change_pct?.toFixed(2)}%)
                                                </span>
                                            </span>
                                            <span className="text-zinc-400">
                                                OI Chg: <span className={`font-bold ${oiColor(selectedContract.oi_change_pct)}`}>
                                                    {selectedContract.oi_change_pct >= 0 ? '+' : ''}{selectedContract.oi_change_pct?.toFixed(1)}%
                                                </span>
                                            </span>
                                            <span className="text-zinc-400">
                                                VWAP Dev: <span className="font-bold text-zinc-300">{selectedContract.vwap_dev_pct?.toFixed(2)}%</span>
                                            </span>
                                            <span className={`${selectedContract.above_ema20 ? 'text-emerald-400' : 'text-rose-400'} font-bold`}>
                                                {selectedContract.above_ema20 ? '↑ Above EMA20' : '↓ Below EMA20'}
                                            </span>
                                            {selectedContract.desk_score != null && (
                                                <span className="text-cyan-300 font-black">
                                                    Desk {selectedContract.desk_score}
                                                    {selectedContract.desk_thesis ? ` · ${selectedContract.desk_thesis}` : ''}
                                                </span>
                                            )}
                                            {(selectedContract.rsi15 != null || selectedContract.rsi60 != null) && (
                                                <span className="text-fuchsia-300 font-bold">
                                                    RSI {selectedContract.rsi15 ?? '—'} / {selectedContract.rsi60 ?? '—'}
                                                    {selectedContract.rsi_event && selectedContract.rsi_event !== 'NONE'
                                                        ? ` ${selectedContract.rsi_event}`
                                                        : ''}
                                                    {selectedContract.rsi_div
                                                        ? ` · ${selectedContract.rsi_div_fresh ? 'FRESH ' : ''}${
                                                              selectedContract.rsi_div === 'BULL_DIV' ? 'BULL DIV' : 'BEAR DIV'
                                                          }`
                                                        : ''}
                                                </span>
                                            )}
                                            {selectedContract.oc_permission != null && (
                                                <span className="text-amber-300 font-bold">
                                                    OC P {selectedContract.oc_permission}
                                                </span>
                                            )}
                                            {selectedContract.h4_bias && (
                                                <span className="text-zinc-300">
                                                    4H {selectedContract.h4_bias}
                                                    {selectedContract.mtf_allowed ? ` · ${selectedContract.mtf_allowed}` : ''}
                                                </span>
                                            )}
                                        </div>
                                        {selectedContract.unusual_flags.length > 0 && (
                                            <div className="flex flex-wrap gap-1 mt-2">
                                                {selectedContract.unusual_flags.map((f, i) => (
                                                    <span key={i} className="px-2 py-0.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[9px] font-bold rounded">
                                                        ⚡ {f}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <button
                                        onClick={() => setBacktestTarget(selectedContract)}
                                        className="px-3 py-2 bg-blue-600/20 border border-blue-500/30 text-blue-400 text-xs font-bold rounded-xl hover:bg-blue-600/30 transition-all"
                                    >
                                        📊 Backtest Signal
                                    </button>
                                </div>

                                {/* Chart */}
                                {flowLoading ? (
                                    <div className="flex items-center gap-3 p-8 bg-[#0e1420] border border-zinc-800 rounded-xl justify-center">
                                        <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                                        <span className="text-xs text-zinc-400">Loading flow data...</span>
                                    </div>
                                ) : flowData && flowData.symbol === selectedContract.symbol ? (
                                    <>
                                        {(() => {
                                            const ideaForFlow =
                                                flowData && flowData.symbol === selectedContract.symbol
                                                    ? flowData.idea || selectedContract.idea
                                                    : selectedContract.idea;
                                            if (!ideaForFlow) return null;
                                            return (
                                            <div className={`p-4 rounded-xl border ${
                                                ideaForFlow.status === 'ACTIVE'
                                                    ? 'border-cyan-500/40 bg-cyan-500/8'
                                                    : 'border-zinc-700 bg-[#0e1420]'
                                            }`}>
                                                <p className="text-[10px] font-black uppercase text-cyan-400 mb-1">
                                                    Process idea · {ideaForFlow.status} · {ideaForFlow.symbol}
                                                </p>
                                                <p className="text-sm text-zinc-200">
                                                    {ideaForFlow.thesis}
                                                </p>
                                                <div className="flex flex-wrap gap-4 mt-2 text-[11px] text-zinc-400">
                                                    <span>Entry zone <b className="text-zinc-100">
                                                        {ideaForFlow.entry_zone?.from != null
                                                            ? `${fmtPx(ideaForFlow.entry_zone?.from)}–${fmtPx(ideaForFlow.entry_zone?.to)}`
                                                            : `${ideaForFlow.entry_label || ''} ${fmtPx(ideaForFlow.entry)}`}
                                                    </b></span>
                                                    <span>Stop <b className="text-rose-300">{fmtPx(ideaForFlow.stop)}</b></span>
                                                    <span>Target <b className="text-emerald-300">{ideaForFlow.target_label || ''} {fmtPx(ideaForFlow.target)}</b></span>
                                                    <span>Inv <b className="text-zinc-200">{fmtPx(ideaForFlow.invalidation)}</b></span>
                                                    <span>Health {ideaForFlow.cluster_health || '—'}</span>
                                                </div>
                                                {(ideaForFlow.exit_warnings || []).length > 0 && (
                                                    <p className="text-[11px] font-bold text-rose-400 mt-1">
                                                        {ideaForFlow.exit_warnings?.join(' · ')}
                                                    </p>
                                                )}
                                            </div>
                                            );
                                        })()}

                                        {flowData.levels && (
                                            <div className="p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                                                <h3 className="text-[10px] font-black text-zinc-400 uppercase tracking-widest mb-3">
                                                    Institutional levels
                                                </h3>
                                                <div className="grid grid-cols-3 md:grid-cols-6 gap-2 text-[10px]">
                                                    {[
                                                        ['P', flowData.levels.day?.pivots?.P],
                                                        ['S1', flowData.levels.day?.pivots?.S1],
                                                        ['R1', flowData.levels.day?.pivots?.R1],
                                                        ['VWAP', flowData.levels.session?.vwap],
                                                        ['Put wall', flowData.levels.structure?.put_wall],
                                                        ['Call wall', flowData.levels.structure?.call_wall],
                                                        ['PDH', flowData.levels.day?.pdh],
                                                        ['PDL', flowData.levels.day?.pdl],
                                                        ['Cam S3', flowData.levels.day?.camarilla?.S3],
                                                        ['Cam R3', flowData.levels.day?.camarilla?.R3],
                                                        ['CPR TC', flowData.levels.day?.cpr?.TC],
                                                        ['Max pain', flowData.levels.structure?.max_pain],
                                                    ].map(([k, v]) => (
                                                        <div key={String(k)} className="p-2 rounded-lg bg-zinc-900/70 border border-zinc-800">
                                                            <p className="text-zinc-500 uppercase font-bold">{k}</p>
                                                            <p className="text-zinc-100 font-black">{fmtPx(v as number)}</p>
                                                        </div>
                                                    ))}
                                                </div>
                                                <p className="text-[10px] text-zinc-500 mt-2">
                                                    {flowData.levels.pivot_side} · {flowData.levels.camarilla_regime}
                                                    {flowData.levels.futures?.label ? ` · ${flowData.levels.futures.label}` : ''}
                                                    {flowData.levels.structure?.pcr_regime ? ` · PCR ${flowData.levels.structure.pcr_regime}` : ''}
                                                </p>
                                            </div>
                                        )}

                                        {/* Underlying meta */}
                                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                            {[
                                                {
                                                    label: 'Spot LTP',
                                                    value: `₹${flowData.spot_price?.toLocaleString('en-IN')}`,
                                                    sub: `${(flowData.underlying?.change_pct || 0) >= 0 ? '+' : ''}${flowData.underlying?.change_pct?.toFixed(2)}%`,
                                                    subColor: (flowData.underlying?.change_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400',
                                                },
                                                {
                                                    label: 'PCR',
                                                    value: flowData.pcr?.toFixed(2) ?? '—',
                                                    sub: flowData.pcr && flowData.pcr > 1.2 ? 'Oversold Puts' : flowData.pcr && flowData.pcr < 0.7 ? 'Oversold Calls' : 'Neutral',
                                                    subColor: 'text-zinc-500',
                                                },
                                                {
                                                    label: 'India VIX',
                                                    value: flowData.india_vix?.toFixed(2) ?? '—',
                                                    sub: flowData.india_vix && flowData.india_vix > 18 ? '⚠ High' : 'Normal',
                                                    subColor: flowData.india_vix && flowData.india_vix > 18 ? 'text-amber-400' : 'text-zinc-500',
                                                },
                                                {
                                                    label: 'ATM Strike',
                                                    value: flowData.atm_strike ?? '—',
                                                    sub: `VWAP dev ${flowData.underlying?.vwap_dev_pct?.toFixed(2)}%`,
                                                    subColor: 'text-zinc-500',
                                                },
                                            ].map(m => (
                                                <div key={m.label} className="p-3 bg-[#0e1420] border border-zinc-800 rounded-xl text-center">
                                                    <p className="text-lg font-black text-zinc-100">{m.value}</p>
                                                    <p className="text-[9px] text-zinc-500 uppercase font-bold">{m.label}</p>
                                                    <p className={`text-[10px] font-bold mt-0.5 ${m.subColor}`}>{m.sub}</p>
                                                </div>
                                            ))}
                                        </div>

                                        {/* Candlestick chart */}
                                        <div className="p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                                            <div className="flex items-center justify-between mb-3">
                                                <h3 className="text-xs font-black text-zinc-300 uppercase tracking-wider">
                                                    5-Min Candlestick — {flowData.name}
                                                </h3>
                                                <span className="text-[9px] text-zinc-600">
                                                    Vertical lines = option flow signals
                                                </span>
                                            </div>
                                            <div className="overflow-x-auto">
                                                <CandleChart
                                                    candles={flowData.candles_5min}
                                                    markers={chartMarkers}
                                                    height={260}
                                                />
                                            </div>
                                        </div>

                                        {/* Option chain widget */}
                                        <div className="p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                                            <div className="flex items-center justify-between mb-3">
                                                <h3 className="text-xs font-black text-zinc-300 uppercase tracking-wider">
                                                    Option Chain — {flowData.name}
                                                </h3>
                                                <div className="flex gap-4 text-[10px] text-zinc-500">
                                                    <span>Expiry: {formatExpiryText(flowData.expiries?.[0])}</span>
                                                    <span className="text-emerald-400/70">CALL</span>
                                                    <span className="text-rose-400/70">PUT</span>
                                                </div>
                                            </div>
                                            <OptionChainWidget
                                                chain={flowData.chain}
                                                atm={flowData.atm_strike}
                                                spot={flowData.spot_price}
                                            />
                                        </div>

                                        {/* Flagged contracts for this symbol */}
                                        {flowData.flagged_contracts.length > 0 && (
                                            <div className="p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                                                <h3 className="text-xs font-black text-zinc-300 uppercase tracking-wider mb-3">
                                                    All Flagged Contracts — {flowData.name}
                                                </h3>
                                                <div className="space-y-2">
                                                    {flowData.flagged_contracts.slice(0, 10).map((c, i) => (
                                                        <div key={i} className="flex items-center gap-3 p-2 bg-zinc-900/50 rounded-lg">
                                                            <LISRing lis={c.lis} />
                                                            <div className="flex-1 min-w-0">
                                                                <div className="flex items-center gap-2">
                                                                    <span className="font-black text-sm text-zinc-200">{c.strike}</span>
                                                                    <span className={`text-xs font-bold ${c.type === 'CE' ? 'text-emerald-400' : 'text-rose-400'}`}>{c.type}</span>
                                                                    <SignalBadge signal={c.signal} />
                                                                </div>
                                                                <div className="flex gap-3 mt-0.5 text-[10px] text-zinc-500">
                                                                    <span>OI Chg: <span className={oiColor(c.oi_change_pct)}>{c.oi_change_pct >= 0 ? '+' : ''}{c.oi_change_pct?.toFixed(1)}%</span></span>
                                                                    <span>Vol: {formatNum(c.volume)}</span>
                                                                    <span>LTP: ₹{c.ltp?.toFixed(1)}</span>
                                                                </div>
                                                            </div>
                                                            <button
                                                                onClick={() => setBacktestTarget(c)}
                                                                className="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white text-[9px] font-bold uppercase rounded transition-colors"
                                                            >
                                                                Backtest
                                                            </button>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <div className="flex items-center justify-center py-12 text-zinc-500 text-sm">
                                        No flow data available
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                )}

                {/* ══════════════════════════════════════════════
                    TAB: SIGNAL LOG
                ══════════════════════════════════════════════ */}
                {tab === 'backtest_list' && (
                    <div className="space-y-4">
                        <div className="p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                            <h2 className="text-sm font-black text-zinc-300 uppercase tracking-wider mb-1">
                                📋 Today's Signal Log
                            </h2>
                            <p className="text-[10px] text-zinc-500">
                                All contracts flagged this session. Click "Backtest" to compute forward returns from signal time.
                            </p>
                        </div>

                        {alerts.length === 0 && (scanData?.flagged?.length ?? 0) === 0 ? (
                            <div className="flex flex-col items-center justify-center py-16">
                                <p className="text-3xl mb-3">📭</p>
                                <p className="text-sm text-zinc-500">No signals logged yet</p>
                                <p className="text-xs text-zinc-600 mt-1">Signals are logged when the radar detects unusual activity (LIS ≥ 70)</p>
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {/* High conviction alerts */}
                                {alerts.length > 0 && (
                                    <div className="p-4 bg-emerald-900/10 border border-emerald-800/40 rounded-xl">
                                        <p className="text-[10px] font-black text-emerald-400 uppercase tracking-widest mb-3">
                                            🔔 High Conviction Alerts (LIS ≥ 70) — {alerts.length} signals
                                        </p>
                                        <div className="space-y-2">
                                            {alerts.map((c, i) => (
                                                <div key={i} className="flex items-center gap-3 p-3 bg-zinc-900/60 rounded-xl">
                                                    <LISRing lis={c.lis} />
                                                    <div className="flex-1">
                                                        <div className="flex items-center gap-2">
                                                            <span className="font-black text-white">{c.name}</span>
                                                            <span className="font-bold text-zinc-300">{c.strike}</span>
                                                            <span className={`text-xs font-black ${c.type === 'CE' ? 'text-emerald-400' : 'text-rose-400'}`}>{c.type}</span>
                                                            <SignalBadge signal={c.signal} />
                                                        </div>
                                                        <p className="text-[9px] text-zinc-500 mt-0.5">
                                                            {new Date(c.timestamp).toLocaleTimeString()} • OI {c.oi_change_pct >= 0 ? '+' : ''}{c.oi_change_pct?.toFixed(1)}% • Vol {formatNum(c.volume)}
                                                        </p>
                                                    </div>
                                                    <button
                                                        onClick={() => setBacktestTarget(c)}
                                                        className="px-3 py-1.5 bg-blue-600/20 border border-blue-500/30 text-blue-400 text-[10px] font-bold rounded-lg hover:bg-blue-600/30 transition-all"
                                                    >
                                                        📊 Backtest
                                                    </button>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* All flagged from current scan */}
                                {sortedContracts.length > 0 && (
                                    <div className="p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                                        <p className="text-[10px] font-black text-zinc-500 uppercase tracking-widest mb-3">
                                            All flagged contracts from latest scan ({sortedContracts.length})
                                        </p>
                                        <div className="space-y-1.5">
                                            {sortedContracts.map((c, i) => (
                                                <div key={i} className="flex items-center gap-3 p-2 bg-zinc-900/40 rounded-lg hover:bg-zinc-900/70 transition-colors">
                                                    <span className={`text-sm font-black min-w-[40px] text-center ${lisColor(c.lis)}`}>
                                                        {Math.round(c.lis)}
                                                    </span>
                                                    <div className="flex-1 text-xs">
                                                        <span className="font-bold text-zinc-200">{c.name}</span>
                                                        <span className="text-zinc-500 mx-1">·</span>
                                                        <span className="text-zinc-300">{c.strike}</span>
                                                        <span className={`ml-1 font-black ${c.type === 'CE' ? 'text-emerald-400' : 'text-rose-400'}`}>{c.type}</span>
                                                        <span className="text-zinc-500 mx-1">·</span>
                                                        <span className={oiColor(c.oi_change_pct)}>OI {c.oi_change_pct >= 0 ? '+' : ''}{c.oi_change_pct?.toFixed(1)}%</span>
                                                        <span className="text-zinc-500 mx-1">·</span>
                                                        <span className="text-zinc-500">{new Date(c.timestamp).toLocaleTimeString()}</span>
                                                    </div>
                                                    <SignalBadge signal={c.signal} />
                                                    <button
                                                        onClick={() => setBacktestTarget(c)}
                                                        className="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white text-[9px] font-bold uppercase rounded transition-colors"
                                                    >
                                                        BT
                                                    </button>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Backtest methodology card */}
                        <div className="p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                            <h3 className="text-xs font-black text-zinc-300 uppercase tracking-wider mb-3">ℹ️ How Backtesting Works</h3>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-zinc-500">
                                <div className="p-3 bg-zinc-900/50 rounded-lg">
                                    <p className="font-bold text-zinc-300 mb-1">Signal Detection</p>
                                    <p>A contract is flagged when LIS score exceeds the threshold. LIS combines OI change, option momentum, VWAP deviation, and EMA position.</p>
                                </div>
                                <div className="p-3 bg-zinc-900/50 rounded-lg">
                                    <p className="font-bold text-zinc-300 mb-1">Forward Returns</p>
                                    <p>We fetch the 5-min candles and compute underlying price change at +15min, +30min, +60min from the signal timestamp.</p>
                                </div>
                                <div className="p-3 bg-zinc-900/50 rounded-lg">
                                    <p className="font-bold text-zinc-300 mb-1">Win Rate</p>
                                    <p>The lead time insight: a positive 30-60 min return after an OI spike (with no corresponding stock move) validates the "front-running" thesis.</p>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </main>

            {/* Footer */}
            <footer className="border-t border-zinc-800 mt-8 py-3 px-4">
                <div className="max-w-screen-2xl mx-auto flex justify-between items-center text-[9px] text-zinc-600 font-bold uppercase tracking-widest">
                    <span>Option Flow Radar v1.0 • Real-Time NSE Data via Fyers API</span>
                    <span>LIS = OI(40%) + Momentum(20%) + VWAP(20%) + Delivery(10%) + EMA(10%)</span>
                </div>
            </footer>
        </div>
    );
}
