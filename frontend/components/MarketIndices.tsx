"use client";

import { useState } from "react";
import { api } from "../lib/api";
import { useApiQuery } from "../lib/hooks/useApiQuery";
import { useMarketPolling } from "../lib/hooks/useMarketPolling";

const INDEX_SYMBOLS = [
    'NSE:NIFTY50-INDEX',
    'NSE:NIFTYBANK-INDEX',
    'NSE:FINNIFTY-INDEX'
];

const INDEX_LABELS: Record<string, string> = {
    'NSE:NIFTY50-INDEX': 'NIFTY 50',
    'NSE:NIFTYBANK-INDEX': 'BANK NIFTY',
    'NSE:FINNIFTY-INDEX': 'FIN NIFTY'
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
    const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
    const { interval, statusText, isOpen } = useMarketPolling(15000);

    const { data, isLoading, error } = useApiQuery(
        ["market", "indices"],
        () => api.market.getIndices(),
        {
            refetchInterval: interval,
            onSuccess: () => {
                setLastUpdate(new Date());
            },
        },
    );

    const indicesData: Record<string, IndexData> = {};

    if (data && (data as any).success && (data as any).data) {
        for (const quote of (data as any).data as any[]) {
            const symbol = quote.symbol || quote.n;
            const v = quote.v || {};
            if (symbol) {
                indicesData[symbol] = {
                    ltp: quote.ltp ?? v.lp ?? v.ltp ?? 0,
                    ch: quote.ch ?? v.ch ?? 0,
                    chp: quote.chp ?? v.chp ?? 0,
                    open: quote.open ?? v.open_price ?? 0,
                    high: quote.high ?? v.high_price ?? 0,
                    low: quote.low ?? v.low_price ?? 0,
                };
            }
        }
    }

    const hasData = Object.keys(indicesData).length > 0;
    const dataMode = (data as any)?.data_mode || (isOpen ? 'live' : 'last_close');

    return (
        <div className="w-full">
            <div className="flex md:grid md:grid-cols-3 gap-2.5 sm:gap-4 overflow-x-auto no-scrollbar snap-x snap-mandatory touch-scroll pb-1">
                {INDEX_SYMBOLS.map((symbol) => {
                    const data = indicesData[symbol] || {};
                    const ltp = data.ltp || 0;
                    const ch = data.ch || 0;
                    const chp = data.chp || 0;
                    const high = data.high || 0;
                    const low = data.low || 0;
                    const isPositive = ch >= 0;

                    return (
                        <div
                            key={symbol}
                            className="min-w-[78vw] sm:min-w-0 flex-1 snap-start p-3.5 sm:p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-sm hover:border-emerald-500/40 transition-all flex flex-col justify-between"
                        >
                            <div className="flex justify-between items-start mb-1.5">
                                <span className="text-xs sm:text-sm font-bold text-zinc-600 dark:text-zinc-300 tracking-tight">
                                    {INDEX_LABELS[symbol]}
                                </span>
                                <span className={`text-[9px] sm:text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                                    hasData && ltp > 0
                                        ? dataMode === 'live'
                                            ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/25"
                                            : "bg-amber-500/10 text-amber-400 border-amber-500/25"
                                        : "bg-zinc-800 text-zinc-500 border-zinc-700"
                                }`}>
                                    {isLoading ? "SYNC" : hasData && ltp > 0 ? (dataMode === 'live' ? "● LIVE" : "○ CLOSE") : "NO DATA"}
                                </span>
                            </div>
                            <div className="flex items-baseline justify-between gap-2">
                                <span className="text-xl sm:text-2xl font-black font-mono tracking-tight text-zinc-900 dark:text-white">
                                    {ltp > 0 ? ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '---'}
                                </span>
                                <span className={`text-xs sm:text-sm font-mono font-bold shrink-0 ${isPositive ? 'text-emerald-500 dark:text-emerald-400' : 'text-rose-500 dark:text-rose-400'}`}>
                                    {ltp > 0 && (
                                        <>
                                            {isPositive ? '+' : ''}{ch.toFixed(2)} ({chp.toFixed(2)}%)
                                        </>
                                    )}
                                </span>
                            </div>
                            {high > 0 && low > 0 && (
                                <div className="mt-2 pt-2 border-t border-zinc-100 dark:border-zinc-800/80 flex items-center justify-between text-[10px] font-mono text-zinc-500">
                                    <span>L: <span className="text-zinc-400">{low.toLocaleString('en-IN', { maximumFractionDigits: 1 })}</span></span>
                                    <span>H: <span className="text-zinc-400">{high.toLocaleString('en-IN', { maximumFractionDigits: 1 })}</span></span>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
            {error && (
                <div className="mt-2 text-[10px] text-rose-500">
                    Failed to load indices. Data may be delayed.
                </div>
            )}
        </div>
    );
}
