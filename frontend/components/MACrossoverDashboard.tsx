'use client';

import { useState, useMemo } from 'react';
import { useMACrossovers } from '@/lib/hooks/useMACrossovers';
import { CrossoverEvent, MAConfig } from '@/lib/ma-crossover';

interface Props {
    onBack: () => void;
}

const MA_TYPES = ['EMA', 'SMA', 'WMA'];
const TIMEFRAMES = ['15min', '30min', '1H', '4H', '1D'];

function Badge({ type }: { type: CrossoverEvent['type'] }) {
    const map = {
        golden_cross: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40',
        death_cross: 'bg-rose-500/20 text-rose-400 border border-rose-500/40',
        nearing: 'bg-amber-500/20 text-amber-400 border border-amber-500/40',
    };
    const label = {
        golden_cross: '🌟 Golden Cross',
        death_cross: '💀 Death Cross',
        nearing: '⚠️ Nearing',
    };
    return (
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide ${map[type]}`}>
            {label[type]}
        </span>
    );
}

function SignalChip({ signal }: { signal?: 'BUY' | 'SELL' }) {
    if (!signal) return null;
    const cls = signal === 'BUY'
        ? 'bg-emerald-500 text-white'
        : 'bg-rose-500 text-white';
    return (
        <span className={`ml-1 px-1.5 py-0.5 rounded text-[9px] font-black uppercase ${cls}`}>
            {signal}
        </span>
    );
}

function TFChip({ tf }: { tf: string }) {
    const map: Record<string, string> = {
        '15min': 'bg-blue-500/20 text-blue-300',
        '30min': 'bg-violet-500/20 text-violet-300',
        '1H': 'bg-teal-500/20 text-teal-300',
        '4H': 'bg-orange-500/20 text-orange-300',
        '1D': 'bg-pink-500/20 text-pink-300',
    };
    return (
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${map[tf] ?? 'bg-zinc-700 text-zinc-300'}`}>
            {tf}
        </span>
    );
}

function formatSymbol(s: string) {
    return s.replace('NSE:', '').replace('-EQ', '').replace('-INDEX', '');
}

function formatPrice(n: number) {
    return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTime(ts: number) {
    return new Date(ts * 1000).toLocaleTimeString('en-IN', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });
}

