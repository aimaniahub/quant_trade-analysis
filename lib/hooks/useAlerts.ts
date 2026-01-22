'use client';

import { useEffect, useRef, useState } from 'react';
import { WSClient } from '../api';

export type AlertType = 'info' | 'warning' | 'signal';

export interface RealtimeAlert {
  id: number;
  type: AlertType;
  message: string;
  timestamp: Date;
}

interface UseAlertsResult {
  alerts: RealtimeAlert[];
  connected: boolean;
}

function normalizeType(raw?: string): AlertType {
  const value = (raw || '').toLowerCase();
  if (value === 'signal') return 'signal';
  if (value === 'warning') return 'warning';
  return 'info';
}

export function useAlerts(): UseAlertsResult {
  const [alerts, setAlerts] = useState<RealtimeAlert[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WSClient | null>(null);

  useEffect(() => {
    const handleMessage = (message: any) => {
      if (message?.type === 'subscription_status') {
        setConnected(message.status === 'active' || message.status === 'success');
        return;
      }

      if (message?.type === 'alert' && message.data) {
        const payload = message.data;
        const text =
          payload.message ||
          payload.reason ||
          payload.description ||
          typeof payload === 'string'
            ? payload
            : JSON.stringify(payload);

        const type = normalizeType(payload.type);

        setAlerts(prev => {
          const next: RealtimeAlert[] = [
            {
              id: Date.now(),
              type,
              message: text,
              timestamp: new Date(),
            },
            ...prev,
          ];

          // Deduplicate by message and cap at last 5
          const unique = next.filter(
            (alert, index, self) =>
              index === self.findIndex(a => a.message === alert.message),
          );

          return unique.slice(0, 5);
        });
      }
    };

    const ws = new WSClient('/ws/alerts', handleMessage);
    wsRef.current = ws;
    ws.connect();

    const timer = setTimeout(() => {
      ws.send({ action: 'subscribe' });
    }, 500);

    return () => {
      clearTimeout(timer);
      ws.close();
    };
  }, []);

  return { alerts, connected };
}
