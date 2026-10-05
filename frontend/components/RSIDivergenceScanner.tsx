'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import LoadingBanner from './ui/LoadingBanner';

interface Ticket {
    side?: string;
    trigger?: string;
    sponsor?: string;
    vehicle?: { style?: string; structure?: string; why?: string; instrument?: string; strike?: number };
    entry?: string;
    stop?: number;
    stop_src?: string;
    target1?: number;
    target1_src?: string;
    rr?: number;
    time_stop?: string;
    invalidation?: string;
}

interface Hit {
    rule?: string;
    detail?: string;
    w?: number;
}

interface Score {
    D?: number;
    E?: number;
    P?: number;
    desk?: number;
}

interface Row {
    symbol: string;
    name: string;
    ltp?: number;
    chg_pct?: number;
    side?: string;
    thesis?: string;
    analysis?: string;
    rsi?: number | null;
    rsi15?: number | null;
    rsi60?: number | null;
    event?: string;
    zone?: string;
    reclaim?: boolean;
    div_type?: string | null;
    div_live?: boolean;
    div_near?: boolean;
    div_fresh?: boolean;
    div_bars_ago?: number | null;
    div_rsi_gap?: number | null;
    div_price_l1?: number | null;
    div_price_l2?: number | null;
    div_rsi_l1?: number | null;
    div_rsi_l2?: number | null;
    price_move_pct?: number | null;
    rsi_move?: number | null;
    pivot_span?: number | null;
    div_magnitude?: number | null;
    div60_type?: string | null;
    div60_live?: boolean;
    htf_priority?: string;
    quality?: string | null;
    permission?: number;
    permission_hits?: Hit[];
    permission_miss?: string[];
    buildup_note?: string;
    futures_state?: string;
    oi_pcr?: number | null;
    put_wall?: number | null;
    call_wall?: number | null;
    rel_vol?: number | null;
    vwap?: number | null;
    near_vwap?: boolean;
    ema20?: string | null;
    adx?: number | null;
    h4_bias?: string;
    mtf_allowed?: string;
    mtf_gate?: string;
    extreme_score?: number;
    desk_score?: number;
    div_score?: number;
    score?: Score;
    board?: string;
    board_reason?: string;
    grade?: string;
    ticket?: Ticket | null;
}

interface Counts {
    trade?: number;
    watch?: number;
    near?: number;
    reject?: number;
    bull?: number;
    bear?: number;
    fresh?: number;
    priority_a?: number;
    quality_a?: number;
    rsi_os?: number;
    rsi_ob?: number;
    knives?: number;
    h4_veto?: number;
    waiting_harvest?: number;
}

interface Stats {
    live?: number;
    near?: number;
    mean_rsi_gap?: number | null;
    mean_magnitude?: number | null;
    breadth_live_pct?: number;
    breadth_os_pct?: number;
    breadth_ob_pct?: number;
}

type Tab = 'TRADE' | 'WATCH' | 'NEAR' | 'REJECT';

interface Props {
    onBack: () => void;
}

const POLL_MS = 45_000;

function fmt(n: number | null | undefined, d = 1) {
    if (n == null || Number.isNaN(Number(n))) return '—';
    return Number(n).toFixed(d);
}

function ScoreBar({ label, value, color }: { label: string; value?: number; color: string }) {
    const v = Math.max(0, Math.min(100, Number(value || 0)));
    return (
        <div>
            <div className="flex justify-between text-[10px] font-black uppercase tracking-wider text-zinc-500 mb-1">
                <span>{label}</span>
                <span className="font-mono text-zinc-300">{fmt(v, 0)}</span>
            </div>
            <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                <div className={`h-full ${color}`} style={{ width: `${v}%` }} />
            </div>
        </div>
    );
}

function StatChip({
    label,
    value,
    tone,
}: {
    label: string;
    value: string | number;
    tone?: 'bull' | 'bear' | 'warn' | 'mute';
}) {
    const cls =
        tone === 'bull'
            ? 'border-emerald-500/30 text-emerald-300 bg-emerald-500/10'
            : tone === 'bear'
              ? 'border-rose-500/30 text-rose-300 bg-rose-500/10'
              : tone === 'warn'
                ? 'border-amber-500/30 text-amber-300 bg-amber-500/10'
                : 'border-zinc-700 text-zinc-400 bg-zinc-900/80';
    return (
        <div className={`px-3 py-2 rounded-xl border ${cls}`}>
            <div className="text-[9px] font-black uppercase tracking-widest opacity-70">{label}</div>
            <div className="text-lg font-black font-mono leading-tight">{value}</div>
        </div>
    );
}

