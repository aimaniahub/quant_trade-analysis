"use client";

import React, { useState, useEffect, useMemo } from "react";
import { api } from "../lib/api";
import { useApiQuery } from "../lib/hooks/useApiQuery";
import { useMarketPolling } from "../lib/hooks/useMarketPolling";

export interface GreekData {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  vanna?: number;
  charm?: number;
}

export interface StrikeLeg {
  ltp: number;
  chg: number;
  oi: number;
  oich: number;
  volume: number;
  iv: number;
  greeks: GreekData;
  state: string;
  color: string;
  badge: string;
}

export interface StrikeRow {
  strike: number;
  is_atm: boolean;
  aar: number;
  net_gex_cr?: number;
  call: StrikeLeg;
  put: StrikeLeg;
}

export interface HeavyweightItem {
  symbol: string;
  name: string;
  sector: string;
  weight: number;
  ltp: number;
  change_pct: number;
  change: number;
  point_impact: number;
  bias: string;
}

export interface BestTrade {
  symbol: string;
  strike: number;
  option_type: string;
  bias: string;
  entry_ltp: number;
  stop_loss: number;
  target_1: number;
  target_2: number;
  risk_reward: string;
  conviction_score: number;
  greeks: GreekData;
  state: string;
  rationale: string;
}

export interface QuantGreeks {
  total_net_gex_cr: number;
  gamma_flip_strike: number;
  gamma_regime: string;
  gamma_regime_badge: string;
  gamma_regime_desc: string;
  dealer_net_dex_cr: number;
  dealer_net_vex_cr: number;
  skew_25d_pct: number;
  skew_bias: string;
  atm_daily_theta_burn_cr: number;
  put_wall: { strike: number; oi: number };
  call_wall: { strike: number; oi: number };
  max_pain: number;
}

export interface ConstituentStockItem {
  symbol: string;
  name: string;
  sector: string;
  weight: number;
  ltp: number;
  change_pct: number;
  point_impact: number;
  bias: string;
  status: string;
  call_wall: number;
  put_wall: number;
  pcr: number;
  clue: string;
}

export interface SectorItem {
  sector: string;
  weight: number;
  net_point_contribution: number;
  advances: number;
  declines: number;
  stocks_count: number;
}

export interface ConstituentsReport {
  net_point_contribution: number;
  advances: number;
  declines: number;
  neutral: number;
  market_breadth_pct: number;
  sentiment: string;
  total_stocks_tracked: number;
  top_positive_drivers: ConstituentStockItem[];
  top_negative_drags: ConstituentStockItem[];
  sectors: SectorItem[];
  stocks: ConstituentStockItem[];
}

export interface StrategyItem {
  id: string;
  name: string;
  tag: string;
  bias: string;
  type: string;
  strike: number;
  entry_ltp: number;
  stop_loss: number;
  target_1: number;
  target_2: number;
  risk_reward: string;
  conviction_score: number;
  rationale: string;
  greeks: {
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
    vanna?: number;
    charm?: number;
  };
}

export interface HeavyweightFnoStock {
  symbol: string;
  name: string;
  weight: number;
  spot: number;
  call_wall: number;
  call_wall_oi: number;
  put_wall: number;
  put_wall_oi: number;
  dist_to_call_wall_pct: number;
  dist_to_put_wall_pct: number;
  pcr: number;
  state: string;
  badge: string;
  color: string;
  predicted_move_pct: number;
  transmitted_nifty_points: number;
  clue: string;
}

export interface HeavyweightFnoReport {
  net_transmitted_thrust_pts: number;
  projected_nifty_target: number;
  recommended_nifty_strike: string;
  recommended_strike_value: number;
  target_opt_type: string;
  consensus: string;
  bull_heavyweights_count: number;
  bear_heavyweights_count: number;
  thesis: string;
  stocks: HeavyweightFnoStock[];
}

interface NiftyQuantResponse {
  success: boolean;
  symbol: string;
  spot_price: number;
  atm_strike: number;
  days_to_expiry: number;
  call_wall: { strike: number; oi: number };
  put_wall: { strike: number; oi: number };
  max_pain: number;
  straddle: {
    strike: number;
    combined_premium: number;
    ce_premium: number;
    pe_premium: number;
    upper_breakeven: number;
    lower_breakeven: number;
    skew_ratio: number;
    regime: string;
    expected_range_points: number;
  };
  pcr: {
    total_pcr: number;
    atm_cluster_pcr: number;
    sentiment: string;
    description: string;
    total_call_oi: number;
    total_put_oi: number;
  };
  traps: Array<{ type: string; severity: string; message: string }>;
  heavyweights: HeavyweightItem[];
  heavyweight_fno?: HeavyweightFnoReport;
  net_heavyweight_points: number;
  best_trade: BestTrade | null;
  quant_greeks?: QuantGreeks;
  constituents_report?: ConstituentsReport;
  strategies?: StrategyItem[];
  strikes: StrikeRow[];
  timestamp: string;
  error?: string;
}

const fmt = (v: number | undefined, dec = 1) =>
  v != null ? Number(v).toLocaleString("en-IN", { maximumFractionDigits: dec }) : "—";

const fmtOI = (oi: number | undefined) => {
  if (!oi || oi <= 0) return "—";
  if (oi >= 10_000_000) return `${(oi / 10_000_000).toFixed(2)}Cr`;
  if (oi >= 100_000) return `${(oi / 100_000).toFixed(1)}L`;
  if (oi >= 1_000) return `${(oi / 1_000).toFixed(0)}k`;
  return `${Math.round(oi)}`;
};

const fmtOiCh = (oich: number | undefined) => {
  if (!oich || oich === 0) return "—";
  const sign = oich > 0 ? "+" : "";
  if (Math.abs(oich) >= 10_000_000) return `${sign}${(oich / 10_000_000).toFixed(2)}Cr`;
  if (Math.abs(oich) >= 100_000) return `${sign}${(oich / 100_000).toFixed(1)}L`;
  if (Math.abs(oich) >= 1_000) return `${sign}${(oich / 1_000).toFixed(0)}k`;
  return `${sign}${Math.round(oich)}`;
};

const fmtVol = (vol: number | undefined) => {
  if (!vol || vol <= 0) return "—";
  if (vol >= 10_000_000) return `${(vol / 10_000_000).toFixed(2)}Cr`;
  if (vol >= 100_000) return `${(vol / 100_000).toFixed(1)}L`;
  if (vol >= 1_000) return `${(vol / 1_000).toFixed(0)}k`;
  return `${Math.round(vol)}`;
};

