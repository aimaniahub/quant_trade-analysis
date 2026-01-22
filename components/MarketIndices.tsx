'use client';

import { useState, useEffect } from 'react';
import { api } from '../lib/api';

const INDEX_SYMBOLS = [
    'NSE:NIFTY50-INDEX',
    'NSE:NIFTYBANK-INDEX',
    'NSE:NIFTYFIN-INDEX'
];

const INDEX_LABELS: Record<string, string> = {
    'NSE:NIFTY50-INDEX': 'NIFTY 50',
    'NSE:NIFTYBANK-INDEX': 'BANK NIFTY',
    'NSE:NIFTYFIN-INDEX': 'FIN NIFTY'
};

interface IndexData {
    ltp: number;
    ch: number;
    chp: number;
    open: number;
    high: number;
    low: number;
}

export default function MarketIndices() {
    const [indicesData, setIndicesData] = useState<Record<string, IndexData>>({});
    const [loading, setLoading] = useState(true);
    const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

    const fetchIndices = async () => {
        try {
            const response = await api.market.getIndices();
            if (response.success && response.data) {
                const parsed: Record<string, IndexData> = {};
                for (const quote of response.data) {
                    const symbol = quote.n;
                    const v = quote.v || {};
                    parsed[symbol] = {
                        ltp: v.lp || v.ltp || 0,
                        ch: v.ch || 0,
                        chp: v.chp || 0,
                        open: v.open_price || 0,
                        high: v.high_price || 0,
                        low: v.low_price || 0
                    };
                }
                setIndicesData(parsed);
                setLastUpdate(new Date());
            }
        } catch (err) {
            console.error('Failed to fetch indices:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchIndices();
        // Refresh every 10 seconds
        const interval = setInterval(fetchIndices, 10000);
        return () => clearInterval(interval);
    }, []);

    const hasData = Object.keys(indicesData).length > 0;

    return (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 w-full">
            {INDEX_SYMBOLS.map((symbol) => {
                const data = indicesData[symbol] || {};
                const ltp = data.ltp || 0;
                const ch = data.ch || 0;
                const chp = data.chp || 0;
                const isPositive = ch >= 0;

                return (
                    <div
                        key={symbol}
                        className="p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-sm hover:border-blue-500/30 transition-all"
                    >
                        <div className="flex justify-between items-start mb-2">
                            <span className="text-sm font-semibold text-zinc-500 dark:text-zinc-400">
                                {INDEX_LABELS[symbol]}
                            </span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded ${hasData && ltp > 0 ? 'bg-emerald-500/10 text-emerald-500' : 'bg-zinc-100 text-zinc-400 dark:bg-zinc-800'}`}>
                                {loading ? 'LOADING' : (hasData && ltp > 0 ? 'LIVE' : 'CLOSED')}
                            </span>
                        </div>
                        <div className="flex items-baseline gap-2">
                            <span className="text-2xl font-bold tracking-tight">
                                {ltp > 0 ? ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '---'}
                            </span>
                            <span className={`text-sm font-medium ${isPositive ? 'text-emerald-500' : 'text-rose-500'}`}>
                                {ltp > 0 && (
                                    <>
                                        {isPositive ? '+' : ''}{ch.toFixed(2)} ({chp.toFixed(2)}%)
                                    </>
                                )}
                            </span>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
