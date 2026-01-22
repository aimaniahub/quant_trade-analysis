'use client';

import { useState, useEffect } from 'react';
import { api } from '../lib/api';

interface StrategyData {
    status: 'scanning' | 'signal' | 'no_trade';
    strategy_type: string;
    strike?: number;
    action?: string;
    rationale?: string;
    confidence?: number;
    invalidation?: string;
    time_window?: string;
}

export default function ActiveStrategy() {
    const [strategy, setStrategy] = useState<StrategyData>({
        status: 'scanning',
        strategy_type: 'Adjustment Setup (A1)'
    });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchStrategy = async () => {
            try {
                const data = await api.market.getMarketState();

                if (data?.adjustment?.detected && data.adjustment.trade_setup) {
                    const setup = data.adjustment.trade_setup;
                    setStrategy({
                        status: 'signal',
                        strategy_type: 'Adjustment Trade',
                        strike: setup.strikes?.[0] || data.atm_strike,
                        action: setup.action,
                        rationale: setup.rationale,
                        confidence: data.adjustment.confidence,
                        invalidation: `Spot move > 100 pts from ${data.spot_price?.toFixed(0)}`,
                        time_window: data.time_window
                    });
                } else if (data?.tradable && data.state === 'TREND') {
                    setStrategy({
                        status: 'scanning',
                        strategy_type: 'Directional Setup',
                        confidence: data.confidence,
                        rationale: data.message,
                        time_window: data.time_window
                    });
                } else {
                    setStrategy({
                        status: 'no_trade',
                        strategy_type: data?.state === 'RANGE' ? 'Range Bound' : 'Waiting',
                        rationale: data?.message || 'No actionable setup detected',
                        time_window: data?.time_window
                    });
                }
            } catch (err) {
                setStrategy({
                    status: 'scanning',
                    strategy_type: 'Adjustment Setup (A1)'
                });
            } finally {
                setLoading(false);
            }
        };

        fetchStrategy();
        const interval = setInterval(fetchStrategy, 30000);
        return () => clearInterval(interval);
    }, []);

    const statusColors = {
        scanning: 'border-blue-500 bg-blue-500/10',
        signal: 'border-purple-500 bg-purple-500/10',
        no_trade: 'border-zinc-400 bg-zinc-100 dark:bg-zinc-800'
    };

    const statusIcons = {
        scanning: (
            <div className="w-6 h-6 border-2 border-blue-500 rounded-full border-t-transparent animate-spin"></div>
        ),
        signal: (
            <div className="w-6 h-6 rounded-full bg-purple-500 flex items-center justify-center text-white text-xs font-bold">🎯</div>
        ),
        no_trade: (
            <div className="w-6 h-6 rounded-full bg-zinc-400 flex items-center justify-center text-white text-xs font-bold">—</div>
        )
    };

    const timeWindowLabel: Record<string, string> = {
        'pre_market': 'Pre-Market',
        'noise': 'Opening (9:15-10:30)',
        'structure': 'Structure (10:30-12:30)',
        'traps': 'Traps (12:30-2:30)',
        'adjustment': 'Adjustment (2:30-3:20)',
        'high_risk': 'High Risk',
        'post_market': 'After Hours'
    };

    return (
        <div className="p-6 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl">
            <h4 className="font-black text-xs uppercase tracking-widest text-zinc-400 mb-4">Active Strategy</h4>

            {loading ? (
                <div className="flex items-center gap-4">
                    <div className="p-3 bg-zinc-100 dark:bg-zinc-800 rounded-lg animate-pulse">
                        <div className="w-6 h-6 bg-zinc-200 dark:bg-zinc-700 rounded-full"></div>
                    </div>
                    <div className="flex-1 h-4 bg-zinc-100 dark:bg-zinc-800 rounded animate-pulse"></div>
                </div>
            ) : strategy.status === 'signal' ? (
                <div className="space-y-3">
                    <div className="flex items-start gap-4">
                        <div className={`p-3 rounded-lg ${statusColors[strategy.status]}`}>
                            {statusIcons[strategy.status]}
                        </div>
                        <div className="flex-1">
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-bold text-purple-600 dark:text-purple-400">
                                    {strategy.action}
                                </span>
                                {strategy.strike && (
                                    <span className="text-sm font-mono font-bold text-zinc-900 dark:text-white">
                                        @ {strategy.strike}
                                    </span>
                                )}
                                {strategy.confidence && (
                                    <span className="text-[10px] px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-600 rounded">
                                        {strategy.confidence}% conf
                                    </span>
                                )}
                            </div>
                            <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-1">
                                {strategy.rationale}
                            </p>
                        </div>
                    </div>

                    {strategy.invalidation && (
                        <div className="flex items-center gap-2 text-[10px] text-zinc-500 border-t border-zinc-100 dark:border-zinc-800 pt-2">
                            <span className="font-bold text-rose-500">INVALIDATION:</span>
                            <span>{strategy.invalidation}</span>
                        </div>
                    )}
                </div>
            ) : (
                <div className="flex items-center gap-4">
                    <div className={`p-3 rounded-lg ${statusColors[strategy.status]}`}>
                        {statusIcons[strategy.status]}
                    </div>
                    <div className="flex-1">
                        <p className="text-sm text-zinc-600 dark:text-zinc-400">
                            {strategy.status === 'scanning' ? (
                                <>Scanning for <span className="text-zinc-900 dark:text-white font-bold">{strategy.strategy_type}</span> in ATM strikes...</>
                            ) : (
                                <>{strategy.rationale}</>
                            )}
                        </p>
                        {strategy.time_window && (
                            <p className="text-[10px] text-zinc-400 mt-1">
                                Window: {timeWindowLabel[strategy.time_window] || strategy.time_window}
                            </p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
