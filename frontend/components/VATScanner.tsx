'use client';

import { useState, useEffect } from 'react';
import { api } from '../lib/api';

// Types
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
}

interface VATResult {
    success: boolean;
    symbol: string;
    spot_price: number;
    anchor_strike: number;
    total_opportunities: number;
    opportunities: VATOpportunity[];
    full_analysis: VATOpportunity[];
}

interface VATScannerProps {
    onBack: () => void;
}

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
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                            <div className="p-6 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl">
                                <p className="text-xs font-bold text-zinc-500 uppercase">Spot Price</p>
                                <p className="text-3xl font-black mt-2">
                                    {data.spot_price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                                </p>
                                <p className="text-xs text-zinc-400 mt-1">Anchor: {data.anchor_strike}</p>
                            </div>

                            <div className="p-6 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl">
                                <p className="text-xs font-bold text-zinc-500 uppercase">Opportunities Found</p>
                                <p className="text-3xl font-black mt-2 text-purple-500">{data.total_opportunities}</p>
                                <p className="text-xs text-zinc-400 mt-1">
                                    {data.total_opportunities > 0 ? "Actionable setups detected" : "No dislocations found"}
                                </p>
                            </div>

                            <div className="p-6 bg-gradient-to-br from-purple-500/10 to-indigo-500/10 border border-purple-500/20 rounded-2xl">
                                <p className="text-xs font-bold text-purple-500 uppercase">Strategy Status</p>
                                <div className="mt-2 flex items-center gap-2">
                                    <div className={`w-3 h-3 rounded-full ${data.total_opportunities > 0 ? 'bg-emerald-500 animate-pulse' : 'bg-zinc-500'}`}></div>
                                    <span className="font-bold text-lg">
                                        {data.total_opportunities > 0 ? "ACTIVE" : "MONITORING"}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Opportunities List */}
                        {data.opportunities.length > 0 && (
                            <div>
                                <h3 className="text-lg font-black uppercase mb-4 flex items-center gap-2">
                                    🔥 Top Opportunities
                                </h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                    {data.opportunities.map((opp, idx) => (
                                        <div key={idx} className="p-5 bg-white dark:bg-zinc-900 border-2 border-purple-500/30 rounded-xl hover:border-purple-500 transition-all shadow-lg hover:shadow-purple-500/10 relative overflow-hidden group">
                                            <div className="absolute top-0 right-0 p-2 bg-purple-500 text-white text-[10px] font-bold rounded-bl-xl">
                                                GAP: ₹{opp.gap.toFixed(2)}
                                            </div>

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

                                            <div className="flex items-center justify-between text-sm mb-4 bg-zinc-50 dark:bg-zinc-800/50 p-2 rounded-lg">
                                                <div className="text-center">
                                                    <p className="text-[10px] text-zinc-500 uppercase">Entry</p>
                                                    <p className="font-bold text-emerald-500">₹{opp.entry_price}</p>
                                                </div>
                                                <div className="text-zinc-300">➜</div>
                                                <div className="text-center">
                                                    <p className="text-[10px] text-zinc-500 uppercase">Target</p>
                                                    <p className="font-bold text-blue-500">₹{opp.theoretical_target}</p>
                                                </div>
                                            </div>

                                            <div className="flex justify-between text-[10px] font-medium text-zinc-500 border-t border-zinc-100 dark:border-zinc-800 pt-3">
                                                <div>
                                                    Call ({opp.call_strike}): ₹{opp.ce_ltp}
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

                        {/* Full Analysis Table */}
                        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl overflow-hidden">
                            <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800">
                                <h3 className="font-black text-sm uppercase">Full Equidistant Analysis</h3>
                            </div>
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm text-left">
                                    <thead className="text-[10px] font-bold text-zinc-500 uppercase bg-zinc-50 dark:bg-zinc-800/50">
                                        <tr>
                                            <th className="px-6 py-3">Offset</th>
                                            <th className="px-6 py-3">Call Strike</th>
                                            <th className="px-6 py-3">Put Strike</th>
                                            <th className="px-6 py-3 text-right">Call Price</th>
                                            <th className="px-6 py-3 text-right">Put Price</th>
                                            <th className="px-6 py-3 text-right">Gap</th>
                                            <th className="px-6 py-3 text-center">Status</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                                        {data.full_analysis.map((row, idx) => (
                                            <tr key={idx} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/30 transition-colors">
                                                <td className="px-6 py-4 font-medium">±{row.offset}</td>
                                                <td className="px-6 py-4 text-zinc-500">{row.call_strike}</td>
                                                <td className="px-6 py-4 text-zinc-500">{row.put_strike}</td>
                                                <td className={`px-6 py-4 text-right font-bold ${row.ce_ltp < row.pe_ltp ? 'text-emerald-500' : ''}`}>
                                                    ₹{row.ce_ltp}
                                                </td>
                                                <td className={`px-6 py-4 text-right font-bold ${row.pe_ltp < row.ce_ltp ? 'text-emerald-500' : ''}`}>
                                                    ₹{row.pe_ltp}
                                                </td>
                                                <td className="px-6 py-4 text-right font-mono">
                                                    {row.gap.toFixed(2)}
                                                </td>
                                                <td className="px-6 py-4 text-center">
                                                    {row.is_opportunity ? (
                                                        <span className="px-2 py-1 bg-purple-500/10 text-purple-500 text-[10px] font-bold rounded uppercase">
                                                            Signal
                                                        </span>
                                                    ) : (
                                                        <span className="text-zinc-400 text-[10px] uppercase">Balanced</span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