export default function NiftyQuantTerminal({
  autoRefresh = true,
  refreshInterval = 15000,
  onClose,
}: {
  autoRefresh?: boolean;
  refreshInterval?: number;
  onClose?: () => void;
}) {
  const [mounted, setMounted] = useState<boolean>(false);
  const [viewMode, setViewMode] = useState<"flow" | "greeks">("flow");
  const [activeStrategyId, setActiveStrategyId] = useState<string>("delta_sweet_spot");
  const [simStock, setSimStock] = useState<string>("NSE:HDFCBANK-EQ");
  const [simMove, setSimMove] = useState<number>(2.5);
  const [simResult, setSimResult] = useState<any>(null);
  const [simLoading, setSimLoading] = useState<boolean>(false);
  const [strikeWindow, setStrikeWindow] = useState<number | "all">(12);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  // 50 Constituents filter states
  const [constituentTab, setConstituentTab] = useState<"all" | "top10" | "gainers" | "drags">("top10");
  const [selectedSector, setSelectedSector] = useState<string>("ALL");
  const [searchStock, setSearchStock] = useState<string>("");

  useEffect(() => {
    setMounted(true);
  }, []);

  const { interval } = useMarketPolling(refreshInterval, autoRefresh);

  const { data, isLoading, error, refetch } = useApiQuery<NiftyQuantResponse>(
    ["options", "nifty-quant"],
    () => api.options.getNiftyQuant(),
    {
      refetchInterval: interval,
    }
  );

  const strikes = data?.strikes || [];

  // All React Hooks MUST be called unconditionally before any early returns
  const displayedStrikes = useMemo(() => {
    if (strikeWindow === "all" || !strikes.length) return strikes;
    const atmIndex = strikes.findIndex((s) => s.is_atm);
    if (atmIndex === -1) return strikes;
    const half = typeof strikeWindow === "number" ? strikeWindow : 12;
    const start = Math.max(0, atmIndex - half);
    const end = Math.min(strikes.length, atmIndex + half + 1);
    return strikes.slice(start, end);
  }, [strikes, strikeWindow]);

  const handleForceRefresh = async () => {
    setIsRefreshing(true);
    try {
      await api.options.getNiftyQuant(true);
      await refetch();
    } catch (e) {
      console.error("Force refresh failed", e);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleSimulate = async () => {
    setSimLoading(true);
    try {
      const res = await api.options.simulateBreakout(simStock, simMove);
      if (res?.success) {
        setSimResult(res.simulation);
      }
    } catch (e) {
      console.error("Simulation failed", e);
    } finally {
      setSimLoading(false);
    }
  };

  const scrollToStrike = (strikeLevel: number) => {
    const el = document.getElementById(`strike-row-${strikeLevel}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  // Filter 50 constituents
  const filteredStocks = useMemo(() => {
    const all = data?.constituents_report?.stocks || [];
    let list = [...all];

    if (constituentTab === "top10") {
      list = list.slice(0, 10);
    } else if (constituentTab === "gainers") {
      list = list.filter((s) => s.change_pct > 0).sort((a, b) => b.point_impact - a.point_impact);
    } else if (constituentTab === "drags") {
      list = list.filter((s) => s.change_pct < 0).sort((a, b) => a.point_impact - b.point_impact);
    }

    if (selectedSector !== "ALL") {
      list = list.filter((s) => s.sector === selectedSector);
    }

    if (searchStock.trim()) {
      const q = searchStock.toLowerCase();
      list = list.filter(
        (s) => s.name.toLowerCase().includes(q) || s.symbol.toLowerCase().includes(q) || s.sector.toLowerCase().includes(q)
      );
    }

    return list;
  }, [data?.constituents_report?.stocks, constituentTab, selectedSector, searchStock]);

  if (!mounted) {
    return (
      <div className="w-full min-h-[300px] flex items-center justify-center bg-[#07090d] border border-violet-900/50 rounded-xl p-8" suppressHydrationWarning>
        <span className="text-xs font-mono text-zinc-500">Initializing Quant Terminal...</span>
      </div>
    );
  }

  if (isLoading && !data) {
    return (
      <div className="w-full min-h-[500px] flex flex-col items-center justify-center bg-[#07090d] border border-violet-900/50 rounded-xl p-8 space-y-4" suppressHydrationWarning>
        <div className="w-10 h-10 border-4 border-violet-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-sm font-mono text-violet-300">
          Computing Nifty 50 Deep Greeks, 50 Constituents Transmission &amp; Market Maker Profiles...
        </span>
        {onClose && (
          <button
            onClick={onClose}
            className="mt-4 px-3 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs"
          >
            Cancel / Close
          </button>
        )}
      </div>
    );
  }

  if (error || !data?.success) {
    return (
      <div className="w-full p-6 bg-[#0c1017] border border-rose-800/80 rounded-xl text-center space-y-3" suppressHydrationWarning>
        <div className="text-rose-400 font-bold text-sm">Nifty Quant Matrix Syncing</div>
        <p className="text-xs font-mono text-zinc-400 max-w-md mx-auto">
          {data?.error || error?.message || "Harvesting option chain snapshot from market..."}
        </p>
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            onClick={handleForceRefresh}
            disabled={isRefreshing}
            className="px-4 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded-md text-xs font-semibold shadow flex items-center gap-2"
          >
            {isRefreshing && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
            {isRefreshing ? "Fetching Live Data..." : "Fetch Live Now"}
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="px-4 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-md text-xs font-semibold"
            >
              Close
            </button>
          )}
        </div>
      </div>
    );
  }

  const {
    spot_price,
    atm_strike,
    days_to_expiry,
    call_wall,
    put_wall,
    max_pain,
    straddle,
    pcr,
    traps,
    heavyweights,
    heavyweight_fno,
    net_heavyweight_points,
    best_trade,
    quant_greeks,
    constituents_report,
    strategies,
  } = data;

  const currentStrategy = strategies?.find((s) => s.id === activeStrategyId) || strategies?.[0];

  return (
    <div className="w-full flex flex-col bg-[#07090d] text-zinc-100 rounded-xl border border-violet-800/60 shadow-2xl overflow-hidden font-sans space-y-4 p-3 sm:p-4">
      {/* ── Top Header / Quick Meta ────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-violet-900/60">
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 w-full md:w-auto">
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="text-base sm:text-lg font-black tracking-tight uppercase bg-gradient-to-r from-violet-300 via-indigo-200 to-white bg-clip-text text-transparent">
                NIFTY 50 DEEP QUANT DESK
              </span>
              <span className="px-1.5 sm:px-2 py-0.5 rounded text-[9px] sm:text-[10px] font-black uppercase bg-violet-600/30 text-violet-300 border border-violet-500/40">
                PRO INSTITUTIONAL LIVE
              </span>
            </div>
            <span className="text-[9px] sm:text-[10px] font-mono text-zinc-500">
              GEX / DEX / VEX Profiles • 50 F&amp;O Constituents Transmission • Vanna &amp; Charm Decay
            </span>
          </div>

          <div className="hidden sm:block h-8 w-px bg-zinc-800" />

          {/* Spot Price readout */}
          <div className="flex items-baseline gap-2 pt-1 sm:pt-0">
            <span className="text-xl sm:text-2xl font-black font-mono tracking-tight text-white">
              {fmt(spot_price, 2)}
            </span>
            <span className="text-xs font-mono text-zinc-400">
              ATM <span className="font-bold text-violet-300">{atm_strike}</span>
            </span>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300">
              {days_to_expiry} DTE
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto justify-between md:justify-start">
          {/* View Mode Toggle */}
          <div className="flex bg-[#0c1017] p-0.5 rounded-lg border border-violet-800/50">
            <button
              onClick={() => setViewMode("flow")}
              className={`px-3 py-1 rounded text-xs font-bold transition-all ${
                viewMode === "flow" ? "bg-violet-600 text-white shadow" : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              🌊 Flow &amp; OI Matrix
            </button>
            <button
              onClick={() => setViewMode("greeks")}
              className={`px-3 py-1 rounded text-xs font-bold transition-all ${
                viewMode === "greeks" ? "bg-violet-600 text-white shadow" : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              📐 Deep Greeks (Δ, Γ, Θ, ν, Vanna, Charm, GEX)
            </button>
          </div>

          <button
            onClick={handleForceRefresh}
            disabled={isRefreshing}
            className={`px-2.5 py-1 rounded-lg border border-zinc-800 bg-[#0c1017] hover:bg-zinc-800 text-zinc-300 hover:text-white transition-all text-xs flex items-center gap-1.5 ${
              isRefreshing ? "opacity-60 cursor-not-allowed" : ""
            }`}
            title="Force Live Scan (bypass cache)"
          >
            <span className={isRefreshing ? "animate-spin inline-block" : ""}>🔄</span>
            <span className="text-[10px] font-mono">{isRefreshing ? "Syncing..." : "Live Scan"}</span>
          </button>

          {onClose && (
            <button
              onClick={onClose}
              className="px-2.5 py-1 rounded-lg border border-zinc-800 bg-[#0c1017] hover:bg-rose-950/40 hover:border-rose-700 text-zinc-400 hover:text-rose-300 text-xs font-bold"
            >
              ✕ Close
            </button>
          )}
        </div>
      </div>

      {/* ── 🧠 DEEP GREEKS & MARKET MAKER PROFILE RIBBON ────────────────── */}
      <div className="p-3.5 rounded-xl border border-violet-900/60 bg-gradient-to-r from-[#0d101a] via-[#101524] to-[#0c0f18] space-y-3 shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-violet-900/40 pb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-black uppercase tracking-wider text-cyan-300 flex items-center gap-1.5">
              <span>🏛️ Institutional Dealer Exposure &amp; Quant Greek Matrix</span>
            </span>
            {quant_greeks && (
              <span
                className={`px-2 py-0.5 rounded text-[9px] font-black uppercase font-mono border ${
                  quant_greeks.gamma_regime.includes("LONG")
                    ? "bg-emerald-950/80 text-emerald-300 border-emerald-600/60"
                    : "bg-rose-950/80 text-rose-300 border-rose-600/60"
                }`}
              >
                {quant_greeks.gamma_regime_badge}
              </span>
            )}
          </div>
          <div className="text-[10px] font-mono text-zinc-400">
            {quant_greeks?.gamma_regime_desc || "Dealer hedging mechanics driving mean-reversion or momentum"}
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
          {/* Net GEX in Cr */}
          <div className="p-2.5 rounded-lg bg-[#07090f] border border-violet-900/40 flex flex-col justify-between">
            <div className="flex items-center justify-between text-[10px] font-mono font-bold text-zinc-400 uppercase">
              <span>Net Gamma (GEX)</span>
              <span className="text-violet-400">₹ Cr</span>
            </div>
            <div
              className={`text-lg font-black font-mono mt-1 ${
                (quant_greeks?.total_net_gex_cr || 0) >= 0 ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {(quant_greeks?.total_net_gex_cr || 0) >= 0 ? "+" : ""}
              {fmt(quant_greeks?.total_net_gex_cr, 1)} Cr
            </div>
            <div className="text-[9px] font-mono text-zinc-500">
              {(quant_greeks?.total_net_gex_cr || 0) >= 0 ? "Dealers sell high / buy low" : "Dealers chase breakouts"}
            </div>
          </div>

          {/* Gamma Flip Strike */}
          <div className="p-2.5 rounded-lg bg-[#07090f] border border-violet-900/40 flex flex-col justify-between">
            <div className="flex items-center justify-between text-[10px] font-mono font-bold text-amber-400 uppercase">
              <span>Gamma Flip Strike</span>
              <span className="text-zinc-500">Pivot</span>
            </div>
            <div className="text-lg font-black font-mono text-amber-300 mt-1">
              {quant_greeks?.gamma_flip_strike || atm_strike}
            </div>
            <div className="text-[9px] font-mono text-zinc-500">
              Dist: {(((spot_price - (quant_greeks?.gamma_flip_strike || atm_strike)) / spot_price) * 100).toFixed(2)}%
            </div>
          </div>

          {/* Dealer Net Delta DEX */}
          <div className="p-2.5 rounded-lg bg-[#07090f] border border-violet-900/40 flex flex-col justify-between">
            <div className="flex items-center justify-between text-[10px] font-mono font-bold text-cyan-400 uppercase">
              <span>Dealer Delta (DEX)</span>
              <span className="text-zinc-500">₹ Cr</span>
            </div>
            <div
              className={`text-lg font-black font-mono mt-1 ${
                (quant_greeks?.dealer_net_dex_cr || 0) >= 0 ? "text-cyan-300" : "text-rose-300"
              }`}
            >
              {(quant_greeks?.dealer_net_dex_cr || 0) >= 0 ? "+" : ""}
              {fmt(quant_greeks?.dealer_net_dex_cr, 1)} Cr
            </div>
            <div className="text-[9px] font-mono text-zinc-500">Underlying hedging load</div>
          </div>

          {/* 25D IV Skew */}
          <div className="p-2.5 rounded-lg bg-[#07090f] border border-violet-900/40 flex flex-col justify-between">
            <div className="flex items-center justify-between text-[10px] font-mono font-bold text-indigo-300 uppercase">
              <span>25Δ IV Skew (PE-CE)</span>
              <span className="text-zinc-500">%</span>
            </div>
            <div className="text-lg font-black font-mono text-indigo-200 mt-1">
              {(quant_greeks?.skew_25d_pct || 0) >= 0 ? "+" : ""}
              {quant_greeks?.skew_25d_pct || 0}%
            </div>
            <div className="text-[9px] font-mono text-zinc-400">
              {quant_greeks?.skew_bias ? String(quant_greeks.skew_bias).replace(/_/g, " ") : "BALANCED SKEW"}
            </div>
          </div>

          {/* ATM Daily Theta Burn */}
          <div className="p-2.5 rounded-lg bg-[#07090f] border border-violet-900/40 flex flex-col justify-between">
            <div className="flex items-center justify-between text-[10px] font-mono font-bold text-rose-400 uppercase">
              <span>Daily Theta Burn</span>
              <span className="text-zinc-500">ATM</span>
            </div>
            <div className="text-lg font-black font-mono text-rose-300 mt-1">
              -₹{fmt(quant_greeks?.atm_daily_theta_burn_cr, 2)} Cr
            </div>
            <div className="text-[9px] font-mono text-zinc-500">Net straddle decay / day</div>
          </div>

          {/* Max Pain & Walls */}
          <div className="p-2.5 rounded-lg bg-[#07090f] border border-violet-900/40 flex flex-col justify-between">
            <div className="flex items-center justify-between text-[10px] font-mono font-bold text-purple-400 uppercase">
              <span>Walls &amp; Pain</span>
              <span className="text-zinc-500">Range</span>
            </div>
            <div className="text-sm font-black font-mono text-purple-200 mt-1">
              P:{put_wall.strike} | C:{call_wall.strike}
            </div>
            <div className="text-[9px] font-mono text-zinc-400">
              Max Pain: <span className="text-white font-bold">{max_pain}</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Active Traps & Anomaly Alerts Banner ──────────────────────── */}
      {traps && traps.length > 0 && (
        <div className="space-y-1.5">
          {traps.map((t, idx) => (
            <div
              key={idx}
              className={`p-2.5 rounded-lg border text-xs font-semibold flex items-center gap-2 ${
                t.severity === "HIGH"
                  ? "bg-rose-950/40 border-rose-700/80 text-rose-200"
                  : "bg-emerald-950/40 border-emerald-700/80 text-emerald-200"
              }`}
            >
              <span className="text-sm">⚡</span>
              <span>{t.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── 🎯 ACTIONABLE MULTI-STRATEGY QUANT DESK (3 PLAYBOOKS) ─────── */}
      <div className="p-3.5 rounded-xl border border-violet-800/60 bg-gradient-to-r from-[#0f1422] via-[#131128] to-[#0d121c] space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-violet-900/40 pb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-violet-300">
              ⚡ INSTITUTIONAL STRATEGY MATRIX (REFINED QUANT DESK)
            </span>
            <span className="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-violet-600 text-white">
              3 STRATEGIES AVAILABLE
            </span>
          </div>

          {/* Strategy Tabs */}
          <div className="flex items-center gap-1 bg-[#090b12] p-1 rounded-lg border border-zinc-800">
            {strategies?.map((strat) => (
              <button
                key={strat.id}
                onClick={() => setActiveStrategyId(strat.id)}
                className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                  activeStrategyId === strat.id
                    ? "bg-violet-600 text-white shadow"
                    : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
                }`}
              >
                <span>{strat.tag === "TREND CAPTURE" ? "🚀" : strat.tag === "VOLATILITY EXPANSION" ? "⚡" : "🛡️"}</span>
                <span>{strat.tag}</span>
              </button>
            ))}
          </div>
        </div>

        {currentStrategy && (
          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pt-1">
            <div className="flex items-center gap-3">
              <div
                className={`w-14 h-14 rounded-xl flex flex-col items-center justify-center font-black text-sm border ${
                  currentStrategy.bias === "BULLISH"
                    ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40"
                    : currentStrategy.bias === "BEARISH"
                    ? "bg-rose-500/20 text-rose-400 border-rose-500/40"
                    : "bg-purple-500/20 text-purple-400 border-purple-500/40"
                }`}
              >
                <span>{currentStrategy.type}</span>
                <span className="text-[9px] font-normal">{currentStrategy.bias}</span>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-black text-white">{currentStrategy.name}</span>
                  <span className="px-1.5 py-0.2 rounded text-[10px] font-black bg-violet-600 text-white">
                    CONVICTION {currentStrategy.conviction_score}/100
                  </span>
                </div>
                <div className="text-xs font-mono font-bold text-zinc-300 mt-0.5 flex items-center gap-2">
                  <span>Strike: <span className="text-violet-300 font-black">{currentStrategy.strike} {currentStrategy.type}</span></span>
                  <span className="text-zinc-500">•</span>
                  <span>Entry LTP: <span className="text-white font-bold">₹{currentStrategy.entry_ltp}</span></span>
                </div>
                <div className="text-[11px] text-zinc-300 mt-1 max-w-2xl leading-relaxed">
                  {currentStrategy.rationale}
                </div>
              </div>
            </div>

            {/* Metrics pills */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 bg-[#080b11] p-3 rounded-lg border border-violet-800/40 w-full md:w-auto">
              <div className="text-center">
                <div className="text-[9px] font-bold text-zinc-500 uppercase">Stop Loss</div>
                <div className="text-xs font-mono font-bold text-rose-400">₹{currentStrategy.stop_loss}</div>
              </div>
              <div className="text-center">
                <div className="text-[9px] font-bold text-zinc-500 uppercase">Target 1</div>
                <div className="text-xs font-mono font-bold text-emerald-400">₹{currentStrategy.target_1}</div>
              </div>
              <div className="text-center">
                <div className="text-[9px] font-bold text-zinc-500 uppercase">Target 2</div>
                <div className="text-xs font-mono font-bold text-emerald-300">₹{currentStrategy.target_2}</div>
              </div>
              <div className="text-center">
                <div className="text-[9px] font-bold text-zinc-500 uppercase">R:R Ratio</div>
                <div className="text-xs font-mono font-black text-violet-300">{currentStrategy.risk_reward}</div>
              </div>
              <div className="text-center col-span-2 sm:col-span-1">
                <div className="text-[9px] font-bold text-zinc-500 uppercase">Delta (Δ) / Vanna</div>
                <div className="text-xs font-mono font-bold text-white">
                  Δ {currentStrategy.greeks.delta} | v {currentStrategy.greeks.vanna ?? 0}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 📊 50 F&O CONSTITUENTS ANALYSIS & SECTOR TRANSMISSION ENGINE ── */}
      <div className="rounded-xl border border-violet-900/60 bg-gradient-to-b from-[#0e121e] to-[#07090e] p-4 shadow-2xl space-y-4">
        {/* Header Row */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-violet-900/40 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-cyan-500"></span>
            </div>
            <div>
              <h2 className="text-sm font-black uppercase tracking-wider text-white flex items-center gap-2">
                <span>⚡ Nifty 50 F&amp;O Constituents &amp; Sector Point Transmission Engine</span>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-violet-950/80 text-violet-300 border border-violet-700/60">
                  ALL 50 STOCKS LIVE
                </span>
              </h2>
              <p className="text-[11px] text-zinc-400 font-medium">
                Real-time weight transmission, advances/declines, F&amp;O wall pressure, and index point attribution
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleForceRefresh}
              disabled={isRefreshing}
              className={`px-2.5 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[11px] font-mono flex items-center gap-1.5 transition-all ${
                isRefreshing ? "opacity-60 cursor-not-allowed" : ""
              }`}
              title="Refresh live option chains & recompute transmission"
            >
              <svg className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {isRefreshing ? "Syncing 50 Stocks..." : "Re-Scan 50 Stocks"}
            </button>
          </div>
        </div>

        {/* 4 Summary Stat Cards for Breadth & Transmission */}
        {constituents_report && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {/* 1. Net Point Impact */}
            <div
              className={`p-3 rounded-lg border flex flex-col justify-between ${
                constituents_report.net_point_contribution >= 0
                  ? "bg-emerald-950/30 border-emerald-800/50"
                  : "bg-rose-950/30 border-rose-800/50"
              }`}
            >
              <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                <span>Net Point Transmission</span>
                <span className={`font-bold ${(constituents_report?.net_point_contribution || 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  {constituents_report?.sentiment ? String(constituents_report.sentiment).replace(/_/g, " ") : "NEUTRAL"}
                </span>
              </div>
              <div className="my-1.5 flex items-baseline gap-2">
                <span
                  className={`text-2xl font-black font-mono tracking-tight ${
                    constituents_report.net_point_contribution >= 0 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {constituents_report.net_point_contribution >= 0 ? "+" : ""}
                  {fmt(constituents_report.net_point_contribution, 1)} pts
                </span>
                <span className="text-[10px] text-zinc-500 font-mono">into Nifty 50</span>
              </div>
              <div className="text-[10px] font-mono text-zinc-400">
                Sum of 50 constituent delta thrusts
              </div>
            </div>

            {/* 2. Market Breadth */}
            <div className="p-3 rounded-lg border bg-[#0b0e17] border-zinc-800 flex flex-col justify-between">
              <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                <span>50 Stock Market Breadth</span>
                <span className="text-zinc-500 font-mono">{constituents_report.total_stocks_tracked} Stocks</span>
              </div>
              <div className="my-1.5 flex items-baseline gap-3">
                <span className="text-base font-black font-mono text-emerald-400">
                  {constituents_report.advances} Adv 🟢
                </span>
                <span className="text-base font-black font-mono text-rose-400">
                  {constituents_report.declines} Dec 🔴
                </span>
                <span className="text-xs font-mono text-zinc-500">
                  {constituents_report.neutral} Flat
                </span>
              </div>
              <div className="w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden flex">
                <div
                  className="bg-emerald-500 h-full"
                  style={{
                    width: `${(constituents_report.advances / Math.max(constituents_report.total_stocks_tracked, 1)) * 100}%`,
                  }}
                />
                <div
                  className="bg-rose-500 h-full"
                  style={{
                    width: `${(constituents_report.declines / Math.max(constituents_report.total_stocks_tracked, 1)) * 100}%`,
                  }}
                />
              </div>
            </div>

            {/* 3. Top Driver */}
            <div className="p-3 rounded-lg border bg-[#0b0e17] border-emerald-900/40 flex flex-col justify-between">
              <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                <span>Top Positive Driver</span>
                <span className="text-emerald-400 font-mono font-bold">LEADER</span>
              </div>
              {constituents_report.top_positive_drivers?.[0] ? (
                <div className="my-1">
                  <div className="text-base font-black font-mono text-white flex items-center justify-between">
                    <span>{constituents_report.top_positive_drivers[0].name}</span>
                    <span className="text-emerald-400 font-bold">
                      +{constituents_report.top_positive_drivers[0].point_impact} pts
                    </span>
                  </div>
                  <div className="text-[10px] font-mono text-zinc-400">
                    +{constituents_report.top_positive_drivers[0].change_pct}% • {constituents_report.top_positive_drivers[0].weight}% wt
                  </div>
                </div>
              ) : (
                <div className="text-xs text-zinc-500">No positive drivers</div>
              )}
              <div className="text-[10px] font-mono text-zinc-500">Primary index supporter</div>
            </div>

            {/* 4. Top Drag */}
            <div className="p-3 rounded-lg border bg-[#0b0e17] border-rose-900/40 flex flex-col justify-between">
              <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                <span>Top Negative Drag</span>
                <span className="text-rose-400 font-mono font-bold">LIFT DOWN</span>
              </div>
              {constituents_report.top_negative_drags?.[0] ? (
                <div className="my-1">
                  <div className="text-base font-black font-mono text-white flex items-center justify-between">
                    <span>{constituents_report.top_negative_drags[0].name}</span>
                    <span className="text-rose-400 font-bold">
                      {constituents_report.top_negative_drags[0].point_impact} pts
                    </span>
                  </div>
                  <div className="text-[10px] font-mono text-zinc-400">
                    {constituents_report.top_negative_drags[0].change_pct}% • {constituents_report.top_negative_drags[0].weight}% wt
                  </div>
                </div>
              ) : (
                <div className="text-xs text-zinc-500">No negative drags</div>
              )}
              <div className="text-[10px] font-mono text-zinc-500">Primary index resistance</div>
            </div>
          </div>
        )}

        {/* ── Sector Breakdown Pills ──────────────────────────────────── */}
        {constituents_report?.sectors && constituents_report.sectors.length > 0 && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-wider text-zinc-400">
              <span>Sector Point Aggregation (Click to filter):</span>
              <span className="text-zinc-500">{constituents_report.sectors.length} Sectors Active</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <button
                onClick={() => setSelectedSector("ALL")}
                className={`px-2.5 py-1 rounded text-[11px] font-mono font-bold transition-all border ${
                  selectedSector === "ALL"
                    ? "bg-violet-600 border-violet-500 text-white shadow"
                    : "bg-[#080b11] border-zinc-800 text-zinc-400 hover:text-white"
                }`}
              >
                ALL SECTORS
              </button>
              {constituents_report.sectors.map((sec) => (
                <button
                  key={sec.sector}
                  onClick={() => setSelectedSector(selectedSector === sec.sector ? "ALL" : sec.sector)}
                  className={`px-2.5 py-1 rounded text-[11px] font-mono transition-all border flex items-center gap-1.5 ${
                    selectedSector === sec.sector
                      ? "bg-violet-600 border-violet-500 text-white font-bold shadow"
                      : "bg-[#080b11] border-zinc-800/80 text-zinc-300 hover:border-zinc-700"
                  }`}
                >
                  <span className="font-semibold">{sec.sector}</span>
                  <span className="text-[9px] text-zinc-500">({sec.weight}%)</span>
                  <span
                    className={`font-black ${
                      sec.net_point_contribution >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {sec.net_point_contribution >= 0 ? "+" : ""}
                    {sec.net_point_contribution}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── 50 Constituents Filters & Search Bar ────────────────────── */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-zinc-800/80">
          <div className="flex flex-wrap items-center gap-1.5 bg-[#080b11] p-1 rounded-lg border border-zinc-800">
            <button
              onClick={() => setConstituentTab("top10")}
              className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition-all ${
                constituentTab === "top10" ? "bg-violet-600 text-white" : "text-zinc-400 hover:text-white"
              }`}
            >
              Top 10 Heavyweights (48.7%)
            </button>
            <button
              onClick={() => setConstituentTab("all")}
              className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition-all ${
                constituentTab === "all" ? "bg-violet-600 text-white" : "text-zinc-400 hover:text-white"
              }`}
            >
              All 50 Stocks ({constituents_report?.stocks?.length || 50})
            </button>
            <button
              onClick={() => setConstituentTab("gainers")}
              className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition-all ${
                constituentTab === "gainers" ? "bg-emerald-600 text-white" : "text-zinc-400 hover:text-emerald-300"
              }`}
            >
              Gainers Only
            </button>
            <button
              onClick={() => setConstituentTab("drags")}
              className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition-all ${
                constituentTab === "drags" ? "bg-rose-600 text-white" : "text-zinc-400 hover:text-rose-300"
              }`}
            >
              Drags Only
            </button>
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto">
            <input
              type="text"
              placeholder="Search symbol, sector (e.g. RELIANCE, Banking)..."
              value={searchStock}
              onChange={(e) => setSearchStock(e.target.value)}
              className="px-3 py-1.5 bg-[#080b11] border border-zinc-700 rounded-lg text-xs font-mono text-white placeholder-zinc-500 w-full sm:w-64 focus:outline-none focus:border-violet-500"
            />
            {searchStock && (
              <button
                onClick={() => setSearchStock("")}
                className="text-xs text-zinc-400 hover:text-white"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* ── 50 Constituents Grid ───────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-2.5 max-h-[520px] overflow-y-auto pr-1">
          {filteredStocks.map((stk) => {
            const isSelected = simStock === stk.symbol;
            return (
              <div
                key={stk.symbol}
                onClick={() => {
                  setSimStock(stk.symbol);
                  setSimMove(stk.change_pct !== 0 ? stk.change_pct : 1.5);
                }}
                className={`p-2.5 rounded-xl border transition-all cursor-pointer flex flex-col justify-between space-y-2 ${
                  isSelected
                    ? "bg-[#101524] border-violet-500 shadow-md shadow-violet-950/40 ring-1 ring-violet-500"
                    : "bg-[#080b11] border-zinc-800/80 hover:border-zinc-700 hover:bg-[#0c1018]"
                }`}
              >
                <div>
                  <div className="flex items-start justify-between gap-1">
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-xs text-white">{stk.name}</span>
                        <span className="text-[9px] font-mono px-1 rounded bg-zinc-800 text-zinc-400">
                          {stk.weight}% wt
                        </span>
                      </div>
                      <div className="text-[10px] font-mono text-zinc-500">{stk.sector}</div>
                    </div>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold tracking-tight border ${
                        stk.bias === "BULLISH"
                          ? "bg-emerald-950/60 text-emerald-300 border-emerald-700/60"
                          : stk.bias === "BEARISH"
                          ? "bg-rose-950/60 text-rose-300 border-rose-700/60"
                          : "bg-zinc-900 text-zinc-400 border-zinc-800"
                      }`}
                    >
                      {stk.bias}
                    </span>
                  </div>

                  <div className="flex items-baseline justify-between mt-1">
                    <span className="text-xs font-mono font-black text-zinc-200">
                      ₹{stk.ltp.toFixed(1)}
                    </span>
                    <span
                      className={`text-xs font-mono font-bold ${
                        stk.change_pct >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {stk.change_pct >= 0 ? "+" : ""}
                      {stk.change_pct}%
                    </span>
                  </div>
                </div>

                {/* Point Impact & Walls */}
                <div className="p-1.5 rounded bg-[#05070a] border border-zinc-800/60 text-[10px] font-mono space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-500">Nifty Thrust:</span>
                    <span
                      className={`font-black ${
                        stk.point_impact >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {stk.point_impact >= 0 ? "+" : ""}
                      {stk.point_impact} pts
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-zinc-400 text-[9px]">
                    <span>P: {stk.put_wall || "—"}</span>
                    <span>PCR: {stk.pcr || "—"}</span>
                    <span>C: {stk.call_wall || "—"}</span>
                  </div>
                </div>

                {/* Action button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setSimStock(stk.symbol);
                    setSimMove(stk.change_pct !== 0 ? stk.change_pct : 1.5);
                    handleSimulate();
                  }}
                  className="w-full py-1 rounded bg-zinc-800/80 hover:bg-violet-600 hover:text-white text-zinc-300 text-[9px] font-mono font-bold transition-all"
                >
                  Simulate Shock →
                </button>
              </div>
            );
          })}
        </div>

        {/* ── What-If Breakout Simulator Bar ─────────────────────────── */}
        <div className="p-3 rounded-xl bg-[#090c13] border border-violet-900/40">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-amber-300">
                🔮 What-If Stock Breakout Shock Simulator
              </span>
              <span className="text-[10px] text-zinc-400">
                Simulate an earnings shock or breakout on any of the 50 constituent stocks to compute projected Nifty rally &amp; target strike.
              </span>
            </div>
            <span className="text-[9px] font-mono text-zinc-500">
              Formula: (Weight% / 100) × Stock% × Nifty Spot
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-center">
            {/* Stock Select */}
            <div className="md:col-span-4">
              <label className="text-[9px] font-mono text-zinc-400 uppercase block mb-1">
                Select Constituent Stock (50 Available)
              </label>
              <select
                value={simStock}
                onChange={(e) => setSimStock(e.target.value)}
                className="w-full bg-[#0c1017] border border-zinc-700 text-xs font-semibold rounded px-2.5 py-1.5 text-white"
              >
                {(constituents_report?.stocks || heavyweights).map((s) => (
                  <option key={s.symbol} value={s.symbol}>
                    {s.name} ({s.weight}% Weight - {s.sector})
                  </option>
                ))}
              </select>
            </div>

            {/* Move % & Presets */}
            <div className="md:col-span-4">
              <label className="text-[9px] font-mono text-zinc-400 uppercase block mb-1">
                Projected Stock Breakout %
              </label>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1 w-24">
                  <input
                    type="number"
                    step="0.5"
                    value={simMove}
                    onChange={(e) => setSimMove(parseFloat(e.target.value) || 0)}
                    className="w-full bg-[#0c1017] border border-zinc-700 text-xs font-mono font-bold rounded px-2 py-1 text-right text-white"
                  />
                  <span className="text-xs text-zinc-400 font-mono">%</span>
                </div>

                <div className="flex gap-1">
                  {[+1.5, +2.5, +4.0, -2.0, -3.5].map((pct) => (
                    <button
                      key={pct}
                      onClick={() => setSimMove(pct)}
                      className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold ${
                        pct > 0
                          ? "bg-emerald-950/60 text-emerald-300 hover:bg-emerald-900"
                          : "bg-rose-950/60 text-rose-300 hover:bg-rose-900"
                      }`}
                    >
                      {pct > 0 ? `+${pct}%` : `${pct}%`}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Run Button */}
            <div className="md:col-span-4 flex items-end">
              <button
                onClick={handleSimulate}
                disabled={simLoading}
                className="w-full py-2 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 font-bold text-xs uppercase tracking-wider text-white transition-all shadow-md"
              >
                {simLoading ? "Calculating Impact..." : "Compute Transmitted Nifty Target →"}
              </button>
            </div>
          </div>

          {/* Simulation Output Card */}
          {simResult && (
            <div className="mt-3 p-3 rounded-lg bg-[#06080e] border border-violet-800/60 grid grid-cols-1 sm:grid-cols-4 gap-2 text-xs font-mono">
              <div>
                <span className="text-zinc-500 text-[10px] block">Stock Simulating</span>
                <span className="font-bold text-white">
                  {simResult.stock_name} ({simResult.expected_stock_move_pct}%)
                </span>
              </div>
              <div>
                <span className="text-zinc-500 text-[10px] block">Nifty Point Impact</span>
                <span
                  className={`font-black text-sm ${
                    simResult.projected_nifty_points >= 0 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {simResult.projected_nifty_points >= 0 ? "+" : ""}
                  {simResult.projected_nifty_points} pts
                </span>
              </div>
              <div>
                <span className="text-zinc-500 text-[10px] block">New Projected Nifty</span>
                <span className="font-black text-sm text-white">
                  {simResult.projected_nifty_target}
                </span>
              </div>
              <div>
                <span className="text-zinc-500 text-[10px] block">Recommended Strike</span>
                <span className="font-black text-sm text-violet-300">
                  {simResult.recommended_strike}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Dynamic Strike Color Matrix Option Chain Table ──────────── */}
      <div className="w-full overflow-hidden rounded-xl border border-violet-900/50 bg-[#080b10]">
        {/* Table Top Controls & Filters */}
        <div className="p-2.5 bg-[#0b0e16] border-b border-violet-900/50 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs font-black uppercase tracking-wider text-zinc-200">
              🎯 Strike-by-Strike 4-Quadrant Color Matrix
            </span>

            {/* Strike Range Window Toggles */}
            <div className="flex items-center gap-1 bg-[#06080d] p-0.5 rounded-lg border border-zinc-800">
              <span className="text-[9px] font-mono text-zinc-500 px-1.5 uppercase">Window:</span>
              {[
                { label: "ATM ± 8", val: 8 },
                { label: "ATM ± 12 (Focused)", val: 12 },
                { label: "ATM ± 16", val: 16 },
                { label: `All (${strikes.length})`, val: "all" as const },
              ].map((opt) => (
                <button
                  key={String(opt.val)}
                  onClick={() => setStrikeWindow(opt.val)}
                  className={`px-2 py-0.5 rounded text-[9px] font-mono font-bold transition-all ${
                    strikeWindow === opt.val
                      ? "bg-violet-600 text-white shadow"
                      : "text-zinc-400 hover:text-white hover:bg-zinc-800/60"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* Jump Navigation Buttons */}
            <div className="flex items-center gap-1.5">
              {best_trade && (
                <button
                  onClick={() => scrollToStrike(best_trade.strike)}
                  className="px-2 py-0.5 rounded text-[9px] font-mono font-black bg-amber-400/20 text-amber-300 border border-amber-400/50 hover:bg-amber-400/30 flex items-center gap-1 transition-all"
                >
                  <span>⭐ Jump to Best Strike ({best_trade.strike} {best_trade.option_type})</span>
                </button>
              )}
              <button
                onClick={() => scrollToStrike(atm_strike)}
                className="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-violet-950/60 text-violet-300 border border-violet-700/60 hover:bg-violet-900/60 flex items-center gap-1 transition-all"
              >
                <span>📍 ATM ({atm_strike})</span>
              </button>
            </div>
          </div>

          {/* Legend Badges */}
          <div className="flex flex-wrap items-center gap-2 text-[10px] font-mono">
            <span className="flex items-center gap-1 text-[#00E676]">
              <span className="w-2 h-2 rounded-full bg-[#00E676]" /> Long Buildup (LBU)
            </span>
            <span className="flex items-center gap-1 text-[#FF1744]">
              <span className="w-2 h-2 rounded-full bg-[#FF1744]" /> Short Buildup (SBU)
            </span>
            <span className="flex items-center gap-1 text-[#00E5FF]">
              <span className="w-2 h-2 rounded-full bg-[#00E5FF]" /> Short Covering (SH-COV)
            </span>
            <span className="flex items-center gap-1 text-[#FF9100]">
              <span className="w-2 h-2 rounded-full bg-[#FF9100]" /> Long Unwinding (LUW)
            </span>
            <span className="flex items-center gap-1 text-[#FFD600]">
              <span className="w-2 h-2 rounded-full bg-[#FFD600]" /> ⚡ Gamma
            </span>
          </div>
        </div>

        {/* Mobile Swipe Cue */}
        <div className="md:hidden px-3 py-1.5 bg-violet-950/40 border-b border-violet-800/50 flex items-center justify-between text-[10px] text-violet-300 font-mono">
          <span>⟵ Swipe strike matrix horizontally ⟶</span>
          <span className="text-zinc-400">13 Columns</span>
        </div>

        <div className="overflow-x-auto touch-scroll max-h-[540px]">
          <table className="w-full text-left border-collapse text-[11px] font-mono min-w-[860px]">
            <thead className="sticky top-0 z-20 bg-[#0c1017] shadow-md border-b-2 border-violet-900">
              <tr>
                <th
                  colSpan={viewMode === "flow" ? 6 : 7}
                  className="py-1 px-2 text-center font-black tracking-widest uppercase bg-emerald-950/40 text-emerald-300 border-r border-violet-900/60"
                >
                  CALLS (CE)
                </th>
                <th className="py-1 px-3 text-center font-black tracking-widest uppercase bg-[#141824] text-violet-300 border-r border-violet-900/60">
                  STRIKE / GEX
                </th>
                <th
                  colSpan={viewMode === "flow" ? 6 : 7}
                  className="py-1 px-2 text-center font-black tracking-widest uppercase bg-rose-950/40 text-rose-300"
                >
                  PUTS (PE)
                </th>
              </tr>
              <tr className="bg-[#080b11] text-[10px] text-zinc-400 border-b border-zinc-800">
                {/* CALL HEADERS */}
                {viewMode === "flow" ? (
                  <>
                    <th className="py-1.5 px-2 text-left">State</th>
                    <th className="py-1.5 px-2 text-right">OI (Shares)</th>
                    <th className="py-1.5 px-2 text-right">Δ OI</th>
                    <th className="py-1.5 px-2 text-right">Vol</th>
                    <th className="py-1.5 px-2 text-right">IV%</th>
                    <th className="py-1.5 px-2 text-right font-black text-white border-r border-violet-900/40">
                      LTP
                    </th>
                  </>
                ) : (
                  <>
                    <th className="py-1.5 px-2 text-left">Delta (Δ)</th>
                    <th className="py-1.5 px-2 text-right">Gamma (Γ)</th>
                    <th className="py-1.5 px-2 text-right">Theta (Θ)</th>
                    <th className="py-1.5 px-2 text-right">Vega (ν)</th>
                    <th className="py-1.5 px-2 text-right text-violet-400">Vanna</th>
                    <th className="py-1.5 px-2 text-right">IV%</th>
                    <th className="py-1.5 px-2 text-right font-black text-white border-r border-violet-900/40">
                      LTP
                    </th>
                  </>
                )}

                {/* STRIKE */}
                <th className="py-1.5 px-3 text-center bg-[#111522] font-black text-white border-r border-violet-900/40">
                  LEVEL
                </th>

                {/* PUT HEADERS */}
                {viewMode === "flow" ? (
                  <>
                    <th className="py-1.5 px-2 text-left font-black text-white">LTP</th>
                    <th className="py-1.5 px-2 text-left">IV%</th>
                    <th className="py-1.5 px-2 text-left">Vol</th>
                    <th className="py-1.5 px-2 text-left">Δ OI</th>
                    <th className="py-1.5 px-2 text-left">OI (Shares)</th>
                    <th className="py-1.5 px-2 text-right">State</th>
                  </>
                ) : (
                  <>
                    <th className="py-1.5 px-2 text-left font-black text-white">LTP</th>
                    <th className="py-1.5 px-2 text-left">IV%</th>
                    <th className="py-1.5 px-2 text-left text-violet-400">Vanna</th>
                    <th className="py-1.5 px-2 text-left">Vega (ν)</th>
                    <th className="py-1.5 px-2 text-left">Theta (Θ)</th>
                    <th className="py-1.5 px-2 text-left">Gamma (Γ)</th>
                    <th className="py-1.5 px-2 text-right">Delta (Δ)</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {displayedStrikes.map((r) => {
                const k = r.strike;
                const isCallWall = k === call_wall.strike;
                const isPutWall = k === put_wall.strike;
                const isMaxPain = k === max_pain;
                const isAtm = r.is_atm;

                // BEST STRIKE DETECTION
                const isBestStrike = best_trade && best_trade.strike === k;
                const isBestLegCall = isBestStrike && best_trade.option_type === "CE";
                const isBestLegPut = isBestStrike && best_trade.option_type === "PE";

                return (
                  <tr
                    key={k}
                    id={`strike-row-${k}`}
                    className={`border-b transition-all ${
                      isBestStrike
                        ? "bg-gradient-to-r from-amber-500/15 via-violet-900/30 to-amber-500/15 border-y-2 border-amber-400 ring-1 ring-amber-400/50 shadow-lg shadow-amber-950/40"
                        : isAtm
                        ? "bg-violet-950/30 border-zinc-900/60 font-bold"
                        : "border-zinc-900/60 hover:bg-white/[0.04]"
                    }`}
                  >
                    {/* ── CALL SIDE ──────────────────────────────────── */}
                    {viewMode === "flow" ? (
                      <>
                        <td className="py-1.5 px-2 text-left">
                          <span
                            className="px-1.5 py-0.5 rounded text-[9px] font-black border"
                            style={{
                              color: r.call.color,
                              borderColor: `${r.call.color}55`,
                              backgroundColor: `${r.call.color}15`,
                            }}
                          >
                            {r.call.badge}
                          </span>
                        </td>
                        <td className="py-1.5 px-2 text-right text-zinc-300">
                          {fmtOI(r.call.oi)}
                        </td>
                        <td
                          className={`py-1.5 px-2 text-right font-bold ${
                            r.call.oich > 0
                              ? "text-emerald-400"
                              : r.call.oich < 0
                              ? "text-rose-400"
                              : "text-zinc-500"
                          }`}
                        >
                          {fmtOiCh(r.call.oich)}
                        </td>
                        <td className="py-1.5 px-2 text-right text-zinc-400">
                          {fmtVol(r.call.volume)}
                        </td>
                        <td className="py-1.5 px-2 text-right text-zinc-300">
                          {r.call.iv.toFixed(1)}%
                        </td>
                        <td
                          className={`py-1.5 px-2 text-right font-black border-r border-violet-900/40 ${
                            isBestLegCall
                              ? "bg-amber-400/20 border-l-2 border-amber-400 text-amber-300"
                              : "text-white"
                          }`}
                        >
                          <div className="flex items-center justify-end gap-1">
                            {isBestLegCall && (
                              <span className="text-[8px] px-1 py-0.2 rounded bg-amber-400 text-black font-black uppercase">
                                BUY
                              </span>
                            )}
                            <span>₹{r.call.ltp.toFixed(1)}</span>
                          </div>
                          {isBestLegCall && (
                            <span className="text-[8px] text-amber-200 font-mono block">
                              Tgt ₹{best_trade.target_1} | SL ₹{best_trade.stop_loss}
                            </span>
                          )}
                        </td>
                      </>
                    ) : (
                      <>
                        <td
                          className={`py-1.5 px-2 text-left font-bold ${
                            Math.abs(r.call.greeks.delta) >= 0.38 &&
                            Math.abs(r.call.greeks.delta) <= 0.52
                              ? "text-amber-300 font-black"
                              : "text-zinc-300"
                          }`}
                        >
                          {r.call.greeks.delta}
                        </td>
                        <td className="py-1.5 px-2 text-right text-zinc-400">
                          {r.call.greeks.gamma}
                        </td>
                        <td className="py-1.5 px-2 text-right text-rose-400">
                          ₹{r.call.greeks.theta}
                        </td>
                        <td className="py-1.5 px-2 text-right text-zinc-400">
                          {r.call.greeks.vega}
                        </td>
                        <td className="py-1.5 px-2 text-right text-violet-300">
                          {r.call.greeks.vanna ?? 0}
                        </td>
                        <td className="py-1.5 px-2 text-right text-zinc-300">
                          {r.call.iv.toFixed(1)}%
                        </td>
                        <td
                          className={`py-1.5 px-2 text-right font-black border-r border-violet-900/40 ${
                            isBestLegCall
                              ? "bg-amber-400/20 border-l-2 border-amber-400 text-amber-300"
                              : "text-white"
                          }`}
                        >
                          <div className="flex items-center justify-end gap-1">
                            {isBestLegCall && (
                              <span className="text-[8px] px-1 py-0.2 rounded bg-amber-400 text-black font-black uppercase">
                                BUY
                              </span>
                            )}
                            <span>₹{r.call.ltp.toFixed(1)}</span>
                          </div>
                        </td>
                      </>
                    )}

                    {/* ── STRIKE PIN & BEST STRIKE MARKER ─────────────── */}
                    <td className="py-1.5 px-3 text-center bg-[#0e121d] border-r border-violet-900/40 font-black">
                      <div className="flex flex-col items-center justify-center gap-0.5">
                        <div className="flex items-center gap-1">
                          <span
                            className={`font-mono ${
                              isBestStrike
                                ? "text-amber-300 text-sm font-black"
                                : isAtm
                                ? "text-violet-300 text-sm"
                                : isCallWall
                                ? "text-rose-400"
                                : isPutWall
                                ? "text-emerald-400"
                                : "text-zinc-300"
                            }`}
                          >
                            {k}
                          </span>
                          {isAtm && (
                            <span className="text-[8px] bg-violet-600 text-white px-1 py-0.2 rounded font-black">
                              ATM
                            </span>
                          )}
                        </div>

                        {/* Net GEX pill if present */}
                        {r.net_gex_cr !== undefined && (
                          <span
                            className={`text-[8px] px-1 rounded font-mono ${
                              r.net_gex_cr >= 0 ? "text-emerald-400" : "text-rose-400"
                            }`}
                          >
                            {r.net_gex_cr >= 0 ? "+" : ""}{r.net_gex_cr} Cr
                          </span>
                        )}

                        {/* Prominent Best Strike Badge */}
                        {isBestStrike && (
                          <span className="text-[9px] bg-amber-400 text-black px-1.5 py-0.5 rounded font-black tracking-wider flex items-center gap-0.5 shadow-sm animate-pulse">
                            ⭐ BEST {best_trade.option_type}
                          </span>
                        )}

                        {isCallWall && !isBestStrike && (
                          <span className="text-[8px] bg-rose-900/60 text-rose-300 border border-rose-700 px-1 py-0.2 rounded font-black">
                            RES
                          </span>
                        )}
                        {isPutWall && !isBestStrike && (
                          <span className="text-[8px] bg-emerald-900/60 text-emerald-300 border border-emerald-700 px-1 py-0.2 rounded font-black">
                            SUP
                          </span>
                        )}
                        {isMaxPain && !isBestStrike && (
                          <span className="text-[8px] bg-purple-900/60 text-purple-300 border border-purple-700 px-1 py-0.2 rounded font-black">
                            PAIN
                          </span>
                        )}
                      </div>
                    </td>

                    {/* ── PUT SIDE ───────────────────────────────────── */}
                    {viewMode === "flow" ? (
                      <>
                        <td
                          className={`py-1.5 px-2 text-left font-black ${
                            isBestLegPut
                              ? "bg-amber-400/20 border-r-2 border-amber-400 text-amber-300"
                              : "text-white"
                          }`}
                        >
                          <div className="flex items-center justify-start gap-1">
                            <span>₹{r.put.ltp.toFixed(1)}</span>
                            {isBestLegPut && (
                              <span className="text-[8px] px-1 py-0.2 rounded bg-amber-400 text-black font-black uppercase">
                                BUY
                              </span>
                            )}
                          </div>
                          {isBestLegPut && (
                            <span className="text-[8px] text-amber-200 font-mono block">
                              Tgt ₹{best_trade.target_1} | SL ₹{best_trade.stop_loss}
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 px-2 text-left text-zinc-300">
                          {r.put.iv.toFixed(1)}%
                        </td>
                        <td className="py-1.5 px-2 text-left text-zinc-400">
                          {fmtVol(r.put.volume)}
                        </td>
                        <td
                          className={`py-1.5 px-2 text-left font-bold ${
                            r.put.oich > 0
                              ? "text-emerald-400"
                              : r.put.oich < 0
                              ? "text-rose-400"
                              : "text-zinc-500"
                          }`}
                        >
                          {fmtOiCh(r.put.oich)}
                        </td>
                        <td className="py-1.5 px-2 text-left text-zinc-300">
                          {fmtOI(r.put.oi)}
                        </td>
                        <td className="py-1.5 px-2 text-right">
                          <span
                            className="px-1.5 py-0.5 rounded text-[9px] font-black border"
                            style={{
                              color: r.put.color,
                              borderColor: `${r.put.color}55`,
                              backgroundColor: `${r.put.color}15`,
                            }}
                          >
                            {r.put.badge}
                          </span>
                        </td>
                      </>
                    ) : (
                      <>
                        <td
                          className={`py-1.5 px-2 text-left font-black ${
                            isBestLegPut
                              ? "bg-amber-400/20 border-r-2 border-amber-400 text-amber-300"
                              : "text-white"
                          }`}
                        >
                          <div className="flex items-center justify-start gap-1">
                            <span>₹{r.put.ltp.toFixed(1)}</span>
                            {isBestLegPut && (
                              <span className="text-[8px] px-1 py-0.2 rounded bg-amber-400 text-black font-black uppercase">
                                BUY
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-1.5 px-2 text-left text-zinc-300">
                          {r.put.iv.toFixed(1)}%
                        </td>
                        <td className="py-1.5 px-2 text-left text-violet-300">
                          {r.put.greeks.vanna ?? 0}
                        </td>
                        <td className="py-1.5 px-2 text-left text-zinc-400">
                          {r.put.greeks.vega}
                        </td>
                        <td className="py-1.5 px-2 text-left text-rose-400">
                          ₹{r.put.greeks.theta}
                        </td>
                        <td className="py-1.5 px-2 text-left text-zinc-400">
                          {r.put.greeks.gamma}
                        </td>
                        <td
                          className={`py-1.5 px-2 text-right font-bold ${
                            Math.abs(r.put.greeks.delta) >= 0.38 &&
                            Math.abs(r.put.greeks.delta) <= 0.52
                              ? "text-amber-300 font-black"
                              : "text-zinc-300"
                          }`}
                        >
                          {r.put.greeks.delta}
                        </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
