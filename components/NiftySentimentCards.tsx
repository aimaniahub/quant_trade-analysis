'use client';

import { useState, useEffect } from 'react';
import { api } from '../lib/api';

interface VixData {
    value: number | null;
    change: number;
    change_pct: number;
    trend: string;
    sentiment: string;
    color: string;
    message: string;
    error?: string;
}

interface PcrData {
    pcr: number | null;
    total_call_oi: number;
    total_put_oi: number;
    sentiment: string;
    color: string;
    message: string;
    error?: string;
}

interface BreadthData {
    advances: number;
    declines: number;
    unchanged: number;
    total: number;
    ratio: number;
    sentiment: string;
    color: string;
    message: string;
    error?: string;
}

interface OiChangeData {
    call_oi_change: number;
    put_oi_change: number;
    net_change: number;
    sentiment: string;
    color: string;
    message: string;
    error?: string;
}

interface LevelsData {
    spot: number;
    support: number;
    support_oi: number;
    resistance: number;
    resistance_oi: number;
    range: string;
    error?: string;
}

interface SentimentData {
    vix: VixData;
    pcr: PcrData;
    breadth: BreadthData;
    oi_change: OiChangeData;
    levels: LevelsData;
    timestamp: string;
}

interface NiftySentimentCardsProps {
    autoRefresh?: boolean;
    refreshInterval?: number;
}

export default function NiftySentimentCards({ autoRefresh = true, refreshInterval = 30000 }: NiftySentimentCardsProps) {
    const [data, setData] = useState<SentimentData | null>(null);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

    const fetchSentiment = async () => {
        try {
            const response = await api.market.getNiftySentiment();
            setData(response);
            setLastUpdated(new Date());
        } catch (error) {
            console.error('Failed to fetch sentiment:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchSentiment();

        if (autoRefresh) {
            const interval = setInterval(fetchSentiment, refreshInterval);
            return () => clearInterval(interval);
        }
    }, [autoRefresh, refreshInterval]);

    const getColorClass = (color: string) => {
        switch (color) {
            case 'green': return 'text-emerald-500 bg-emerald-500/10 border-emerald-500/30';
            case 'lime': return 'text-lime-500 bg-lime-500/10 border-lime-500/30';
            case 'amber': return 'text-amber-500 bg-amber-500/10 border-amber-500/30';
            case 'orange': return 'text-orange-500 bg-orange-500/10 border-orange-500/30';
            case 'red': return 'text-rose-500 bg-rose-500/10 border-rose-500/30';
            default: return 'text-zinc-400 bg-zinc-800 border-zinc-700';
        }
    };

    const getTrendIcon = (trend: string) => {
        if (trend === 'up') return '▲';
        if (trend === 'down') return '▼';
        return '–';
    };

    if (loading) {
        return (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 animate-pulse">
                {[...Array(5)].map((_, i) => (
                    <div key={i} className="h-24 bg-zinc-900 rounded-xl border border-zinc-800" />
                ))}
            </div>
        );
    }

    if (!data) {
        return (
            <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400">
                Failed to load sentiment data
            </div>
        );
    }

    return (
        <div className="space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between">
                <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
                    Nifty 50 Sentiment
                </h2>
                <span className="text-[10px] text-zinc-600">
                    {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : ''}
                </span>
            </div>

            {/* Cards Grid */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                {/* VIX Card */}
                <div className={`p-4 rounded-xl border ${getColorClass(data.vix.color)} transition-all hover:scale-105`}>
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider opacity-70">VIX</span>
                        <span className={`text-xs ${data.vix.trend === 'up' ? 'text-rose-500' : 'text-emerald-500'}`}>
                            {getTrendIcon(data.vix.trend)} {data.vix.change_pct?.toFixed(1)}%
                        </span>
                    </div>
                    <div className="text-2xl font-black">{data.vix.value?.toFixed(1) || '–'}</div>
                    <div className="text-[10px] mt-1 opacity-70">{data.vix.sentiment?.replace(/_/g, ' ')}</div>
                </div>

                {/* PCR Card */}
                <div className={`p-4 rounded-xl border ${getColorClass(data.pcr.color)} transition-all hover:scale-105`}>
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider opacity-70">PCR</span>
                    </div>
                    <div className="text-2xl font-black">{data.pcr.pcr?.toFixed(2) || '–'}</div>
                    <div className="text-[10px] mt-1 opacity-70">{data.pcr.sentiment?.replace(/_/g, ' ')}</div>
                </div>

                {/* Market Breadth Card */}
                <div className={`p-4 rounded-xl border ${getColorClass(data.breadth.color)} transition-all hover:scale-105`}>
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider opacity-70">BREADTH</span>
                    </div>
                    <div className="flex items-baseline gap-1">
                        <span className="text-xl font-black text-emerald-500">{data.breadth.advances}</span>
                        <span className="text-zinc-500">/</span>
                        <span className="text-xl font-black text-rose-500">{data.breadth.declines}</span>
                    </div>
                    <div className="text-[10px] mt-1 opacity-70">A/D Ratio: {data.breadth.ratio}</div>
                </div>

                {/* OI Change Card */}
                <div className={`p-4 rounded-xl border ${getColorClass(data.oi_change.color)} transition-all hover:scale-105`}>
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider opacity-70">OI CHANGE</span>
                    </div>
                    <div className="text-lg font-black">
                        {data.oi_change.net_change > 0 ? '+' : ''}{(data.oi_change.net_change / 1000).toFixed(0)}K
                    </div>
                    <div className="text-[10px] mt-1 opacity-70">{data.oi_change.sentiment?.replace(/_/g, ' ')}</div>
                </div>

                {/* Nifty Levels Card */}
                <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-900/50 transition-all hover:scale-105">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">NIFTY RANGE</span>
                    </div>
                    <div className="text-lg font-black text-white">{data.levels.spot?.toFixed(0) || '–'}</div>
                    <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] text-emerald-500">S: {data.levels.support}</span>
                        <span className="text-[10px] text-rose-500">R: {data.levels.resistance}</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
