'use client';

import { useState, useEffect } from 'react';
import NiftySentimentCards from './NiftySentimentCards';
import LiveTradeSignal from './LiveTradeSignal';
import GreeksHeatmap from './GreeksHeatmap';
import { api } from '../lib/api';

interface HighVolumeStock {
    symbol: string;
    name: string;
    cap: string;
    price: number;
    price_change_pct: number;
    composite_score: number;
}

interface QuantDashboardProps {
    onBack?: () => void;
}

export default function QuantDashboard({ onBack }: QuantDashboardProps) {
    const [selectedStock, setSelectedStock] = useState<string>('NSE:NIFTY50-INDEX');
    const [topStocks, setTopStocks] = useState<HighVolumeStock[]>([]);
    const [loadingStocks, setLoadingStocks] = useState(true);
    const [activeTab, setActiveTab] = useState<'signal' | 'greeks'>('signal');

    // Fetch top high-volume stocks on load
    useEffect(() => {
        const fetchTopStocks = async () => {
            try {
                const response = await api.market.scanHighVolume('60', 5);
                if (response.success && response.top_stocks) {
                    setTopStocks(response.top_stocks);
                    if (response.top_stocks.length > 0) {
                        setSelectedStock(response.top_stocks[0].symbol);
                    }
                }
            } catch (error) {
                console.error('Failed to fetch top stocks:', error);
            } finally {
                setLoadingStocks(false);
            }
        };
        fetchTopStocks();
    }, []);

    return (
        <div className="min-h-screen bg-black text-white">
            {/* Header */}
            <header className="p-4 border-b border-zinc-800">
                <div className="max-w-7xl mx-auto flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        {onBack && (
                            <button
                                onClick={onBack}
                                className="p-2 text-zinc-400 hover:text-white transition-colors"
                            >
                                ← Back
                            </button>
                        )}
                        <div>
                            <h1 className="text-xl font-black tracking-tight">
                                QUANT DASHBOARD
                            </h1>
                            <p className="text-xs text-zinc-500">Real-time F&O Intelligence</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                        <span className="text-xs text-zinc-400">LIVE</span>
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="max-w-7xl mx-auto p-4 space-y-6">
                {/* Nifty Sentiment Cards */}
                <section>
                    <NiftySentimentCards autoRefresh={true} refreshInterval={30000} />
                </section>

                {/* Stock Selector */}
                <section className="flex items-center gap-4 overflow-x-auto pb-2">
                    <span className="text-xs font-bold uppercase text-zinc-500 whitespace-nowrap">Analyze:</span>

                    {/* Quick select Nifty */}
                    <button
                        onClick={() => setSelectedStock('NSE:NIFTY50-INDEX')}
                        className={`px-4 py-2 text-sm font-bold rounded-lg transition-all whitespace-nowrap ${selectedStock === 'NSE:NIFTY50-INDEX'
                            ? 'bg-blue-500 text-white'
                            : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                            }`}
                    >
                        NIFTY 50
                    </button>

                    <button
                        onClick={() => setSelectedStock('NSE:NIFTYBANK-INDEX')}
                        className={`px-4 py-2 text-sm font-bold rounded-lg transition-all whitespace-nowrap ${selectedStock === 'NSE:NIFTYBANK-INDEX'
                            ? 'bg-blue-500 text-white'
                            : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                            }`}
                    >
                        BANK NIFTY
                    </button>

                    <div className="h-6 w-px bg-zinc-700" />

                    {/* Top High Volume Stocks */}
                    {loadingStocks ? (
                        <div className="flex gap-2">
                            {[1, 2, 3].map(i => (
                                <div key={i} className="w-24 h-9 bg-zinc-800 rounded-lg animate-pulse" />
                            ))}
                        </div>
                    ) : (
                        topStocks.map(stock => (
                            <button
                                key={stock.symbol}
                                onClick={() => setSelectedStock(stock.symbol)}
                                className={`px-4 py-2 text-sm font-bold rounded-lg transition-all whitespace-nowrap ${selectedStock === stock.symbol
                                    ? 'bg-emerald-500 text-white'
                                    : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                                    }`}
                            >
                                {stock.name}
                                <span className={`ml-2 text-xs ${stock.price_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {stock.price_change_pct >= 0 ? '+' : ''}{stock.price_change_pct.toFixed(1)}%
                                </span>
                            </button>
                        ))
                    )}
                </section>

                {/* Tab Switch */}
                <section className="flex items-center gap-2">
                    <button
                        onClick={() => setActiveTab('signal')}
                        className={`px-4 py-2 text-sm font-bold rounded-lg transition-all ${activeTab === 'signal'
                            ? 'bg-white text-black'
                            : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                            }`}
                    >
                        📊 Trade Signal
                    </button>
                    <button
                        onClick={() => setActiveTab('greeks')}
                        className={`px-4 py-2 text-sm font-bold rounded-lg transition-all ${activeTab === 'greeks'
                            ? 'bg-white text-black'
                            : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                            }`}
                    >
                        🔥 Greeks Heatmap
                    </button>
                </section>

                {/* Analysis Section */}
                <section>
                    {activeTab === 'signal' ? (
                        <LiveTradeSignal
                            symbol={selectedStock}
                            autoRefresh={true}
                            refreshInterval={30000}
                        />
                    ) : (
                        <GreeksHeatmap
                            symbol={selectedStock}
                            strikeCount={15}
                            autoRefresh={true}
                            refreshInterval={60000}
                        />
                    )}
                </section>
            </main>

            {/* Footer */}
            <footer className="p-4 border-t border-zinc-800 mt-8">
                <div className="max-w-7xl mx-auto flex items-center justify-between text-xs text-zinc-600">
                    <span>Powered by Fyers API • Real-time F&O Analytics</span>
                    <span>Auto-refresh active</span>
                </div>
            </footer>
        </div>
    );
}
