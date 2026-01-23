"use client";

import { api } from "../lib/api";
import { useApiQuery } from "../lib/hooks/useApiQuery";

interface OptionChainProps {
    symbol?: string;
}

export default function OptionChainTable({ symbol = 'NSE:NIFTY50-INDEX' }: OptionChainProps) {
    const { data: chain, isLoading, error, refetch } = useApiQuery<any>(
        ["options", "chain", symbol],
        () => api.options.getChain(symbol),
        {
            refetchInterval: 30000,
            enabled: Boolean(symbol),
        },
    );

    if (isLoading && !chain) {
        return (
            <div className="w-full h-64 flex items-center justify-center bg-white dark:bg-zinc-900 border rounded-xl animate-pulse">
                <span className="text-zinc-400">Loading Option Chain...</span>
            </div>
        );
    }

    if (error) {
        return (
            <div className="w-full p-8 text-center bg-rose-50 dark:bg-rose-900/10 border border-rose-200 dark:border-rose-800 rounded-xl">
                <p className="text-rose-500 font-medium">{error.message}</p>
                <button
                    onClick={() => refetch()}
                    className="mt-4 px-4 py-2 bg-rose-500 text-white rounded-md text-sm hover:bg-rose-600 transition-colors"
                >
                    Retry
                </button>
            </div>
        );
    }

    const rows = chain?.chain || [];

    return (
        <div className="w-full overflow-hidden border border-zinc-200 dark:border-zinc-800 rounded-xl bg-white dark:bg-zinc-900 shadow-sm">
            <div className="bg-zinc-50 dark:bg-zinc-800/50 p-4 border-b border-zinc-200 dark:border-zinc-800 flex justify-between items-center">
                <h3 className="font-bold text-zinc-800 dark:text-zinc-100 flex items-center gap-2">
                    Option Chain: {symbol.split(':')[1]}
                    <span className="text-xs font-normal text-zinc-500 bg-zinc-200 dark:bg-zinc-700 px-2 py-0.5 rounded">
                        Near Expiry
                    </span>
                </h3>
                <div className="text-xs text-zinc-500 dark:text-zinc-400">
                    Spot: <span className="font-mono font-bold text-zinc-900 dark:text-white">{chain?.spot_price?.toFixed(2)}</span>
                </div>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse">
                    <thead>
                        <tr className="bg-zinc-50 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 uppercase tracking-wider font-bold">
                            <th className="py-3 px-2 border-r border-zinc-200 dark:border-zinc-700 text-center" colSpan={4}>CALLS</th>
                            <th className="py-3 px-2 border-r border-zinc-200 dark:border-zinc-700 text-center bg-zinc-100 dark:bg-zinc-700">STRIKE</th>
                            <th className="py-3 px-2 text-center" colSpan={4}>PUTS</th>
                        </tr>
                        <tr className="bg-zinc-50/50 dark:bg-zinc-800/50 text-[10px] text-zinc-500 dark:text-zinc-400 border-b border-zinc-200 dark:border-zinc-700">
                            <th className="py-2 px-1 text-center">OI</th>
                            <th className="py-2 px-1 text-center">IV</th>
                            <th className="py-2 px-1 text-center">CHG</th>
                            <th className="py-2 px-1 text-center border-r border-zinc-200 dark:border-zinc-700 font-bold text-zinc-900 dark:text-zinc-100">LTP</th>
                            <th className="py-2 px-1 text-center border-r border-zinc-200 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-700 font-bold text-zinc-900 dark:text-zinc-100">---</th>
                            <th className="py-2 px-1 text-center font-bold text-zinc-900 dark:text-zinc-100">LTP</th>
                            <th className="py-2 px-1 text-center">CHG</th>
                            <th className="py-2 px-1 text-center">IV</th>
                            <th className="py-2 px-1 text-center">OI</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row: any, idx: number) => {
                            const strike = row.strike_price;
                            const atmDist = Math.abs(strike - (chain?.spot_price || 0));
                            const isATM = atmDist < 25; // Approximate for NIFTY

                            return (
                                <tr
                                    key={`${idx}-${strike}`}
                                    className={`border-b border-zinc-100 dark:border-zinc-800 hover:bg-zinc-100/50 dark:hover:bg-zinc-800/50 transition-colors ${isATM ? 'bg-blue-500/5 dark:bg-blue-500/10' : ''}`}
                                >
                                    {/* CALLS */}
                                    <td className="py-3 px-1 text-center text-zinc-500">{(row.call?.oi / 1000).toFixed(1)}k</td>
                                    <td className="py-3 px-1 text-center text-zinc-500">{row.call?.iv?.toFixed(1) || '-'}</td>
                                    <td className={`py-3 px-1 text-center font-medium ${row.call?.chg >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                                        {row.call?.chg?.toFixed(1) || '0.0'}
                                    </td>
                                    <td className="py-3 px-1 text-center font-bold text-zinc-900 dark:text-zinc-100 border-r border-zinc-200 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-800/20">
                                        {row.call?.ltp?.toFixed(2) || '0.00'}
                                    </td>

                                    {/* STRIKE */}
                                    <td className="py-3 px-4 text-center border-r border-zinc-200 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-700 font-black text-zinc-900 dark:text-white">
                                        {strike}
                                    </td>

                                    {/* PUTS */}
                                    <td className="py-3 px-1 text-center font-bold text-zinc-900 dark:text-zinc-100 bg-zinc-50/50 dark:bg-zinc-800/20">
                                        {row.put?.ltp?.toFixed(2) || '0.00'}
                                    </td>
                                    <td className={`py-3 px-1 text-center font-medium ${row.put?.chg >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                                        {row.put?.chg?.toFixed(1) || '0.0'}
                                    </td>
                                    <td className="py-3 px-1 text-center text-zinc-500">{row.put?.iv?.toFixed(1) || '-'}</td>
                                    <td className="py-3 px-1 text-center text-zinc-500">{(row.put?.oi / 1000).toFixed(1)}k</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
            <div className="p-3 bg-zinc-50 dark:bg-zinc-800/50 border-t border-zinc-200 dark:border-zinc-800 text-[10px] text-zinc-500 flex justify-between">
                <span>* OI in lots (k=1000)</span>
                <span>Last Updated: {new Date().toLocaleTimeString()}</span>
            </div>
        </div>
    );
}
