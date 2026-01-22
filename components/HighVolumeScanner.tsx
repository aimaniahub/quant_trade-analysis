'use client';

import { useState, useEffect } from 'react';
import { api } from '../lib/api';

// Type definitions
interface VolumeData {
    current_volume: number;
    avg_volume: number;
    relative_volume: number;
}

interface BuyingPressure {
    is_buying: boolean;
    strength: number;
    pattern: string;
    close_position: number;
}

interface HighVolumeStock {
    symbol: string;
    name: string;
    cap: string;
    price: number;
    price_change_pct: number;
    volume: VolumeData;
    buying_pressure: BuyingPressure;
    composite_score: number;
}

interface ScanResult {
    success: boolean;
    timeframe: string;
    total_scanned: number;
    high_volume_count: number;
    top_stocks: HighVolumeStock[];
    timestamp: string;
}

interface OIConcentration {
    strike: number;
    call_oi: number;
    put_oi: number;
    total_oi: number;
    pcr: number;
}

interface BreakoutSignal {
    type: string;
    message: string;
    strength: string;
}

interface AnalyzedStock {
    symbol: string;
    name: string;
    spot_price: number;
    day_high: number | null;
    atm_strike: number;
    composite_score: number;
    rank: number;
    oi_analysis: {
        support: number | null;
        resistance: number | null;
        support_oi: number;
        resistance_oi: number;
        concentrations: OIConcentration[];
    };
    breakout_analysis: {
        signals: BreakoutSignal[];
        breakout_score: number;
        is_breakout: boolean;
    };
    greeks_analysis: {
        score: number;
        analysis: {
            delta_ratio: number;
            delta_bias: string;
            max_gamma_strike: number | null;
            max_gamma: number;
        };
    };
    intel_analysis: {
        state: string;
        tradable: boolean;
        confidence: number;
        message: string;
    };
    reasons: string[];
    trade_recommendation?: {
        action: string;
        option_type?: string;
        strike?: number;
        entry_zone?: string;
        stop_loss?: number;
        target?: number;
        confidence?: string;
        reason?: string;
        suggestion?: string;
    };
}

interface AnalysisResult {
    success: boolean;
    total_analyzed: number;
    results: AnalyzedStock[];
    timestamp: string;
}

interface HighVolumeScannerProps {
    onBack: () => void;
}

