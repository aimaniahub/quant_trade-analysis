'use client';

import { useState } from 'react';
import { api } from '../lib/api';
import { useApiQuery } from '../lib/hooks/useApiQuery';
import { useAuth } from '../lib/hooks/useAuth';
import { useMarketPolling } from '../lib/hooks/useMarketPolling';

interface ReadyResponse {
  status?: string;
  authenticated?: boolean;
  dependencies?: {
    fyers_api?: string;
    grok_api?: string;
    mcp_trading?: string;
    redis?: string;
  };
  fyers?: {
    requests_last_minute?: number;
    rpm?: number;
    limit?: number;
    rpm_limit?: number;
    cooldown?: boolean;
    cooldown_remaining?: number;
    '429_count'?: number;
  };
  radar?: {
    scan_running?: boolean;
    phase?: string;
    scanned?: number;
    total?: number;
  };
}

export default function SystemStatus() {
  const { status: auth } = useAuth();
  const { interval } = useMarketPolling(30000);
  const { data, isError, isFetching } = useApiQuery<ReadyResponse>(
    ['system', 'ready'],
    () => api.market.getReady() as Promise<ReadyResponse>,
    { refetchInterval: interval },
  );

  const backendOk = !isError && Boolean(data);
  const fyersOk =
    data?.dependencies?.fyers_api === 'ok' ||
    Boolean(auth?.authenticated || auth?.is_valid);
  const trading =
    data?.dependencies?.mcp_trading === 'enabled' ? 'ARMED' : 'OFF';
  const grok = data?.dependencies?.grok_api || '—';
  const redis = data?.dependencies?.redis || '—';
  const rpm = data?.fyers?.rpm ?? data?.fyers?.requests_last_minute ?? 0;
  const rpmLimit = data?.fyers?.rpm_limit ?? data?.fyers?.limit ?? 200;
  const cooling = Boolean(data?.fyers?.cooldown);
  const coolLeft = Math.ceil(Number(data?.fyers?.cooldown_remaining || 0));

  const [showTelemetry, setShowTelemetry] = useState(false);

  return (
    <div className="relative flex items-center gap-1.5 sm:gap-2.5 text-[10px] uppercase tracking-wider shrink-0">
      {/* Backend Status */}
      <span
        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-zinc-900/60 border border-zinc-800 text-zinc-300 shrink-0 select-none"
        title={backendOk ? 'Backend API Connected & Operational' : 'Backend API Offline'}
      >
        <span
          className={`w-1.5 h-1.5 rounded-full shrink-0 ${
            backendOk ? 'bg-emerald-500' : isFetching ? 'bg-amber-400 animate-pulse' : 'bg-rose-500'
          }`}
        />
        <span className="hidden sm:inline font-mono">{backendOk ? 'API OK' : 'API DOWN'}</span>
      </span>

      {/* Fyers Auth Status */}
      <span
        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-zinc-900/60 border border-zinc-800 text-zinc-300 shrink-0 select-none"
        title={fyersOk ? 'Fyers Token Valid & Active' : 'Fyers Token Missing or Expired'}
      >
        <span
          className={`w-1.5 h-1.5 rounded-full shrink-0 ${fyersOk ? 'bg-blue-400' : 'bg-zinc-500'}`}
        />
        <span className="hidden sm:inline font-mono">{fyersOk ? 'FYERS OK' : 'FYERS OFF'}</span>
      </span>

      {/* Telemetry Popover Button for quick inspection */}
      <div className="relative">
        <button
          onClick={() => setShowTelemetry(!showTelemetry)}
          className={`p-1 rounded bg-zinc-900/60 hover:bg-zinc-800 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors flex items-center gap-1 ${
            cooling ? 'border-amber-500/40 text-amber-400' : ''
          }`}
          title="Toggle System Telemetry"
          aria-label="System Telemetry"
        >
          <span className="font-mono text-[9px] px-0.5">{cooling ? '⚠️ RATE' : 'SYS'}</span>
        </button>

        {showTelemetry && (
          <div
            className="absolute right-0 mt-2 w-56 rounded-xl bg-[#0c1017] border border-zinc-800 shadow-2xl p-3 z-50 text-xs font-mono normal-case space-y-2 animate-fadeIn"
            onMouseLeave={() => setShowTelemetry(false)}
          >
            <div className="flex items-center justify-between pb-1.5 border-b border-zinc-800 text-zinc-300 font-bold text-[11px] uppercase tracking-wider">
              <span>System Telemetry</span>
              <button
                onClick={() => setShowTelemetry(false)}
                className="text-zinc-500 hover:text-white"
              >
                ✕
              </button>
            </div>
            <div className="space-y-1.5 text-[11px]">
              <div className="flex justify-between items-center text-zinc-400">
                <span>Trading MCP:</span>
                <span className={trading === 'ARMED' ? 'text-emerald-400 font-bold' : 'text-zinc-500'}>
                  {trading}
                </span>
              </div>
              <div className="flex justify-between items-center text-zinc-400">
                <span>News Engine:</span>
                <span className={grok === 'configured' ? 'text-emerald-400' : 'text-zinc-500'}>
                  {grok === 'configured' ? 'ACTIVE' : 'OFF'}
                </span>
              </div>
              <div className="flex justify-between items-center text-zinc-400">
                <span>Redis Cache:</span>
                <span className={redis === 'ok' ? 'text-emerald-400' : 'text-zinc-500'}>
                  {redis.toUpperCase()}
                </span>
              </div>
              <div className="flex justify-between items-center text-zinc-400">
                <span>Fyers RPM:</span>
                <span className={cooling ? 'text-amber-400 font-bold' : 'text-zinc-300'}>
                  {rpm} / {rpmLimit}
                </span>
              </div>
              {cooling && (
                <div className="pt-1 border-t border-zinc-800 text-amber-400 text-[10px]">
                  Cooldown active: {coolLeft}s remaining
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Extra Telemetry: Inline only on ultra-wide screens */}
      <span className="hidden min-[1680px]:flex items-center gap-1 text-zinc-500 font-mono text-[9px]">
        {rpm}/{rpmLimit} RPM
      </span>
    </div>
  );
}
