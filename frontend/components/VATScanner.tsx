'use client';

import { useState, useEffect } from 'react';
import { api } from '../lib/api';

// Types - Enhanced for new VAT response
interface VATOpportunity {
    offset: number;
    call_strike: number;
    put_strike: number;
    ce_ltp: number;
    pe_ltp: number;
    gap: number;
    is_opportunity: boolean;
    signal: string;
    undervalued_strike: number;
    entry_price: number;
    theoretical_target: number;
    // Enhanced fields
    confidence_score?: number;
    signal_strength?: string;
    stop_loss?: number;
    target_1?: number;
    risk_reward_ratio?: number;
}

interface VATResult {
    success: boolean;
    symbol: string;
    spot_price: number;
    anchor_strike: number;
    total_opportunities: number;
    opportunities: VATOpportunity[];
    full_analysis: VATOpportunity[];
    // Enhanced fields
    expiry_phase?: string;
    is_optimal_window?: boolean;
}

interface VATScannerProps {
    onBack: () => void;
}

// Helper function to get confidence color
const getConfidenceColor = (score: number): string => {
    if (score >= 80) return 'text-emerald-500';
    if (score >= 60) return 'text-amber-500';
    if (score >= 40) return 'text-orange-500';
    return 'text-zinc-500';
};

const getConfidenceBg = (score: number): string => {
    if (score >= 80) return 'bg-emerald-500/10 border-emerald-500/30';
    if (score >= 60) return 'bg-amber-500/10 border-amber-500/30';
    if (score >= 40) return 'bg-orange-500/10 border-orange-500/30';
    return 'bg-zinc-500/10 border-zinc-500/30';
};

const getStrengthLabel = (strength: string): { label: string; emoji: string } => {
    switch (strength) {
        case 'high': return { label: 'HIGH CONFIDENCE', emoji: '🔥' };
        case 'medium': return { label: 'MEDIUM', emoji: '⚡' };
        case 'low': return { label: 'LOW', emoji: '⚠️' };
        default: return { label: 'SKIP', emoji: '🚫' };
    }
};

