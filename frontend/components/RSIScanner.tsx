'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import LoadingBanner from './ui/LoadingBanner';

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
}

interface Hit {
    rule: string;
    detail: string;
}

interface Row {
    symbol: string;
    name: string;
    ltp: number;
    side?: string;
    thesis?: string;
    rsi15?: number | null;
    rsi60?: number | null;
    event?: string;
    zone?: string;
    reclaim?: boolean;
    fresh?: boolean;
    extreme_score?: number;
    permission?: number;
    permission_hits?: Hit[];
    permission_miss?: string[];
    buildup_note?: string;
    futures_state?: string;
    rel_vol?: number;
    vwap?: number;
    ema20?: string;
    adx?: number;
    h4_bias?: string;
    mtf_allowed?: string;
    desk_score?: number;
    board?: string;
    board_reason?: string;
    grade?: string;
    htf_priority?: string;
    ticket?: Ticket | null;
    div_type?: string | null;
    div_event?: string | null;
    div_live?: boolean;
    div_fresh?: boolean;
    div_bars_ago?: number | null;
    div_rsi_gap?: number | null;
    div_price_l1?: number | null;
    div_price_l2?: number | null;
    div_rsi_l1?: number | null;
    div_rsi_l2?: number | null;
}

interface Props {
    onBack: () => void;
}

const POLL_MS = 45_000;

