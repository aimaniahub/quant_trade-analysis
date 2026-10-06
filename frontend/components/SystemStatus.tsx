'use client';

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

  return (
    <div className="flex items-center gap-2 sm:gap-3 text-[10px] uppercase tracking-wider">
      {/* Backend Status */}
      <span className="flex items-center gap-1 shrink-0" title={backendOk ? 'Backend API Connected' : 'Backend API Offline'}>
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            backendOk ? 'bg-emerald-500' : isFetching ? 'bg-amber-400' : 'bg-rose-500'
          }`}
        />
        <span className="hidden sm:inline">{backendOk ? 'Backend Active' : 'Backend Down'}</span>
        <span className="sm:hidden">{backendOk ? 'API OK' : 'API ERR'}</span>
      </span>

      {/* Fyers Auth Status */}
      <span className="flex items-center gap-1 shrink-0" title={fyersOk ? 'Fyers Token Valid & Active' : 'Fyers Token Missing or Expired'}>
        <span
          className={`w-1.5 h-1.5 rounded-full ${fyersOk ? 'bg-blue-500' : 'bg-zinc-500'}`}
        />
        <span className="hidden sm:inline">{fyersOk ? 'Fyers Auth OK' : 'Fyers Unauthenticated'}</span>
        <span className="sm:hidden">{fyersOk ? 'Auth OK' : 'No Auth'}</span>
      </span>

      {/* Secondary Telemetry: Visible on Tablets & Desktops */}
      <span className="hidden md:flex items-center gap-1 text-zinc-500">
        Trading {trading}
      </span>
      <span className="hidden lg:flex items-center gap-1 text-zinc-500">
        News {grok === 'configured' ? 'Key Set' : 'Off'}
      </span>
      <span className="hidden lg:flex items-center gap-1 text-zinc-500">
        Redis {redis === 'ok' ? 'OK' : redis === 'down' ? 'Down' : 'Off'}
      </span>
      <span className={`hidden md:flex items-center gap-1 ${cooling ? 'text-amber-400' : 'text-zinc-500'}`}>
        Fyers {rpm}/{rpmLimit} RPM{cooling ? ` cooldown ${coolLeft}s` : ''}
      </span>
    </div>
  );
}
