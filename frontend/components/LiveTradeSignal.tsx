'use client';

import { useState } from 'react';
import { api } from '../lib/api';
import { useApiQuery } from '../lib/hooks/useApiQuery';

interface TradeRecommendation {
    action: string;
    option_type?: string;
    strike?: number;
    entry_zone?: string;
    stop_loss?: number;
    target?: number;
    confidence?: string;
    reason?: string;
    suggestion?: string;
}

interface OiAnalysis {
    support: number | null;
    resistance: number | null;
    support_oi: number;
    resistance_oi: number;
}

interface GreeksAnalysis {
    score: number;
    analysis: {
        delta_ratio: number;
        delta_bias: string;
        max_gamma_strike: number | null;
        max_gamma: number;
    };
}

interface TradeSignalData {
    symbol: string;
    name: string;
    spot_price: number;
    atm_strike: number;
    oi_analysis: OiAnalysis;
    greeks_analysis: GreeksAnalysis;
    intel_state: string;
    tradable: boolean;
    trade_recommendation: TradeRecommendation;
    timestamp: string;
}

interface LiveTradeSignalProps {
    symbol: string;
    autoRefresh?: boolean;
    refreshInterval?: number;
}

export default function LiveTradeSignal({ symbol, autoRefresh = true, refreshInterval = 30000 }: LiveTradeSignalProps) {
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

    const { data, isLoading, error } = useApiQuery<TradeSignalData>(
        ['market', 'live-trade-signal', symbol],
        () => api.market.getLiveTradeSignal(symbol) as Promise<TradeSignalData>,
        {
            enabled: Boolean(symbol),
            refetchInterval: autoRefresh ? refreshInterval : false,
            onSuccess: () => setLastUpdated(new Date()),
        },
    );

    if (isLoading && !data) {
        return (
            <div className="p-6 bg-zinc-900 rounded-2xl border border-zinc-800 animate-pulse">
                <div className="h-6 bg-zinc-800 rounded w-1/3 mb-4" />
                <div className="h-16 bg-zinc-800 rounded mb-4" />
                <div className="h-8 bg-zinc-800 rounded w-1/2" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-6 bg-rose-500/10 rounded-2xl border border-rose-500/30">
                <p className="text-rose-400 text-sm">{error.message}</p>
            </div>
        );
    }

    if (!data) return null;

    const rec = data.trade_recommendation;
    const isBuy = rec.action === 'BUY';
    const isWait = rec.action === 'WAIT';
    const isCE = rec.option_type === 'CE';

    return (
        <div className="p-6 bg-gradient-to-br from-zinc-900 to-zinc-950 rounded-2xl border border-zinc-800">
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-lg font-black text-white">{data.name}</h3>
                    <p className="text-sm text-zinc-500">₹{data.spot_price.toFixed(2)} • ATM: {data.atm_strike}</p>
                </div>
                <div className="text-right">
                    <span className={`px-3 py-1 text-xs font-bold uppercase rounded-lg ${data.tradable ? 'bg-emerald-500/20 text-emerald-500' : 'bg-zinc-700 text-zinc-400'
                        }`}>
                        {data.intel_state}
                    </span>
                    <p className="text-[10px] text-zinc-600 mt-1">
                        {lastUpdated?.toLocaleTimeString()}
                    </p>
                </div>
            </div>

            {/* Trade Signal */}
            {isBuy ? (
                <div className={`p-5 rounded-xl border-2 ${isCE ? 'bg-emerald-500/10 border-emerald-500' : 'bg-rose-500/10 border-rose-500'
                    }`}>
                    <div className="flex items-center gap-3 mb-4">
                        <span className={`text-3xl font-black ${isCE ? 'text-emerald-500' : 'text-rose-500'}`}>
                            BUY {rec.option_type}
                        </span>
                        <span className="text-2xl font-black text-white">
                            {rec.strike}
                        </span>
                        <span className={`px-2 py-1 text-xs font-bold uppercase rounded ${rec.confidence === 'HIGH' ? 'bg-emerald-500/30 text-emerald-400' : 'bg-amber-500/30 text-amber-400'
                            }`}>
                            {rec.confidence}
                        </span>
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                        <div>
                            <p className="text-[10px] font-bold uppercase text-zinc-500 mb-1">Entry Zone</p>
                            <p className="text-lg font-bold text-white">{rec.entry_zone}</p>
                        </div>
                        <div>
                            <p className="text-[10px] font-bold uppercase text-zinc-500 mb-1">Stop Loss</p>
                            <p className="text-lg font-bold text-rose-500">₹{rec.stop_loss}</p>
                        </div>
                        <div>
                            <p className="text-[10px] font-bold uppercase text-zinc-500 mb-1">Target</p>
                            <p className="text-lg font-bold text-emerald-500">
                                ₹{typeof rec.target === 'number' ? rec.target.toFixed(0) : rec.target}
                            </p>
                        </div>
                    </div>

                    <p className="mt-4 text-sm text-zinc-400">{rec.reason}</p>
                </div>
            ) : isWait ? (
                <div className="p-5 rounded-xl bg-amber-500/10 border-2 border-amber-500/50">
                    <div className="flex items-center gap-3 mb-3">
                        <span className="text-2xl">⏳</span>
                        <span className="text-xl font-bold text-amber-400">WAIT</span>
                    </div>
                    <p className="text-sm text-zinc-400">{rec.reason}</p>
                    {rec.suggestion && (
                        <p className="text-xs text-amber-500/70 mt-2">💡 {rec.suggestion}</p>
                    )}
                </div>
            ) : (
                <div className="p-5 rounded-xl bg-zinc-800 border border-zinc-700">
                    <p className="text-lg font-bold text-zinc-400">NO TRADE</p>
                    <p className="text-sm text-zinc-500 mt-1">{rec.reason}</p>
                </div>
            )}

            {/* Quick Stats */}
            <div className="grid grid-cols-4 gap-3 mt-4">
                <div className="text-center p-2 bg-zinc-800/50 rounded-lg">
                    <p className="text-[10px] font-bold uppercase text-zinc-500">Support</p>
                    <p className="text-sm font-bold text-emerald-500">{data.oi_analysis.support || '–'}</p>
                </div>
                <div className="text-center p-2 bg-zinc-800/50 rounded-lg">
                    <p className="text-[10px] font-bold uppercase text-zinc-500">Resistance</p>
                    <p className="text-sm font-bold text-rose-500">{data.oi_analysis.resistance || '–'}</p>
                </div>
                <div className="text-center p-2 bg-zinc-800/50 rounded-lg">
                    <p className="text-[10px] font-bold uppercase text-zinc-500">Delta Bias</p>
                    <p className={`text-sm font-bold ${data.greeks_analysis.analysis.delta_bias === 'BULLISH' ? 'text-emerald-500' :
                        data.greeks_analysis.analysis.delta_bias === 'BEARISH' ? 'text-rose-500' : 'text-zinc-400'
                        }`}>
                        {data.greeks_analysis.analysis.delta_bias}
                    </p>
                </div>
                <div className="text-center p-2 bg-zinc-800/50 rounded-lg">
                    <p className="text-[10px] font-bold uppercase text-zinc-500">Greeks Score</p>
                    <p className="text-sm font-bold text-blue-500">{data.greeks_analysis.score}</p>
                </div>
            </div>
        </div>
    );
}
