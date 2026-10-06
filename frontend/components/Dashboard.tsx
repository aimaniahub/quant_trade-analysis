'use client';

import React, { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import MarketIndices from './MarketIndices';
import AuthButton from './AuthButton';
import SystemStatus from './SystemStatus';
import { useMarketPolling } from '../lib/hooks/useMarketPolling';
import { setStoredFyersToken } from '../lib/api';

// Lazy load heavy terminal sub-components for instant initial page render
const OptionFlowRadar = dynamic(() => import('./OptionFlowRadar'), {
  loading: () => <TerminalLoading label="Option Flow Radar" />,
});
const NiftyQuantTerminal = dynamic(() => import('./NiftyQuantTerminal'), {
  loading: () => <TerminalLoading label="Nifty Quant Terminal" />,
});
const MA7200Scanner = dynamic(() => import('./MA7200Scanner'), {
  loading: () => <TerminalLoading label="7/200 MA Scanner" />,
});
const RSIScanner = dynamic(() => import('./RSIScanner'), {
  loading: () => <TerminalLoading label="RSI Scanner" />,
});
const TradeWatch = dynamic(() => import('./TradeWatch'), {
  loading: () => <TerminalLoading label="Paper Trade Desk" />,
});
const StockAnalysis = dynamic(() => import('./StockAnalysis'), {
  loading: () => <TerminalLoading label="F&O Stock Intelligence" />,
});

function TerminalLoading({ label }: { label: string }) {
  return (
    <div className="w-full min-h-[60vh] flex flex-col items-center justify-center bg-[#07090d] text-zinc-400 font-mono text-sm gap-3">
      <div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
      <span className="tracking-wide text-xs">Initializing {label}...</span>
    </div>
  );
}

export type TabKey = 'home' | 'radar' | 'quant' | 'ma7200' | 'rsi' | 'watch' | 'stocks';

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState<TabKey>('home');
  const [authBanner, setAuthBanner] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const market = useMarketPolling(15000);

  // Sync with browser back/forward, hash, and OAuth callback status
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const hash = window.location.hash.replace('#', '') as TabKey;
      if (['home', 'radar', 'quant', 'ma7200', 'rsi', 'watch', 'stocks'].includes(hash)) {
        setActiveTab(hash);
      }

      // Check for OAuth redirect response
      const params = new URLSearchParams(window.location.search);
      const token = params.get('token');
      if (token) {
        setStoredFyersToken(token);
      }
      if (params.get('auth') === 'success') {
        setAuthBanner({
          type: 'success',
          message: 'Fyers Authentication Successful! Access token generated and active.',
        });
        window.history.replaceState({}, document.title, window.location.pathname + window.location.hash);
      } else if (params.get('auth') === 'error') {
        const msg = params.get('message') || 'Authentication failed. Please verify credentials.';
        setAuthBanner({
          type: 'error',
          message: msg,
        });
        window.history.replaceState({}, document.title, window.location.pathname + window.location.hash);
      }
    }
  }, []);

  const switchTab = (tab: TabKey) => {
    setActiveTab(tab);
    setMobileMenuOpen(false);
    if (typeof window !== 'undefined') {
      window.location.hash = tab === 'home' ? '' : tab;
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  return (
    <div className="min-h-screen bg-[#07090d] text-zinc-100 font-sans selection:bg-emerald-500/20 selection:text-emerald-300 pb-24 sm:pb-12">
      {/* ── Top Header & Global Bar ───────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 bg-[#07090d]/90 backdrop-blur-md border-b border-zinc-800/80 px-4 py-2.5 sm:px-6">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
          {/* Logo & Brand */}
          <div className="flex items-center gap-3 cursor-pointer" onClick={() => switchTab('home')}>
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-emerald-600 via-teal-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <span className="font-mono font-black text-black text-sm">OG</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-sm tracking-tight text-white">OPTIONGREEK</span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800/80 text-zinc-400 border border-zinc-700/50 hidden sm:inline-block">
                  PROD v2.4
                </span>
              </div>
              <p className="text-[10px] text-zinc-400 font-mono hidden sm:block">Quant & F&O Execution Terminal</p>
            </div>
          </div>

          {/* Desktop Navigation Tabs */}
          <nav className="hidden lg:flex items-center gap-1 bg-zinc-900/60 p-1 rounded-xl border border-zinc-800/60">
            <button
              onClick={() => switchTab('home')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'home'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
              }`}
            >
              🏠 Home
            </button>
            <button
              onClick={() => switchTab('radar')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'radar'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
              }`}
            >
              🎯 Flow Radar
            </button>
            <button
              onClick={() => switchTab('quant')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'quant'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
              }`}
            >
              ⚡ Nifty Quant
            </button>
            <button
              onClick={() => switchTab('ma7200')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'ma7200'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
              }`}
            >
              📈 7/200 MA
            </button>
            <button
              onClick={() => switchTab('rsi')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'rsi'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
              }`}
            >
              📊 RSI Desk
            </button>
            <button
              onClick={() => switchTab('watch')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'watch'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
              }`}
            >
              ⏱️ Paper Desk
            </button>
            <button
              onClick={() => switchTab('stocks')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'stocks'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
              }`}
            >
              🔬 F&O Stocks
            </button>
          </nav>

          {/* Right Header Status: Market Clock, SystemStatus & Auth */}
          <div className="flex items-center gap-1.5 sm:gap-3">
            {/* Live IST Market Hours Gate Pill */}
            <div
              className={`flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-lg text-[10px] sm:text-[11px] font-mono border ${
                market.isOpen
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/25'
              }`}
              title={
                market.isOpen
                  ? 'Indian Market Open (Active Dynamic Refresh 15-30s)'
                  : 'Market Closed (Adaptive 15m Refresh Active - API Rate Shield)'
              }
            >
              <span className={`w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full ${market.isOpen ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
              <span className="font-semibold hidden sm:inline">{market.statusText}</span>
              <span className="text-zinc-400">({market.istTimeStr})</span>
            </div>

            <SystemStatus />
            <AuthButton compact />

            {/* Mobile Hamburger Menu Button */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="lg:hidden p-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-300 hover:text-white hover:bg-zinc-800 transition-colors"
              aria-label="Toggle Navigation Desks"
            >
              {mobileMenuOpen ? (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* ── Mobile Slide-Out Navigation Drawer ─────────────────────────────────── */}
      {mobileMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex flex-col justify-end animate-fadeIn">
          <div className="flex-1" onClick={() => setMobileMenuOpen(false)} />
          <div className="bg-[#0b0e14] border-t border-zinc-800 rounded-t-2xl p-4 sm:p-5 space-y-4 max-h-[85vh] overflow-y-auto shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded bg-emerald-500 flex items-center justify-center font-mono font-black text-black text-xs">
                  OG
                </div>
                <span className="font-bold text-sm text-white">OPTIONGREEK Desks</span>
              </div>
              <button
                onClick={() => setMobileMenuOpen(false)}
                className="text-zinc-400 hover:text-white px-2 py-1 rounded bg-zinc-900 text-xs font-mono"
              >
                ✕ Close
              </button>
            </div>

            {/* Desk Buttons Grid in Drawer */}
            <div className="grid grid-cols-2 gap-2 text-xs">
              {[
                { key: 'home', icon: '🏠', label: 'Command Center', desc: 'Indices & Overview' },
                { key: 'radar', icon: '🎯', label: 'Flow Radar', desc: 'Institutional Tracking' },
                { key: 'quant', icon: '⚡', label: 'Nifty Quant', desc: 'Greeks & Walls' },
                { key: 'ma7200', icon: '📈', label: '7/200 MA', desc: 'Trend Crossovers' },
                { key: 'rsi', icon: '📊', label: 'RSI Desk', desc: 'Momentum Divergence' },
                { key: 'watch', icon: '⏱️', label: 'Paper Desk', desc: 'Simulated Execution' },
                { key: 'stocks', icon: '🔬', label: 'F&O Stocks', desc: 'Stock Intelligence' },
              ].map((item) => (
                <button
                  key={item.key}
                  onClick={() => switchTab(item.key as TabKey)}
                  className={`p-3 rounded-xl border text-left flex flex-col justify-between gap-1 transition-all ${
                    activeTab === item.key
                      ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                      : 'bg-zinc-900/80 border-zinc-800 text-zinc-300 hover:border-zinc-700'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-base">{item.icon}</span>
                    <span className="font-bold">{item.label}</span>
                  </div>
                  <span className="text-[10px] text-zinc-400">{item.desc}</span>
                </button>
              ))}
            </div>

            {/* Quick Status Inside Drawer */}
            <div className="p-3 rounded-xl bg-zinc-900/60 border border-zinc-800 text-xs space-y-1.5">
              <div className="font-bold text-zinc-300 text-[11px] uppercase tracking-wider">System Telemetry</div>
              <div className="flex items-center justify-between text-[11px] text-zinc-400 font-mono">
                <span>Market Hours:</span>
                <span className={market.isOpen ? 'text-emerald-400 font-semibold' : 'text-amber-400'}>
                  {market.statusText} ({market.istTimeStr})
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px] text-zinc-400 font-mono">
                <span>Rate Shield Interval:</span>
                <span className="text-zinc-300">
                  {typeof market.interval === 'number' ? `${market.interval / 1000}s` : '15m (Shield)'}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── OAuth Status Toast / Banner ───────────────────────────────────────── */}
      {authBanner && (
        <div
          className={`border-b px-4 py-3 text-xs flex items-center justify-between transition-all ${
            authBanner.type === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
              : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
          }`}
        >
          <div className="max-w-7xl mx-auto flex items-center gap-2">
            <span>{authBanner.type === 'success' ? '✅' : '⚠️'}</span>
            <span className="font-medium">{authBanner.message}</span>
          </div>
          <button
            onClick={() => setAuthBanner(null)}
            className="text-zinc-400 hover:text-white font-mono text-sm px-2"
          >
            ×
          </button>
        </div>
      )}

      {/* ── Subheader Return Link when on a sub-terminal ──────────────────────── */}
      {activeTab !== 'home' && (
        <div className="bg-zinc-900/40 border-b border-zinc-800/50 px-4 py-2">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <button
              onClick={() => switchTab('home')}
              className="inline-flex items-center gap-2 text-xs font-mono text-emerald-400 hover:text-emerald-300 transition-colors"
            >
              <span>← Back to Command Center</span>
            </button>
            <span className="text-[11px] font-mono text-zinc-400 uppercase tracking-widest">
              Active Desk: <span className="text-white font-bold">{activeTab.toUpperCase()}</span>
            </span>
          </div>
        </div>
      )}

      {/* ── Main View Container ──────────────────────────────────────────────── */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 pt-4 sm:pt-6">
        {activeTab === 'home' && (
          <div className="space-y-6 sm:space-y-8 animate-fadeIn">
            {/* 1. Market Live Tape / Hero Bar */}
            <section className="space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <h2 className="text-lg sm:text-xl font-bold tracking-tight text-white flex items-center gap-2">
                    <span>Live Market Indices</span>
                    <span className="text-xs font-mono font-normal text-emerald-400 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20">
                      {market.isOpen ? '● Real-Time Tape' : '○ Last Close · 15m Sync'}
                    </span>
                  </h2>
                  <p className="text-xs text-zinc-400">
                    NSE benchmark spot prices with automated rate shielding & edge CDN cache.
                  </p>
                </div>
                {!market.isOpen && (
                  <div className="text-[11px] font-mono text-amber-400/90 bg-amber-500/10 border border-amber-500/20 px-3 py-1.5 rounded-lg">
                    ⚡ Market Gate Active: Auto-refresh switched to 15m to protect daily API quotas
                  </div>
                )}
              </div>

              {/* Indices Grid Component */}
              <MarketIndices />
            </section>

            {/* 2. Command Launchpad Grid */}
            <section className="space-y-4">
              <div className="border-b border-zinc-800 pb-2 flex items-center justify-between">
                <div>
                  <h2 className="text-base sm:text-lg font-bold tracking-tight text-white">
                    Quant Execution Desks & Scanners
                  </h2>
                  <p className="text-xs text-zinc-400">
                    Select a dedicated terminal to monitor order flow, option chains, and momentum.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-5">
                {/* Card 1: Option Flow Radar */}
                <div
                  onClick={() => switchTab('radar')}
                  className="group relative p-5 rounded-2xl bg-zinc-900/70 border border-zinc-800 hover:border-emerald-500/50 hover:bg-zinc-900 transition-all duration-200 cursor-pointer flex flex-col justify-between shadow-lg hover:shadow-emerald-500/10"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-2xl p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 group-hover:scale-110 transition-transform">
                        🎯
                      </span>
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                        INSTITUTIONAL
                      </span>
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-white group-hover:text-emerald-400 transition-colors">
                        Option Flow Radar
                      </h3>
                      <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                        Detect unusual volume bursts, smart money call/put writing clusters, sweepers, and institutional delta shifts.
                      </p>
                    </div>
                    <div className="pt-2 flex flex-wrap gap-1.5 text-[10px] font-mono text-zinc-400">
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Unusual Vol</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Sweepers</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Live Tape</span>
                    </div>
                  </div>
                  <div className="mt-5 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs font-semibold text-emerald-400 group-hover:translate-x-1 transition-transform">
                    <span>Launch Flow Radar</span>
                    <span>→</span>
                  </div>
                </div>

                {/* Card 2: Nifty 50 Quant Terminal */}
                <div
                  onClick={() => switchTab('quant')}
                  className="group relative p-5 rounded-2xl bg-zinc-900/70 border border-zinc-800 hover:border-cyan-500/50 hover:bg-zinc-900 transition-all duration-200 cursor-pointer flex flex-col justify-between shadow-lg hover:shadow-cyan-500/10"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-2xl p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 group-hover:scale-110 transition-transform">
                        ⚡
                      </span>
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">
                        GAMMA & PCR
                      </span>
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-white group-hover:text-cyan-400 transition-colors">
                        Nifty 50 Quant Terminal
                      </h3>
                      <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                        Full option chain analytics, Gamma walls, Max Pain, Volume/OI PCR regimes, and price shock breakout simulator.
                      </p>
                    </div>
                    <div className="pt-2 flex flex-wrap gap-1.5 text-[10px] font-mono text-zinc-400">
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Gamma Walls</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Max Pain</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Simulator</span>
                    </div>
                  </div>
                  <div className="mt-5 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs font-semibold text-cyan-400 group-hover:translate-x-1 transition-transform">
                    <span>Launch Nifty Quant</span>
                    <span>→</span>
                  </div>
                </div>

                {/* Card 3: 7/200 MA + Momentum Scanner */}
                <div
                  onClick={() => switchTab('ma7200')}
                  className="group relative p-5 rounded-2xl bg-zinc-900/70 border border-zinc-800 hover:border-amber-500/50 hover:bg-zinc-900 transition-all duration-200 cursor-pointer flex flex-col justify-between shadow-lg hover:shadow-amber-500/10"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-2xl p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 group-hover:scale-110 transition-transform">
                        📈
                      </span>
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30">
                        15M TREND
                      </span>
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-white group-hover:text-amber-400 transition-colors">
                        7/200 MA + OC Momentum
                      </h3>
                      <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                        15m trend confirmation with Moving Average crosses, option chain validation, and low-risk entry signals.
                      </p>
                    </div>
                    <div className="pt-2 flex flex-wrap gap-1.5 text-[10px] font-mono text-zinc-400">
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">15m Candles</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Trend Filter</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">OC Check</span>
                    </div>
                  </div>
                  <div className="mt-5 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs font-semibold text-amber-400 group-hover:translate-x-1 transition-transform">
                    <span>Launch 7/200 MA Scanner</span>
                    <span>→</span>
                  </div>
                </div>

                {/* Card 4: RSI Desk & Divergence */}
                <div
                  onClick={() => switchTab('rsi')}
                  className="group relative p-5 rounded-2xl bg-zinc-900/70 border border-zinc-800 hover:border-violet-500/50 hover:bg-zinc-900 transition-all duration-200 cursor-pointer flex flex-col justify-between shadow-lg hover:shadow-violet-500/10"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-2xl p-2.5 rounded-xl bg-violet-500/10 border border-violet-500/20 text-violet-400 group-hover:scale-110 transition-transform">
                        📊
                      </span>
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-violet-500/15 text-violet-400 border border-violet-500/30">
                        DIVERGENCE
                      </span>
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-white group-hover:text-violet-400 transition-colors">
                        RSI Desk & Divergence Scanner
                      </h3>
                      <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                        Multi-timeframe RSI extremes, bullish/bearish regular and hidden divergence detection across high-liquidity F&O names.
                      </p>
                    </div>
                    <div className="pt-2 flex flex-wrap gap-1.5 text-[10px] font-mono text-zinc-400">
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">RSI 15/60</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Divergence</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Extreme Zone</span>
                    </div>
                  </div>
                  <div className="mt-5 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs font-semibold text-violet-400 group-hover:translate-x-1 transition-transform">
                    <span>Launch RSI Scanner</span>
                    <span>→</span>
                  </div>
                </div>

                {/* Card 5: Paper Trading Desk */}
                <div
                  onClick={() => switchTab('watch')}
                  className="group relative p-5 rounded-2xl bg-zinc-900/70 border border-zinc-800 hover:border-emerald-500/50 hover:bg-zinc-900 transition-all duration-200 cursor-pointer flex flex-col justify-between shadow-lg hover:shadow-emerald-500/10"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-2xl p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 group-hover:scale-110 transition-transform">
                        ⏱️
                      </span>
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                        09:23 RULE DESK
                      </span>
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-white group-hover:text-emerald-400 transition-colors">
                        Automated Paper Trading Desk
                      </h3>
                      <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                        Automated 09:23 AM rule engine, 2-trade daily cap, live price mark, target/trailing SL management, and execution journal.
                      </p>
                    </div>
                    <div className="pt-2 flex flex-wrap gap-1.5 text-[10px] font-mono text-zinc-400">
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">09:23 Entry</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Auto Trail SL</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Live P&L</span>
                    </div>
                  </div>
                  <div className="mt-5 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs font-semibold text-emerald-400 group-hover:translate-x-1 transition-transform">
                    <span>Launch Paper Desk</span>
                    <span>→</span>
                  </div>
                </div>

                {/* Card 6: F&O Stock Deep-Dive */}
                <div
                  onClick={() => switchTab('stocks')}
                  className="group relative p-5 rounded-2xl bg-zinc-900/70 border border-zinc-800 hover:border-pink-500/50 hover:bg-zinc-900 transition-all duration-200 cursor-pointer flex flex-col justify-between shadow-lg hover:shadow-pink-500/10"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-2xl p-2.5 rounded-xl bg-pink-500/10 border border-pink-500/20 text-pink-400 group-hover:scale-110 transition-transform">
                        🔬
                      </span>
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-pink-500/15 text-pink-400 border border-pink-500/30">
                        200+ UNIVERSE
                      </span>
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-white group-hover:text-pink-400 transition-colors">
                        F&O Universe Stock Intelligence
                      </h3>
                      <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                        Comprehensive stock scanner for 200+ F&O equities. Intent scoring, buildup analysis, and institutional conviction rank.
                      </p>
                    </div>
                    <div className="pt-2 flex flex-wrap gap-1.5 text-[10px] font-mono text-zinc-400">
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Full Universe</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Intent Score</span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/50">Buildup Matrix</span>
                    </div>
                  </div>
                  <div className="mt-5 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs font-semibold text-pink-400 group-hover:translate-x-1 transition-transform">
                    <span>Launch Stock Scanner</span>
                    <span>→</span>
                  </div>
                </div>
              </div>
            </section>

            {/* 3. Production Architecture & API Rate Shield Info Banner */}
            <section className="p-5 rounded-2xl bg-zinc-900/40 border border-zinc-800/80 space-y-3">
              <div className="flex items-center gap-2 text-xs font-mono font-bold text-zinc-300">
                <span className="w-2 h-2 rounded-full bg-cyan-400" />
                <span>PRODUCTION ARCHITECTURE & VERIFICATION STATUS</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-zinc-400">
                <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/60 space-y-1">
                  <div className="font-semibold text-white flex items-center gap-1.5">
                    <span>🛡️ API Rate Shield</span>
                    <span className="text-[10px] font-mono text-emerald-400">ACTIVE</span>
                  </div>
                  <p className="text-zinc-400 leading-relaxed text-[11px]">
                    Market hours auto-polling stays under 200 RPM limit. Non-market hours (3:30 PM - 9:15 AM IST) automatically throttled to 15-minute intervals.
                  </p>
                </div>
                <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/60 space-y-1">
                  <div className="font-semibold text-white flex items-center gap-1.5">
                    <span>⚡ Vercel Edge Caching</span>
                    <span className="text-[10px] font-mono text-cyan-400">ACTIVE</span>
                  </div>
                  <p className="text-zinc-400 leading-relaxed text-[11px]">
                    Read routes use HTTP Cache-Control headers (<code className="text-zinc-300">s-maxage=10, stale-while-revalidate=60</code>), serving repeated requests directly from Vercel's global CDN edge.
                  </p>
                </div>
                <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/60 space-y-1">
                  <div className="font-semibold text-white flex items-center gap-1.5">
                    <span>🔑 Fyers OAuth Callback</span>
                    <span className="text-[10px] font-mono text-amber-400">CONFIG</span>
                  </div>
                  <p className="text-zinc-400 leading-relaxed text-[11px]">
                    Ensure your Fyers API dashboard has Redirect URL set to <code className="text-zinc-300">https://&lt;your-app&gt;.vercel.app/api/v1/auth/callback</code> to log in seamlessly.
                  </p>
                </div>
              </div>
            </section>
          </div>
        )}

        {/* ── Active Terminal Views ─────────────────────────────────────────── */}
        {activeTab === 'radar' && <OptionFlowRadar />}
        {activeTab === 'quant' && <NiftyQuantTerminal onClose={() => switchTab('home')} />}
        {activeTab === 'ma7200' && <MA7200Scanner onBack={() => switchTab('home')} />}
        {activeTab === 'rsi' && <RSIScanner onBack={() => switchTab('home')} />}
        {activeTab === 'watch' && <TradeWatch />}
        {activeTab === 'stocks' && <StockAnalysis onBack={() => switchTab('home')} />}
      </main>

      {/* ── Mobile Sticky Bottom Navigation Bar ───────────────────────────────── */}
      <nav className="lg:hidden fixed bottom-0 left-0 right-0 z-40 bg-[#07090d]/95 backdrop-blur-xl border-t border-zinc-800/80 px-2 pt-1.5 pb-[calc(env(safe-area-inset-bottom,0px)+8px)]">
        <div className="flex items-center justify-around">
          <button
            onClick={() => switchTab('home')}
            className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl text-[10px] font-medium transition-all ${
              activeTab === 'home' ? 'text-emerald-400 font-bold bg-emerald-500/10' : 'text-zinc-400 hover:text-white'
            }`}
          >
            <span className="text-base leading-none">🏠</span>
            <span>Home</span>
          </button>
          <button
            onClick={() => switchTab('radar')}
            className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl text-[10px] font-medium transition-all ${
              activeTab === 'radar' ? 'text-emerald-400 font-bold bg-emerald-500/10' : 'text-zinc-400 hover:text-white'
            }`}
          >
            <span className="text-base leading-none">🎯</span>
            <span>Radar</span>
          </button>
          <button
            onClick={() => switchTab('quant')}
            className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl text-[10px] font-medium transition-all ${
              activeTab === 'quant' ? 'text-cyan-400 font-bold bg-cyan-500/10' : 'text-zinc-400 hover:text-white'
            }`}
          >
            <span className="text-base leading-none">⚡</span>
            <span>Quant</span>
          </button>
          <button
            onClick={() => switchTab('ma7200')}
            className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl text-[10px] font-medium transition-all ${
              activeTab === 'ma7200' ? 'text-amber-400 font-bold bg-amber-500/10' : 'text-zinc-400 hover:text-white'
            }`}
          >
            <span className="text-base leading-none">📈</span>
            <span>7/200</span>
          </button>
          <button
            onClick={() => setMobileMenuOpen(true)}
            className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl text-[10px] font-medium transition-all ${
              ['rsi', 'watch', 'stocks'].includes(activeTab) || mobileMenuOpen
                ? 'text-violet-400 font-bold bg-violet-500/10'
                : 'text-zinc-400 hover:text-white'
            }`}
          >
            <span className="text-base leading-none">☰</span>
            <span>Desks</span>
          </button>
        </div>
      </nav>
    </div>
  );
}
