'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../lib/api';
import LoadingBanner from './ui/LoadingBanner';

// ─────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────

interface SignalInfo {
    signal: string;       // STRONG_BULLISH | WEAK_BULLISH | BEARISH | EXHAUSTION | NEUTRAL
    label: string;
    icon: string;
    color: string;
}

interface ConvictionInfo {
    level: string;        // HIGH | MEDIUM | LOW
    icon: string;
    label: string;
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
    conviction: ConvictionInfo;
    unusual_flags: string[];
}


interface ScanResult {
    success: boolean;
    scanned: number;
    total_flagged: number;
    flagged: FlaggedContract[];
    errors: string[];
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

// Signal badge
function SignalBadge({ signal }: { signal: SignalInfo }) {
    const bg: Record<string, string> = {
        emerald: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
        amber: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
        rose: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
        blue: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
        zinc: 'bg-zinc-500/15 text-zinc-400 border-zinc-700',
    };
    const cls = bg[signal.color] || bg.zinc;
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-bold ${cls}`}>
            {signal.icon} {signal.label}
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

type TabType = 'live' | 'flow' | 'backtest_list';

export default function OptionFlowRadar({ onBack }: Props) {
    const [tab, setTab] = useState<TabType>('live');

    // Scan state
    const [scanData, setScanData] = useState<ScanResult | null>(null);
    const [scanLoading, setScanLoading] = useState(false);
    const [scanError, setScanError] = useState<string | null>(null);
    const [scanProgress, setScanProgress] = useState(0);
    const [scanCurrent, setScanCurrent] = useState<string | null>(null);
    const scanPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const scanRunRef = useRef(0);

    // Filters
    const [minLis, setMinLis] = useState(0);
    const [optTypeFilter, setOptTypeFilter] = useState<'CE' | 'PE' | ''>('');
    const [sortBy, setSortBy] = useState<'lis' | 'oi_change_pct' | 'volume'>('lis');

    // Selected contract for detail
    const [selectedContract, setSelectedContract] = useState<FlaggedContract | null>(null);

    // Symbol flow detail
    const [flowData, setFlowData] = useState<SymbolFlow | null>(null);
    const [flowLoading, setFlowLoading] = useState(false);

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
        flagged
            .filter(c => c.lis >= 70)
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

    const runScan = useCallback(async (silent = false) => {
        const myRun = ++scanRunRef.current;
        stopScanPoll();
        if (!silent) setScanLoading(true);
        setScanError(null);
        setScanProgress(p => (silent && scanData ? p : 2));
        setScanCurrent(null);

        try {
            const started: any = await api.radar.startScan(
                minLis,
                optTypeFilter || undefined,
                8,
            );
            if (myRun !== scanRunRef.current) return;
            const jid = started.job_id as string;
            if (!jid) throw new Error('No radar job id returned');

            const pollOnce = async () => {
                if (myRun !== scanRunRef.current) return;
                try {
                    const snap: any = await api.radar.getScanJob(jid);
                    if (myRun !== scanRunRef.current) return;
                    setScanProgress(Number(snap.completion_pct ?? 0));
                    setScanCurrent(snap.current_symbol || null);
                    const flagged = snap.flagged || [];
                    if (flagged.length || snap.status === 'completed' || snap.status === 'failed') {
                        setScanData({
                            success: true,
                            scanned: snap.scanned ?? snap.completed ?? 0,
                            total_flagged: snap.total_flagged ?? flagged.length,
                            flagged,
                            errors: snap.errors || [],
                            timestamp: snap.timestamp || new Date().toISOString(),
                            market_hours: snap.market_hours ?? true,
                        });
                    }
                    const done =
                        snap.status === 'completed' ||
                        snap.status === 'failed' ||
                        snap.status === 'cancelled';
                    if (done) {
                        stopScanPoll();
                        setScanLoading(false);
                        setLastRefresh(new Date());
                        applyRadarAlerts(flagged);
                        if (snap.status === 'failed') {
                            setScanError(snap.error_message || 'Radar job failed');
                        }
                    }
                } catch (e: any) {
                    if (myRun !== scanRunRef.current) return;
                    stopScanPoll();
                    setScanLoading(false);
                    setScanError(e?.message || 'Radar poll failed');
                }
            };

            await pollOnce();
            if (myRun !== scanRunRef.current) return;
            scanPollRef.current = setInterval(pollOnce, 1500);
        } catch (e: any) {
            if (myRun !== scanRunRef.current) return;
            setScanError(e.message || 'Scan failed');
            setScanLoading(false);
        }
    }, [applyRadarAlerts, minLis, optTypeFilter, scanData, stopScanPoll]);

    // Initial scan
    useEffect(() => {
        runScan();
        return () => {
            scanRunRef.current += 1;
            stopScanPoll();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [minLis, optTypeFilter]);

    // Auto-refresh every 90s (jobs are heavy — avoid 60s pile-up)
    useEffect(() => {
        if (autoRefresh) {
            refreshTimerRef.current = setInterval(() => runScan(true), 90_000);
        } else {
            if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
        }
        return () => {
            if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
        };
    }, [autoRefresh, runScan]);

    // ── Symbol flow ───────────────────────────────────────────────

    const loadFlow = async (symbol: string) => {
        setFlowLoading(true);
        try {
            const data: SymbolFlow = await api.radar.getSymbolFlow(symbol, 10);
            setFlowData(data);
        } catch (e: any) {
            console.error('Flow load error:', e);
        } finally {
            setFlowLoading(false);
        }
    };

    const handleSelectContract = (contract: FlaggedContract) => {
        setSelectedContract(contract);
        loadFlow(contract.symbol);
    };

    // ── Derived data ─────────────────────────────────────────────

    const sortedContracts = (scanData?.flagged ?? []).sort((a, b) => {
        if (sortBy === 'lis') return b.lis - a.lis;
        if (sortBy === 'oi_change_pct') return Math.abs(b.oi_change_pct) - Math.abs(a.oi_change_pct);
        return b.volume - a.volume;
    });

    const chartMarkers = flowData?.flagged_contracts.map(c => ({
        timestamp: new Date(c.timestamp).getTime() / 1000,
        lis: c.lis,
        type: c.type,
    }));

    // ── LIS stats ─────────────────────────────────────────────────

    const highConviction = sortedContracts.filter(c => c.lis >= 70).length;
    const mediumConviction = sortedContracts.filter(c => c.lis >= 40 && c.lis < 70).length;
    const callCount = sortedContracts.filter(c => c.type === 'CE').length;
    const putCount = sortedContracts.filter(c => c.type === 'PE').length;

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
                            🎯 Option Flow Radar
                        </h1>
                        <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-widest">
                            Detect Institutional Accumulation Before The First Big Candle
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
                            disabled={scanLoading}
                            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-[10px] font-black uppercase rounded-full transition-all disabled:opacity-50"
                        >
                            {scanLoading ? 'Scanning...' : '↻ Refresh'}
                        </button>

                        {lastRefresh && (
                            <span className="text-[9px] text-zinc-600">
                                {lastRefresh.toLocaleTimeString()}
                            </span>
                        )}
                    </div>
                </div>

                {/* Tab bar */}
                <div className="max-w-screen-2xl mx-auto px-4 flex gap-1 pb-0">
                    {[
                        { id: 'live', label: '📡 Live Monitor' },
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
                    label={scanData ? 'Refreshing option flow radar' : 'Scanning watchlist option chains'}
                    progress={scanProgress}
                    detail={
                        scanCurrent
                            ? `Now: ${String(scanCurrent).replace('NSE:', '').replace('-EQ', '')} · ${Math.round(scanProgress)}%`
                            : scanData
                              ? `Live job… ${scanData.scanned} scanned · ${scanData.total_flagged} flagged so far`
                              : 'Background job · LIS · OI change · volume spikes · greeks'
                    }
                />

                {/* ══════════════════════════════════════════════
                    TAB: LIVE MONITOR
                ══════════════════════════════════════════════ */}
                {tab === 'live' && (
                    <div className="space-y-4">

                        {/* Stats row */}
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                            {[
                                { label: 'Symbols Scanned', value: scanData?.scanned ?? '—', color: 'text-zinc-300' },
                                { label: 'Flagged Contracts', value: scanData?.total_flagged ?? '—', color: 'text-blue-400' },
                                { label: 'High Conviction (≥70)', value: highConviction, color: 'text-emerald-400' },
                                { label: 'Calls / Puts', value: `${callCount} / ${putCount}`, color: 'text-amber-400' },
                                { label: 'Active Alerts', value: alerts.length, color: 'text-rose-400' },
                            ].map(s => (
                                <div key={s.label} className="bg-[#0e1420] border border-zinc-800 rounded-xl p-3 text-center">
                                    <p className={`text-2xl font-black ${s.color}`}>{s.value}</p>
                                    <p className="text-[9px] font-bold text-zinc-600 uppercase mt-0.5">{s.label}</p>
                                </div>
                            ))}
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
                                    <option value="lis">LIS Score</option>
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

                        {/* Loading */}
                        {scanLoading && (
                            <div className="flex items-center gap-3 p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                                <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                                <p className="text-xs text-zinc-400">Scanning option chains across watchlist...</p>
                            </div>
                        )}

                        {/* Main table */}
                        {!scanLoading && sortedContracts.length > 0 && (
                            <div className="bg-[#0e1420] border border-zinc-800 rounded-xl overflow-hidden">
                                <div className="overflow-x-auto">
                                    <table className="w-full">
                                        <thead>
                                            <tr className="border-b border-zinc-800 text-[10px] text-zinc-500 uppercase">
                                                <th className="py-2 pl-4 text-left">Time</th>
                                                <th className="py-2 text-left">Symbol</th>
                                                <th className="py-2 text-center">Strike</th>
                                                <th className="py-2 text-center">Type</th>
                                                <th className="py-2 text-right">OI Chg%</th>
                                                <th className="py-2 text-right">Volume</th>
                                                <th className="py-2 text-right">Option LTP</th>
                                                <th className="py-2 text-right">IV</th>
                                                <th className="py-2 text-right">Spot Chg%</th>
                                                <th className="py-2 text-center">Signal</th>
                                                <th className="py-2 text-center">LIS</th>
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
                                                            <p className="text-sm font-black text-white">{c.name}</p>
                                                            <p className="text-[9px] text-zinc-500">
                                                                Exp: {formatExpiryText(c.expiry)} • ATM dist: {c.atm_dist_pct?.toFixed(1)}%
                                                            </p>
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
                                                    <td className={`py-2.5 text-right text-sm font-bold tabular-nums ${oiColor(c.oi_change_pct)}`}>
                                                        {c.oi_change_pct > 0 ? '+' : ''}{c.oi_change_pct?.toFixed(1)}%
                                                    </td>
                                                    <td className="py-2.5 text-right text-xs text-zinc-300 tabular-nums">
                                                        {formatNum(c.volume)}
                                                    </td>
                                                    <td className="py-2.5 text-right">
                                                        <p className="text-sm font-bold text-zinc-200">₹{c.ltp?.toFixed(1)}</p>
                                                        <p className={`text-[10px] font-bold ${c.ltp_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                            {c.ltp_change_pct >= 0 ? '+' : ''}{c.ltp_change_pct?.toFixed(1)}%
                                                        </p>
                                                    </td>
                                                    <td className="py-2.5 text-right text-xs text-zinc-400">
                                                        {c.iv ? `${c.iv.toFixed(1)}%` : '—'}
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

                        {!scanLoading && sortedContracts.length === 0 && !scanError && (
                            <div className="flex flex-col items-center justify-center py-16 text-center">
                                <p className="text-4xl mb-3">🔍</p>
                                <p className="text-sm font-bold text-zinc-400">No signals found</p>
                                <p className="text-xs text-zinc-600 mt-1">
                                    {minLis > 0 ? `Try lowering Min LIS below ${minLis}` : 'Market may be closed or no unusual activity detected'}
                                </p>
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
                                {/* Selected contract header */}
                                <div className="flex items-start gap-4 p-4 bg-[#0e1420] border border-zinc-800 rounded-xl">
                                    <LISRing lis={selectedContract.lis} />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-3 flex-wrap">
                                            <h2 className="text-xl font-black text-white">{selectedContract.name}</h2>
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
                                ) : flowData ? (
                                    <>
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
