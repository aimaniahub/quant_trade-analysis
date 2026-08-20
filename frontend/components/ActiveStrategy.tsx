'use client';

import { api } from '../lib/api';
import { useApiQuery } from '../lib/hooks/useApiQuery';

interface TradeSetup {
    action?: string;
    rationale?: string;
    strikes?: number[];
    bias?: string;
    invalidation?: string;
    trades?: Array<{ strike?: number; instrument?: string; type?: string; rationale?: string }>;
}

interface MarketStateData {
    state?: string;
    confidence?: number;
    message?: string;
    time_window?: string;
    tradable?: boolean;
    spot_price?: number;
    atm_strike?: number;
    adjustment?: {
        detected?: boolean;
        confidence?: number;
        conditions?: string[];
        trade_setup?: TradeSetup | null;
    };
    strike_guidance?: {
        suggested?: boolean;
        bias?: string;
        trades?: Array<{ strike?: number; instrument?: string; type?: string; rationale?: string }>;
        expert_note?: string;
    };
}

type StrategyStatus = 'scanning' | 'signal' | 'no_trade';

function deriveStrategy(data: MarketStateData | null | undefined) {
    if (!data) {
        return {
            status: 'scanning' as StrategyStatus,
            strategy_type: 'Market State',
            rationale: 'Waiting for market data...',
        };
    }

    const setup = data.adjustment?.trade_setup;
    const guidanceTrades = data.strike_guidance?.trades || [];

    if (data.adjustment?.detected && setup) {
        const strike = setup.strikes?.[0] ?? guidanceTrades[0]?.strike ?? data.atm_strike;
        return {
            status: 'signal' as StrategyStatus,
            strategy_type:
                data.state === 'ADJUSTMENT'
                    ? 'Adjustment Trade'
                    : data.state === 'INTENT'
                      ? 'Institutional Intent'
                      : 'Directional Setup',
            strike,
            action: setup.action,
            rationale: setup.rationale || data.message,
            confidence: data.adjustment.confidence ?? data.confidence,
            invalidation:
                setup.invalidation ||
                (data.spot_price
                    ? `Spot move > ${Math.max(50, Math.round(data.spot_price * 0.005))} pts from ${Math.round(data.spot_price)}`
                    : undefined),
            time_window: data.time_window,
        };
    }

    // Fallback: tradable + strike guidance without adjustment wrapper
    if (data.tradable && data.strike_guidance?.suggested && guidanceTrades.length > 0) {
        const primary = guidanceTrades[0];
        return {
            status: 'signal' as StrategyStatus,
            strategy_type: data.state === 'INTENT' ? 'Institutional Intent' : 'Directional Setup',
            strike: primary.strike ?? data.atm_strike,
            action: `BUY ${primary.instrument || 'CE'} (${primary.type || 'ATM_BUY'})`,
            rationale: primary.rationale || data.strike_guidance.expert_note || data.message,
            confidence: data.confidence,
            invalidation: data.spot_price
                ? `Spot structure breaks around ${Math.round(data.spot_price)}`
                : undefined,
            time_window: data.time_window,
        };
    }

    if (data.tradable && (data.state === 'TREND' || data.state === 'INTENT' || data.state === 'ADJUSTMENT')) {
        return {
            status: 'scanning' as StrategyStatus,
            strategy_type:
                data.state === 'INTENT'
                    ? 'Intent Watch'
                    : data.state === 'ADJUSTMENT'
                      ? 'Adjustment Window'
                      : 'Directional Setup',
            confidence: data.confidence,
            rationale: data.message,
            time_window: data.time_window,
        };
    }

    return {
        status: 'no_trade' as StrategyStatus,
        strategy_type:
            data.state === 'RANGE'
                ? 'Range Bound'
                : data.state === 'NO-TRADE'
                  ? 'No Trade'
                  : 'Waiting',
        rationale: data.message || 'No actionable setup detected',
        time_window: data.time_window,
        confidence: data.confidence,
    };
}

export default function ActiveStrategy() {
    const { data, isLoading } = useApiQuery<MarketStateData>(
        ['market', 'state', 'NIFTY'],
        () => api.market.getMarketState() as Promise<MarketStateData>,
        { refetchInterval: 45000 },
    );

    const strategy = deriveStrategy(data);

    const statusColors = {
        scanning: 'border-blue-500 bg-blue-500/10',
        signal: 'border-purple-500 bg-purple-500/10',
        no_trade: 'border-zinc-400 bg-zinc-100 dark:bg-zinc-800',
    };

    const statusIcons = {
        scanning: (
            <div className="w-6 h-6 border-2 border-blue-500 rounded-full border-t-transparent animate-spin"></div>
        ),
        signal: (
            <div className="w-6 h-6 rounded-full bg-purple-500 flex items-center justify-center text-white text-xs font-bold">
                🎯
            </div>
        ),
        no_trade: (
            <div className="w-6 h-6 rounded-full bg-zinc-400 flex items-center justify-center text-white text-xs font-bold">
                —
            </div>
        ),
    };

    const timeWindowLabel: Record<string, string> = {
        pre_market: 'Pre-Market',
        noise: 'Opening (9:15-10:30)',
        structure: 'Structure (10:30-12:30)',
        traps: 'Traps (12:30-2:30)',
        adjustment: 'Adjustment (2:30-3:20)',
        high_risk: 'High Risk',
        post_market: 'After Hours',
    };

    return (
        <div className="p-6 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl">
            <h4 className="font-black text-xs uppercase tracking-widest text-zinc-400 mb-4">
                Active Strategy
            </h4>

            {isLoading && !data ? (
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
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-bold text-purple-600 dark:text-purple-400">
                                    {strategy.action}
                                </span>
                                {strategy.strike != null && (
                                    <span className="text-sm font-mono font-bold text-zinc-900 dark:text-white">
                                        @ {strategy.strike}
                                    </span>
                                )}
                                {strategy.confidence != null && strategy.confidence > 0 && (
                                    <span className="text-[10px] px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-600 rounded">
                                        {strategy.confidence}% conf
                                    </span>
                                )}
                                <span className="text-[10px] px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-500 rounded">
                                    {strategy.strategy_type}
                                </span>
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
                                <>
                                    Scanning for{' '}
                                    <span className="text-zinc-900 dark:text-white font-bold">
                                        {strategy.strategy_type}
                                    </span>
                                    {strategy.rationale ? ` — ${strategy.rationale}` : '...'}
                                </>
                            ) : (
                                <>{strategy.rationale}</>
                            )}
                        </p>
                        {strategy.time_window && (
                            <p className="text-[10px] text-zinc-400 mt-1">
                                Window:{' '}
                                {timeWindowLabel[strategy.time_window] || strategy.time_window}
                            </p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
