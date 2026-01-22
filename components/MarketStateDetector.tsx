'use client';

import { useState, useEffect } from 'react';
import { api } from '../lib/api';

interface MarketStateData {
    symbol: string;
    spot_price: number;
    atm_strike: number;
    state: string;
    confidence: number;
    message: string;
    time_window: string;
    tradable: boolean;
    pcr: number;
    vix: number;
    support: number;
    resistance: number;
    adjustment?: {
        detected: boolean;
        confidence: number;
        conditions: string[];
        trade_setup?: {
            action: string;
            rationale: string;
            strikes: number[];
        }
    };
    alerts?: Array<{
        type: string;
        message: string;
    }>;
}

export default function MarketStateDetector() {
    const [state, setState] = useState<MarketStateData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchState = async () => {
            try {
                const data = await api.market.getMarketState();
                setState(data);
                setError(null);
            } catch (err: any) {
                setError(err.message || 'Failed to fetch market state');
            } finally {
                setLoading(false);
            }
        };

        fetchState();
        // Refresh every 30 seconds
        const interval = setInterval(fetchState, 30000);
        return () => clearInterval(interval);
    }, []);

    const stateColors: Record<string, string> = {
        'TREND': 'bg-blue-500 text-white',
        'RANGE': 'bg-amber-500 text-white',
        'ADJUSTMENT': 'bg-purple-500 text-white',
        'NO-TRADE': 'bg-zinc-600 text-white'
    };

    const timeWindowLabels: Record<string, string> = {
        'pre_market': '🌙 Pre-Market',
        'noise': '⚡ Opening Noise',
        'structure': '🏗️ Structure Building',
        'traps': '⚠️ Trap Zone',
        'adjustment': '🎯 Adjustment Window',
        'high_risk': '🔴 High Risk',
        'post_market': '🌙 Market Closed'
    };

    const currentState = state?.state || 'NO-TRADE';
    const timeWindow = state?.time_window || 'post_market';

    if (loading) {
        return (
            <div className="p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-sm animate-pulse">
                <div className="flex items-center gap-3">
                    <div className="w-24 h-8 bg-zinc-200 dark:bg-zinc-700 rounded-full"></div>
                    <div className="flex-1 h-4 bg-zinc-200 dark:bg-zinc-700 rounded"></div>
                </div>
            </div>
        );
    }

    return (
        <div className="p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-sm space-y-3">
            {/* Main State Display */}
            <div className="flex items-center gap-3">
                <div className={`px-3 py-1.5 rounded-full text-xs font-black tracking-widest ${stateColors[currentState]}`}>
                    {currentState}
                </div>
                <div className="flex flex-col flex-1">
                    <span className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Market Condition</span>
                    <span className="text-xs text-zinc-800 dark:text-zinc-200 font-medium">
                        {state?.message || 'Analyzing market structure...'}
                    </span>
                </div>
                {state?.confidence && state.confidence > 0 && (
                    <div className="flex flex-col items-end">
                        <span className="text-[10px] text-zinc-500 font-bold">CONFIDENCE</span>
                        <span className="text-sm font-black text-blue-500">{state.confidence}%</span>
                    </div>
                )}
            </div>

            {/* Key Metrics Row */}
            {state && (
                <div className="grid grid-cols-5 gap-2 pt-2 border-t border-zinc-100 dark:border-zinc-800">
                    <div className="text-center">
                        <div className="text-[9px] text-zinc-500 font-bold">SPOT</div>
                        <div className="text-xs font-bold text-zinc-900 dark:text-white">{state.spot_price?.toLocaleString('en-IN', { minimumFractionDigits: 2 }) || '---'}</div>
                    </div>
                    <div className="text-center">
                        <div className="text-[9px] text-zinc-500 font-bold">ATM</div>
                        <div className="text-xs font-bold text-zinc-900 dark:text-white">{state.atm_strike || '---'}</div>
                    </div>
                    <div className="text-center">
                        <div className="text-[9px] text-zinc-500 font-bold">PCR</div>
                        <div className={`text-xs font-bold ${state.pcr > 1 ? 'text-emerald-500' : state.pcr < 0.7 ? 'text-rose-500' : 'text-zinc-900 dark:text-white'}`}>
                            {state.pcr?.toFixed(2) || '---'}
                        </div>
                    </div>
                    <div className="text-center">
                        <div className="text-[9px] text-zinc-500 font-bold">VIX</div>
                        <div className={`text-xs font-bold ${(state.vix || 0) > 18 ? 'text-rose-500' : 'text-zinc-900 dark:text-white'}`}>
                            {state.vix?.toFixed(1) || '---'}
                        </div>
                    </div>
                    <div className="text-center">
                        <div className="text-[9px] text-zinc-500 font-bold">RANGE</div>
                        <div className="text-xs font-bold text-zinc-900 dark:text-white">
                            {state.support && state.resistance ? `${state.support}-${state.resistance}` : '---'}
                        </div>
                    </div>
                </div>
            )}

            {/* Time Window & Tradability */}
            <div className="flex items-center justify-between pt-2 border-t border-zinc-100 dark:border-zinc-800">
                <div className="text-[10px] text-zinc-500">
                    {timeWindowLabels[timeWindow] || timeWindow}
                </div>
                <div className={`text-[10px] font-bold px-2 py-0.5 rounded ${state?.tradable ? 'bg-emerald-500/10 text-emerald-600' : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500'}`}>
                    {state?.tradable ? '✓ TRADABLE' : '✗ NO TRADE'}
                </div>
            </div>

            {/* Adjustment Signal */}
            {state?.adjustment?.detected && state.adjustment.trade_setup && (
                <div className="p-2 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800 rounded-lg">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-purple-600 dark:text-purple-400">🎯 ADJUSTMENT SIGNAL</span>
                        <span className="text-[10px] text-purple-500">{state.adjustment.confidence}% confidence</span>
                    </div>
                    <div className="text-xs text-purple-700 dark:text-purple-300 mt-1">
                        <strong>{state.adjustment.trade_setup.action}</strong>: {state.adjustment.trade_setup.rationale}
                    </div>
                </div>
            )}

            {/* Alerts */}
            {state?.alerts && state.alerts.length > 0 && (
                <div className="space-y-1 pt-2 border-t border-zinc-100 dark:border-zinc-800">
                    {state.alerts.slice(0, 3).map((alert, idx) => (
                        <div key={idx} className={`text-[10px] flex items-center gap-1 ${alert.type === 'SIGNAL' ? 'text-purple-600' :
                                alert.type === 'WARNING' ? 'text-amber-600' :
                                    'text-zinc-500'
                            }`}>
                            <span>{alert.type === 'SIGNAL' ? '🎯' : alert.type === 'WARNING' ? '⚠️' : 'ℹ️'}</span>
                            <span>{alert.message}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