export default function VATScanner({ onBack }: VATScannerProps) {
    const [selectedSymbol, setSelectedSymbol] = useState("NSE:NIFTY50-INDEX");
    const [data, setData] = useState<VATResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchVATData = async () => {
        setLoading(true);
        setError(null);
        try {
            const result = await api.market.scanVAT(selectedSymbol);
            if (result.success) {
                setData(result);
            } else {
                setError(result.error || "Failed to fetch analysis");
            }
        } catch (err: any) {
            setError(err.message || "Network error");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchVATData();
        const interval = setInterval(fetchVATData, 30000); // Poll every 30s
        return () => clearInterval(interval);
    }, [selectedSymbol]);

    return (
        <div className="min-h-screen bg-zinc-50 dark:bg-black p-4 md:p-8 text-zinc-900 dark:text-zinc-100">
            <div className="max-w-7xl mx-auto">
                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
                    <div className="flex items-center gap-4">
                        <button
                            onClick={onBack}
                            className="p-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
                        >
                            ←
                        </button>
                        <div>
                            <h1 className="text-2xl font-black italic tracking-tighter uppercase">
                                Value Adjustment Scanner<span className="text-purple-600">.</span>
                            </h1>
                            <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest mt-1">
                                Premium Dislocation & Arbitrage Finder
                            </p>
                        </div>
                    </div>

                    <div className="flex gap-2">
                        <button
                            onClick={() => setSelectedSymbol("NSE:NIFTY50-INDEX")}
                            className={`px-4 py-2 text-xs font-bold uppercase rounded-lg transition-all ${selectedSymbol.includes("NIFTY50")
                                ? 'bg-purple-600 text-white shadow-lg'
                                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600'
                                }`}
                        >
                            NIFTY 50
                        </button>
                        <button
                            onClick={() => setSelectedSymbol("NSE:NIFTYBANK-INDEX")}
                            className={`px-4 py-2 text-xs font-bold uppercase rounded-lg transition-all ${selectedSymbol.includes("BANK")
                                ? 'bg-purple-600 text-white shadow-lg'
                                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600'
                                }`}
                        >
                            BANK NIFTY
                        </button>
                        <button
                            onClick={fetchVATData}
                            className="px-4 py-2 bg-zinc-200 dark:bg-zinc-800 hover:bg-zinc-300 dark:hover:bg-zinc-700 rounded-lg text-xs font-bold uppercase"
                        >
                            ↻
                        </button>
                    </div>
                </div>

                {loading && !data && (
                    <div className="text-center py-20">
                        <div className="animate-spin w-8 h-8 border-4 border-purple-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                        <p className="text-zinc-500 font-medium">Scanning Option Chain...</p>
                    </div>
                )}

                {error && (
                    <div className="p-4 bg-rose-50 dark:bg-rose-900/20 text-rose-600 rounded-xl mb-6">
                        Error: {error}
                    </div>
                )}

                {data && (
                    <div className="space-y-8">
                        {/* Summary Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                            <div className="p-6 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl">
                                <p className="text-xs font-bold text-zinc-500 uppercase">Spot Price</p>
                                <p className="text-3xl font-black mt-2">
                                    {data.spot_price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                                </p>
                                <p className="text-xs text-zinc-400 mt-1">Anchor: {data.anchor_strike}</p>
                            </div>

                            <div className="p-6 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl">
                                <p className="text-xs font-bold text-zinc-500 uppercase">Opportunities</p>
                                <p className="text-3xl font-black mt-2 text-purple-500">{data.total_opportunities}</p>
                                <p className="text-xs text-zinc-400 mt-1">
                                    {data.total_opportunities > 0 ? "Actionable setups" : "No dislocations"}
                                </p>
                            </div>

                            <div className="p-6 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl">
                                <p className="text-xs font-bold text-zinc-500 uppercase">Expiry Phase</p>
                                <p className={`text-xl font-black mt-2 ${data.expiry_phase === 'ex-d0' ? 'text-rose-500' :
                                        data.expiry_phase === 'ex-d1' ? 'text-amber-500' :
                                            data.expiry_phase === 'ex-d2' ? 'text-blue-500' : 'text-zinc-500'
                                    }`}>
                                    {data.expiry_phase?.toUpperCase() || 'REGULAR'}
                                </p>
                                <p className="text-xs text-zinc-400 mt-1">
                                    {data.expiry_phase === 'ex-d0' ? '🔥 EXPIRY DAY' :
                                        data.expiry_phase === 'ex-d1' ? '⚡ 1 day left' :
                                            data.expiry_phase === 'ex-d2' ? '📅 2 days left' : 'Normal trading'}
                                </p>
                            </div>

                            <div className={`p-6 rounded-2xl border ${data.is_optimal_window
                                ? 'bg-gradient-to-br from-emerald-500/10 to-green-500/10 border-emerald-500/20'
                                : 'bg-gradient-to-br from-zinc-500/10 to-zinc-500/10 border-zinc-500/20'}`}>
                                <p className="text-xs font-bold text-zinc-500 uppercase">Trading Window</p>
                                <div className="mt-2 flex items-center gap-2">
                                    <div className={`w-3 h-3 rounded-full ${data.is_optimal_window ? 'bg-emerald-500 animate-pulse' : 'bg-zinc-500'}`}></div>
                                    <span className={`font-bold text-lg ${data.is_optimal_window ? 'text-emerald-500' : 'text-zinc-500'}`}>
                                        {data.is_optimal_window ? "OPTIMAL" : "OFF-HOURS"}
                                    </span>
                                </div>
                                <p className="text-xs text-zinc-400 mt-1">
                                    {data.is_optimal_window ? '10AM - 3PM IST' : 'Wait for market hours'}
                                </p>
                            </div>
                        </div>

                        {/* Opportunities List - Enhanced */}
                        {data.opportunities.length > 0 && (
                            <div>
                                <h3 className="text-lg font-black uppercase mb-4 flex items-center gap-2">
                                    🔥 Top Opportunities
                                </h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                    {data.opportunities.map((opp, idx) => (
                                        <div key={idx} className={`p-5 bg-white dark:bg-zinc-900 border-2 rounded-xl hover:shadow-lg transition-all relative overflow-hidden group ${opp.signal_strength ? getConfidenceBg(opp.confidence_score || 0) : 'border-purple-500/30 hover:border-purple-500'
                                            }`}>
                                            {/* Confidence Badge */}
                                            {opp.confidence_score !== undefined && (
                                                <div className={`absolute top-0 right-0 p-2 ${opp.confidence_score >= 80 ? 'bg-emerald-500' :
                                                        opp.confidence_score >= 60 ? 'bg-amber-500' : 'bg-zinc-500'
                                                    } text-white text-[10px] font-bold rounded-bl-xl`}>
                                                    {opp.confidence_score}% {getStrengthLabel(opp.signal_strength || '').emoji}
                                                </div>
                                            )}

                                            <div className="flex justify-between items-start mb-4">
                                                <div>
                                                    <span className={`px-2 py-1 rounded text-[10px] font-bold uppercase ${opp.signal === 'BUY_CE' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-rose-500/10 text-rose-500'
                                                        }`}>
                                                        {opp.signal.replace('_', ' ')}
                                                    </span>
                                                    <h4 className="text-xl font-black mt-2">
                                                        {opp.undervalued_strike} {opp.signal === 'BUY_CE' ? 'CE' : 'PE'}
                                                    </h4>
                                                </div>
                                            </div>

                                            {/* Trade Parameters */}
                                            <div className="grid grid-cols-3 gap-1 text-xs mb-3 bg-zinc-50 dark:bg-zinc-800/50 p-2 rounded-lg">
                                                <div className="text-center">
                                                    <p className="text-[10px] text-zinc-500 uppercase">Entry</p>
                                                    <p className="font-bold text-emerald-500">₹{opp.entry_price}</p>
                                                </div>
                                                <div className="text-center border-x border-zinc-200 dark:border-zinc-700">
                                                    <p className="text-[10px] text-zinc-500 uppercase">SL</p>
                                                    <p className="font-bold text-rose-500">₹{opp.stop_loss || '-'}</p>
                                                </div>
                                                <div className="text-center">
                                                    <p className="text-[10px] text-zinc-500 uppercase">Target</p>
                                                    <p className="font-bold text-blue-500">₹{opp.target_1 || opp.theoretical_target}</p>
                                                </div>
                                            </div>

                                            {/* Risk Reward */}
                                            {opp.risk_reward_ratio && (
                                                <div className="flex justify-between items-center text-[10px] mb-3 px-2 py-1 bg-purple-500/10 rounded">
                                                    <span className="text-zinc-500">Risk:Reward</span>
                                                    <span className={`font-bold ${opp.risk_reward_ratio >= 2 ? 'text-emerald-500' : opp.risk_reward_ratio >= 1.5 ? 'text-amber-500' : 'text-zinc-500'}`}>
                                                        1:{opp.risk_reward_ratio.toFixed(1)}
                                                    </span>
                                                </div>
                                            )}

                                            {/* Premium Gap */}
                                            <div className="flex justify-between text-[10px] font-medium text-zinc-500 border-t border-zinc-100 dark:border-zinc-800 pt-3">
                                                <div>
                                                    Call ({opp.call_strike}): ₹{opp.ce_ltp}
                                                </div>
                                                <div className="font-bold text-purple-500">
                                                    Gap: ₹{opp.gap.toFixed(2)}
                                                </div>
                                                <div>
                                                    Put ({opp.put_strike}): ₹{opp.pe_ltp}
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Full Analysis Table - Enhanced */}
                        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl overflow-hidden">
                            <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800">
                                <h3 className="font-black text-sm uppercase">Full Equidistant Analysis</h3>
                            </div>
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm text-left">
                                    <thead className="text-[10px] font-bold text-zinc-500 uppercase bg-zinc-50 dark:bg-zinc-800/50">
                                        <tr>
                                            <th className="px-4 py-3">Offset</th>
                                            <th className="px-4 py-3">Call Strike</th>
                                            <th className="px-4 py-3">Put Strike</th>
                                            <th className="px-4 py-3 text-right">Call ₹</th>
                                            <th className="px-4 py-3 text-right">Put ₹</th>
                                            <th className="px-4 py-3 text-right">Gap</th>
                                            <th className="px-4 py-3 text-center">Confidence</th>
                                            <th className="px-4 py-3 text-center">R:R</th>
                                            <th className="px-4 py-3 text-center">Signal</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                                        {data.full_analysis.map((row, idx) => (
                                            <tr key={idx} className={`hover:bg-zinc-50 dark:hover:bg-zinc-800/30 transition-colors ${row.is_opportunity ? 'bg-purple-500/5' : ''}`}>
                                                <td className="px-4 py-3 font-medium">±{row.offset}</td>
                                                <td className="px-4 py-3 text-zinc-500">{row.call_strike}</td>
                                                <td className="px-4 py-3 text-zinc-500">{row.put_strike}</td>
                                                <td className={`px-4 py-3 text-right font-bold ${row.ce_ltp < row.pe_ltp ? 'text-emerald-500' : ''}`}>
                                                    ₹{row.ce_ltp}
                                                </td>
                                                <td className={`px-4 py-3 text-right font-bold ${row.pe_ltp < row.ce_ltp ? 'text-emerald-500' : ''}`}>
                                                    ₹{row.pe_ltp}
                                                </td>
                                                <td className="px-4 py-3 text-right font-mono">
                                                    {row.gap.toFixed(2)}
                                                </td>
                                                <td className="px-4 py-3 text-center">
                                                    {row.confidence_score !== undefined ? (
                                                        <span className={`font-bold ${getConfidenceColor(row.confidence_score)}`}>
                                                            {row.confidence_score}%
                                                        </span>
                                                    ) : '-'}
                                                </td>
                                                <td className="px-4 py-3 text-center">
                                                    {row.risk_reward_ratio ? (
                                                        <span className={`font-mono ${row.risk_reward_ratio >= 1.5 ? 'text-emerald-500' : 'text-zinc-400'}`}>
                                                            1:{row.risk_reward_ratio.toFixed(1)}
                                                        </span>
                                                    ) : '-'}
                                                </td>
                                                <td className="px-4 py-3 text-center">
                                                    {row.is_opportunity ? (
                                                        <span className={`px-2 py-1 text-[10px] font-bold rounded uppercase ${row.signal_strength === 'high' ? 'bg-emerald-500/10 text-emerald-500' :
                                                                row.signal_strength === 'medium' ? 'bg-amber-500/10 text-amber-500' :
                                                                    'bg-purple-500/10 text-purple-500'
                                                            }`}>
                                                            {row.signal_strength || 'Signal'}
                                                        </span>
                                                    ) : (
                                                        <span className="text-zinc-400 text-[10px] uppercase">—</span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* Strategy Info */}
                        <div className="p-4 bg-zinc-100 dark:bg-zinc-900/50 rounded-xl text-xs text-zinc-500">
                            <p className="font-bold mb-2">📚 Value Adjustment Theory</p>
                            <p>Equidistant strikes should have similar premiums. When they don't, buy the undervalued option and target convergence. Best on expiry days (ex-d2 to ex-d0), during 10AM-3PM IST.</p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
