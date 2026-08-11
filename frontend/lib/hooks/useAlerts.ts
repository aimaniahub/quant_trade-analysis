'use client';

import { useEffect, useState } from 'react';
import {
  alertsHub,
  type AlertType,
  type RealtimeAlert,
} from '../alerts-hub';

export type { AlertType, RealtimeAlert };

interface UseAlertsResult {
  alerts: RealtimeAlert[];
  connected: boolean;
}

/**
 * Subscribes to the tab-level alerts hub (single WS + REST poll).
 */
export function useAlerts(): UseAlertsResult {
  const [alerts, setAlerts] = useState<RealtimeAlert[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    return alertsHub.subscribe(state => {
      setAlerts(state.alerts);
      setConnected(state.connected);
    });
  }, []);

  return { alerts, connected };
}