export default function RSIDivergenceScanner({ onBack }: Props) {
    const [tf, setTf] = useState<'15' | 'D'>('15');
    const [source, setSource] = useState<'full' | 'top'>('full');
    const [trade, setTrade] = useState<Row[]>([]);
    const [watch, setWatch] = useState<Row[]>([]);
    const [near, setNear] = useState<Row[]>([]);
    const [reject, setReject] = useState<Row[]>([]);
    const [tab, setTab] = useState<Tab>('WATCH');
    const [sideFilter, setSideFilter] = useState<'both' | 'bull' | 'bear'>('both');
    const [freshOnly, setFreshOnly] = useState(false);
    const [selected, setSelected] = useState<Row | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [counts, setCounts] = useState<Counts>({});
    const [stats, setStats] = useState<Stats>({});
    const [harvest, setHarvest] = useState<{
        symbols?: number;
        history_15_fresh?: number;
        freshest_age?: number | null;
        redis?: string;
    } | null>(null);
    const [scanned, setScanned] = useState(0);
    const [universe, setUniverse] = useState(0);
    const [updated, setUpdated] = useState<Date | null>(null);
    const runId = useRef(0);
    const bootTab = useRef(true);

    const pull = useCallback(async () => {
        const my = ++runId.current;
        setLoading(true);
        setError(null);
        try {
            const snap: any = await api.rsi.divergence(tf, source);
            if (my !== runId.current) return;
            const t: Row[] = snap.trade || [];
            const w: Row[] = snap.watch || [];
            const n: Row[] = snap.near || [];
            const r: Row[] = snap.reject || [];
            setTrade(t);
            setWatch(w);
            setNear(n);
            setReject(r);
            setCounts(snap.counts || {});
            setStats(snap.stats || {});
            setHarvest(snap.harvest || null);
            setScanned(snap.scanned || 0);
            setUniverse(snap.universe || 0);
            setUpdated(new Date());
            setSelected((prev) => {
                const pool = [...t, ...w, ...n, ...r];
                if (prev) {
                    const hit = pool.find((x) => x.symbol === prev.symbol);
                    if (hit) return hit;
                }
                return t[0] || w[0] || n[0] || null;
            });
            if (bootTab.current) {
                bootTab.current = false;
                if (t.length) setTab('TRADE');
                else if (w.length) setTab('WATCH');
                else if (n.length) setTab('NEAR');
            }
            if (!t.length && !w.length && !n.length && (snap.counts?.waiting_harvest || 0) > 10) {
                setError(`History book warming — ${snap.counts.waiting_harvest} names waiting harvest.`);
            }
        } catch (e: any) {
            if (my !== runId.current) return;
            setError(e?.message || 'Divergence scan failed');
        } finally {
            if (my !== runId.current) return;
            setLoading(false);
        }
    }, [tf, source]);

    useEffect(() => {
        pull();
        const t = setInterval(pull, POLL_MS);
        return () => {
            runId.current += 1;
            clearInterval(t);
        };
    }, [pull]);

    const raw =
        tab === 'TRADE' ? trade : tab === 'WATCH' ? watch : tab === 'NEAR' ? near : reject;

    const rows = useMemo(() => {
        return raw.filter((c) => {
            if (sideFilter === 'bull' && c.thesis !== 'BOUNCE') return false;
            if (sideFilter === 'bear' && c.thesis !== 'FADE') return false;
            if (freshOnly && !c.div_fresh) return false;
            return true;
        });
    }, [raw, sideFilter, freshOnly]);

    const ticket = selected?.ticket || null;
    const sc = selected?.score || {};
    const bullish = selected?.thesis === 'BOUNCE';

    return (
        <div className="min-h-screen bg-[#080b11] text-zinc-100">
            <header className="border-b border-zinc-800 bg-[#0c1018]/95 backdrop-blur-sm sticky top-0 z-30">
                <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center gap-4">
                    <button
                        onClick={onBack}
                        className="p-2 hover:bg-zinc-800 rounded-lg text-zinc-400 hover:text-white"
                    >
                        ←
                    </button>
                    <div>
                        <h1 className="text-lg font-black tracking-tight uppercase">
                            RSI Divergence{' '}
                            <span className="text-fuchsia-500 text-xs not-italic font-black">desk</span>
                        </h1>
                        <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-widest">
                            Classic LL/HL · 1H confirm · OC permission · 4H gate
                        </p>
                    </div>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                        {(['15', 'D'] as const).map((id) => (
                            <button
                                key={id}
                                onClick={() => setTf(id)}
                                className={`px-3 py-1.5 text-[10px] font-bold uppercase rounded-full border ${
                                    tf === id
                                        ? 'bg-fuchsia-600 border-fuchsia-500 text-white'
                                        : 'bg-zinc-900 border-zinc-700 text-zinc-500'
                                }`}
                            >
                                {id === '15' ? '15m' : 'Daily'}
                            </button>
                        ))}
                        <button
                            onClick={() => setSource(source === 'full' ? 'top' : 'full')}
                            className="px-3 py-1.5 text-[10px] font-bold uppercase rounded-full border border-zinc-700 bg-zinc-900 text-zinc-400"
                        >
                            {source === 'full' ? 'All F&O' : 'Top liquid'}
                        </button>
                        <button
                            onClick={pull}
                            disabled={loading}
                            className="px-4 py-1.5 bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-[10px] font-black uppercase rounded-full disabled:opacity-50"
                        >
                            {loading ? 'Scoring…' : '↻ Rescore'}
                        </button>
                        {updated && (
                            <span className="text-[9px] text-zinc-600">{updated.toLocaleTimeString()}</span>
                        )}
                    </div>
                </div>
            </header>

            <main className="max-w-screen-2xl mx-auto px-4 py-4 space-y-4">
                <LoadingBanner
                    active={loading && trade.length + watch.length + near.length === 0}
                    label={`Scoring ${tf === '15' ? '15m' : 'daily'} RSI divergence on harvest book`}
                    detail={`${scanned}/${universe || '—'} names · no Fyers · 1H derived from 15m`}
                />

                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
                    <StatChip label="Live" value={stats.live ?? 0} />
                    <StatChip label="Bull" value={counts.bull ?? 0} tone="bull" />
                    <StatChip label="Bear" value={counts.bear ?? 0} tone="bear" />
                    <StatChip label="Fresh" value={counts.fresh ?? 0} tone="warn" />
                    <StatChip label="Building" value={counts.near ?? 0} />
                    <StatChip label="Knife" value={counts.knives ?? 0} tone="bear" />
                    <StatChip label="RSI ≤30" value={`${fmt(stats.breadth_os_pct, 0)}%`} />
                    <StatChip label="RSI ≥70" value={`${fmt(stats.breadth_ob_pct, 0)}%`} />
                </div>

                <div className="flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase text-zinc-500">
                    <span className="px-3 py-1 rounded-full border border-zinc-800 bg-zinc-900/80">
                        Book {harvest?.history_15_fresh ?? 0}/{harvest?.symbols ?? 0} · gap{' '}
                        {fmt(stats.mean_rsi_gap)} · mag {fmt(stats.mean_magnitude)} · live{' '}
                        {fmt(stats.breadth_live_pct, 0)}%
                    </span>
                    <span className="text-zinc-600">
                        Divergence is exhaustion, not a buy. OC + 4H still own the ticket.
                    </span>
                </div>

                {error && (
                    <div className="p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-xs text-amber-300">
                        {error}
                    </div>
                )}

                <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
                    <div className="xl:col-span-3 rounded-2xl border border-zinc-800 bg-[#0e1420] overflow-hidden">
                        <div className="px-3 py-2 border-b border-zinc-800 flex flex-wrap gap-1">
                            {(
                                [
                                    ['TRADE', trade.length, 'emerald'],
                                    ['WATCH', watch.length, 'amber'],
                                    ['NEAR', near.length, 'fuchsia'],
                                    ['REJECT', reject.length, 'zinc'],
                                ] as const
                            ).map(([id, n, tone]) => (
                                <button
                                    key={id}
                                    onClick={() => setTab(id)}
                                    className={`px-3 py-1.5 text-[10px] font-black uppercase rounded-lg ${
                                        tab === id
                                            ? tone === 'emerald'
                                                ? 'bg-emerald-600 text-white'
                                                : tone === 'amber'
                                                  ? 'bg-amber-600 text-white'
                                                  : tone === 'fuchsia'
                                                    ? 'bg-fuchsia-600 text-white'
                                                    : 'bg-zinc-600 text-white'
                                            : 'bg-zinc-900 text-zinc-500'
                                    }`}
                                >
                                    {id === 'NEAR' ? 'BUILDING' : id} {n}
                                </button>
                            ))}
                            <div className="ml-auto flex gap-1">
                                {(['both', 'bull', 'bear'] as const).map((s) => (
                                    <button
                                        key={s}
                                        onClick={() => setSideFilter(s)}
                                        className={`px-2 py-1 text-[9px] font-black uppercase rounded ${
                                            sideFilter === s
                                                ? 'bg-zinc-100 text-zinc-900'
                                                : 'bg-zinc-900 text-zinc-500'
                                        }`}
                                    >
                                        {s}
                                    </button>
                                ))}
                                <button
                                    onClick={() => setFreshOnly((v) => !v)}
                                    className={`px-2 py-1 text-[9px] font-black uppercase rounded ${
                                        freshOnly
                                            ? 'bg-amber-500 text-black'
                                            : 'bg-zinc-900 text-zinc-500'
                                    }`}
                                >
                                    Fresh
                                </button>
                            </div>
                        </div>
                        <div className="overflow-x-auto max-h-[62vh] overflow-y-auto">
                            <table className="w-full text-left text-xs">
                                <thead className="sticky top-0 bg-[#0e1420] text-[9px] uppercase text-zinc-500">
                                    <tr>
                                        <th className="px-3 py-2">Name</th>
                                        <th className="px-3 py-2">Div</th>
                                        <th className="px-3 py-2">Q</th>
                                        <th className="px-3 py-2">RSI 15/1H</th>
                                        <th className="px-3 py-2">Gap · bars</th>
                                        <th className="px-3 py-2">1H</th>
                                        <th className="px-3 py-2">4H</th>
                                        <th className="px-3 py-2">P</th>
                                        <th className="px-3 py-2">Desk</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {!loading && rows.length === 0 && (
                                        <tr>
                                            <td colSpan={9} className="px-4 py-12 text-center text-zinc-500">
                                                {scanned > 0
                                                    ? 'No names in this slice — try Building or clear Fresh.'
                                                    : 'Waiting for harvest 15m / daily book.'}
                                            </td>
                                        </tr>
                                    )}
                                    {rows.map((c) => {
                                        const bull = c.thesis === 'BOUNCE';
                                        return (
                                            <tr
                                                key={c.symbol}
                                                onClick={() => setSelected(c)}
                                                className={`border-t border-zinc-800/80 hover:bg-zinc-800/40 cursor-pointer ${
                                                    selected?.symbol === c.symbol ? 'bg-fuchsia-500/10' : ''
                                                }`}
                                            >
                                                <td className="px-3 py-2.5">
                                                    <div className="font-black">{c.name}</div>
                                                    <div className="text-[10px] font-mono text-zinc-500">
                                                        {fmt(c.ltp, 1)}
                                                        {c.chg_pct != null && (
                                                            <span
                                                                className={
                                                                    c.chg_pct >= 0
                                                                        ? ' text-emerald-400'
                                                                        : ' text-rose-400'
                                                                }
                                                            >
                                                                {' '}
                                                                {c.chg_pct >= 0 ? '+' : ''}
                                                                {fmt(c.chg_pct, 1)}%
                                                            </span>
                                                        )}
                                                    </div>
                                                </td>
                                                <td className="px-3 py-2.5">
                                                    <span
                                                        className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded ${
                                                            bull
                                                                ? 'bg-emerald-500/15 text-emerald-400'
                                                                : 'bg-rose-500/15 text-rose-400'
                                                        }`}
                                                    >
                                                        {c.div_near
                                                            ? bull
                                                                ? 'NEAR BULL'
                                                                : 'NEAR BEAR'
                                                            : bull
                                                              ? 'BULL DIV'
                                                              : 'BEAR DIV'}
                                                        {c.div_fresh ? ' · F' : ''}
                                                    </span>
                                                </td>
                                                <td className="px-3 py-2.5 font-black text-zinc-300">
                                                    {c.quality || '—'}
                                                </td>
                                                <td className="px-3 py-2.5 font-mono">
                                                    {fmt(c.rsi, 1)}
                                                    <span className="text-zinc-600"> / {fmt(c.rsi60, 1)}</span>
                                                </td>
                                                <td className="px-3 py-2.5 font-mono text-[10px] text-zinc-400">
                                                    {fmt(c.div_rsi_gap, 1)} · {c.div_bars_ago ?? '—'}b
                                                </td>
                                                <td className="px-3 py-2.5 text-[10px] font-black">
                                                    {c.htf_priority === 'A' ? (
                                                        <span className="text-emerald-400">CONFIRM</span>
                                                    ) : c.htf_priority === 'C' ? (
                                                        <span className="text-rose-400">OPPOSE</span>
                                                    ) : (
                                                        <span className="text-zinc-500">{c.htf_priority || '—'}</span>
                                                    )}
                                                </td>
                                                <td className="px-3 py-2.5 text-[10px] font-bold text-zinc-400">
                                                    {c.h4_bias || '—'}
                                                </td>
                                                <td className="px-3 py-2.5 font-mono">{fmt(c.permission, 0)}</td>
                                                <td className="px-3 py-2.5 font-black">{fmt(c.desk_score, 0)}</td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="xl:col-span-2 rounded-2xl border border-zinc-800 bg-[#0e1420] p-4 space-y-4 min-h-[320px]">
                        <div className="text-[10px] font-black uppercase tracking-widest text-zinc-500">
                            Quant analysis
                        </div>
                        {!selected && (
                            <p className="text-sm text-zinc-500 py-8 text-center">
                                Select a name to read the divergence.
                            </p>
                        )}
                        {selected && (
                            <div className="space-y-4">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-lg font-black">{selected.name}</span>
                                    <span
                                        className={`text-[10px] font-black uppercase px-2 py-0.5 rounded border ${
                                            selected.board === 'TRADE'
                                                ? 'border-emerald-500/40 text-emerald-400'
                                                : selected.board === 'REJECT'
                                                  ? 'border-rose-500/40 text-rose-400'
                                                  : selected.board === 'NEAR'
                                                    ? 'border-fuchsia-500/40 text-fuchsia-400'
                                                    : 'border-amber-500/40 text-amber-300'
                                        }`}
                                    >
                                        {selected.board}
                                    </span>
                                    {selected.quality && (
                                        <span className="text-[10px] font-black text-zinc-400">
                                            Q {selected.quality}
                                        </span>
                                    )}
                                    {selected.grade && (
                                        <span className="text-[10px] font-black text-zinc-500">
                                            {selected.grade}
                                        </span>
                                    )}
                                </div>

                                <p className="text-[12px] leading-relaxed text-zinc-300">
                                    {selected.analysis || selected.board_reason}
                                </p>

                                <div className="grid grid-cols-2 gap-3">
                                    <div className="p-3 rounded-xl border border-zinc-800 bg-black/30 space-y-1">
                                        <div className="text-[9px] font-black uppercase text-zinc-500">Price pivots</div>
                                        <div className="font-mono text-sm">
                                            {fmt(selected.div_price_l1, 2)} → {fmt(selected.div_price_l2, 2)}
                                        </div>
                                        <div className="text-[10px] text-zinc-500">
                                            {fmt(selected.price_move_pct, 2)}% · span {selected.pivot_span ?? '—'}b
                                        </div>
                                    </div>
                                    <div className="p-3 rounded-xl border border-zinc-800 bg-black/30 space-y-1">
                                        <div className="text-[9px] font-black uppercase text-zinc-500">RSI pivots</div>
                                        <div className={`font-mono text-sm ${bullish ? 'text-emerald-400' : 'text-rose-400'}`}>
                                            {fmt(selected.div_rsi_l1, 1)} → {fmt(selected.div_rsi_l2, 1)}
                                        </div>
                                        <div className="text-[10px] text-zinc-500">
                                            gap {fmt(selected.div_rsi_gap, 1)} · mag {fmt(selected.div_magnitude, 1)}
                                        </div>
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <ScoreBar label="Divergence D" value={sc.D ?? selected.div_score} color="bg-fuchsia-500" />
                                    <ScoreBar label="Extreme E" value={sc.E ?? selected.extreme_score} color="bg-cyan-500" />
                                    <ScoreBar label="Permission P" value={sc.P ?? selected.permission} color="bg-emerald-500" />
                                    <ScoreBar label="Desk" value={sc.desk ?? selected.desk_score} color="bg-zinc-200" />
                                </div>

                                <div className="grid grid-cols-3 gap-2 text-[10px]">
                                    <div className="p-2 rounded-lg bg-black/30 border border-zinc-800">
                                        <div className="text-zinc-500 font-black uppercase">RSI 15</div>
                                        <div className="font-mono font-black">{fmt(selected.rsi, 1)}</div>
                                    </div>
                                    <div className="p-2 rounded-lg bg-black/30 border border-zinc-800">
                                        <div className="text-zinc-500 font-black uppercase">RSI 1H</div>
                                        <div className="font-mono font-black">{fmt(selected.rsi60, 1)}</div>
                                    </div>
                                    <div className="p-2 rounded-lg bg-black/30 border border-zinc-800">
                                        <div className="text-zinc-500 font-black uppercase">ADX / RVOL</div>
                                        <div className="font-mono font-black">
                                            {fmt(selected.adx, 0)} / {fmt(selected.rel_vol, 1)}
                                        </div>
                                    </div>
                                    <div className="p-2 rounded-lg bg-black/30 border border-zinc-800">
                                        <div className="text-zinc-500 font-black uppercase">VWAP</div>
                                        <div className="font-mono font-black">
                                            {fmt(selected.vwap, 1)} {selected.near_vwap ? '· near' : ''}
                                        </div>
                                    </div>
                                    <div className="p-2 rounded-lg bg-black/30 border border-zinc-800">
                                        <div className="text-zinc-500 font-black uppercase">EMA20</div>
                                        <div className="font-black">{selected.ema20 || '—'}</div>
                                    </div>
                                    <div className="p-2 rounded-lg bg-black/30 border border-zinc-800">
                                        <div className="text-zinc-500 font-black uppercase">1H div</div>
                                        <div className="font-black">{selected.div60_type || 'none'}</div>
                                    </div>
                                </div>

                                <div className="p-3 rounded-xl border border-zinc-800 bg-black/30 space-y-1.5">
                                    <div className="text-[9px] font-black uppercase text-zinc-500">
                                        Option chain · 4H
                                    </div>
                                    <div className="text-[11px] text-zinc-300">
                                        {selected.buildup_note || 'No buildup note'}
                                        {selected.futures_state ? ` · fut ${selected.futures_state}` : ''}
                                    </div>
                                    <div className="text-[10px] text-zinc-500">
                                        4H {selected.h4_bias || '—'} · allowed {selected.mtf_allowed || '—'} ·{' '}
                                        {selected.mtf_gate || '—'}
                                    </div>
                                    {selected.put_wall != null && (
                                        <div className="text-[10px] font-mono text-zinc-500">
                                            put wall {selected.put_wall} · call wall {selected.call_wall ?? '—'}
                                            {selected.oi_pcr != null ? ` · PCR ${fmt(selected.oi_pcr, 2)}` : ''}
                                        </div>
                                    )}
                                    {(selected.permission_hits || []).length > 0 && (
                                        <div className="flex flex-wrap gap-1 pt-1">
                                            {(selected.permission_hits || []).slice(0, 6).map((h, i) => (
                                                <span
                                                    key={i}
                                                    className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                                >
                                                    {h.rule || h.detail}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    {(selected.permission_miss || []).length > 0 && (
                                        <div className="flex flex-wrap gap-1">
                                            {(selected.permission_miss || []).slice(0, 4).map((m, i) => (
                                                <span
                                                    key={i}
                                                    className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20"
                                                >
                                                    {m}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                {ticket ? (
                                    <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 space-y-1.5 text-[11px]">
                                        <div className="text-[10px] font-black uppercase text-emerald-400">
                                            {ticket.side} · {ticket.vehicle?.style}
                                        </div>
                                        <div className="text-sm font-black font-mono">
                                            {ticket.vehicle?.structure}
                                        </div>
                                        <div className="text-zinc-400">{ticket.trigger}</div>
                                        <div>
                                            Stop <strong>{ticket.stop}</strong> ({ticket.stop_src}) · Target{' '}
                                            <strong>{ticket.target1}</strong> ({ticket.target1_src})
                                        </div>
                                        <div className="text-zinc-500">
                                            R:R {ticket.rr ?? '—'} · {ticket.time_stop}
                                        </div>
                                        {ticket.invalidation && (
                                            <div className="text-rose-300/80">Invalidation: {ticket.invalidation}</div>
                                        )}
                                    </div>
                                ) : (
                                    <p className="text-[11px] text-zinc-500">
                                        No ticket — {selected.board_reason}. Divergence does not trade alone.
                                    </p>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
}
