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
import VATScanner from './VATScanner';
import MCPTradingPanel from './MCPTradingPanel';
import OptionFlowRadar from './OptionFlowRadar';
import HighVolumeScanner from './HighVolumeScanner';
import MA7200Scanner from './MA7200Scanner';
import RSIScanner from './RSIScanner';
import RSIDivergenceScanner from './RSIDivergenceScanner';
import ConfluencePanel from './ConfluencePanel';
import SystemStatus from './SystemStatus';

type ViewType =
    | 'dashboard'
    | 'stockAnalysis'
    | 'quantDashboard'
    | 'vatScanner'
    | 'mcpTrading'
    | 'optionFlowRadar'
    | 'highVolume'
    | 'ma7200'
    | 'rsi'
    | 'rsiDiv';

export default function Dashboard() {
    const [currentView, setCurrentView] = useState<ViewType>('dashboard');
    // Keep Flow Radar mounted so Back → Radar does not wipe the book.
    const [keepRadar, setKeepRadar] = useState(false);

    const go = (view: ViewType) => {
        if (view === 'optionFlowRadar') setKeepRadar(true);
        setCurrentView(view);
    };

    return (
        <>
        <div className={currentView === 'dashboard' ? 'min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8' : 'hidden'}>
            <header className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
                <div>
                    <h1 className="text-3xl font-black italic tracking-tighter text-zinc-900 dark:text-white uppercase leading-none">
                        OptionGreek<span className="text-blue-600">.</span>
                    </h1>
                    <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest mt-1">
                        Market Structure & Premium Intelligence
                    </p>
                </div>
                <div className="flex items-center gap-3 flex-wrap justify-end">
                    <button
                        onClick={() => go('quantDashboard')}
                        className="px-4 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        🚀 Quant Dashboard
                    </button>
                    <button
                        onClick={() => go('stockAnalysis')}
                        className="px-4 py-2 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        📊 Stocks Option
                    </button>
                    <button
                        onClick={() => go('vatScanner')}
                        className="px-4 py-2 bg-gradient-to-r from-pink-600 to-rose-600 hover:from-pink-700 hover:to-rose-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        ⚡ VAT Scanner
                    </button>
                    <button
                        onClick={() => go('mcpTrading')}
                        className="px-4 py-2 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-700 hover:to-orange-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        💹 Trading
                    </button>
                    <button
                        onClick={() => go('ma7200')}
                        className="px-4 py-2 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-700 hover:to-indigo-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        🔀 7/200 Cross
                    </button>

                    <button
                        onClick={() => go('rsiDiv')}
                        className="px-4 py-2 bg-gradient-to-r from-fuchsia-600 to-pink-600 hover:from-fuchsia-700 hover:to-pink-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        📉 RSI Div
                    </button>
                    <button
                        onClick={() => go('optionFlowRadar')}
                        className="px-4 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-700 hover:to-indigo-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        🎯 Flow Radar
                    </button>
                    <button
                        onClick={() => go('highVolume')}
                        className="px-4 py-2 bg-gradient-to-r from-lime-600 to-green-600 hover:from-lime-700 hover:to-green-700 text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-all shadow-lg hover:shadow-xl"
                    >
                        📶 High Vol
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

                {/* Confluence: multi-source trade filter */}
                <div className="grid grid-cols-1 gap-6">
                    <ConfluencePanel />
                </div>

                {/* Bottom Row: Strategy & Alerts */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <ActiveStrategy />
                    <RealTimeAlerts />
                </div>
            </main>

            <footer className="max-w-7xl mx-auto mt-12 pt-8 border-t border-zinc-200 dark:border-zinc-800 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 text-[10px] font-bold text-zinc-400 uppercase tracking-widest">
                <span>© 2026 OptionGreek Engineering</span>
                <SystemStatus />
            </footer>
        </div>

        {keepRadar && (
            <div className={currentView === 'optionFlowRadar' ? '' : 'hidden'}>
                <OptionFlowRadar onBack={() => go('dashboard')} />
            </div>
        )}
        {currentView === 'stockAnalysis' && (
            <StockAnalysis onBack={() => go('dashboard')} />
        )}
        {currentView === 'quantDashboard' && (
            <QuantDashboard onBack={() => go('dashboard')} />
        )}
        {currentView === 'vatScanner' && (
            <VATScanner onBack={() => go('dashboard')} />
        )}
        {currentView === 'mcpTrading' && (
            <MCPTradingPanel onBack={() => go('dashboard')} />
        )}
        {currentView === 'highVolume' && (
            <HighVolumeScanner onBack={() => go('dashboard')} />
        )}
        {currentView === 'ma7200' && (
            <MA7200Scanner onBack={() => go('dashboard')} />
        )}
        {currentView === 'rsi' && (
            <RSIScanner onBack={() => go('dashboard')} />
        )}
        {currentView === 'rsiDiv' && (
            <RSIDivergenceScanner onBack={() => go('dashboard')} />
        )}
        </>
    );
}

