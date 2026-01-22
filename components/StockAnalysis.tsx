'use client';

import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useApiQuery } from '../lib/hooks/useApiQuery';

interface StockAnalysis {
    symbol: string;
    spot_price: number;
    atm_strike: number;
    state: string;
    intent_score: number;
    confidence: number;
    message: string;
    time_window: string;
    tradable: boolean;
    pcr: number;
    vix: number;
    support: number;
    resistance: number;
    strike_guidance?: {
        suggested: boolean;
        bias: string;
        trades: Array<{
            type: string;
            strike: number;
            instrument: string;
            rationale: string;
        }>;
        expert_note: string;
    };
    institutional_flow?: {
        intent_score: number;
        big_money_present: boolean;
        clusters: Array<{
            strike: number;
            type: string;
            strength: number;
            is_institutional: boolean;
        }>;
    };
    alerts?: Array<{
        type: string;
        message: string;
    }>;
}

interface ScanResponse {
    success: boolean;
    count: number;
    total_scanned: number;
    tradable_count: number;
    stocks: StockAnalysis[];
    timestamp: string;
}

type FilterType = 'all' | 'tradable' | 'TREND' | 'ADJUSTMENT';

interface StockAnalysisProps {
    onBack: () => void;
}

export default function StockAnalysis({ onBack }: StockAnalysisProps) {
    const [filter, setFilter] = useState<FilterType>('all');
    const [progress, setProgress] = useState(0);

    const { data, isLoading, error, isFetching, refetch } = useApiQuery<ScanResponse>(
        ['market', 'stocks-scan'],
        () => api.market.scanStocks(20, false) as Promise<ScanResponse>,
    );

    // Simulated progress indicator while scanning for stocks
    useEffect(() => {
        const active = isLoading || isFetching;

        if (active) {
            setProgress(0);
            const id = setInterval(() => {
                setProgress(prev => {
                    if (prev >= 90) return prev;
                    return prev + 2;
                });
            }, 100);
            return () => clearInterval(id);
        }

        setProgress(100);
        return undefined;
    }, [isLoading, isFetching]);

    const stateColors: Record<string, string> = {
        'TREND': 'bg-blue-500',
        'RANGE': 'bg-amber-500',
        'INTENT': 'bg-emerald-500',
        'NO-TRADE': 'bg-zinc-600'
    };

    const stateBorderColors: Record<string, string> = {
        'TREND': 'border-blue-500/30',
        'RANGE': 'border-amber-500/30',
        'INTENT': 'border-emerald-500/30',
        'NO-TRADE': 'border-zinc-600/30'
    };

    const filteredStocks = data?.stocks.filter(stock => {
        if (filter === 'all') return true;
        if (filter === 'tradable') return stock.tradable;
        return stock.state === filter;
    }) || [];

    const extractStockName = (symbol: string) => {
        return symbol.replace('NSE:', '').replace('-EQ', '');
    };

    if (isLoading && !data) {
        return (
            <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8">
                <div className="max-w-7xl mx-auto">
                    <div className="flex items-center justify-between mb-8">
                        <div className="animate-pulse">
                            <div className="h-8 w-48 bg-zinc-200 dark:bg-zinc-800 rounded"></div>
                            <div className="h-4 w-32 bg-zinc-200 dark:bg-zinc-800 rounded mt-2"></div>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {[...Array(6)].map((_, i) => (
                            <div key={i} className="p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl animate-pulse">
                                <div className="h-6 w-24 bg-zinc-200 dark:bg-zinc-700 rounded mb-3"></div>
                                <div className="h-4 w-full bg-zinc-200 dark:bg-zinc-700 rounded mb-2"></div>
                                <div className="h-4 w-3/4 bg-zinc-200 dark:bg-zinc-700 rounded"></div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8">
            <div className="max-w-7xl mx-auto">
                {/* Header */}
                <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                    <div>
                        <div className="flex items-center gap-3">
                            <button
                                onClick={onBack}
                                className="p-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
                            >
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                                </svg>
                            </button>
                            <div>
                                <h1 className="text-2xl font-black italic tracking-tighter text-zinc-900 dark:text-white uppercase">
                                    F&O Stock Analysis<span className="text-blue-600">.</span>
                                </h1>
                                <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest">
                                    {data?.count || 0} stocks analyzed • {data?.tradable_count || 0} tradable setups
                                </p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-3">
                        <button
                            onClick={() => refetch()}
                            disabled={isFetching}
                            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-colors disabled:opacity-50"
                        >
                            {isFetching ? 'Scanning...' : '🔄 Refresh'}
                        </button>
                        {(isLoading || isFetching) && (
                            <span className="text-[10px] text-zinc-500">
                                Scanning F&O universe: {progress}%
                            </span>
                        )}
                    </div>
                </header>

                {/* Filter Tabs */}
                <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
                    {[
                        { key: 'all', label: 'All Stocks' },
                        { key: 'tradable', label: 'Tradable Only' },
                        { key: 'TREND', label: '📈 Trend' },
                        { key: 'INTENT', label: '🎯 Intent / Flow' },
                    ].map(({ key, label }) => (
                        <button
                            key={key}
                            onClick={() => setFilter(key as FilterType)}
                            className={`px-4 py-2 text-xs font-bold uppercase tracking-wider rounded-lg whitespace-nowrap transition-all ${filter === key
                                ? 'bg-blue-600 text-white'
                                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                                }`}
                        >
                            {label}
                        </button>
                    ))}
                </div>

                {/* Error State */}
                {error && (
                    <div className="p-4 bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 rounded-xl mb-6">
                        <p className="text-sm text-rose-600 dark:text-rose-400">{error.message}</p>
                    </div>
                )}

                {/* Stock Cards Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filteredStocks.map((stock, idx) => (
                        <div
                            key={idx}
                            className={`p-4 bg-white dark:bg-zinc-900 border-2 ${stateBorderColors[stock.state] || 'border-zinc-200 dark:border-zinc-800'} rounded-xl shadow-sm hover:shadow-md transition-shadow`}
                        >
                            {/* Stock Header */}
                            <div className="flex items-center justify-between mb-3">
                                <div>
                                    <h3 className="text-lg font-black text-zinc-900 dark:text-white">
                                        {extractStockName(stock.symbol)}
                                    </h3>
                                    <p className="text-xs text-zinc-500">
                                        ₹{stock.spot_price?.toLocaleString('en-IN', { minimumFractionDigits: 2 }) || '---'}
                                    </p>
                                </div>
                                <div className="flex flex-col items-end gap-1">
                                    <span className={`px-2 py-1 text-[10px] font-black tracking-wider rounded ${stateColors[stock.state]} text-white`}>
                                        {stock.state}
                                    </span>
                                    {stock.tradable && (
                                        <span className="text-[10px] font-bold text-emerald-500">✓ TRADABLE</span>
                                    )}
                                </div>
                            </div>

                            {/* Confidence Bar */}
                            <div className="mb-3">
                                <div className="flex justify-between text-[10px] text-zinc-500 mb-1">
                                    <span>Institutional Intent Score</span>
                                    <span className={`font-bold ${stock.intent_score > 60 ? 'text-emerald-500' : 'text-blue-500'}`}>{stock.intent_score}%</span>
                                </div>
                                <div className="h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
                                    <div
                                        className={`h-full ${stock.intent_score > 60 ? 'bg-emerald-500' : 'bg-blue-500'} rounded-full transition-all`}
                                        style={{ width: `${stock.intent_score}%` }}
                                    ></div>
                                </div>
                                {stock.institutional_flow?.big_money_present && (
                                    <div className="flex items-center gap-1 mt-1">
                                        <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></span>
                                        <span className="text-[9px] font-black text-emerald-600 uppercase tracking-tighter">Big Money Detected</span>
                                    </div>
                                )}
                            </div>

                            {/* Key Metrics */}
                            <div className="grid grid-cols-3 gap-2 mb-3 text-center">
                                <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded">
                                    <p className="text-[9px] text-zinc-500 font-bold">ATM</p>
                                    <p className="text-xs font-bold text-zinc-900 dark:text-white">{stock.atm_strike}</p>
                                </div>
                                <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded">
                                    <p className="text-[9px] text-zinc-500 font-bold">PCR</p>
                                    <p className={`text-xs font-bold ${stock.pcr > 1 ? 'text-emerald-500' : stock.pcr < 0.7 ? 'text-rose-500' : 'text-zinc-900 dark:text-white'}`}>
                                        {stock.pcr?.toFixed(2) || '---'}
                                    </p>
                                </div>
                                <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded">
                                    <p className="text-[9px] text-zinc-500 font-bold">VIX</p>
                                    <p className={`text-xs font-bold ${(stock.vix || 0) > 18 ? 'text-rose-500' : 'text-zinc-900 dark:text-white'}`}>
                                        {stock.vix?.toFixed(1) || '---'}
                                    </p>
                                </div>
                            </div>

                            {/* Range */}
                            {stock.support && stock.resistance && (
                                <div className="text-[10px] text-zinc-500 mb-2">
                                    Range: <span className="font-bold text-zinc-700 dark:text-zinc-300">{stock.support} - {stock.resistance}</span>
                                </div>
                            )}

                            {/* Message */}
                            <p className="text-[11px] text-zinc-600 dark:text-zinc-400 border-t border-zinc-100 dark:border-zinc-800 pt-2 mb-3">
                                {stock.message}
                            </p>

                            {/* Strike Guidance - Buy Only */}
                            {stock.strike_guidance?.suggested && (
                                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 rounded-xl">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className={`text-[10px] font-black uppercase tracking-widest ${stock.strike_guidance.bias === 'BULLISH' ? 'text-emerald-500' : 'text-rose-500'}`}>
                                            {stock.strike_guidance.bias} SETUP
                                        </span>
                                        <span className="text-[9px] text-zinc-400 font-bold uppercase tracking-widest">BUY ONLY</span>
                                    </div>
                                    <div className="space-y-2">
                                        {stock.strike_guidance.trades.map((trade, tIdx) => (
                                            <div key={tIdx} className="flex items-center justify-between p-2 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg">
                                                <div>
                                                    <p className="text-[9px] font-bold text-zinc-400 uppercase leading-none mb-1">{trade.type}</p>
                                                    <p className="text-xs font-black text-zinc-900 dark:text-white">
                                                        {trade.strike} {trade.instrument}
                                                    </p>
                                                </div>
                                                <div className="text-right">
                                                    <p className="text-[9px] text-zinc-500 leading-tight italic max-w-[100px]">{trade.rationale}</p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                    <p className="mt-2 text-[9px] text-zinc-500 italic leading-tight border-t border-zinc-200 dark:border-zinc-800 pt-2">
                                        <span className="font-bold text-zinc-400 not-italic uppercase tracking-tighter mr-1">Expert Note:</span>
                                        {stock.strike_guidance.expert_note}
                                    </p>
                                </div>
                            )}
                        </div>
                    ))}
                </div>

                {/* Empty State */}
                {filteredStocks.length === 0 && !isLoading && (
                    <div className="text-center py-12">
                        <p className="text-zinc-500">No stocks match the current filter.</p>
                        <button
                            onClick={() => setFilter('all')}
                            className="mt-4 px-4 py-2 bg-blue-600 text-white text-xs font-bold rounded-lg"
                        >
                            Show All Stocks
                        </button>
                    </div>
                )}

                {/* Footer */}
                <footer className="mt-12 pt-8 border-t border-zinc-200 dark:border-zinc-800 flex justify-between items-center text-[10px] font-bold text-zinc-400 uppercase tracking-widest">
                    <span>Last updated: {data?.timestamp ? new Date(data.timestamp).toLocaleTimeString() : '---'}</span>
                    <span>Analysis Engine v1.0</span>
                </footer>
            </div>
        </div>
    );
}
