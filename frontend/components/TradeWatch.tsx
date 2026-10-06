'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import AuthButton from './AuthButton';
import SystemStatus from './SystemStatus';
import { getMarketHoursInfo, NON_MARKET_REFRESH_MS } from '../lib/market-hours';

interface WatchTrade {
    id: string;
    symbol: string;
    name: string;
    side: 'CE' | 'PE' | string;
    strike: number;
    status: 'OPEN' | 'CLOSED' | string;
    qty_lots: number;
    lot_size: number;
    lot_estimated?: boolean;
    entry: number;
    ltp: number;
    sl: number;
    tp: number;
    notional: number;
    pnl: number;
    pnl_pct: number;
    thesis?: string;
    invalidation?: string;
    exit_reason?: string | null;
    entered_at?: string;
    exited_at?: string | null;
    exit?: number | null;
    px_at?: string;
}

interface WatchEvent {
    ts?: string;
    kind?: string;
    message?: string;
}

interface WatchSnap {
    phase?: string;
    session_date?: string;
    entry_at?: string;
    can_enter?: boolean;
    session_open?: boolean;
    open_count?: number;
    realized_pnl?: number;
    unrealized_pnl?: number;
    skip_reason?: string | null;
    error?: string | null;
    px_at?: string;
    live?: boolean;
    trades?: WatchTrade[];
    events?: WatchEvent[];
    dump_meta?: {
        model?: string;
        candidates?: string[];
        ai_picks?: number;
        bullish?: number;
        bearish?: number;
        news_n?: number;
        chains_n?: number;
    };
}

function inr(n?: number | null, d = 2) {
    if (n == null || Number.isNaN(Number(n))) return '—';
    return Number(n).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d });
}

function pnlClass(n?: number) {
    const v = Number(n || 0);
    if (v > 0.005) return 'text-emerald-300';
    if (v < -0.005) return 'text-rose-300';
    return 'text-zinc-300';
}

function phaseLabel(p?: string) {
    if (p === 'waiting_923') return 'Waiting for 09:23 IST';
    if (p === 'picking') return 'Dumping book → picking 2 trades';
    if (p === 'open') return '2-lot desk live';
    if (p === 'closed') return 'Squared off';
    if (p === 'skipped') return 'No high-conviction print';
    if (p === 'blocked') return 'Need a harvest first';
    if (p === 'error') return 'Desk error';
    return 'Idle';
}