export default function HighVolumeScanner({ onBack }: HighVolumeScannerProps) {
    // State
    const [phase, setPhase] = useState<'scanning' | 'results' | 'analyzing' | 'analysis'>('scanning');
    const [timeframe, setTimeframe] = useState<'15' | '60'>('15');
    const [scanResult, setScanResult] = useState<ScanResult | null>(null);
    const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [scanProgress, setScanProgress] = useState(0);

    // Scan for high volume stocks
    const scanStocks = async () => {
        setLoading(true);
        setError(null);
        setPhase('scanning');
        setScanProgress(0);

        // Simulate progress for better UX
        const progressInterval = setInterval(() => {
            setScanProgress(prev => Math.min(prev + 2, 90));
        }, 100);

        try {
            const result = await api.market.scanHighVolume(timeframe, 5);
            setScanResult(result);
            setScanProgress(100);
            setPhase('results');
        } catch (err: any) {
            setError(err.message || 'Failed to scan stocks');
        } finally {
            clearInterval(progressInterval);
            setLoading(false);
        }
    };

    // Analyze option chains for selected stocks
    const analyzeOptionChains = async () => {
        if (!scanResult?.top_stocks.length) return;

        setPhase('analyzing');
        setError(null);
        setScanProgress(0);

        const symbols = scanResult.top_stocks.map(s => s.symbol);

        // Simulate progress
        const progressInterval = setInterval(() => {
            setScanProgress(prev => Math.min(prev + 5, 90));
        }, 200);

        try {
            const result = await api.market.bulkOCAnalysis(symbols);
            setAnalysisResult(result);
            setScanProgress(100);
            setPhase('analysis');
        } catch (err: any) {
            setError(err.message || 'Failed to analyze option chains');
            setPhase('results');
        } finally {
            clearInterval(progressInterval);
        }
    };

    // Initial scan on mount or timeframe change
    useEffect(() => {
        scanStocks();
    }, [timeframe]);

    // Volume badge color
    const getVolumeBadgeColor = (relativeVol: number) => {
        if (relativeVol >= 3) return 'bg-emerald-500';
        if (relativeVol >= 2) return 'bg-blue-500';
        if (relativeVol >= 1.5) return 'bg-amber-500';
        return 'bg-zinc-500';
    };

    // Score color
    const getScoreColor = (score: number) => {
        if (score >= 70) return 'text-emerald-500';
        if (score >= 50) return 'text-blue-500';
        if (score >= 30) return 'text-amber-500';
        return 'text-zinc-500';
    };

    // Render loading state
    const renderLoading = () => (
        <div className="flex flex-col items-center justify-center py-20">
            <div className="relative w-32 h-32">
                {/* Circular progress */}
                <svg className="w-full h-full transform -rotate-90">
                    <circle
                        cx="64" cy="64" r="56"
                        className="stroke-zinc-200 dark:stroke-zinc-800"
                        strokeWidth="8" fill="none"
                    />
                    <circle
                        cx="64" cy="64" r="56"
                        className="stroke-blue-500"
                        strokeWidth="8" fill="none"
                        strokeDasharray={`${scanProgress * 3.52} 352`}
                        strokeLinecap="round"
                    />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-2xl font-black text-zinc-900 dark:text-white">{scanProgress}%</span>
                </div>
            </div>
            <p className="mt-6 text-sm font-bold text-zinc-500 uppercase tracking-widest">
                {phase === 'scanning' ? 'Scanning FNO Stocks...' : 'Analyzing Option Chains...'}
            </p>
            <p className="mt-2 text-xs text-zinc-400">
                {phase === 'scanning'
                    ? 'Fetching volume data for 200+ stocks'
                    : `Analyzing ${scanResult?.top_stocks.length || 0} stocks`
                }
            </p>
        </div>
    );

    // Render scan results
    const renderResults = () => (
        <div className="space-y-6">
            {/* Summary */}
            <div className="grid grid-cols-3 gap-4">
                <div className="p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl text-center">
                    <p className="text-3xl font-black text-zinc-900 dark:text-white">{scanResult?.total_scanned || 0}</p>
                    <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mt-1">Stocks Scanned</p>
                </div>
                <div className="p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl text-center">
                    <p className="text-3xl font-black text-blue-500">{scanResult?.high_volume_count || 0}</p>
                    <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mt-1">High Volume</p>
                </div>
                <div className="p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl text-center">
                    <p className="text-3xl font-black text-emerald-500">{scanResult?.top_stocks.length || 0}</p>
                    <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mt-1">Top Picks</p>
                </div>
            </div>

            {/* Top Stocks */}
            <div className="space-y-3">
                <h3 className="text-sm font-black text-zinc-900 dark:text-white uppercase tracking-wider">
                    Top High Volume Stocks
                </h3>
                {scanResult?.top_stocks.map((stock, idx) => (
                    <div
                        key={stock.symbol}
                        className="p-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl hover:border-blue-500/50 transition-colors"
                    >
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="w-8 h-8 bg-blue-500/10 text-blue-500 rounded-lg flex items-center justify-center text-sm font-black">
                                    #{idx + 1}
                                </div>
                                <div>
                                    <h4 className="text-lg font-black text-zinc-900 dark:text-white">{stock.name}</h4>
                                    <p className="text-xs text-zinc-500">{stock.cap.replace('_', ' ')}</p>
                                </div>
                            </div>
                            <div className="text-right">
                                <p className="text-lg font-bold text-zinc-900 dark:text-white">
                                    ₹{stock.price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                                </p>
                                <p className={`text-xs font-bold ${stock.price_change_pct >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                                    {stock.price_change_pct >= 0 ? '+' : ''}{stock.price_change_pct.toFixed(2)}%
                                </p>
                            </div>
                        </div>

                        <div className="grid grid-cols-3 gap-3 mt-4">
                            <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg text-center">
                                <p className="text-[9px] font-bold text-zinc-500 uppercase">Rel. Volume</p>
                                <p className={`text-sm font-black ${getVolumeBadgeColor(stock.volume.relative_volume).replace('bg-', 'text-')}`}>
                                    {stock.volume.relative_volume}x
                                </p>
                            </div>
                            <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg text-center">
                                <p className="text-[9px] font-bold text-zinc-500 uppercase">Pressure</p>
                                <p className={`text-sm font-black ${stock.buying_pressure.is_buying ? 'text-emerald-500' : 'text-zinc-400'}`}>
                                    {stock.buying_pressure.pattern.replace('_', ' ')}
                                </p>
                            </div>
                            <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg text-center">
                                <p className="text-[9px] font-bold text-zinc-500 uppercase">Score</p>
                                <p className={`text-sm font-black ${getScoreColor(stock.composite_score)}`}>
                                    {stock.composite_score}
                                </p>
                            </div>
                        </div>

                        {/* Volume bar */}
                        <div className="mt-3">
                            <div className="flex justify-between text-[9px] text-zinc-500 mb-1">
                                <span>Volume Strength</span>
                                <span>{stock.buying_pressure.strength}%</span>
                            </div>
                            <div className="h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
                                <div
                                    className={`h-full ${getVolumeBadgeColor(stock.volume.relative_volume)} rounded-full transition-all`}
                                    style={{ width: `${stock.buying_pressure.strength}%` }}
                                />
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            {/* Analyze Button */}
            <button
                onClick={analyzeOptionChains}
                className="w-full py-4 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white text-sm font-black uppercase tracking-wider rounded-xl transition-all shadow-lg hover:shadow-xl"
            >
                🔍 Option Chain Analysis
            </button>
        </div>
    );

    // Render analysis results
    const renderAnalysis = () => (
        <div className="space-y-6">
            {/* Back to results */}
            <button
                onClick={() => setPhase('results')}
                className="flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white transition-colors"
            >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                Back to Volume Scan
            </button>

            <h3 className="text-sm font-black text-zinc-900 dark:text-white uppercase tracking-wider">
                Option Chain Analysis Results
            </h3>

            {/* Analysis Cards */}
            {analysisResult?.results.map((stock) => (
                <div
                    key={stock.symbol}
                    className="p-5 bg-white dark:bg-zinc-900 border-2 border-zinc-200 dark:border-zinc-800 rounded-xl hover:border-blue-500/50 transition-colors"
                >
                    {/* Header */}
                    <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                            <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg font-black text-white ${stock.rank === 1 ? 'bg-amber-500' : stock.rank === 2 ? 'bg-zinc-400' : stock.rank === 3 ? 'bg-amber-700' : 'bg-zinc-600'
                                }`}>
                                #{stock.rank}
                            </div>
                            <div>
                                <h4 className="text-xl font-black text-zinc-900 dark:text-white">{stock.name}</h4>
                                <p className="text-xs text-zinc-500">
                                    Spot: ₹{stock.spot_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                                    {stock.day_high && ` • Day High: ₹${stock.day_high.toLocaleString('en-IN')}`}
                                </p>
                            </div>
                        </div>
                        <div className="text-right">
                            <p className={`text-3xl font-black ${getScoreColor(stock.composite_score)}`}>
                                {stock.composite_score}
                            </p>
                            <p className="text-[9px] font-bold text-zinc-500 uppercase">Score</p>
                        </div>
                    </div>

                    {/* Metrics Grid */}
                    <div className="grid grid-cols-4 gap-2 mb-4">
                        <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg text-center">
                            <p className="text-[9px] font-bold text-zinc-500 uppercase">Support</p>
                            <p className="text-sm font-black text-emerald-500">
                                {stock.oi_analysis.support || '---'}
                            </p>
                        </div>
                        <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg text-center">
                            <p className="text-[9px] font-bold text-zinc-500 uppercase">Resistance</p>
                            <p className="text-sm font-black text-rose-500">
                                {stock.oi_analysis.resistance || '---'}
                            </p>
                        </div>
                        <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg text-center">
                            <p className="text-[9px] font-bold text-zinc-500 uppercase">ATM</p>
                            <p className="text-sm font-black text-blue-500">
                                {stock.atm_strike}
                            </p>
                        </div>
                        <div className="p-2 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg text-center">
                            <p className="text-[9px] font-bold text-zinc-500 uppercase">State</p>
                            <p className={`text-sm font-black ${stock.intel_analysis.tradable ? 'text-emerald-500' : 'text-zinc-400'}`}>
                                {stock.intel_analysis.state}
                            </p>
                        </div>
                    </div>

                    {/* Breakout Signals */}
                    {stock.breakout_analysis.signals.length > 0 && (
                        <div className="mb-4">
                            <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider mb-2">Breakout Signals</p>
                            <div className="flex flex-wrap gap-2">
                                {stock.breakout_analysis.signals.map((signal, idx) => (
                                    <span
                                        key={idx}
                                        className={`px-2 py-1 text-[10px] font-bold rounded ${signal.strength === 'STRONG'
                                            ? 'bg-emerald-500/10 text-emerald-500'
                                            : 'bg-amber-500/10 text-amber-500'
                                            }`}
                                    >
                                        {signal.type.replace(/_/g, ' ')}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Greeks Analysis */}
                    <div className="mb-4 p-3 bg-zinc-50 dark:bg-zinc-800/30 rounded-lg">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-[10px] font-bold text-zinc-500 uppercase">Delta Bias</p>
                                <p className={`text-sm font-black ${stock.greeks_analysis.analysis.delta_bias === 'BULLISH' ? 'text-emerald-500' :
                                    stock.greeks_analysis.analysis.delta_bias === 'BEARISH' ? 'text-rose-500' : 'text-zinc-400'
                                    }`}>
                                    {stock.greeks_analysis.analysis.delta_bias}
                                </p>
                            </div>
                            <div className="text-right">
                                <p className="text-[10px] font-bold text-zinc-500 uppercase">Greeks Score</p>
                                <p className={`text-sm font-black ${getScoreColor(stock.greeks_analysis.score)}`}>
                                    {stock.greeks_analysis.score}
                                </p>
                            </div>
                        </div>
                    </div>

                    {/* Trade Recommendation */}
                    {stock.trade_recommendation && (
                        <div className="mb-4 p-4 bg-gradient-to-r from-blue-500/10 to-indigo-500/10 border border-blue-500/30 rounded-xl">
                            <p className="text-[10px] font-bold text-blue-500 uppercase tracking-wider mb-2">Trade Recommendation</p>
                            {stock.trade_recommendation.action === 'BUY' ? (
                                <div className="space-y-2">
                                    <div className="flex items-center gap-2">
                                        <span className={`px-3 py-1 text-sm font-black rounded-lg ${stock.trade_recommendation.option_type === 'CE' ? 'bg-emerald-500/20 text-emerald-500' : 'bg-rose-500/20 text-rose-500'}`}>
                                            BUY {stock.trade_recommendation.option_type}
                                        </span>
                                        <span className="text-lg font-black text-zinc-900 dark:text-white">
                                            Strike: {stock.trade_recommendation.strike}
                                        </span>
                                        <span className={`px-2 py-0.5 text-[10px] font-bold uppercase rounded ${stock.trade_recommendation.confidence === 'HIGH' ? 'bg-emerald-500/20 text-emerald-500' : 'bg-amber-500/20 text-amber-500'}`}>
                                            {stock.trade_recommendation.confidence}
                                        </span>
                                    </div>
                                    <div className="grid grid-cols-3 gap-2 text-xs">
                                        <div>
                                            <span className="text-zinc-500">Entry:</span>
                                            <span className="ml-1 font-bold text-zinc-900 dark:text-white">{stock.trade_recommendation.entry_zone}</span>
                                        </div>
                                        <div>
                                            <span className="text-zinc-500">SL:</span>
                                            <span className="ml-1 font-bold text-rose-500">{stock.trade_recommendation.stop_loss}</span>
                                        </div>
                                        <div>
                                            <span className="text-zinc-500">Target:</span>
                                            <span className="ml-1 font-bold text-emerald-500">{typeof stock.trade_recommendation.target === 'number' ? stock.trade_recommendation.target.toFixed(0) : stock.trade_recommendation.target}</span>
                                        </div>
                                    </div>
                                    <p className="text-xs text-zinc-500">{stock.trade_recommendation.reason}</p>
                                </div>
                            ) : stock.trade_recommendation.action === 'WAIT' ? (
                                <div className="text-amber-500">
                                    <p className="font-bold">⏳ {stock.trade_recommendation.reason}</p>
                                    {stock.trade_recommendation.suggestion && (
                                        <p className="text-xs mt-1">{stock.trade_recommendation.suggestion}</p>
                                    )}
                                </div>
                            ) : (
                                <p className="text-zinc-500">{stock.trade_recommendation.reason}</p>
                            )}
                        </div>
                    )}

                    {/* Reasons */}
                    <div className="border-t border-zinc-100 dark:border-zinc-800 pt-4">
                        <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider mb-2">Analysis Reasons</p>
                        <ul className="space-y-1">
                            {stock.reasons.map((reason, idx) => (
                                <li key={idx} className="flex items-start gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                                    <span className="text-blue-500 mt-0.5">•</span>
                                    {reason}
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            ))}
        </div>
    );

    return (
        <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8">
            <div className="max-w-4xl mx-auto">
                {/* Header */}
                <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                    <div>
                        <div className="flex items-center gap-3">
                            <button
                                onClick={onBack}
                                className="p-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
                            >
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                                </svg>
                            </button>
                            <div>
                                <h1 className="text-2xl font-black italic tracking-tighter text-zinc-900 dark:text-white uppercase">
                                    High Volume Scanner<span className="text-blue-600">.</span>
                                </h1>
                                <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest">
                                    Find High Volume F&O Stocks with Option Chain Analysis
                                </p>
                            </div>
                        </div>
                    </div>

                    {/* Timeframe Toggle */}
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setTimeframe('15')}
                            className={`px-4 py-2 text-xs font-bold uppercase tracking-wider rounded-lg transition-all ${timeframe === '15'
                                ? 'bg-blue-600 text-white'
                                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                                }`}
                        >
                            15 Min
                        </button>
                        <button
                            onClick={() => setTimeframe('60')}
                            className={`px-4 py-2 text-xs font-bold uppercase tracking-wider rounded-lg transition-all ${timeframe === '60'
                                ? 'bg-blue-600 text-white'
                                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                                }`}
                        >
                            1 Hour
                        </button>
                        {(phase === 'results' || phase === 'analysis') && (
                            <button
                                onClick={scanStocks}
                                className="px-4 py-2 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-xs font-bold uppercase tracking-wider rounded-lg transition-all"
                            >
                                🔄 Refresh
                            </button>
                        )}
                    </div>
                </header>

                {/* Error State */}
                {error && (
                    <div className="p-4 bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 rounded-xl mb-6">
                        <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>
                        <button
                            onClick={scanStocks}
                            className="mt-2 px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold rounded-lg"
                        >
                            Retry
                        </button>
                    </div>
                )}

                {/* Main Content */}
                {(phase === 'scanning' || phase === 'analyzing') && renderLoading()}
                {phase === 'results' && !loading && renderResults()}
                {phase === 'analysis' && renderAnalysis()}

                {/* Footer */}
                <footer className="mt-12 pt-8 border-t border-zinc-200 dark:border-zinc-800 flex justify-between items-center text-[10px] font-bold text-zinc-400 uppercase tracking-widest">
                    <span>
                        {scanResult?.timestamp
                            ? `Scanned: ${new Date(scanResult.timestamp).toLocaleTimeString()}`
                            : '---'
                        }
                    </span>
                    <span>High Volume Scanner v1.0</span>
                </footer>
            </div>
        </div>
    );
}
