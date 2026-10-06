'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import AuthButton from './AuthButton';
import SystemStatus from './SystemStatus';
import NiftyQuantTerminal from './NiftyQuantTerminal';
import { getMarketHoursInfo, NON_MARKET_REFRESH_MS } from '../lib/market-hours';

type Grade = 'TRADEABLE' | 'WATCH' | 'QUIET' | string;
type Bias = 'BULLISH' | 'BEARISH' | 'CONFLICTED' | 'NEUTRAL' | string;
type ScreenKey =
    | 'or_break'
    | 'early_mover'
    | 'squeeze_active'
    | 'call_buying'
    | 'put_writing'
    | 'short_covering'
    | 'vol_spike'
    | 'oi_spike'
    | 'premium_expansion'
    | 'clean_room'
    | 'support'
    | 'resistance';

interface Anomaly {
    type?: string;
    side?: string;
    strike?: number;
    label?: string;
    oi_added?: number;
    vol_x?: number;
    volume?: number;
    vor?: number;
    oi_velocity?: number;
}

interface TradeCard {
    side?: string;
    action?: string;
    instrument?: string;
    strike?: number;
    entry?: number;
    entry_label?: string;
    stop?: number;
    target?: number;
    rr?: number;
    invalidation?: string;
    thesis?: string;
}

interface ScreenFlags {
    high_oi?: boolean;
    high_vol?: boolean;
    support?: boolean;
    resistance?: boolean;
    call_buying?: boolean;
    put_writing?: boolean;
    short_covering?: boolean;
    call_writing?: boolean;
    early_mover?: boolean;
    squeeze_active?: boolean;
    vol_spike?: boolean;
    oi_spike?: boolean;
    skew_pop?: boolean;
    or_break_long?: boolean;
    or_break_short?: boolean;
    premium_expansion?: boolean;
    clean_room?: boolean;
    unique?: boolean;
    unique_score?: number;
    tags?: string[];
    oi_added?: number;
    opt_volume?: number;
    vol_x?: number;
    vor?: number;
    oi_velocity?: number;
    support_strike?: number;
    resistance_strike?: number;
}

interface BoardRow {
    symbol: string;
    name?: string;
    spot?: number;
    grade?: Grade;
    chain_bias?: Bias;
    regime?: string;
    setup_score?: number;
    oi_pcr?: number;
    call_wall?: number;
    put_wall?: number;
    top_anomaly?: Anomaly | null;
    top_anomaly_label?: string;
    pcr_label?: string;
    pcr_sentence?: string;
    skew_sentence?: string;
    buildup_sentence?: string;
    trade?: TradeCard | null;
    why_not?: string | null;
    vol_x?: number;
    vol_x_avg?: number;
    chain_volume?: number;
    vor?: number;
    oi_velocity?: number;
    ts?: string;
    volume?: {
        vs_avg?: number;
        total_volume?: number;
        expanded?: boolean;
        hottest_vol_x?: number;
        hottest?: { vol_x?: number; volume?: number };
    };
    flags?: ScreenFlags;
    hot?: boolean;
    unique_score?: number;
    session?: {
        orh?: number;
        orl?: number;
        or_break_state?: string;
        or_confirmed?: boolean;
        or_reason?: string;
        clean_room?: { clean?: boolean; distance_atr?: number; next_level?: string; reason?: string };
    };
}

interface NewsPick {
    rank?: number;
    symbol: string;
    name?: string;
    news?: string;
    news_intent?: string;
    event_type?: string;
    repeat_n?: number;
    hot?: boolean;
    action?: string;
    alignment_score?: number;
    alignment_reasons?: string[];
    conflict_note?: string;
    chain?: {
        grade?: string | null;
        chain_bias?: string;
        intent?: string;
        top_anomaly_label?: string;
        setup_score?: number;
        explode_state?: string;
        error?: string;
        trade?: { action?: string; strike?: number } | null;
    };
}

interface ChainLeg {
    ltp?: number;
    oi?: number;
    prev_oi?: number;
    volume?: number;
    iv?: number;
    signal?: string;
    signal_icon?: string;
    signal_direction?: string;
    oi_change_pct?: number;
}

interface ChainRow {
    strike_price?: number;
    call?: ChainLeg;
    put?: ChainLeg;
}

interface TapeItem {
    symbol?: string;
    label?: string;
    ltp?: number;
    ch?: number;
    chp?: number;
    ok?: boolean;
    as_of?: string;
}

interface SymbolDetail {
    success?: boolean;
    report?: {
        grade?: Grade;
        chain_bias?: Bias;
        why_not?: string | null;
        structure?: Record<string, any>;
        futures?: Record<string, any>;
        anomalies?: Anomaly[];
        trade?: TradeCard | null;
        spot?: number;
        atm?: number;
        dte?: number;
        setup_score?: number;
        flags?: ScreenFlags;
        volume?: Record<string, any>;
    };
    chain?: ChainRow[];
    spot_price?: number;
    pcr?: number;
    structure?: Record<string, any>;
    futures?: Record<string, any>;
    volume?: Record<string, any>;
    flags?: ScreenFlags;
}

const SCREEN_FILTERS: { id: ScreenKey; label: string; tip: string }[] = [
    { id: 'or_break', label: 'OR Break', tip: '15m close through first candle + OI add + premium up + no wall within 0.45 ATR' },
    { id: 'early_mover', label: 'Footstep', tip: 'Early institutional footstep: VOR + OI velocity near ATM' },
    { id: 'squeeze_active', label: 'Squeeze', tip: 'Futures covering + fresh call buying — not a fade' },
    { id: 'call_buying', label: 'Call buy', tip: 'Fresh CE buying, premium expanding, not exhaustion' },
    { id: 'put_writing', label: 'Put write', tip: 'PE OI up + premium down at a live put wall' },
    { id: 'short_covering', label: 'Cover', tip: 'Short covering that is not a squeeze' },
    { id: 'vol_spike', label: 'Vol', tip: 'Chain volume ≥ 2× own 5-day average' },
    { id: 'oi_spike', label: 'OI', tip: 'Session ΔOI above this name’s liquidity floor' },
    { id: 'premium_expansion', label: 'Premium', tip: 'Option premium expanding with size, not a ₹2 tick' },
    { id: 'clean_room', label: 'Clean room', tip: 'Next wall/PDH/Cam level ≥ 0.45 ATR away' },
    { id: 'support', label: 'At put wall', tip: 'Live OI being added at the put wall now' },
    { id: 'resistance', label: 'At call wall', tip: 'Live OI being added at the call wall now' },
];

function fmt(n?: number | null, d = 2) {
    if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
    return Number(n).toLocaleString('en-IN', { maximumFractionDigits: d });
}

function scoreTone(score?: number) {
    const s = score || 0;
    if (s >= 70) return 'text-emerald-300';
    if (s >= 50) return 'text-amber-300';
    return 'text-zinc-300';
}

