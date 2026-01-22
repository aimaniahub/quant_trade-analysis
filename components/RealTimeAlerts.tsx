"use client";

import { useAlerts } from "../lib/hooks/useAlerts";

export default function RealTimeAlerts() {
    const { alerts, connected } = useAlerts();

    const typeColors = {
        info: 'bg-zinc-300 dark:bg-zinc-600',
        warning: 'bg-amber-400',
        signal: 'bg-purple-500'
    };

    const typeIcons = {
        info: 'ℹ️',
        warning: '⚠️',
        signal: '🎯'
    };

    return (
        <div className="p-6 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl">
            <div className="flex items-center justify-between mb-4">
                <h4 className="font-black text-xs uppercase tracking-widest text-zinc-400">Real-Time Alerts</h4>
                <span className="text-[10px] text-zinc-400 flex items-center gap-1">
                    <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-500' : 'bg-zinc-400'}`}></span>
                    {connected ? 'LIVE' : 'OFFLINE'}
                </span>
            </div>
            <div className="space-y-3">
                {alerts.length === 0 ? (
                    <div className="flex items-center gap-3 text-xs text-zinc-500">
                        <span className="w-1.5 h-1.5 rounded-full bg-zinc-300"></span>
                        <span>System initialized. Waiting for market anomalies...</span>
                    </div>
                ) : (
                    alerts.map((alert) => (
                        <div key={alert.id} className="flex items-start gap-3 text-xs">
                            <span className={`w-1.5 h-1.5 mt-1.5 rounded-full ${typeColors[alert.type]}`}></span>
                            <div className="flex-1">
                                <span className={`
                                    ${alert.type === 'signal' ? 'text-purple-600 dark:text-purple-400 font-medium' :
                                        alert.type === 'warning' ? 'text-amber-600 dark:text-amber-400' :
                                            'text-zinc-600 dark:text-zinc-400'}
                                `}>
                                    {alert.message}
                                </span>
                                <span className="text-[10px] text-zinc-400 ml-2">
                                    {alert.timestamp.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                                </span>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
