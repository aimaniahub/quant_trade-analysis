'use client';

import { api } from '../lib/api';
import { useApiQuery } from '../lib/hooks/useApiQuery';
import { useAuth } from '../lib/hooks/useAuth';

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
  const { data, isError, isFetching } = useApiQuery<ReadyResponse>(
    ['system', 'ready'],
    () => api.market.getReady() as Promise<ReadyResponse>,
    { refetchInterval: 20000 },
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
    <div className="flex flex-wrap items-center gap-3 text-[10px] uppercase tracking-wider">
      <span className="flex items-center gap-1">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            backendOk ? 'bg-emerald-500' : isFetching ? 'bg-amber-400' : 'bg-rose-500'
          }`}
        />
        {backendOk ? 'Backend Active' : 'Backend Down'}
      </span>
      <span className="flex items-center gap-1">
        <span
          className={`w-1.5 h-1.5 rounded-full ${fyersOk ? 'bg-blue-500' : 'bg-zinc-500'}`}
        />
        {fyersOk ? 'Fyers Auth OK' : 'Fyers Unauthenticated'}
      </span>
      <span className="flex items-center gap-1 text-zinc-500">
        Trading {trading}
      </span>
      <span className="flex items-center gap-1 text-zinc-500">
        News {grok === 'configured' ? 'Key Set' : 'Off'}
      </span>
      <span className="flex items-center gap-1 text-zinc-500">
        Redis {redis === 'ok' ? 'OK' : redis === 'down' ? 'Down' : 'Off'}
      </span>
      <span className={`flex items-center gap-1 ${cooling ? 'text-amber-400' : 'text-zinc-500'}`}>
        Fyers {rpm}/{rpmLimit} RPM{cooling ? ` cooldown ${coolLeft}s` : ''}
      </span>
    </div>
  );
}