function freshnessBadge(ts?: string, dataMode?: string) {
    if (dataMode === 'last_close') {
        return (
            <span className="px-1 py-0.2 rounded text-[8px] font-bold bg-zinc-800 text-zinc-300 border border-zinc-600">
                LAST CLOSE
            </span>
        );
    }
    if (!ts) return null;
    try {
        const diffSec = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000));
        if (diffSec < 90) {
            return (
                <span className="px-1 py-0.2 rounded text-[8px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                    LIVE
                </span>
            );
        }
        if (diffSec < 420) {
            return (
                <span className="px-1 py-0.2 rounded text-[8px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">
                    {Math.round(diffSec / 60)}m
                </span>
            );
        }
        return (
            <span className="px-1 py-0.2 rounded text-[8px] font-bold bg-zinc-800 text-zinc-400 border border-zinc-700">
                {Math.round(diffSec / 60)}m
            </span>
        );
    } catch {
        return null;
    }
}

function volOf(row: BoardRow): number | null {
    const v = row.flags?.opt_volume ?? row.chain_volume ?? row.volume?.total_volume;
    return v != null && Number(v) > 0 ? Number(v) : null;
}

function fmtVol(n?: number | null) {
    if (n == null || Number.isNaN(Number(n)) || n <= 0) return '—';
    const v = Number(n);
    if (v >= 100000) return `${(v / 100000).toFixed(v >= 1000000 ? 2 : 1)}L`;
    if (v >= 1000) return `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k`;
    return String(Math.round(v));
}

function oiOf(row: BoardRow): number | null {
    const v = flagsOf(row).oi_added ?? row.top_anomaly?.oi_added;
    return v != null ? Number(v) : null;
}

function flagsOf(row: BoardRow): ScreenFlags {
    const stored = row.flags || {};
    const tags = Array.isArray(stored.tags) ? stored.tags : [];
    const has = (t: string) => tags.includes(t);
    const oiAdd = stored.oi_added ?? row.top_anomaly?.oi_added;
    const optVol = stored.opt_volume ?? row.chain_volume ?? row.volume?.total_volume;
    const volX = stored.vol_x ?? row.vol_x ?? 0;
    const vor = stored.vor ?? row.vor ?? row.top_anomaly?.vor ?? 0;
    const orLong = stored.or_break_long === true || has('OR_BREAK_LONG');
    const orShort = stored.or_break_short === true || has('OR_BREAK_SHORT');

    return {
        high_oi: stored.high_oi === true,
        high_vol: stored.high_vol === true,
        support: stored.support === true || has('SUPPORT'),
        resistance: stored.resistance === true || has('RESISTANCE'),
        call_buying: stored.call_buying === true || has('CALL_BUYING'),
        put_writing: stored.put_writing === true || has('PUT_FLOOR'),
        short_covering: stored.short_covering === true || has('SHORT_COVER'),
        early_mover: stored.early_mover === true || has('EARLY_MOVER') || has('FOOTSTEP_EARLY'),
        squeeze_active: stored.squeeze_active === true || has('SQUEEZE_ACTIVE'),
        vol_spike: stored.vol_spike === true || has('VOL_SURGE'),
        oi_spike: stored.oi_spike === true || has('OI_SURGE'),
        skew_pop: stored.skew_pop === true || has('SKEW_POP'),
        or_break_long: orLong,
        or_break_short: orShort,
        premium_expansion: stored.premium_expansion === true || has('PREMIUM_EXPANSION'),
        clean_room: stored.clean_room === true || has('CLEAN_ROOM'),
        unique: stored.unique === true || has('UNIQUE'),
        unique_score: stored.unique_score,
        tags,
        oi_added: oiAdd,
        opt_volume: optVol,
        vol_x: volX,
        vor,
        support_strike: stored.support_strike,
        resistance_strike: stored.resistance_strike,
    };
}

function flagValue(f: ScreenFlags, key: ScreenKey): boolean {
    if (key === 'or_break') return Boolean(f.or_break_long || f.or_break_short);
    return f[key] === true;
}

function matchesFilters(row: BoardRow, keys: ScreenKey[]): boolean {
    if (!keys.length) return false;
    const f = flagsOf(row);
    return keys.every((k) => flagValue(f, k));
}

function orLine(row: BoardRow): string {
    const sess = row.session || {};
    const f = flagsOf(row);
    if (!(f.or_break_long || f.or_break_short)) return '';
    const orh = sess.orh;
    const room = sess.clean_room?.distance_atr;
    const bits = [
        orh ? `ORH ${fmt(orh, 1)}` : '',
        room != null ? `room ${Number(room).toFixed(1)} ATR` : '',
    ].filter(Boolean);
    return bits.length ? `· ${bits.join(' · ')}` : '';
}

function getTopTwoTags(row: BoardRow, hotSet?: Set<string>): string[] {
    const f = flagsOf(row);
    const candidateTags: { tag: string; priority: number }[] = [];

    if (hotSet?.has(row.symbol)) {
        candidateTags.push({ tag: '📰 AI HOT', priority: 1 });
    }
    if (f.or_break_long || f.or_break_short) {
        candidateTags.push({ tag: f.or_break_short ? 'OR BREAK ▼' : 'OR BREAK ▲', priority: 2 });
    }
    if (f.squeeze_active) {
        candidateTags.push({ tag: 'SQUEEZE', priority: 3 });
    }
    if (f.early_mover) {
        candidateTags.push({ tag: 'FOOTSTEP', priority: 4 });
    }
    if (f.call_buying) {
        candidateTags.push({ tag: 'CALL BUY', priority: 5 });
    }
    if (f.put_writing) {
        candidateTags.push({ tag: 'PUT WRITE', priority: 6 });
    }
    if (f.short_covering) {
        candidateTags.push({ tag: 'COVER', priority: 7 });
    }
    if (f.premium_expansion) {
        candidateTags.push({ tag: 'PREMIUM', priority: 8 });
    }
    if (f.clean_room) {
        candidateTags.push({ tag: 'CLEAN', priority: 9 });
    }
    if (f.vol_spike) {
        candidateTags.push({ tag: 'VOL', priority: 10 });
    }
    if (f.oi_spike) {
        candidateTags.push({ tag: 'OI', priority: 11 });
    }
    if (f.unique) {
        candidateTags.push({ tag: 'UNIQUE', priority: 12 });
    }

    candidateTags.sort((a, b) => a.priority - b.priority);
    const top2 = candidateTags.slice(0, 2).map((c) => c.tag);

    if (top2.length === 0) {
        top2.push(row.grade === 'TRADEABLE' ? '🎯 TRADE' : 'WATCH');
    }
    return top2;
}

function formatSignalLabel(sig?: string, icon?: string): { text: string; icon: string } {
    if (!sig || sig.includes('Neutral') || sig.includes('Inconclusive')) {
        return { text: 'Neutral', icon: '⚪' };
    }
    if (sig.includes('Call Buying')) return { text: 'Call Buy', icon: '🟢' };
    if (sig.includes('Put Writing')) return { text: 'Put Floor', icon: '🟢' };
    if (sig.includes('Call Writing')) return { text: 'Call Write', icon: '🔴' };
    if (sig.includes('Put Buying')) return { text: 'Put Buy', icon: '🔴' };
    if (sig.includes('Short Covering')) return { text: 'Short Cover', icon: '🟡' };
    if (sig.includes('Long Unwinding')) return { text: 'Long Unwind', icon: '🟧' };
    return { text: sig.split(' ')[0] || sig, icon: icon || '⚪' };
}

