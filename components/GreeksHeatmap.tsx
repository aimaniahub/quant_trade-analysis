'use client';

import { useState } from 'react';
import { api } from '../lib/api';
import { useApiQuery } from '../lib/hooks/useApiQuery';

interface HeatmapRow {
    strike: number;
    is_atm: boolean;
    is_itm_ce: boolean;
    is_itm_pe: boolean;
    call_delta: number;
    call_gamma: number;
    call_theta: number;
    call_vega: number;
    call_iv: number;
    call_oi: number;
    call_ltp: number;
    put_delta: number;
    put_gamma: number;
    put_theta: number;
    put_vega: number;
    put_iv: number;
    put_oi: number;
    put_ltp: number;
}

interface HeatmapData {
    symbol: string;
    spot_price: number;
    atm_strike: number;
    max_gamma_strike: number | null;
    heatmap: HeatmapRow[];
    timestamp: string;
}

interface GreeksHeatmapProps {
    symbol: string;
    strikeCount?: number;
    autoRefresh?: boolean;
    refreshInterval?: number;
}

export default function GreeksHeatmap({ symbol, strikeCount = 15, autoRefresh = true, refreshInterval = 60000 }: GreeksHeatmapProps) {
    const [viewMode, setViewMode] = useState<'delta' | 'gamma' | 'theta' | 'oi'>('delta');

    const { data, isLoading, error } = useApiQuery<HeatmapData>(
        ['market', 'greeks-heatmap', symbol, strikeCount],
        () => api.market.getGreeksHeatmap(symbol, strikeCount) as Promise<HeatmapData>,
        {
            enabled: Boolean(symbol),
            refetchInterval: autoRefresh ? refreshInterval : false,
        },
    );

    // Color intensity based on value
    const getHeatColor = (value: number, max: number, isPositive: boolean = true) => {
        const intensity = Math.min(Math.abs(value) / max, 1);
        if (isPositive) {
            return value > 0
                ? `rgba(34, 197, 94, ${intensity * 0.8})`
                : `rgba(239, 68, 68, ${Math.abs(value / max) * 0.6})`;
        }
        return `rgba(59, 130, 246, ${intensity * 0.7})`;
    };

    const formatNumber = (num: number, decimals: number = 2) => {
        if (Math.abs(num) >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
        if (Math.abs(num) >= 1000) return `${(num / 1000).toFixed(1)}K`;
        return num.toFixed(decimals);
    };

    if (isLoading && !data) {
        return (
            <div className="p-6 bg-zinc-900 rounded-2xl border border-zinc-800 animate-pulse">
                <div className="h-6 bg-zinc-800 rounded w-1/4 mb-4" />
                <div className="space-y-2">
                    {[...Array(10)].map((_, i) => (
                        <div key={i} className="h-8 bg-zinc-800 rounded" />
                    ))}
                </div>
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

    // Calculate max values for normalization
    const maxDelta = Math.max(...data.heatmap.map(r => Math.max(Math.abs(r.call_delta), Math.abs(r.put_delta))));
    const maxGamma = Math.max(...data.heatmap.map(r => Math.max(r.call_gamma, r.put_gamma)));
    const maxTheta = Math.max(...data.heatmap.map(r => Math.max(Math.abs(r.call_theta), Math.abs(r.put_theta))));
    const maxOI = Math.max(...data.heatmap.map(r => Math.max(r.call_oi, r.put_oi)));

    return (
        <div className="bg-zinc-900 rounded-2xl border border-zinc-800 overflow-hidden">
            {/* Header */}
            <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
                <div>
                    <h3 className="text-sm font-bold text-white">Greeks Heatmap</h3>
                    <p className="text-xs text-zinc-500">Spot: ₹{data.spot_price.toFixed(2)}</p>
                </div>
                <div className="flex gap-1">
                    {(['delta', 'gamma', 'theta', 'oi'] as const).map((mode) => (
                        <button
                            key={mode}
                            onClick={() => setViewMode(mode)}
                            className={`px-3 py-1 text-xs font-bold uppercase rounded transition-all ${viewMode === mode
                                ? 'bg-blue-500 text-white'
                                : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                                }`}
                        >
                            {mode === 'oi' ? 'OI' : mode.charAt(0).toUpperCase() + mode.slice(1)}
                        </button>
                    ))}
                </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
                <table className="w-full text-xs">
                    <thead>
                        <tr className="bg-zinc-800/50 text-zinc-400">
                            <th className="py-2 px-3 text-center">CE {viewMode === 'oi' ? 'OI' : viewMode.toUpperCase()}</th>
                            <th className="py-2 px-3 text-center">CE LTP</th>
                            <th className="py-2 px-3 text-center font-bold text-white">STRIKE</th>
                            <th className="py-2 px-3 text-center">PE LTP</th>
                            <th className="py-2 px-3 text-center">PE {viewMode === 'oi' ? 'OI' : viewMode.toUpperCase()}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {data.heatmap.map((row, idx) => {
                            const callValue = viewMode === 'delta' ? row.call_delta
                                : viewMode === 'gamma' ? row.call_gamma
                                    : viewMode === 'theta' ? row.call_theta
                                        : row.call_oi;
                            const putValue = viewMode === 'delta' ? row.put_delta
                                : viewMode === 'gamma' ? row.put_gamma
                                    : viewMode === 'theta' ? row.put_theta
                                        : row.put_oi;
                            const maxVal = viewMode === 'delta' ? maxDelta
                                : viewMode === 'gamma' ? maxGamma
                                    : viewMode === 'theta' ? maxTheta
                                        : maxOI;

                            return (
                                <tr
                                    key={row.strike}
                                    className={`border-t border-zinc-800 ${row.is_atm ? 'bg-blue-500/20' : ''
                                        } ${row.strike === data.max_gamma_strike ? 'ring-2 ring-amber-500/50' : ''}`}
                                >
                                    <td
                                        className="py-2 px-3 text-center font-mono"
                                        style={{ backgroundColor: getHeatColor(callValue, maxVal, viewMode !== 'theta') }}
                                    >
                                        {viewMode === 'oi' ? formatNumber(callValue, 0) : callValue.toFixed(viewMode === 'gamma' ? 4 : 2)}
                                    </td>
                                    <td className={`py-2 px-3 text-center ${row.is_itm_ce ? 'text-emerald-400' : 'text-zinc-400'}`}>
                                        {row.call_ltp.toFixed(1)}
                                    </td>
                                    <td className={`py-2 px-3 text-center font-bold ${row.is_atm ? 'text-blue-400' : 'text-white'
                                        }`}>
                                        {row.strike}
                                        {row.strike === data.max_gamma_strike && (
                                            <span className="ml-1 text-amber-400" title="Max Gamma">⚡</span>
                                        )}
                                    </td>
                                    <td className={`py-2 px-3 text-center ${row.is_itm_pe ? 'text-rose-400' : 'text-zinc-400'}`}>
                                        {row.put_ltp.toFixed(1)}
                                    </td>
                                    <td
                                        className="py-2 px-3 text-center font-mono"
                                        style={{ backgroundColor: getHeatColor(putValue, maxVal, viewMode !== 'theta') }}
                                    >
                                        {viewMode === 'oi' ? formatNumber(putValue, 0) : putValue.toFixed(viewMode === 'gamma' ? 4 : 2)}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {/* Legend */}
            <div className="p-3 border-t border-zinc-800 flex items-center justify-between text-[10px] text-zinc-500">
                <div className="flex items-center gap-4">
                    <span>🔵 ATM Strike</span>
                    <span>⚡ Max Gamma (Pivot)</span>
                </div>
                <span>Auto-refresh: {autoRefresh ? `${refreshInterval / 1000}s` : 'Off'}</span>
            </div>
        </div>
    );
}
