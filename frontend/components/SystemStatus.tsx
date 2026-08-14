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

  return (
    <div className="flex flex-wrap items-center gap-4">
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
    </div>
  );
}