export default function RSIScanner({ onBack }: Props) {
    const [trade, setTrade] = useState<Row[]>([]);
    const [watch, setWatch] = useState<Row[]>([]);
    const [reject, setReject] = useState<Row[]>([]);
    const [tab, setTab] = useState<'TRADE' | 'WATCH' | 'REJECT'>('TRADE');
    const [side, setSide] = useState<'both' | 'oversold' | 'overbought'>('both');
    const [source, setSource] = useState<'full' | 'top'>('full');
    const [selected, setSelected] = useState<Row | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [harvest, setHarvest] = useState<{
        symbols?: number;
        history_15_fresh?: number;
        freshest_age?: number | null;
        redis?: string;
    } | null>(null);
    const [counts, setCounts] = useState<{
        trade?: number;
        watch?: number;
        reject?: number;
        oversold?: number;
        overbought?: number;
        waiting_harvest?: number;
    }>({});
    const [scanned, setScanned] = useState(0);
    const [universe, setUniverse] = useState(0);
    const [updated, setUpdated] = useState<Date | null>(null);

    const runId = useRef(0);

    const pull = useCallback(async () => {
        const my = ++runId.current;
        setLoading(true);
        setError(null);
        try {
            const snap: any = await api.rsi.scan(source, side);
            if (my !== runId.current) return;
            const t = snap.trade || [];
            const w = snap.watch || [];
            const r = snap.reject || [];
            setTrade(t);
            setWatch(w);
            setReject(r);
            setCounts(snap.counts || {});
            setHarvest(snap.harvest || null);
            setScanned(snap.scanned || 0);
            setUniverse(snap.universe || 0);
            setUpdated(new Date());
            setSelected((prev) => {
                const pool = [...t, ...w, ...r];
                if (prev) {
                    const hit = pool.find((x) => x.symbol === prev.symbol);
                    if (hit) return hit;
                }
                return t[0] || w[0] || null;
            });
            if (!t.length && !w.length && (snap.counts?.waiting_harvest || 0) > 10) {
                setError(
                    `15m book warming — ${snap.counts.waiting_harvest} names waiting harvest.`,
                );
            }
        } catch (e: any) {
            if (my !== runId.current) return;
            setError(e?.message || 'RSI scan failed');
        } finally {
            if (my === runId.current) setLoading(false);
        }
    }, [source, side]);

    useEffect(() => {
        pull();
        const t = setInterval(pull, POLL_MS);
        return () => {
            runId.current += 1;
            clearInterval(t);
        };
    }, [pull]);

    const rows = tab === 'TRADE' ? trade : tab === 'WATCH' ? watch : reject;
    const ticket = selected?.ticket || null;

    const badge = (s?: string) => {
        if (s === 'TRADE' || s === 'A-SETUP' || s === 'SETUP')
            return 'text-emerald-500 border-emerald-500/40 bg-emerald-500/10';
        if (s === 'REJECT') return 'text-rose-500 border-rose-500/40 bg-rose-500/10';
        return 'text-amber-600 border-amber-500/40 bg-amber-500/10';
    };

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
                                RSI Desk<span className="text-fuchsia-500">.</span>
                            </h1>
                            <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest">
                                15m + 1H RSI(14) · OC bounce / fade · 4H gate
                            </p>
                        </div>
                    </div>
                    <div className="flex flex-wrap gap-2 items-center">
                        {(['both', 'oversold', 'overbought'] as const).map((id) => (
                            <button
                                key={id}
                                onClick={() => setSide(id)}
                                className={`px-3 py-2 text-[10px] font-bold uppercase rounded-lg ${
                                    side === id
                                        ? 'bg-fuchsia-600 text-white'
                                        : 'bg-zinc-200 dark:bg-zinc-800 text-zinc-500'
                                }`}
                            >
                                {id === 'both' ? 'Both' : id === 'oversold' ? 'Oversold bounce' : 'Overbought fade'}
                            </button>
                        ))}
                        <button
                            onClick={() => setSource(source === 'full' ? 'top' : 'full')}
                            className="px-3 py-2 text-[10px] font-bold uppercase rounded-lg bg-zinc-200 dark:bg-zinc-800 text-zinc-500"
                        >
                            {source === 'full' ? 'All F&O' : 'Top liquid'}
                        </button>
                        <button
                            onClick={pull}
                            disabled={loading}
                            className="px-4 py-2 bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-xs font-bold uppercase rounded-lg disabled:opacity-50"
                        >
                            {loading ? 'Scoring…' : '↻ Rescore'}
                        </button>
                    </div>
                </header>

                <LoadingBanner
                    active={loading && trade.length + watch.length === 0}
                    label="Scoring harvest book — RSI(14) 15m + derived 1H + stored chain"
                    detail="No Fyers walk · 4H allowed_side hard gate"
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
                        {updated ? ` · ${updated.toLocaleTimeString()}` : ''}
                    </div>
                )}

                <div className="mb-4 p-3 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/5 text-[11px] text-zinc-600 dark:text-zinc-400">
                    <strong className="text-fuchsia-500">Desk:</strong> bounce = RSI15 ≤30 +
                    bullish OC (PE writing / CE LB). Fade = RSI15 ≥70 + bearish OC. Reclaim of
                    30/70 preferred. 4H opposite = no ticket. 5m not harvested. Poll 45s.
                    {' · '}
                    scored {scanned}/{universe || '—'} · waiting harvest{' '}
                    {counts.waiting_harvest ?? 0}
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
                                        ['TRADE', trade.length],
                                        ['WATCH', watch.length],
                                        ['REJECT', reject.length],
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
                        </div>
                        <div className="overflow-x-auto max-h-[65vh] overflow-y-auto">
                            <table className="w-full text-left text-xs">
                                <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-900/95 text-[10px] uppercase text-zinc-500">
                                    <tr>
                                        <th className="px-3 py-2">Stock</th>
                                        <th className="px-3 py-2">LTP</th>
                                        <th className="px-3 py-2">Thesis</th>
                                        <th className="px-3 py-2">15m</th>
                                        <th className="px-3 py-2">1H</th>
                                        <th className="px-3 py-2">Event</th>
                                        <th className="px-3 py-2">4H</th>
                                        <th className="px-3 py-2">P</th>
                                        <th className="px-3 py-2">Desk</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {!loading && rows.length === 0 && (
                                        <tr>
                                            <td
                                                colSpan={9}
                                                className="px-4 py-12 text-center text-zinc-500"
                                            >
                                                {scanned > 0
                                                    ? tab === 'TRADE'
                                                        ? 'No permissioned RSI tickets. Check WATCH (waiting reclaim / mixed 4H).'
                                                        : `No ${tab} rows.`
                                                    : 'Waiting for harvest 15m book.'}
                                            </td>
                                        </tr>
                                    )}
                                    {rows.map((c) => (
                                        <tr
                                            key={c.symbol}
                                            onClick={() => setSelected(c)}
                                            className={`border-t border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/40 cursor-pointer ${
                                                selected?.symbol === c.symbol
                                                    ? 'bg-fuchsia-500/10'
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
                                                        c.thesis === 'BOUNCE'
                                                            ? 'bg-emerald-500/15 text-emerald-600'
                                                            : 'bg-rose-500/15 text-rose-600'
                                                    }`}
                                                >
                                                    {c.thesis}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2.5 font-mono font-bold">
                                                {c.rsi15 ?? '—'}
                                            </td>
                                            <td className="px-3 py-2.5 font-mono">
                                                {c.rsi60 ?? '—'}
                                            </td>
                                            <td className="px-3 py-2.5 text-[10px] font-black text-fuchsia-500">
                                                <div>{c.event}</div>
                                                {c.div_type && (
                                                    <div
                                                        className={`text-[9px] font-black ${
                                                            c.div_type === 'BULL_DIV'
                                                                ? 'text-emerald-600'
                                                                : 'text-rose-600'
                                                        }`}
                                                        title={[
                                                            c.div_event,
                                                            c.div_price_l1 != null && c.div_price_l2 != null
                                                                ? `price ${c.div_price_l1}→${c.div_price_l2}`
                                                                : null,
                                                            c.div_rsi_l1 != null && c.div_rsi_l2 != null
                                                                ? `RSI ${c.div_rsi_l1}→${c.div_rsi_l2}`
                                                                : null,
                                                            c.div_bars_ago != null ? `${c.div_bars_ago} bars ago` : null,
                                                        ]
                                                            .filter(Boolean)
                                                            .join(' · ')}
                                                    >
                                                        {c.div_type === 'BULL_DIV' ? 'BULL DIV' : 'BEAR DIV'}
                                                        {c.div_fresh ? ' FRESH' : ''}
                                                    </div>
                                                )}
                                            </td>
                                            <td className="px-3 py-2.5 text-[10px] font-bold">
                                                {c.h4_bias || '—'}
                                            </td>
                                            <td className="px-3 py-2.5 font-mono font-bold">
                                                {c.permission ?? '—'}
                                            </td>
                                            <td className="px-3 py-2.5 font-black">
                                                {c.desk_score ?? '—'}
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
                        {!selected && (
                            <p className="text-sm text-zinc-500 py-8 text-center">
                                Select a row. TRADE already has a ticket from the book.
                            </p>
                        )}
                        {selected && (
                            <div className="space-y-3">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-lg font-black">{selected.name}</span>
                                    <span
                                        className={`text-[10px] font-black uppercase px-2 py-1 rounded border ${badge(
                                            selected.grade || selected.board,
                                        )}`}
                                    >
                                        {selected.grade || selected.board}
                                    </span>
                                </div>
                                <div
                                    className={`p-3 rounded-xl border text-sm font-bold ${badge(
                                        selected.board,
                                    )}`}
                                >
                                    {selected.board_reason}
                                    <div className="text-[11px] font-medium mt-1 opacity-90">
                                        RSI15 {selected.rsi15} · RSI60 {selected.rsi60} ·{' '}
                                        {selected.event}
                                        {selected.div_event ? ` · ${selected.div_event}` : ''}
                                        {' · '}4H {selected.h4_bias || '—'} allowed{' '}
                                        {selected.mtf_allowed || '—'}
                                        {' · '}P {selected.permission ?? '—'}
                                    </div>
                                    {selected.div_live && (
                                        <div className="text-[10px] font-bold mt-1">
                                            {selected.div_fresh ? 'FRESH ' : ''}
                                            {selected.div_type === 'BULL_DIV' ? 'Bullish' : 'Bearish'} divergence
                                            {selected.div_price_l1 != null
                                                ? ` · price ${selected.div_price_l1}→${selected.div_price_l2}`
                                                : ''}
                                            {selected.div_rsi_l1 != null
                                                ? ` · RSI ${selected.div_rsi_l1}→${selected.div_rsi_l2}`
                                                : ''}
                                            {selected.div_bars_ago != null ? ` · ${selected.div_bars_ago} bars ago` : ''}
                                        </div>
                                    )}
                                </div>
                                {ticket ? (
                                    <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 space-y-1.5 text-[11px]">
                                        <div className="text-[10px] font-black uppercase text-emerald-600">
                                            {ticket.side} · {ticket.vehicle?.style}
                                        </div>
                                        <div className="text-sm font-black font-mono">
                                            {ticket.vehicle?.structure}
                                        </div>
                                        <div className="text-zinc-500">{ticket.vehicle?.why}</div>
                                        <div>{ticket.trigger}</div>
                                        <div>Entry: {ticket.entry}</div>
                                        <div>
                                            Stop: <strong>{ticket.stop}</strong> ({ticket.stop_src})
                                        </div>
                                        <div>
                                            Target: <strong>{ticket.target1}</strong> (
                                            {ticket.target1_src})
                                        </div>
                                        <div>
                                            R:R {ticket.rr ?? '—'} · {ticket.time_stop}
                                        </div>
                                        <div className="text-zinc-500">{ticket.invalidation}</div>
                                    </div>
                                ) : (
                                    <p className="text-[11px] text-zinc-500">
                                        No ticket — {selected.board_reason}. 4H opposite or a
                                        bearish chain on an oversold print is a hard block.
                                    </p>
                                )}
                                {selected.permission_hits && selected.permission_hits.length > 0 && (
                                    <ul className="space-y-1">
                                        {selected.permission_hits.map((h, i) => (
                                            <li
                                                key={i}
                                                className="text-[10px] text-zinc-600 dark:text-zinc-400"
                                            >
                                                ✓ <strong>{h.rule}</strong> — {h.detail}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                {selected.permission_miss &&
                                    selected.permission_miss.slice(0, 4).map((m, i) => (
                                        <div key={i} className="text-[10px] text-zinc-500">
                                            · {m}
                                        </div>
                                    ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
