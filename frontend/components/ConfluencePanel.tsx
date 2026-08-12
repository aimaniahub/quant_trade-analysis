'use client';

import { api } from '../lib/api';
import { useApiQuery } from '../lib/hooks/useApiQuery';
import LoadingBanner from './ui/LoadingBanner';

interface ConfluenceSource {
    name: string;
    direction: string;
    detail?: string;
    weight?: number;
    lis?: number;
}

interface ConfluenceCard {
    symbol: string;
    name: string;
    direction: string;
    status: 'ACTIONABLE' | 'WATCH' | 'CONFLICT' | 'IDLE' | string;
    score: number;
    sources_count: number;
    source_names: string[];
    sources: ConfluenceSource[];
    tradeable: boolean;
}

interface ConfluenceData {
    success: boolean;
    summary?: {
        actionable_count: number;
        watch_count: number;
        total_scored: number;
        min_sources: number;
        bias: string;
        news_bias?: string;
        news_available?: boolean;
    };
    cards?: ConfluenceCard[];
    actionable?: ConfluenceCard[];
    nifty_state?: string;
    news?: {
        bias?: string;
        score?: number;
        summary?: string;
        available?: boolean;
        cached?: boolean;
    };
    radar_cache_age?: number | null;
    timestamp?: string;
}

const statusStyle: Record<string, string> = {
    ACTIONABLE: 'bg-emerald-500/15 text-emerald-500 border-emerald-500/30',
    WATCH: 'bg-amber-500/15 text-amber-500 border-amber-500/30',
    CONFLICT: 'bg-rose-500/15 text-rose-500 border-rose-500/30',
    IDLE: 'bg-zinc-500/10 text-zinc-500 border-zinc-500/20',
};

const dirStyle: Record<string, string> = {
    BULLISH: 'text-emerald-500',
    BEARISH: 'text-rose-500',
    CONFLICT: 'text-amber-500',
    NEUTRAL: 'text-zinc-500',
    MIXED: 'text-amber-500',
};