export default function TradeWatch() {
    const [snap, setSnap] = useState<WatchSnap | null>(null);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const d: any = await api.radar.getTradeWatch();
            setSnap(d);
            setErr(null);
        } catch (e: any) {
            setErr(e?.message || 'Watch load failed');
        }
    }, []);

    useEffect(() => {
        load();
        const market = getMarketHoursInfo();
        const interval = market.isOpen ? 4000 : NON_MARKET_REFRESH_MS;
        const id = setInterval(load, interval);
        return () => clearInterval(id);
    }, [load]);

    const run = async (force = false) => {
        setBusy(true);
        setErr(null);
        try {
            const d: any = await api.radar.runTradeWatch(force);
            setSnap(d);
        } catch (e: any) {
            setErr(e?.message || 'Pick failed');
        } finally {
            setBusy(false);
        }
    };

    const mark = async () => {
        setBusy(true);
        try {
            const d: any = await api.radar.markTradeWatch();
            setSnap(d);
        } catch (e: any) {
            setErr(e?.message || 'Mark failed');
        } finally {
            setBusy(false);
        }
    };

    const flat = async () => {
        setBusy(true);
        try {
            const d: any = await api.radar.flattenTradeWatch();
            setSnap(d);
        } catch (e: any) {
            setErr(e?.message || 'Flatten failed');
        } finally {
            setBusy(false);
        }
    };

    const trades = snap?.trades || [];
    const events = [...(snap?.events || [])].reverse();
    const meta = snap?.dump_meta || {};
    const realized = snap?.realized_pnl || 0;
    const unreal = snap?.unrealized_pnl || 0;

    return (
        <div className="h-screen bg-[#07090d] text-zinc-100 flex flex-col overflow-hidden">
            <header className="shrink-0 px-4 py-2.5 flex items-center gap-4 border-b-2 border-[#c4b5fd] bg-[#080b10]">
                <div className="min-w-[150px]">
                    <div className="text-[15px] font-black italic tracking-tighter uppercase leading-none">
                        OptionGreek<span className="text-white">.</span>
                    </div>
                    <div className="text-[9px] font-semibold uppercase tracking-[0.28em] text-zinc-500 mt-1">
                        Trade Watch
                    </div>
                </div>
                <Link
                    href="/"
                    className="px-3 py-1.5 rounded-full border-2 border-[#c4b5fd] text-[10px] font-bold uppercase tracking-wider hover:bg-violet-600/30"
                >
                    Flow Radar
                </Link>
                <div className="flex-1" />
                <div className="hidden md:flex items-center gap-3 text-[10px] font-mono text-zinc-400">
                    <span>{phaseLabel(snap?.phase)}</span>
                    <span className={pnlClass(unreal)}>U ₹{inr(unreal, 2)}</span>
                    <span className={pnlClass(realized)}>R ₹{inr(realized, 2)}</span>
                </div>
                <button
                    onClick={() => run(trades.length > 0)}
                    disabled={busy}
                    className="px-4 py-1.5 rounded-full bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-[10px] font-bold uppercase tracking-wider"
                >
                    {busy ? 'Working…' : 'Take 2 trades'}
                </button>
                <button
                    onClick={mark}
                    disabled={busy || !(snap?.open_count)}
                    className="px-3 py-1.5 rounded-full border-2 border-[#c4b5fd] text-[10px] font-bold uppercase tracking-wider disabled:opacity-40"
                >
                    Ask exit
                </button>
                <button
                    onClick={flat}
                    disabled={busy || !(snap?.open_count)}
                    className="px-3 py-1.5 rounded-full border border-rose-700 text-rose-300 text-[10px] font-bold uppercase tracking-wider disabled:opacity-40"
                >
                    Flatten
                </button>
                <AuthButton compact />
            </header>

            {err && <div className="px-4 py-1 text-[11px] text-rose-400 bg-rose-950/30">{err}</div>}
            {snap?.error && <div className="px-4 py-1 text-[11px] text-rose-400 bg-rose-950/30">{snap.error}</div>}
            {snap?.skip_reason && snap.phase === 'skipped' && (
                <div className="px-4 py-1 text-[11px] text-amber-200 bg-amber-950/30">{snap.skip_reason}</div>
            )}

            <div className="shrink-0 px-4 py-2 text-[11px] text-zinc-400 border-b border-[#c4b5fd]/40 flex flex-wrap gap-x-4 gap-y-1">
                <span>Entry clock <b className="text-zinc-200">09:23 IST</b> · 1 lot · dummy fill at chain premium</span>
                <span>
                    Dump {meta.ai_picks ?? 0} AI · {meta.bullish ?? 0} bull · {meta.bearish ?? 0} bear · {meta.news_n ?? 0} news · {meta.chains_n ?? 0} chains
                </span>
                {meta.model && <span className="text-violet-300">{meta.model}</span>}
                {snap?.session_date && <span>Session {snap.session_date}</span>}
            </div>

            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1.2fr_0.8fr]">
                <section className="min-h-0 overflow-y-auto p-4 grid grid-cols-1 md:grid-cols-2 gap-3 content-start">
                    {trades.length === 0 && (
                        <div className="md:col-span-2 h-full min-h-[240px] flex items-center justify-center text-center px-8">
                            <div>
                                <div className="text-sm font-semibold text-zinc-200">No paper trades yet</div>
                                <div className="text-[12px] text-zinc-500 mt-2 leading-relaxed max-w-md">
                                    At 09:23 the desk dumps AI-chain, unique bullish/bearish flow, scraper headlines and
                                    option chains, then buys at most two high-conviction strikes — 1 lot each, any
                                    premium on the book. P&amp;L is (exit − entry) × lot size.
                                </div>
                            </div>
                        </div>
                    )}
                    {trades.map((t) => {
                        const pnl = Number(t.pnl || 0);
                        const up = pnl >= 0;
                        const live = t.status === 'OPEN';
                        return (
                            <article
                                key={t.id}
                                className={`rounded-lg border-2 p-3 ${
                                    live
                                        ? 'border-[#c4b5fd] bg-[#0c1017]'
                                        : 'border-zinc-800 bg-[#0a0d13]'
                                }`}
                            >
                                <div className="flex items-center gap-2 mb-2">
                                    <h2 className="text-lg font-black tracking-tight">{t.name}</h2>
                                    <span className={`text-[11px] font-bold ${t.side === 'CE' ? 'text-emerald-300' : 'text-rose-300'}`}>
                                        {Math.round(t.strike)} {t.side}
                                    </span>
                                    <span className="ml-auto flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-zinc-500">
                                        {live && (
                                            <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/40">
                                                LIVE
                                            </span>
                                        )}
                                        {t.status} · 1 lot
                                    </span>
                                </div>
                                <div
                                    className={`mb-3 rounded-md border px-3 py-2 ${
                                        up ? 'border-emerald-500/30 bg-emerald-950/30' : 'border-rose-500/30 bg-rose-950/30'
                                    }`}
                                >
                                    <div className="text-[9px] uppercase tracking-widest text-zinc-500">
                                        1-lot P&amp;L
                                    </div>
                                    <div className={`text-2xl font-black tabular-nums ${pnlClass(pnl)}`}>
                                        {up ? '+' : ''}₹{inr(pnl, 2)}
                                    </div>
                                    <div className={`text-[12px] font-mono ${pnlClass(pnl)}`}>
                                        {up ? '+' : ''}{inr(t.pnl_pct, 2)}% on premium
                                        {t.px_at ? ` · ${new Date(t.px_at).toLocaleTimeString('en-IN')}` : ''}
                                    </div>
                                </div>
                                <div className="grid grid-cols-3 gap-2 text-[11px] font-mono mb-3">
                                    <div>
                                        <div className="text-[9px] uppercase text-zinc-500">Entry</div>
                                        ₹{inr(t.entry)}
                                    </div>
                                    <div>
                                        <div className="text-[9px] uppercase text-zinc-500">Last</div>
                                        ₹{inr(t.ltp)}
                                    </div>
                                    <div>
                                        <div className="text-[9px] uppercase text-zinc-500">1-lot value</div>
                                        ₹{inr(t.notional, 0)}
                                        <span className="block text-[9px] text-zinc-600">
                                            {t.lot_size} qty{t.lot_estimated ? ' est.' : ''}
                                        </span>
                                    </div>
                                    <div>
                                        <div className="text-[9px] uppercase text-zinc-500">SL</div>
                                        ₹{inr(t.sl)}
                                    </div>
                                    <div>
                                        <div className="text-[9px] uppercase text-zinc-500">TP</div>
                                        ₹{inr(t.tp)}
                                    </div>
                                    <div>
                                        <div className="text-[9px] uppercase text-zinc-500">Notional in</div>
                                        ₹{inr((t.entry || 0) * (t.lot_size || 0), 0)}
                                    </div>
                                </div>
                                <div className="text-[12px] text-zinc-300 leading-snug mb-2">
                                    <span className="text-[9px] uppercase tracking-wider text-violet-300 mr-1">Why</span>
                                    {t.thesis || '—'}
                                </div>
                                {t.invalidation && (
                                    <div className="text-[11px] text-zinc-500 mb-2">Kill: {t.invalidation}</div>
                                )}
                                {t.exit_reason && (
                                    <div className="text-[12px] text-amber-200 bg-amber-950/30 border border-amber-800/40 rounded px-2 py-1">
                                        Exit · {t.exit_reason}
                                    </div>
                                )}
                            </article>
                        );
                    })}
                </section>

                <aside className="min-h-0 overflow-y-auto border-l-2 border-[#c4b5fd] bg-[#080b10] p-3">
                    <div className="text-[10px] uppercase tracking-widest text-zinc-500 mb-2">Desk tape</div>
                    {events.length === 0 && <div className="text-zinc-600 text-sm">No fills yet.</div>}
                    <ol className="space-y-2">
                        {events.map((e, i) => (
                            <li key={`${e.ts}-${i}`} className="text-[12px] leading-snug border-b border-zinc-800/80 pb-2">
                                <div className="text-[9px] uppercase tracking-wider text-violet-300">
                                    {e.kind} · {e.ts ? new Date(e.ts).toLocaleTimeString('en-IN') : ''}
                                </div>
                                <div className="text-zinc-300">{e.message}</div>
                            </li>
                        ))}
                    </ol>
                </aside>
            </div>

            <footer className="shrink-0 border-t-2 border-[#c4b5fd] px-3 py-1 flex justify-between text-zinc-500">
                <span className="text-[9px] uppercase tracking-widest">
                    09:23 dump → 2 trades max → SL/TP + AI exit · 1 lot P&amp;L
                </span>
                <SystemStatus />
            </footer>
        </div>
    );
}
