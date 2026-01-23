'use client';

import { useState } from 'react';
import MarketIndices from './MarketIndices';
import OptionChainTable from './OptionChainTable';
import MarketStateDetector from './MarketStateDetector';
import AuthButton from './AuthButton';
import ActiveStrategy from './ActiveStrategy';
import RealTimeAlerts from './RealTimeAlerts';
import StockAnalysis from './StockAnalysis';
import QuantDashboard from './QuantDashboard';

type ViewType = 'dashboard' | 'stockAnalysis' | 'quantDashboard';

export default function Dashboard() {
    const [currentView, setCurrentView] = useState<ViewType>('dashboard');

    // Show Stock Analysis page
    if (currentView === 'stockAnalysis') {
        return <StockAnalysis onBack={() => setCurrentView('dashboard')} />;
    }

    // Show Quant Dashboard page
    if (currentView === 'quantDashboard') {
        return <QuantDashboard onBack={() => setCurrentView('dashboard')} />;
    }

    return (
        <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8">
            <header className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
                <div>
                    <h1 className="text-3xl font-black italic tracking-tighter text-zinc-900 dark:text-white uppercase leading-none">
                        OptionGreek<span className="text-blue-600">.</span>
                    </h1>
                    <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest mt-1">
                        Market Structure & Premium Intelligence
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => setCurrentView('quantDashboard')}
                        className="px-4 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        🚀 Quant Dashboard
                    </button>
                    <button
                        onClick={() => setCurrentView('stockAnalysis')}
                        className="px-4 py-2 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        📊 Stocks Option
                    </button>
                    <AuthButton />
                </div>
            </header>

            <main className="max-w-7xl mx-auto space-y-6">
                {/* Top Row: Market State & Indices */}
                <div className="flex flex-col lg:flex-row gap-6">
                    <div className="w-full lg:w-1/3">
                        <MarketStateDetector />
                    </div>
                    <div className="w-full lg:w-2/3">
                        <MarketIndices />
                    </div>
                </div>

                {/* Middle Row: Option Chain */}
                <div className="grid grid-cols-1 gap-6">
                    <OptionChainTable symbol="NSE:NIFTY50-INDEX" />
                </div>

                {/* Bottom Row: Strategy & Alerts */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <ActiveStrategy />
                    <RealTimeAlerts />
                </div>
            </main>

            <footer className="max-w-7xl mx-auto mt-12 pt-8 border-t border-zinc-200 dark:border-zinc-800 flex justify-between items-center text-[10px] font-bold text-zinc-400 uppercase tracking-widest">
                <span>© 2026 OptionGreek Engineering</span>
                <div className="flex gap-4">
                    <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                        Backend Active
                    </span>
                    <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-blue-500"></span>
                        Fyers v3 API
                    </span>
                </div>
            </footer>
        </div>
    );
}