export default function ConfluencePanel() {
    const { data, isLoading, error, refetch, isFetching } = useApiQuery<ConfluenceData>(
        ['confluence'],
        () => api.confluence.get(2, true) as Promise<ConfluenceData>,
        { refetchInterval: 60000 },
    );

    const summary = data?.summary;
    const cards = (data?.actionable?.length ? data.actionable : data?.cards || []).slice(0, 8);

    return (
        <div className="p-5 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-sm">
            <div className="flex items-start justify-between gap-3 mb-4">
                <div>
                    <h4 className="font-black text-xs uppercase tracking-widest text-zinc-400">
                        Multi-Source Confluence
                    </h4>
                    <p className="text-[10px] text-zinc-500 mt-1">
                        MA + Radar + Intelligence agree before tradeable
                    </p>
                </div>
                <button
                    onClick={() => refetch()}
                    className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-md bg-zinc-100 dark:bg-zinc-800 text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                >
                    {isFetching ? '…' : 'Refresh'}
                </button>
            </div>

            {/* Summary chips */}
            <div className="grid grid-cols-5 gap-2 mb-4">
                <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800/50 p-2 text-center">
                    <div className="text-[9px] font-bold text-zinc-500">BIAS</div>
                    <div className={`text-xs font-black ${dirStyle[summary?.bias || 'NEUTRAL'] || ''}`}>
                        {summary?.bias || '—'}
                    </div>
                </div>
                <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800/50 p-2 text-center">
                    <div className="text-[9px] font-bold text-zinc-500">ACTION</div>
                    <div className="text-xs font-black text-emerald-500">
                        {summary?.actionable_count ?? 0}
                    </div>
                </div>
                <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800/50 p-2 text-center">
                    <div className="text-[9px] font-bold text-zinc-500">WATCH</div>
                    <div className="text-xs font-black text-amber-500">
                        {summary?.watch_count ?? 0}
                    </div>
                </div>
                <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800/50 p-2 text-center">
                    <div className="text-[9px] font-bold text-zinc-500">NIFTY</div>
                    <div className="text-xs font-black text-zinc-800 dark:text-zinc-100">
                        {data?.nifty_state || '—'}
                    </div>
                </div>
                <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800/50 p-2 text-center">
                    <div className="text-[9px] font-bold text-zinc-500">NEWS</div>
                    <div className={`text-xs font-black ${dirStyle[data?.news?.bias || 'NEUTRAL'] || ''}`}>
                        {data?.news?.available ? (data?.news?.bias || '—') : 'OFF'}
                    </div>
                </div>
            </div>

            {data?.news?.available && data.news.summary && (
                <div className="mb-3 p-2 rounded-lg bg-zinc-50 dark:bg-zinc-800/40 text-[10px] text-zinc-500 line-clamp-2">
                    {data.news.summary}
                </div>
            )}

            <LoadingBanner
                active={isLoading || isFetching}
                label={data ? 'Refreshing confluence' : 'Aggregating multi-source signals'}
                detail="MA · Radar · Intelligence · bus (+ soft news)"
            />

            {isLoading && !data && (
                <div className="animate-pulse space-y-2">
                    <div className="h-10 bg-zinc-100 dark:bg-zinc-800 rounded" />
                    <div className="h-10 bg-zinc-100 dark:bg-zinc-800 rounded" />
                </div>
            )}

            {error && (
                <div className="text-xs text-rose-500 mb-2">
                    {error.message}
                    <span className="block text-[10px] text-zinc-500 mt-1">
                        Radar cache + MA results feed this panel. Run a radar scan if empty.
                    </span>
                </div>
            )}

            {!isLoading && cards.length === 0 && !error && (
                <div className="text-xs text-zinc-500 py-4 text-center">
                    No multi-source setups yet. MA crosses and radar hits will appear here when
                    they align (min {summary?.min_sources ?? 2} sources).
                    {data?.radar_cache_age == null && (
                        <span className="block text-[10px] mt-1 text-zinc-400">
                            No radar cache — scheduler runs in market hours, or open Flow Radar.
                        </span>
                    )}
                </div>
            )}

            <div className="space-y-2">
                {cards.map((card) => (
                    <div
                        key={card.symbol}
                        className="flex items-start gap-3 p-2.5 rounded-lg border border-zinc-100 dark:border-zinc-800 hover:border-blue-500/20 transition-colors"
                    >
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-bold text-zinc-900 dark:text-white">
                                    {card.name}
                                </span>
                                <span
                                    className={`text-[10px] font-black uppercase ${dirStyle[card.direction] || 'text-zinc-500'}`}
                                >
                                    {card.direction}
                                </span>
                                <span
                                    className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${statusStyle[card.status] || statusStyle.IDLE}`}
                                >
                                    {card.status}
                                </span>
                                <span className="text-[10px] font-mono text-zinc-400">
                                    {card.score}
                                </span>
                            </div>
                            <div className="flex flex-wrap gap-1 mt-1">
                                {Array.from(new Set(card.source_names)).map((s) => (
                                    <span
                                        key={`${card.symbol}-src-${s}`}
                                        className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 font-bold uppercase"
                                    >
                                        {s}
                                    </span>
                                ))}
                            </div>
                            {card.sources?.[0]?.detail && (
                                <p className="text-[10px] text-zinc-500 mt-1 truncate">
                                    {card.sources[0].detail}
                                </p>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            {data?.radar_cache_age != null && (
                <div className="text-[9px] text-zinc-400 mt-3 pt-2 border-t border-zinc-100 dark:border-zinc-800">
                    Radar cache age: {Math.round(Number(data.radar_cache_age))}s
                    {data.timestamp && (
                        <> · Updated {new Date(data.timestamp).toLocaleTimeString('en-IN')}</>
                    )}
                </div>
            )}
        </div>
    );
}