// ─────────────────────────────────────────────────────────────
// Settings panel
// ─────────────────────────────────────────────────────────────
function SettingsPanel({
    config,
    onSave,
    onClose,
}: {
    config: MAConfig;
    onSave: (c: Partial<MAConfig>) => void;
    onClose: () => void;
}) {
    const [local, setLocal] = useState({ ...config });

    function set<K extends keyof MAConfig>(k: K, v: MAConfig[K]) {
        setLocal((p) => ({ ...p, [k]: v }));
    }

    function toggleTF(tf: string) {
        set('timeframes',
            local.timeframes.includes(tf)
                ? local.timeframes.filter(x => x !== tf)
                : [...local.timeframes, tf]
        );
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
                <div className="flex justify-between items-center mb-5">
                    <h2 className="text-white font-bold text-lg">⚙️ Scanner Settings</h2>
                    <button onClick={onClose} className="text-zinc-400 hover:text-white text-xl">✕</button>
                </div>

                <div className="space-y-4 text-sm">
                    {/* Short MA */}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="text-zinc-400 text-xs mb-1 block">Short MA Type</label>
                            <select
                                value={local.ma_short_type}
                                onChange={e => set('ma_short_type', e.target.value)}
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white text-sm"
                            >
                                {MA_TYPES.map(t => <option key={t}>{t}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="text-zinc-400 text-xs mb-1 block">Short MA Period</label>
                            <input
                                type="number" min={2} max={200}
                                value={local.ma_short_period}
                                onChange={e => set('ma_short_period', +e.target.value)}
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white"
                            />
                        </div>
                    </div>

                    {/* Long MA */}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="text-zinc-400 text-xs mb-1 block">Long MA Type</label>
                            <select
                                value={local.ma_long_type}
                                onChange={e => set('ma_long_type', e.target.value)}
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white text-sm"
                            >
                                {MA_TYPES.map(t => <option key={t}>{t}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="text-zinc-400 text-xs mb-1 block">Long MA Period</label>
                            <input
                                type="number" min={2} max={500}
                                value={local.ma_long_period}
                                onChange={e => set('ma_long_period', +e.target.value)}
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white"
                            />
                        </div>
                    </div>

                    {/* Trend MA (200EMA) */}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="text-zinc-400 text-xs mb-1 block">200EMA Type (Trend Filter)</label>
                            <select
                                value={local.ma_trend_type}
                                onChange={e => set('ma_trend_type', e.target.value)}
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white text-sm"
                            >
                                {MA_TYPES.map(t => <option key={t}>{t}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="text-zinc-400 text-xs mb-1 block">200EMA Period</label>
                            <input
                                type="number" min={2} max={500}
                                value={local.ma_trend_period}
                                onChange={e => set('ma_trend_period', +e.target.value)}
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white"
                            />
                        </div>
                    </div>

                    {/* Timeframes */}
                    <div>
                        <label className="text-zinc-400 text-xs mb-2 block">Active Timeframes</label>
                        <div className="flex gap-2 flex-wrap">
                            {TIMEFRAMES.map(tf => (
                                <button
                                    key={tf}
                                    onClick={() => toggleTF(tf)}
                                    className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-all ${local.timeframes.includes(tf)
                                        ? 'bg-blue-600 border-blue-500 text-white'
                                        : 'bg-zinc-800 border-zinc-600 text-zinc-400'
                                        }`}
                                >
                                    {tf}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Proximity + cooldown */}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="text-zinc-400 text-xs mb-1 block">Proximity Threshold %</label>
                            <input
                                type="number" step="0.1" min={0.1} max={5}
                                value={local.proximity_threshold}
                                onChange={e => set('proximity_threshold', +e.target.value)}
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white"
                            />
                        </div>
                        <div>
                            <label className="text-zinc-400 text-xs mb-1 block">Cooldown (minutes)</label>
                            <input
                                type="number" min={1} max={120}
                                value={local.cooldown_minutes}
                                onChange={e => set('cooldown_minutes', +e.target.value)}
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white"
                            />
                        </div>
                    </div>
                </div>

                <div className="flex gap-3 mt-6">
                    <button
                        onClick={() => { onSave(local); onClose(); }}
                        className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl transition-all"
                    >
                        Save & Apply
                    </button>
                    <button
                        onClick={onClose}
                        className="px-5 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-white rounded-xl transition-all"
                    >
                        Cancel
                    </button>
                </div>
            </div>
        </div>
    );
}

// ─────────────────────────────────────────────────────────────
// Crossover Row
// ─────────────────────────────────────────────────────────────
function CrossoverRow({ ev }: { ev: CrossoverEvent }) {
    // Gap between short MA and long MA (the crossover gap itself)
    const dist = ev.distance_pct > 0
        ? `+${ev.distance_pct.toFixed(3)}%`
        : `${ev.distance_pct.toFixed(3)}%`;
    const distColor = ev.distance_pct > 0 ? 'text-emerald-400' : 'text-rose-400';

    // Price relative to 200EMA — the institutional reference that matters
    const p200 = ev.price_to_200ema_pct;
    const p200Str = p200 !== undefined
        ? (p200 > 0 ? `+${p200.toFixed(2)}%` : `${p200.toFixed(2)}%`)
        : '—';
    const p200Color = p200 === undefined
        ? 'text-zinc-500'
        : p200 > 0 ? 'text-emerald-400' : 'text-rose-400';

    return (
        <tr className="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors group">
            <td className="px-3 py-2.5">
                <div className="font-mono font-bold text-white text-sm">{formatSymbol(ev.symbol)}</div>
            </td>
            <td className="px-3 py-2.5"><TFChip tf={ev.timeframe} /></td>
            <td className="px-3 py-2.5">
                <Badge type={ev.type} />
                <SignalChip signal={ev.signal} />
            </td>
            <td className="px-3 py-2.5 text-right font-mono text-white text-sm">
                ₹{formatPrice(ev.price)}
            </td>
            <td className="px-3 py-2.5 text-right font-mono text-xs text-zinc-300">
                {ev.ma_short.toFixed(2)}
            </td>
            <td className="px-3 py-2.5 text-right font-mono text-xs text-zinc-300">
                {ev.ma_long.toFixed(2)}
            </td>
            <td className="px-3 py-2.5 text-right font-mono text-xs text-zinc-400">
                {ev.ma_trend.toFixed(2)}
            </td>
            {/* Short↔Long gap — size of the crossover */}
            <td className={`px-3 py-2.5 text-right font-mono text-xs font-bold ${distColor}`}>
                {dist}
            </td>
            {/* Price↔200EMA — institutional reference, what traders actually watch */}
            <td className={`px-3 py-2.5 text-right font-mono text-xs font-bold ${p200Color}`}>
                {p200Str}
            </td>
            <td className="px-3 py-2.5 text-right text-xs text-zinc-500 font-mono">
                {formatTime(ev.timestamp)}
            </td>
        </tr>
    );
}

// ─────────────────────────────────────────────────────────────
// Nearing Row (compact)
// ─────────────────────────────────────────────────────────────
function NearingRow({ ev }: { ev: CrossoverEvent }) {
    const isApproachingGolden = ev.direction?.includes('golden');
    const dirColor = isApproachingGolden ? 'text-emerald-400' : 'text-rose-400';
    const dirLabel = isApproachingGolden ? '▲ Bull' : '▼ Bear';

    // Price relative to 200EMA
    const p200 = ev.price_to_200ema_pct;
    const p200Str = p200 !== undefined
        ? (p200 > 0 ? `+${p200.toFixed(2)}%` : `${p200.toFixed(2)}%`)
        : '';
    const p200Color = p200 === undefined ? '' : p200 > 0 ? 'text-emerald-400' : 'text-rose-400';

    return (
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-zinc-800/40 hover:bg-zinc-800/20 transition-colors">
            <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-white text-sm">{formatSymbol(ev.symbol)}</span>
                <TFChip tf={ev.timeframe} />
            </div>
            <div className="flex items-center gap-3">
                <span className={`text-xs font-bold ${dirColor}`}>{dirLabel}</span>
                {/* Short↔Long proximity — how close to crossover */}
                <span className="font-mono text-xs text-amber-400 font-bold">
                    {Math.abs(ev.distance_pct).toFixed(3)}%
                </span>
                {/* Price↔200EMA — institutional reference */}
                {p200 !== undefined && (
                    <span className={`font-mono text-xs font-semibold ${p200Color}`} title="Price to 200EMA">
                        200E: {p200Str}
                    </span>
                )}
                <span className="font-mono text-xs text-zinc-500">{formatTime(ev.timestamp)}</span>
            </div>
        </div>
    );
}

// ─────────────────────────────────────────────────────────────
// Main Dashboard
// ─────────────────────────────────────────────────────────────
export default function MACrossoverDashboard({ onBack }: Props) {
    const {
        crossovers, nearing, status, connected, error, progress,
        handleStart, handleStop, handleTriggerScan, handleConfigUpdate, refresh,
    } = useMACrossovers();

    const [tab, setTab] = useState<'crossovers' | 'nearing'>('crossovers');
    const [filterTF, setFilterTF] = useState<string>('ALL');
    const [filterType, setFilterType] = useState<string>('ALL');
    const [search, setSearch] = useState('');
    const [showSettings, setShowSettings] = useState(false);

    // Filtered crossovers
    const filtered = useMemo(() => {
        return crossovers.filter(ev => {
            if (filterTF !== 'ALL' && ev.timeframe !== filterTF) return false;
            if (filterType !== 'ALL' && ev.type !== filterType) return false;
            if (search && !ev.symbol.toLowerCase().includes(search.toLowerCase())) return false;
            return true;
        });
    }, [crossovers, filterTF, filterType, search]);

    const filteredNearing = useMemo(() => {
        return nearing.filter(ev => {
            if (filterTF !== 'ALL' && ev.timeframe !== filterTF) return false;
            if (search && !ev.symbol.toLowerCase().includes(search.toLowerCase())) return false;
            return true;
        });
    }, [nearing, filterTF, search]);

    const golden = crossovers.filter(e => e.type === 'golden_cross').length;
    const death = crossovers.filter(e => e.type === 'death_cross').length;

    return (
        <div className="min-h-screen bg-black text-zinc-100 p-4 md:p-6">
            {/* ── Header ───────────────────────────────── */}
            <header className="max-w-[1600px] mx-auto flex flex-wrap items-center justify-between gap-4 mb-6">
                <div className="flex items-center gap-4">
                    <button
                        onClick={onBack}
                        className="text-zinc-400 hover:text-white text-sm font-bold flex items-center gap-1 transition-colors"
                    >
                        ← Back
                    </button>
                    <div>
                        <h1 className="text-2xl font-black text-white tracking-tight">
                            📈 MA Crossover <span className="text-blue-500">Monitor</span>
                        </h1>
                        <p className="text-xs text-zinc-500 mt-0.5">
                            {status?.symbols_tracked ?? '—'} symbols · {status?.timeframes?.join(', ') ?? '—'} ·{' '}
                            {status?.config
                                ? `${status.config.ma_short_period}${status.config.ma_short_type}/${status.config.ma_long_period}${status.config.ma_long_type}/${status.config.ma_trend_period}${status.config.ma_trend_type}`
                                : '20EMA/50EMA/200EMA'}
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-3 flex-wrap">
                    {/* Connection status */}
                    <div className={`flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full border ${connected
                        ? 'text-emerald-400 border-emerald-700 bg-emerald-950'
                        : 'text-zinc-500 border-zinc-700 bg-zinc-900'
                        }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'}`} />
                        {connected ? 'LIVE' : 'Polling'}
                    </div>

                    {/* Market status */}
                    {status && (
                        <div className={`flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full border ${status.market_open
                            ? 'text-teal-400 border-teal-700 bg-teal-950'
                            : 'text-zinc-500 border-zinc-700 bg-zinc-900'
                            }`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${status.market_open ? 'bg-teal-400 animate-pulse' : 'bg-zinc-600'}`} />
                            {status.market_open ? 'Market Open' : status.market_info}
                        </div>
                    )}

                    {/* Controls */}
                    <button
                        onClick={refresh}
                        className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-bold rounded-lg border border-zinc-700 transition-all"
                    >
                        🔄 Refresh
                    </button>
                    
                    {status?.authenticated && (
                        <button
                            onClick={handleTriggerScan}
                            disabled={progress?.active}
                            className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-all flex items-center gap-1 ${
                                progress?.active 
                                    ? 'bg-zinc-800 border-zinc-700 text-zinc-500 cursor-not-allowed'
                                    : 'bg-blue-600 border-blue-500 text-white hover:bg-blue-700'
                            }`}
                        >
                            {progress?.active ? (
                                <>
                                    <span className="animate-spin w-3 h-3 border-2 border-zinc-600 border-t-zinc-400 rounded-full inline-block mr-1" />
                                    Scanning...
                                </>
                            ) : (
                                <>⚡ Scan Now</>
                            )}
                        </button>
                    )}

                    <button
                        onClick={() => setShowSettings(true)}
                        className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-bold rounded-lg border border-zinc-700 transition-all"
                    >
                        ⚙️ Settings
                    </button>

                    {status?.running ? (
                        <button
                            onClick={handleStop}
                            className="px-4 py-1.5 bg-rose-700 hover:bg-rose-800 text-white text-xs font-bold rounded-lg transition-all"
                        >
                            ⏹ Stop Scanner
                        </button>
                    ) : (
                        <button
                            onClick={handleStart}
                            className="px-4 py-1.5 bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold rounded-lg transition-all"
                        >
                            ▶ Start Scanner
                        </button>
                    )}
                </div>
            </header>

            {/* ── Fyers Authentication Warning ──────────── */}
            {status && !status.authenticated && (
                <div className="max-w-[1600px] mx-auto mb-5 bg-amber-950/40 border border-amber-700/60 rounded-xl p-4 text-amber-300 shadow-md">
                    <div className="flex items-start gap-3">
                        <span className="text-lg">⚠️</span>
                        <div>
                            <h4 className="font-bold text-sm text-white">Fyers API is not authenticated</h4>
                            <p className="text-xs text-amber-400/90 mt-1">
                                OptionGreek needs a valid active token to execute live market scans. 
                                Please go back to the main dashboard and click the <b>Fyers Login</b> button.
                            </p>
                        </div>
                    </div>
                </div>
            )}

            {/* ── Scan Progress Indicator ──────────────── */}
            {progress && progress.active && (
                <div className="max-w-[1600px] mx-auto mb-5 bg-zinc-900/60 border border-blue-900/60 rounded-xl p-4 shadow-lg backdrop-blur-md">
                    <div className="flex flex-wrap justify-between items-center mb-2 gap-2">
                        <div className="flex items-center gap-2">
                            <span className="flex h-2 w-2 relative">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                                <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                            </span>
                            <span className="text-sm font-bold text-white">Full Market Scan in Progress</span>
                        </div>
                        <span className="text-xs font-mono text-blue-400 font-bold bg-blue-950/60 border border-blue-800/40 px-2 py-0.5 rounded">
                            {progress.percentage.toFixed(1)}% ({progress.current} / {progress.total})
                        </span>
                    </div>
                    {/* Progress Bar Container */}
                    <div className="w-full bg-zinc-800 h-2.5 rounded-full overflow-hidden border border-zinc-700/50 mb-2">
                        <div 
                            className="bg-gradient-to-r from-blue-500 via-indigo-500 to-violet-500 h-full rounded-full transition-all duration-300 ease-out shadow-[0_0_8px_rgba(59,130,246,0.5)]"
                            style={{ width: `${progress.percentage}%` }}
                        />
                    </div>
                    {progress.last_symbol && (
                        <div className="text-[11px] text-zinc-400 font-mono">
                            <span className="text-zinc-500">Analyzing:</span> {formatSymbol(progress.last_symbol)}
                        </div>
                    )}
                </div>
            )}

            {/* ── Stat bar ─────────────────────────────── */}

            <div className="max-w-[1600px] mx-auto grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
                {[
                    { label: 'Golden Crosses', value: golden, color: 'text-emerald-400', bg: 'bg-emerald-950 border-emerald-800' },
                    { label: 'Death Crosses', value: death, color: 'text-rose-400', bg: 'bg-rose-950 border-rose-800' },
                    { label: 'Nearing Alert', value: nearing.length, color: 'text-amber-400', bg: 'bg-amber-950 border-amber-800' },
                    { label: 'Total Signals', value: crossovers.length + nearing.length, color: 'text-blue-400', bg: 'bg-blue-950 border-blue-900' },
                ].map(s => (
                    <div key={s.label} className={`${s.bg} border rounded-xl px-4 py-3 flex items-center justify-between`}>
                        <span className="text-zinc-400 text-xs font-semibold">{s.label}</span>
                        <span className={`text-2xl font-black ${s.color}`}>{s.value}</span>
                    </div>
                ))}
            </div>

            {/* ── Filters ──────────────────────────────── */}
            <div className="max-w-[1600px] mx-auto flex flex-wrap items-center gap-3 mb-4">
                <input
                    type="text"
                    placeholder="Search symbol…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-white placeholder-zinc-500 w-40 focus:outline-none focus:border-blue-500 transition"
                />

                {/* TF filter */}
                <div className="flex gap-1">
                    {['ALL', ...TIMEFRAMES].map(tf => (
                        <button
                            key={tf}
                            onClick={() => setFilterTF(tf)}
                            className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-all ${filterTF === tf
                                ? 'bg-blue-600 border-blue-500 text-white'
                                : 'bg-zinc-900 border-zinc-700 text-zinc-400 hover:text-white'
                                }`}
                        >
                            {tf}
                        </button>
                    ))}
                </div>

                {/* Type filter */}
                <div className="flex gap-1">
                    {['ALL', 'golden_cross', 'death_cross'].map(t => (
                        <button
                            key={t}
                            onClick={() => setFilterType(t)}
                            className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-all ${filterType === t
                                ? 'bg-violet-600 border-violet-500 text-white'
                                : 'bg-zinc-900 border-zinc-700 text-zinc-400 hover:text-white'
                                }`}
                        >
                            {t === 'ALL' ? 'All Types' : t === 'golden_cross' ? '🌟 Golden' : '💀 Death'}
                        </button>
                    ))}
                </div>

                {/* Tabs */}
                <div className="ml-auto flex rounded-xl overflow-hidden border border-zinc-700">
                    <button
                        onClick={() => setTab('crossovers')}
                        className={`px-4 py-1.5 text-xs font-bold transition-all ${tab === 'crossovers' ? 'bg-blue-600 text-white' : 'bg-zinc-900 text-zinc-400 hover:text-white'}`}
                    >
                        Crossovers ({filtered.length})
                    </button>
                    <button
                        onClick={() => setTab('nearing')}
                        className={`px-4 py-1.5 text-xs font-bold transition-all ${tab === 'nearing' ? 'bg-amber-600 text-white' : 'bg-zinc-900 text-zinc-400 hover:text-white'}`}
                    >
                        Nearing ({filteredNearing.length})
                    </button>
                </div>
            </div>

            {/* ── Main table ───────────────────────────── */}
            <div className="max-w-[1600px] mx-auto">
                {tab === 'crossovers' ? (
                    <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-zinc-800 bg-zinc-900">
                                        {[
                                            'Symbol', 'TF', 'Type', 'Price',
                                            '20EMA', '50EMA', '200EMA',
                                            'Cross Gap%',
                                            'P↔200E%',
                                            'Time',
                                        ].map(h => (
                                            <th key={h} className="px-3 py-3 text-left text-[10px] font-bold text-zinc-500 uppercase tracking-widest" title={
                                                h === 'Cross Gap%' ? 'Gap between Short MA and Long MA — size of the crossover' :
                                                h === 'P↔200E%'   ? 'Price distance from 200EMA — institutional reference' : undefined
                                            }>
                                                {h}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {filtered.length === 0 ? (
                                        <tr>
                                            <td colSpan={10} className="px-3 py-12 text-center text-zinc-500">
                                                {status?.running
                                                    ? '🔍 Scanner running — waiting for crossovers…'
                                                    : '▶ Start the scanner to detect live crossovers'}
                                            </td>
                                        </tr>
                                    ) : (
                                        filtered.map((ev, i) => (
                                            <CrossoverRow key={`${ev.symbol}-${ev.timeframe}-${ev.timestamp}-${i}`} ev={ev} />
                                        ))
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : (
                    <div className="bg-zinc-900/60 border border-zinc-800 rounded-2xl overflow-hidden">
                        <div className="px-4 py-3 border-b border-zinc-800 text-xs text-zinc-400 font-semibold">
                            ⚠️ Stocks within {status?.config?.proximity_threshold ?? 0.5}% of a crossover — act before it triggers
                        </div>
                        {filteredNearing.length === 0 ? (
                            <div className="px-3 py-12 text-center text-zinc-500">
                                No nearing crossovers at current proximity threshold
                            </div>
                        ) : (
                            filteredNearing.map((ev, i) => (
                                <NearingRow key={`${ev.symbol}-${ev.timeframe}-${i}`} ev={ev} />
                            ))
                        )}
                    </div>
                )}
            </div>

            {/* ── Error banner ──────────────────────────── */}
            {error && (
                <div className="max-w-[1600px] mx-auto mt-4 px-4 py-3 bg-rose-950 border border-rose-700 rounded-xl text-rose-300 text-sm">
                    ⚠️ {error}
                </div>
            )}

            {/* ── Settings modal ──────────────────────── */}
            {showSettings && status?.config && (
                <SettingsPanel
                    config={status.config}
                    onSave={handleConfigUpdate}
                    onClose={() => setShowSettings(false)}
                />
            )}
        </div>
    );
}