function rankRows(rows: BoardRow[]) {
    return [...rows].sort((a, b) => {
        const ga = a.grade === 'TRADEABLE' ? 0 : 1;
        const gb = b.grade === 'TRADEABLE' ? 0 : 1;
        if (ga !== gb) return ga - gb;
        return (b.setup_score || 0) - (a.setup_score || 0);
    });
}

export default function OptionFlowRadar() {
    const [board, setBoard] = useState<any>(null);
    const [scanLoading, setScanLoading] = useState(false);
    const [scanError, setScanError] = useState<string | null>(null);
    const [selected, setSelected] = useState<string | null>(null);
    const [detail, setDetail] = useState<SymbolDetail | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [onlyTradeable, setOnlyTradeable] = useState(false);
    const [tape, setTape] = useState<TapeItem[]>([]);
    const [scanTypes, setScanTypes] = useState<ScreenKey[]>([]);
    const [aiPicks, setAiPicks] = useState<NewsPick[]>([]);
    const [aiPhase, setAiPhase] = useState<string | null>(null);
    const [aiError, setAiError] = useState<string | null>(null);
    const [aiLoading, setAiLoading] = useState(false);
    const [showNiftyModal, setShowNiftyModal] = useState(false);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const aiPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const scanRun = useRef(0);
    const aiRun = useRef(0);

    const commit = useCallback((snap: any) => {
        if (!snap) return;
        setBoard((prev: any) => {
            const next = { ...prev, ...snap };
            next.tradeable = snap.tradeable || snap.flagged || prev?.tradeable || [];
            next.watch = snap.watch || prev?.watch || [];
            next.flow = snap.flow || snap.all_hits || prev?.flow;
            if (snap.screen) next.screen = snap.screen;
            if (snap.bullish) next.bullish = snap.bullish;
            if (snap.bearish) next.bearish = snap.bearish;
            return next;
        });
    }, []);

    const loadLast = useCallback(async () => {
        try {
            const last: any = await api.radar.getLastScan();
            commit(last);
        } catch (e: any) {
            setScanError(e?.message || 'Board load failed');
        }
    }, [commit]);

    const loadTape = useCallback(async () => {
        try {
            const res: any = await api.market.getIndices();
            const raw = Array.isArray(res?.tape) && res.tape.length
                ? res.tape
                : Array.isArray(res?.data)
                  ? res.data
                  : [];
            const rows: TapeItem[] = raw.map((r: any) => {
                const v = r?.v && typeof r.v === 'object' ? r.v : {};
                const ltp = r?.ltp ?? v.lp ?? v.ltp ?? r?.lp;
                return {
                    symbol: r?.symbol || r?.n,
                    label: r?.label,
                    ltp: ltp != null ? Number(ltp) : undefined,
                    ch: r?.ch ?? v.ch,
                    chp: r?.chp ?? v.chp,
                    ok: Boolean(ltp),
                    as_of: r?.as_of,
                };
            });
            if (rows.some((r) => r.ok && r.ltp)) setTape(rows);
        } catch {
            /* keep last */
        }
    }, []);

    const stopPoll = () => {
        if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    };

    const stopAiPoll = () => {
        if (aiPollRef.current) {
            clearInterval(aiPollRef.current);
            aiPollRef.current = null;
        }
    };

    const applyAiSnap = (snap: any) => {
        if (Array.isArray(snap?.picks)) setAiPicks(snap.picks);
        if (snap?.phase) setAiPhase(snap.phase);
        if (snap?.error_message) setAiError(snap.error_message);
        const done = ['completed', 'failed', 'cancelled', 'interrupted'].includes(snap?.status);
        if (done) {
            setAiLoading(false);
            if (snap.status === 'failed') setAiError(snap.error_message || 'AI + Chain failed');
            else setAiError(null);
        }
    };

    const runAiChain = useCallback(async () => {
        const runId = ++aiRun.current;
        setAiLoading(true);
        setAiError(null);
        setAiPhase('queued');
        try {
            const started: any = await api.radar.startAiChain();
            const jid = started?.job_id;
            if (!jid) {
                setAiLoading(false);
                setAiError('Could not start AI + Chain');
                return;
            }
            stopAiPoll();
            const tick = async () => {
                if (runId !== aiRun.current) return;
                try {
                    const snap: any = await api.radar.getAiChainJob(jid);
                    if (runId !== aiRun.current) return;
                    applyAiSnap(snap);
                    const done = ['completed', 'failed', 'cancelled', 'interrupted'].includes(snap.status);
                    if (done) stopAiPoll();
                } catch (e: any) {
                    stopAiPoll();
                    setAiLoading(false);
                    setAiError(e?.message || 'AI job poll failed');
                }
            };
            await tick();
            aiPollRef.current = setInterval(tick, 1500);
        } catch (e: any) {
            setAiLoading(false);
            setAiError(e?.message || 'Could not start AI + Chain');
        }
    }, []);

    const runScan = useCallback(async () => {
        const runId = ++scanRun.current;
        setScanLoading(true);
        setScanError(null);
        try {
            const started: any = await api.radar.startScan(0, undefined, 14);
            const jid = started?.job_id;
            if (!jid) {
                await loadLast();
                setScanLoading(false);
                return;
            }
            stopPoll();
            const tick = async () => {
                if (runId !== scanRun.current) return;
                try {
                    const snap: any = await api.radar.getScanJob(jid);
                    if (runId !== scanRun.current) return;
                    commit(snap);
                    const done =
                        ['completed', 'failed', 'cancelled', 'interrupted'].includes(snap.status) ||
                        snap.scan_running === false;
                    if (done) {
                        stopPoll();
                        setScanLoading(false);
                        if (snap.status === 'failed') setScanError(snap.error_message || 'Harvest failed');
                    }
                } catch (e: any) {
                    stopPoll();
                    setScanLoading(false);
                    setScanError(e?.message || 'Job poll failed');
                }
            };
            await tick();
            pollRef.current = setInterval(tick, 1500);
        } catch (e: any) {
            setScanLoading(false);
            setScanError(e?.message || 'Could not start harvest');
        }
    }, [commit, loadLast]);

    useEffect(() => {
        loadLast();
        loadTape();
        api.radar
            .getAiChainLast()
            .then((d: any) => {
                if (Array.isArray(d?.picks) && d.picks.length) {
                    setAiPicks(d.picks);
                    setAiPhase('done');
                }
            })
            .catch(() => {});
        const market = getMarketHoursInfo();
        const lastInterval = market.isOpen ? 20000 : NON_MARKET_REFRESH_MS;
        const tapeInterval = market.isOpen ? 12000 : NON_MARKET_REFRESH_MS;

        const a = setInterval(loadLast, lastInterval);
        const b = setInterval(loadTape, tapeInterval);
        return () => {
            clearInterval(a);
            clearInterval(b);
            stopPoll();
            stopAiPoll();
        };
    }, [loadLast, loadTape]);

    useEffect(() => {
        if (!selected) return;
        let cancelled = false;
        setDetailLoading(true);
        api.radar
            .getSymbolFlow(selected, 14)
            .then((d) => {
                if (!cancelled) setDetail(d as SymbolDetail);
            })
            .catch(() => {
                if (!cancelled) setDetail(null);
            })
            .finally(() => {
                if (!cancelled) setDetailLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [selected, board?.pass_id, board?.ok_chain]);

    const tradeable: BoardRow[] = board?.tradeable || board?.flagged || [];
    const watch: BoardRow[] = board?.watch || [];

    const pool = useMemo(() => {
        const all = [...tradeable, ...watch, ...(board?.flow || [])];
        const seen = new Set<string>();
        return all.filter((r) => {
            if (!r?.symbol || seen.has(r.symbol)) return false;
            seen.add(r.symbol);
            return true;
        });
    }, [tradeable, watch, board?.flow]);

    const boardRows = useMemo(() => rankRows(pool), [pool]);

    const withTradeable = (rows: BoardRow[]) =>
        onlyTradeable ? rows.filter((r) => r.grade === 'TRADEABLE') : rows;

    const bullish = useMemo(() => {
        const src: BoardRow[] =
            Array.isArray(board?.bullish) && board.bullish.length
                ? board.bullish
                : boardRows.filter((r) => r.chain_bias === 'BULLISH');
        return rankRows(withTradeable(src));
    }, [board?.bullish, boardRows, onlyTradeable]);

    const bearish = useMemo(() => {
        const src: BoardRow[] =
            Array.isArray(board?.bearish) && board.bearish.length
                ? board.bearish
                : boardRows.filter((r) => r.chain_bias === 'BEARISH');
        return rankRows(withTradeable(src));
    }, [board?.bearish, boardRows, onlyTradeable]);

    const screenPool = useMemo(() => {
        const raw = board?.screen;
        if (Array.isArray(raw) && raw.length) return raw as BoardRow[];
        return boardRows;
    }, [board?.screen, boardRows]);

    const screened = useMemo(() => {
        if (!scanTypes.length) {
            const uniqueRows = screenPool.filter((row) => {
                const f = flagsOf(row);
                return row.grade === 'TRADEABLE' && f.unique;
            });
            return rankRows(uniqueRows).slice(0, 12);
        }
        return rankRows(screenPool.filter((row) => matchesFilters(row, scanTypes))).slice(0, 12);
    }, [screenPool, scanTypes]);

    useEffect(() => {
        if (selected) return;
        const first = screened[0];
        if (first?.symbol) setSelected(first.symbol);
    }, [selected, screened]);

    const harvest = board?.harvest || {};
    const attempted = board?.attempted || board?.scanned || harvest.scanned || 0;
    const total = board?.universe_requested || board?.total || harvest.total || 0;
    const pct = board?.completion_pct ?? (total ? Math.round((attempted / total) * 1000) / 10 : 0);
    const running = Boolean(board?.scan_running || scanLoading);
    const marketHours = Boolean(board?.market_hours);
    const dataMode: string = board?.data_mode || (marketHours ? 'live' : 'last_close');
    const hasAnyBoardData = Boolean(
        board && (
            (board.tradeable?.length ?? 0) ||
            (board.watch?.length ?? 0) ||
            (board.bullish?.length ?? 0) ||
            (board.bearish?.length ?? 0) ||
            (board.screen?.length ?? 0) ||
            (board.flow?.length ?? 0)
        )
    );

    const tapeMap = useMemo(() => {
        const out: Record<string, TapeItem> = {};
        for (const row of tape) {
            const n = `${row.label || ''} ${row.symbol || ''}`.toUpperCase();
            if (n.includes('VIX') || n.includes('INDIAVIX')) out.vix = row;
            else if (n.includes('BANK')) out.bank = row;
            else if (n.includes('NIFTY50') || row.label === 'NIFTY' || n.endsWith('NIFTY ')) out.nifty = row;
            else if (n.includes('NIFTY') && !out.nifty) out.nifty = row;
        }
        return out;
    }, [tape]);

    const hotSet = useMemo(() => new Set(aiPicks.map((p) => p.symbol).filter(Boolean)), [aiPicks]);

    const recipe = scanTypes.length
        ? scanTypes.map((k) => SCREEN_FILTERS.find((f) => f.id === k)?.label).join(' + ')
        : 'all setups';

    const toggleType = (id: ScreenKey) => {
        setScanTypes((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
    };

    const report = detail?.report || (detail as any) || {};
    const structure = report?.structure || (detail as any)?.structure || {
        oi_pcr: detail?.pcr ?? (detail as any)?.oi_pcr,
        put_wall: (detail as any)?.put_wall,
        call_wall: (detail as any)?.call_wall,
        gamma_wall: (detail as any)?.gamma_wall,
        max_pain: (detail as any)?.max_pain,
        iv_skew: (detail as any)?.iv_skew,
    };
    const futures = report?.futures || (detail as any)?.futures || {};
    const volume = report?.volume || (detail as any)?.volume || {};
    const chain = detail?.chain || [];
    const selFlags = report?.flags || (detail as any)?.flags || {};

    return (
        <div className="h-screen bg-[#07090d] text-zinc-100 flex flex-col overflow-hidden">
            <header className="shrink-0 px-4 py-2.5 flex items-center gap-4 border-b-2 border-[#c4b5fd] bg-[#080b10]">
                <div className="min-w-[150px]">
                    <div className="text-[15px] font-black italic tracking-tighter uppercase leading-none">
                        OptionGreek<span className="text-white">.</span>
                    </div>
                    <div className="text-[9px] font-semibold uppercase tracking-[0.28em] text-zinc-500 mt-1">
                        Flow Radar
                    </div>
                </div>
                <a
                    href="/watch"
                    className="px-3 py-1.5 rounded-full border-2 border-[#c4b5fd] text-[10px] font-bold uppercase tracking-wider hover:bg-violet-600/30"
                >
                    Watch
                </a>

                <button
                    onClick={() => setShowNiftyModal(true)}
                    className="px-3 py-1.5 rounded-full border-2 border-[#c4b5fd] bg-violet-600/30 text-[10px] font-black uppercase tracking-wider text-violet-200 hover:bg-violet-500 hover:text-white transition-all shadow flex items-center gap-1.5 cursor-pointer"
                    title="Open Nifty 50 Quant Analytics, Greeks & Breakout Simulator"
                >
                    <span>⚡</span>
                    <span>NIFTY 50 QUANT</span>
                </button>

                <div className="flex items-stretch rounded-md border-2 border-[#c4b5fd] overflow-hidden">
                    <TapeChip
                        label="NIFTY"
                        row={tapeMap.nifty}
                        lastClose={dataMode === 'last_close'}
                        onClick={() => setShowNiftyModal(true)}
                    />
                    <TapeChip label="BANK" row={tapeMap.bank} lastClose={dataMode === 'last_close'} />
                    <TapeChip label="VIX" row={tapeMap.vix} lastClose={dataMode === 'last_close'} />
                </div>

                <div className="flex-1" />

                <div className="hidden lg:flex items-center gap-3 text-[10px] font-mono text-zinc-400">
                    <span className={running ? 'text-violet-300' : ''}>
                        BOOK {attempted}/{total || '—'} {fmt(pct, 0)}%
                    </span>
                    {dataMode === 'last_close' && (
                        <span className="text-amber-300">
                            AS OF {board?.session_date || 'last session'}
                        </span>
                    )}
                    <span>T {tradeable.length}</span>
                    <span className="text-emerald-400">B {bullish.length}</span>
                    <span className="text-rose-400">S {bearish.length}</span>
                </div>

                <label className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-400">
                    <input
                        type="checkbox"
                        checked={onlyTradeable}
                        onChange={(e) => setOnlyTradeable(e.target.checked)}
                        className="accent-violet-500"
                    />
                    Tradeable
                </label>
                <button
                    onClick={runScan}
                    disabled={running}
                    className="px-4 py-1.5 rounded-full bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-[10px] font-bold uppercase tracking-wider"
                >
                    {running ? 'Harvesting' : 'Scan'}
                </button>
                <button
                    onClick={runAiChain}
                    disabled={aiLoading}
                    className="px-4 py-1.5 rounded-full border-2 border-[#c4b5fd] bg-[#12101c] hover:bg-violet-600/30 disabled:opacity-40 text-[10px] font-bold uppercase tracking-wider"
                >
                    {aiLoading ? aiPhase || 'AI…' : 'AI + Chain'}
                </button>
                <AuthButton compact />
            </header>

            {running && (
                <div className="h-0.5 bg-zinc-900">
                    <div className="h-0.5 bg-violet-500" style={{ width: `${Math.min(pct, 100)}%` }} />
                </div>
            )}
            {dataMode === 'last_close' && hasAnyBoardData && (
                <div className="shrink-0 px-4 py-1 text-[11px] text-amber-200 bg-amber-950/40 border-b border-amber-900/50">
                    Showing last session{board?.session_date ? ` · ${board.session_date}` : ''}
                    {board?.next_open ? ` · ${board.next_open}` : ''}
                </div>
            )}
            {scanError && (
                <div className="px-4 py-1 text-[11px] text-rose-400 bg-rose-950/30">{scanError}</div>
            )}
            {aiError && (
                <div className="px-4 py-1 text-[11px] text-rose-400 bg-rose-950/30">{aiError}</div>
            )}
            {(aiPicks.length > 0 || aiLoading) && (
                <div className="shrink-0 border-b-2 border-[#c4b5fd] bg-[#080b10] px-3 py-2 flex gap-2 overflow-x-auto">
                    {aiLoading && aiPicks.length === 0 && (
                        <div className="text-[11px] text-violet-300 uppercase tracking-wider py-2">
                            {aiPhase === 'scraping'
                                ? 'Scraping Whalesbook…'
                                : aiPhase === 'ranking'
                                  ? 'Ranking news…'
                                  : aiPhase === 'analysing'
                                    ? 'Analysing chains…'
                                    : 'AI + Chain running…'}
                        </div>
                    )}
                    {aiPicks.map((p) => {
                        const score = p.alignment_score;
                        const scoreColor =
                            score != null && score >= 70
                                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                                : score != null && score >= 50
                                ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                                : 'bg-zinc-800 text-zinc-400 border-zinc-700';

                        return (
                            <button
                                key={p.symbol}
                                onClick={() => setSelected(p.symbol)}
                                className={`min-w-[210px] max-w-[260px] text-left rounded-md border px-2.5 py-1.5 transition-all ${
                                    selected === p.symbol
                                        ? 'border-[#c4b5fd] bg-violet-500/20 shadow-sm'
                                        : 'border-violet-700/60 hover:border-[#c4b5fd] bg-[#0c1017]'
                                }`}
                            >
                                <div className="flex items-center gap-1.5">
                                    <span className="font-mono text-[10px] text-zinc-500">#{p.rank}</span>
                                    <span className="text-[12px] font-bold truncate">{p.name}</span>
                                    {score != null && (
                                        <span
                                            title="News ↔ Chain Alignment Score (0-100)"
                                            className={`ml-auto text-[9px] font-black px-1.5 py-0.2 rounded border ${scoreColor}`}
                                        >
                                            {score}/100
                                        </span>
                                    )}
                                </div>
                                <div className="text-[10px] text-zinc-400 leading-snug line-clamp-2 mt-0.5">
                                    {p.news || '—'}
                                </div>
                                <div className="flex items-center gap-1 mt-1 text-[9px] font-mono text-zinc-400">
                                    <span className={p.news_intent === 'BULLISH' ? 'text-emerald-400 font-bold' : p.news_intent === 'BEARISH' ? 'text-rose-400 font-bold' : 'text-zinc-400'}>
                                        📰 {p.news_intent || 'NEWS'}
                                    </span>
                                    <span>→</span>
                                    <span className={p.chain?.chain_bias === 'BULLISH' ? 'text-emerald-400 font-bold' : p.chain?.chain_bias === 'BEARISH' ? 'text-rose-400 font-bold' : 'text-zinc-400'}>
                                        ⛓️ {p.chain?.chain_bias || 'NO CHAIN'}
                                    </span>
                                    <span className="ml-auto text-violet-300 font-bold">
                                        {p.action || 'WATCH'}
                                    </span>
                                </div>
                                {p.conflict_note && (
                                    <div className="mt-1 text-[8px] text-amber-300 bg-amber-950/40 px-1 py-0.5 rounded border border-amber-800/50 truncate" title={p.conflict_note}>
                                        ⚠️ {p.conflict_note}
                                    </div>
                                )}
                            </button>
                        );
                    })}
                </div>
            )}

            {/* 3-column body */}
            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[minmax(260px,1fr)_minmax(340px,1.15fr)_minmax(260px,1fr)]">
                <SetupTable
                    title="Bullish setups"
                    tone="bull"
                    count={bullish.length}
                    rows={bullish}
                    selected={selected}
                    onSelect={setSelected}
                    hotSet={hotSet}
                    dataMode={dataMode}
                />

                <section className="min-h-0 flex flex-col border-x-2 border-[#c4b5fd] bg-[#080b10]">
                    <div className="shrink-0 py-2 px-3 flex items-center gap-1.5 border-b-2 border-[#c4b5fd] overflow-x-auto whitespace-nowrap bg-[#0b0e14]">
                        {SCREEN_FILTERS.map((f) => {
                            const on = scanTypes.includes(f.id);
                            return (
                                <button
                                    key={f.id}
                                    title={f.tip}
                                    onClick={() => toggleType(f.id)}
                                    className={`shrink-0 px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all border ${
                                        on
                                            ? 'border-[#c4b5fd] bg-violet-600/40 text-violet-100 shadow-sm'
                                            : 'border-violet-800/60 bg-[#121520] text-zinc-400 hover:border-[#c4b5fd] hover:text-zinc-200'
                                    }`}
                                >
                                    {f.label}
                                </button>
                            );
                        })}
                        {scanTypes.length > 0 && (
                            <button
                                onClick={() => setScanTypes([])}
                                className="shrink-0 ml-1 text-[10px] uppercase tracking-wider text-zinc-400 hover:text-violet-200 underline"
                            >
                                Clear
                            </button>
                        )}
                        <span className="shrink-0 ml-auto font-mono text-[10px] text-violet-200 pl-2">
                            {scanTypes.length ? `${screened.length} matches` : `${screened.length} unique`}
                        </span>
                    </div>
                    <div className="grid grid-cols-[40px_1fr_72px_56px] px-3 py-1 text-[9px] uppercase tracking-wider text-zinc-400 border-b-2 border-[#c4b5fd]">
                        <span>Scr</span>
                        <span>Name</span>
                        <span className="text-right">ΔOI</span>
                        <span className="text-right">Vol</span>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto">
                        {screened.length === 0 ? (
                            <div className="h-full flex items-center justify-center text-zinc-500 text-sm px-4 text-center leading-relaxed">
                                <div>
                                    <div className="font-semibold text-zinc-300">
                                        {hasAnyBoardData
                                            ? scanTypes.length
                                                ? `No names matching ${recipe}`
                                                : 'No unique tradeable names'
                                            : 'No last-session board yet'}
                                    </div>
                                    <div className="mt-1 text-[12px] text-zinc-500">
                                        {hasAnyBoardData
                                            ? 'AND filters — add fewer chips, or wait for an OR break with OI + premium + clean room.'
                                            : dataMode === 'last_close'
                                              ? 'Last harvest is not pinned yet. Scan once after auth to freeze last close.'
                                              : 'Waiting for the first harvest of the session.'}
                                    </div>
                                </div>
                            </div>
                        ) : (
                            screened.map((row) => {
                                const topTags = getTopTwoTags(row, hotSet);
                                return (
                                    <button
                                        key={row.symbol}
                                        onClick={() => setSelected(row.symbol)}
                                        className={`w-full grid grid-cols-[40px_1fr_72px_56px] items-center px-3 py-1.5 text-left border-b border-[#c4b5fd]/40 ${
                                            selected === row.symbol ? 'bg-violet-500/20' : 'hover:bg-white/[0.03]'
                                        }`}
                                    >
                                        <span className={`font-mono text-[12px] font-bold ${scoreTone(row.setup_score)}`}>
                                            {row.setup_score ?? '—'}
                                        </span>
                                        {(() => {
                                            const vorVal = row.vor ?? row.flags?.vor ?? row.top_anomaly?.vor;
                                            return (
                                                <span className="min-w-0">
                                                    <span className="flex items-center gap-1 text-[12px] font-semibold truncate">
                                                        <span className="truncate">{row.name}</span>
                                                        {freshnessBadge(row.ts, dataMode)}
                                                    </span>
                                                    <span className="block text-[10px] text-violet-300/90 font-mono truncate">
                                                        {topTags.join(' · ')} {orLine(row)} {vorVal && vorVal >= 0.4 ? `· VOR ${Number(vorVal).toFixed(1)}×` : ''}
                                                    </span>
                                                </span>
                                            );
                                        })()}
                                        <span className="text-right font-mono text-[11px]">{fmt(oiOf(row), 0)}</span>
                                        <span className="text-right font-mono text-[11px] text-zinc-400">
                                            {fmtVol(volOf(row))}
                                        </span>
                                    </button>
                                );
                            })
                        )}
                    </div>
                </section>

                <SetupTable
                    title="Bearish setups"
                    tone="bear"
                    count={bearish.length}
                    rows={bearish}
                    selected={selected}
                    onSelect={setSelected}
                    hotSet={hotSet}
                    dataMode={dataMode}
                />
            </div>

            {/* Bottom: selected + chain */}
            <div className="shrink-0 border-t-2 border-[#c4b5fd] grid grid-cols-1 lg:grid-cols-[minmax(260px,0.85fr)_minmax(560px,1.5fr)] h-[32vh] min-h-[200px]">
                <div className="p-2.5 overflow-hidden border-r-2 border-[#c4b5fd]">
                    {selected ? (
                        <>
                            <div className="flex items-center gap-2 mb-2">
                                <h2 className="text-sm font-black tracking-tight">
                                    {selected.split(':').pop()?.replace('-EQ', '').replace('-INDEX', '')}
                                </h2>
                                {detailLoading && <span className="text-[10px] text-zinc-500">…</span>}
                                <Tag on={report?.grade === 'WATCH' || report?.grade === 'TRADEABLE'}>
                                    {report?.grade || '—'}
                                </Tag>
                                <Tag on={report?.chain_bias === 'BEARISH'} danger={report?.chain_bias === 'BEARISH'} ok={report?.chain_bias === 'BULLISH'}>
                                    {report?.chain_bias || '—'}
                                </Tag>
                                <Tag>{structure.regime || '—'}</Tag>
                            </div>
                            <div className="grid grid-cols-5 gap-2 mb-2">
                                <Mini k="PCR" v={fmt(structure.oi_pcr, 2)} />
                                <Mini k="Put wall" v={fmt(structure.put_wall, 0)} />
                                <Mini k="Call wall" v={fmt(structure.call_wall, 0)} />
                                <Mini k="Futures" v={futures.state || '—'} />
                                <Mini k="Chain vol" v={fmt(volume.total_volume, 0)} />
                                <Mini k="γ wall" v={fmt(structure.gamma_wall, 0)} />
                                <Mini k="Max pain" v={fmt(structure.max_pain, 0)} />
                                <Mini k="IV skew" v={fmt(structure.iv_skew, 1)} />
                                <Mini k="VOR Mult" v={report?.top_anomaly?.vor || selFlags?.vor ? `${Number(report?.top_anomaly?.vor || selFlags?.vor).toFixed(2)}×` : '—'} />
                                <Mini k="OI Vel" v={report?.top_anomaly?.oi_velocity || selFlags?.oi_velocity ? `${fmt(report?.top_anomaly?.oi_velocity || selFlags?.oi_velocity, 0)}/m` : '—'} />
                                <Mini k="ORH" v={fmt((report?.session || (detail as any)?.session || {}).orh, 1)} />
                                <Mini k="ORL" v={fmt((report?.session || (detail as any)?.session || {}).orl, 1)} />
                            </div>
                            <div className="flex gap-1.5 mb-2 text-[9px] font-bold uppercase tracking-wider overflow-x-auto">
                                {SCREEN_FILTERS.map((f) => {
                                    const on = flagValue(flagsOf({ symbol: selected || '', flags: selFlags }), f.id);
                                    return (
                                    <span
                                        key={f.id}
                                        title={f.tip}
                                        className={`px-1.5 py-0.5 rounded border shrink-0 ${
                                            on
                                                ? 'border-[#c4b5fd] text-violet-100'
                                                : 'border-[#6d28d9] text-zinc-600'
                                        }`}
                                    >
                                        {f.label}
                                    </span>
                                    );
                                })}
                                <span className="ml-auto font-mono text-zinc-400">
                                    Vol {fmtVol(volume.total_volume || selFlags.opt_volume)}
                                </span>
                            </div>
                            {report?.trade ? (
                                <div className="text-[12px] font-mono text-emerald-300">
                                    {report.trade.action} {fmt(report.trade.strike, 0)} · stop {fmt(report.trade.stop)} · tgt {fmt(report.trade.target)}
                                </div>
                            ) : (
                                <div className="text-[12px] text-zinc-400 leading-snug">
                                    {report?.why_not || 'Select a name from the lists.'}
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="text-zinc-600 text-sm">Select a stock</div>
                    )}
                </div>

                <div className="overflow-auto min-h-0">
                    <table className="w-full text-[11px] font-mono">
                        <thead className="sticky top-0 z-10">
                            <tr>
                                <th colSpan={6} className="bg-emerald-950/50 text-emerald-300 text-[10px] tracking-[0.18em] uppercase py-1.5 font-bold">
                                    Calls
                                </th>
                                <th className="bg-[#12141c] text-zinc-300 text-[10px] tracking-[0.18em] uppercase py-1.5 font-bold">
                                    Strike
                                </th>
                                <th colSpan={6} className="bg-rose-950/50 text-rose-300 text-[10px] tracking-[0.18em] uppercase py-1.5 font-bold">
                                    Puts
                                </th>
                            </tr>
                            <tr className="text-zinc-500 bg-[#0c1016] border-b-2 border-[#c4b5fd]">
                                <th className="px-1.5 py-1 text-left font-medium">Signal</th>
                                <th className="px-1.5 py-1 text-right font-medium">CE OI</th>
                                <th className="px-1.5 py-1 text-right font-medium">Δ</th>
                                <th className="px-1.5 py-1 text-right font-medium">Vol</th>
                                <th className="px-1.5 py-1 text-right font-medium">IV</th>
                                <th className="px-1.5 py-1 text-right font-medium">LTP</th>
                                <th className="px-1.5 py-1 text-center font-medium"> </th>
                                <th className="px-1.5 py-1 text-left font-medium">Signal</th>
                                <th className="px-1.5 py-1 text-right font-medium">PE OI</th>
                                <th className="px-1.5 py-1 text-right font-medium">Δ</th>
                                <th className="px-1.5 py-1 text-right font-medium">Vol</th>
                                <th className="px-1.5 py-1 text-right font-medium">IV</th>
                                <th className="px-1.5 py-1 text-right font-medium">LTP</th>
                            </tr>
                        </thead>
                        <tbody>
                            {chain.map((r) => {
                                const k = r.strike_price;
                                const isCallWall = k === structure.call_wall;
                                const isPutWall = k === structure.put_wall;
                                const isAtm = k === report?.atm;
                                const rowBg = isAtm
                                    ? 'bg-violet-950/40 font-bold'
                                    : isCallWall
                                    ? 'bg-rose-950/20'
                                    : isPutWall
                                    ? 'bg-emerald-950/20'
                                    : '';

                                const cChg = (r.call?.oi || 0) - (r.call?.prev_oi || 0);
                                const pChg = (r.put?.oi || 0) - (r.put?.prev_oi || 0);
                                const fuelStrike = report?.trade?.strike || report?.top_anomaly?.strike;
                                const dim = !isAtm && !isCallWall && !isPutWall && k !== fuelStrike
                                    && (r.call?.signal || '').includes('Neutral')
                                    && (r.put?.signal || '').includes('Neutral');

                                return (
                                    <tr key={k} className={`${rowBg} hover:bg-white/[0.04] border-b border-zinc-900/40 ${dim ? 'opacity-40' : ''}`}>
                                        <td className="p-1 text-left text-[10px] truncate max-w-[110px]" title={r.call?.signal}>
                                            <span className="mr-0.5">{r.call?.signal_icon || '⚪'}</span>
                                            <span className={r.call?.signal_direction === 'BULLISH' ? 'text-emerald-400' : r.call?.signal_direction === 'BEARISH' ? 'text-rose-400' : 'text-zinc-400'}>
                                                {r.call?.signal || 'Neutral'}
                                            </span>
                                        </td>
                                        <td className="p-1 text-right text-emerald-200/80">{fmt(r.call?.oi, 0)}</td>
                                        <td className={`p-1 text-right text-[10px] ${cChg > 0 ? 'text-emerald-400 font-bold' : cChg < 0 ? 'text-rose-400' : 'text-zinc-500'}`}>
                                            {cChg > 0 ? '+' : ''}{fmt(cChg, 0)}
                                        </td>
                                        <td className="p-1 text-right">{fmt(r.call?.volume, 0)}</td>
                                        <td className="p-1 text-right">{fmt(r.call?.iv, 1)}</td>
                                        <td className="p-1 text-right">{fmt(r.call?.ltp, 1)}</td>
                                        <td className="p-1 text-center font-bold bg-zinc-900/90 text-violet-300">
                                            {fmt(k, 0)}
                                            {isCallWall ? <span className="ml-0.5 text-[8px] text-rose-400">RES</span> : null}
                                            {isPutWall ? <span className="ml-0.5 text-[8px] text-emerald-400">SUP</span> : null}
                                        </td>
                                        <td className="p-1 text-left text-[10px] truncate max-w-[110px]" title={r.put?.signal}>
                                            <span className="mr-0.5">{r.put?.signal_icon || '⚪'}</span>
                                            <span className={r.put?.signal_direction === 'BULLISH' ? 'text-emerald-400' : r.put?.signal_direction === 'BEARISH' ? 'text-rose-400' : 'text-zinc-400'}>
                                                {r.put?.signal || 'Neutral'}
                                            </span>
                                        </td>
                                        <td className="p-1 text-right text-rose-200/80">{fmt(r.put?.oi, 0)}</td>
                                        <td className={`p-1 text-right text-[10px] ${pChg > 0 ? 'text-emerald-400 font-bold' : pChg < 0 ? 'text-rose-400' : 'text-zinc-500'}`}>
                                            {pChg > 0 ? '+' : ''}{fmt(pChg, 0)}
                                        </td>
                                        <td className="p-1 text-right">{fmt(r.put?.volume, 0)}</td>
                                        <td className="p-1 text-right">{fmt(r.put?.iv, 1)}</td>
                                        <td className="p-1 text-right">{fmt(r.put?.ltp, 1)}</td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>

            <footer className="shrink-0 border-t-2 border-[#c4b5fd] px-3 py-1 flex justify-between text-zinc-500">
                <span className="text-[9px] uppercase tracking-widest">
                    Unique · OR break · OI · Premium · Clean room — AND filters
                </span>
                <SystemStatus />
            </footer>

            {/* Nifty 50 Quant Terminal Modal Overlay */}
            {showNiftyModal && (
                <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md p-4 overflow-y-auto flex items-start justify-center animate-in fade-in duration-200">
                    <div className="w-full max-w-7xl my-6">
                        <NiftyQuantTerminal onClose={() => setShowNiftyModal(false)} />
                    </div>
                </div>
            )}
        </div>
    );
}

function TapeChip({
    label,
    row,
    lastClose,
    onClick,
}: {
    label: string;
    row?: TapeItem;
    lastClose?: boolean;
    onClick?: () => void;
}) {
    const px = row?.ltp;
    const chp = row?.chp;
    const hasPx = Boolean(px && px > 0);
    const up = Number(chp) >= 0;
    return (
        <div
            onClick={onClick}
            className={`px-3 py-1.5 min-w-[120px] bg-[#0c1016] border-r-2 border-[#c4b5fd] last:border-0 transition-all ${
                onClick ? 'cursor-pointer hover:bg-violet-950/60 hover:brightness-125' : ''
            }`}
        >
            <div className="flex items-center justify-between gap-2">
                <div className="text-[9px] font-bold uppercase tracking-widest text-zinc-500 flex items-center gap-1">
                    {label}
                    {onClick && <span className="text-[8px] text-violet-400">⚡</span>}
                </div>
                {hasPx && lastClose && (
                    <span className="text-[8px] font-bold uppercase tracking-wider text-zinc-500">close</span>
                )}
            </div>
            <div className="flex items-baseline gap-1.5 font-mono leading-none mt-0.5">
                <span className="text-[14px] font-semibold tabular-nums">
                    {hasPx
                        ? Number(px).toLocaleString('en-IN', { maximumFractionDigits: label === 'VIX' ? 2 : 1 })
                        : '—'}
                </span>
                <span className={`text-[10px] ${hasPx ? (up ? 'text-emerald-400' : 'text-rose-400') : 'text-zinc-600'}`}>
                    {hasPx && chp != null ? `${up ? '+' : ''}${Number(chp).toFixed(2)}%` : ''}
                </span>
            </div>
        </div>
    );
}

type SortKey = 'score' | 'oi' | 'vol';
type SortDir = 'desc' | 'asc';

function sortArrow(active: boolean, dir: SortDir) {
    if (!active) return '↕';
    return dir === 'desc' ? '↓' : '↑';
}

function SetupTable({
    title,
    tone,
    count,
    rows,
    selected,
    onSelect,
    hotSet,
    dataMode,
}: {
    title: string;
    tone: 'bull' | 'bear';
    count: number;
    rows: BoardRow[];
    selected: string | null;
    onSelect: (s: string) => void;
    hotSet?: Set<string>;
    dataMode?: string;
}) {
    const color = tone === 'bull' ? 'text-emerald-400' : 'text-rose-400';
    const dot = tone === 'bull' ? 'bg-emerald-400' : 'bg-rose-400';
    const [sortKey, setSortKey] = useState<SortKey>('score');
    const [sortDir, setSortDir] = useState<SortDir>('desc');

    const toggleSort = (key: SortKey) => {
        if (sortKey === key) {
            setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
            return;
        }
        setSortKey(key);
        setSortDir('desc');
    };

    const sorted = useMemo(() => {
        const mul = sortDir === 'desc' ? 1 : -1;
        return [...rows].sort((a, b) => {
            const av =
                sortKey === 'oi'
                    ? oiOf(a) ?? -1
                    : sortKey === 'vol'
                      ? volOf(a) ?? -1
                      : a.setup_score ?? 0;
            const bv =
                sortKey === 'oi'
                    ? oiOf(b) ?? -1
                    : sortKey === 'vol'
                      ? volOf(b) ?? -1
                      : b.setup_score ?? 0;
            if (av === bv) return (b.setup_score || 0) - (a.setup_score || 0);
            return av < bv ? mul : -mul;
        });
    }, [rows, sortKey, sortDir]);

    return (
        <section className="min-h-0 flex flex-col bg-[#0a0d13]">
            <div className="shrink-0 px-3 py-2 flex items-center justify-between border-b-2 border-[#c4b5fd]">
                <div className="flex items-center gap-2">
                    <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
                    <h3 className={`text-[11px] font-bold uppercase tracking-widest ${color}`}>{title}</h3>
                </div>
                <span className="text-[11px] font-mono text-zinc-500">{count}</span>
            </div>
            <div className="grid grid-cols-[40px_1fr_72px_56px] px-3 py-1 text-[9px] uppercase tracking-wider text-zinc-500 border-b-2 border-[#c4b5fd]">
                <button
                    type="button"
                    onClick={() => toggleSort('score')}
                    className={`text-left hover:text-zinc-200 ${sortKey === 'score' ? 'text-violet-200' : ''}`}
                    title="Sort by score"
                >
                    Scr {sortArrow(sortKey === 'score', sortDir)}
                </button>
                <span>Name</span>
                <button
                    type="button"
                    onClick={() => toggleSort('oi')}
                    className={`text-right hover:text-zinc-200 ${sortKey === 'oi' ? 'text-violet-200' : ''}`}
                    title="Sort by ΔOI"
                >
                    ΔOI {sortArrow(sortKey === 'oi', sortDir)}
                </button>
                <button
                    type="button"
                    onClick={() => toggleSort('vol')}
                    className={`text-right hover:text-zinc-200 ${sortKey === 'vol' ? 'text-violet-200' : ''}`}
                    title="Sort by volume"
                >
                    Vol {sortArrow(sortKey === 'vol', sortDir)}
                </button>
            </div>
            <div className="flex-1 overflow-y-auto">
                {sorted.map((row) => (
                    <button
                        key={row.symbol}
                        onClick={() => onSelect(row.symbol)}
                        className={`w-full grid grid-cols-[40px_1fr_72px_56px] items-center px-3 py-1.5 text-left border-b border-[#c4b5fd]/45 ${
                            selected === row.symbol ? 'bg-violet-500/15' : 'hover:bg-white/[0.03]'
                        }`}
                    >
                        <span className={`font-mono text-[12px] font-bold ${scoreTone(row.setup_score)}`}>
                            {row.setup_score ?? '—'}
                        </span>
                        {(() => {
                            const topTags = getTopTwoTags(row, hotSet);
                            const vorVal = row.vor ?? row.flags?.vor ?? row.top_anomaly?.vor;
                            return (
                                <span className="min-w-0">
                                    <span className="flex items-center gap-1 text-[12px] font-semibold truncate">
                                        <span className="truncate">{row.name}</span>
                                        {freshnessBadge(row.ts, dataMode)}
                                    </span>
                                    <span className="block text-[10px] text-violet-300/90 font-mono truncate">
                                        {topTags.join(' · ')} {vorVal && vorVal >= 0.4 ? `· VOR ${Number(vorVal).toFixed(1)}×` : ''}
                                    </span>
                                </span>
                            );
                        })()}
                        <span className="text-right font-mono text-[11px]">{fmt(oiOf(row), 0)}</span>
                        <span className="text-right font-mono text-[11px] text-zinc-400">
                            {fmtVol(volOf(row))}
                        </span>
                    </button>
                ))}
            </div>
        </section>
    );
}

function Mini({ k, v }: { k: string; v: string }) {
    return (
        <div>
            <div className="text-[9px] uppercase tracking-widest text-zinc-500">{k}</div>
            <div className="font-mono text-[12px]">{v}</div>
        </div>
    );
}

function Tag({
    children,
    on,
    danger,
    ok,
}: {
    children: React.ReactNode;
    on?: boolean;
    danger?: boolean;
    ok?: boolean;
}) {
    const cls = danger
        ? 'border-rose-500/40 text-rose-300'
        : ok
          ? 'border-emerald-500/40 text-emerald-300'
          : on
            ? 'border-zinc-500 text-zinc-200'
            : 'border-zinc-800 text-zinc-500';
    return <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold uppercase tracking-wider ${cls}`}>{children}</span>;
}
