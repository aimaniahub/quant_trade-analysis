/**
 * useMACrossovers – React hook for the MA Crossover dashboard.
 *
 * • Connects to /ws/ma-crossover for live push updates.
 * • Falls back to REST polling (30s) if the WebSocket drops.
 * • Exposes crossovers, nearing, status, config, and control actions.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CrossoverEvent,
  MAConfig,
  ServiceStatus,
  fetchCrossovers,
  fetchNearing,
  fetchStatus,
  startService,
  stopService,
  triggerScan,
  updateConfig,
} from "@/lib/ma-crossover";

const WS_URL =
  (process.env.NEXT_PUBLIC_BACKEND_WS_URL || "ws://localhost:8000") +
  "/api/v1/ws/ma-crossover";

const MAX_CROSSOVERS = 200;

export function useMACrossovers() {
  const [crossovers, setCrossovers] = useState<CrossoverEvent[]>([]);
  const [nearing, setNearing] = useState<CrossoverEvent[]>([]);
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{
    active: boolean;
    current: number;
    total: number;
    percentage: number;
    last_symbol: string;
  } | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);

  // ------------------------------------------------------------------
  // REST fallback poll
  // ------------------------------------------------------------------
  const pollRest = useCallback(async () => {
    try {
      const [co, nr, st] = await Promise.all([
        fetchCrossovers(),
        fetchNearing(),
        fetchStatus(),
      ]);
      setCrossovers(co);
      setNearing(nr);
      setStatus(st);
      if (st.scan_progress) {
        setProgress(st.scan_progress);
      }
    } catch (e) {
      console.warn("[MACrossover] REST poll error", e);
    }
  }, []);

  const startPoll = useCallback(() => {
    pollRest();
    if (pollTimerRef.current) return;
    pollTimerRef.current = setInterval(pollRest, 30_000);
  }, [pollRest]);

  const stopPoll = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  // ------------------------------------------------------------------
  // WebSocket connection
  // ------------------------------------------------------------------
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setError(null);
        stopPoll();
      };

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);

          if (msg.type === "snapshot") {
            setCrossovers(msg.crossovers ?? []);
            setNearing(msg.nearing ?? []);
            if (msg.status) {
              setStatus(msg.status);
              if (msg.status.scan_progress) {
                setProgress(msg.status.scan_progress);
              }
            }
          } else if (msg.type === "ma_crossover") {
            const ev: CrossoverEvent = msg.data;
            if (ev.type === "nearing") {
              setNearing((prev) => {
                const filtered = prev.filter(
                  (x) => !(x.symbol === ev.symbol && x.timeframe === ev.timeframe)
                );
                return [ev, ...filtered].slice(0, 100);
              });
            } else {
              setCrossovers((prev) => {
                const filtered = prev.filter(
                  (x) =>
                    !(
                      x.symbol === ev.symbol &&
                      x.timeframe === ev.timeframe &&
                      x.type === ev.type
                    )
                );
                return [ev, ...filtered].slice(0, MAX_CROSSOVERS);
              });
            }
          } else if (msg.type === "scan_progress") {
            setProgress(msg.data);
          } else if (msg.type === "config_updated") {
            setStatus((prev) =>
              prev ? { ...prev, config: msg.config } : prev
            );
          }
        } catch (e) {
          console.error("[MACrossover] WS parse error", e);
        }
      };

      ws.onerror = () => setError("WebSocket error");

      ws.onclose = () => {
        setConnected(false);
        startPoll();
        // Reconnect after 5 s
        reconnectTimerRef.current = setTimeout(connect, 5_000);
      };
    } catch (e) {
      setError("Cannot connect to backend");
      startPoll();
    }
  }, [startPoll, stopPoll]);

  // ------------------------------------------------------------------
  // Lifecycle
  // ------------------------------------------------------------------
  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      stopPoll();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
  }, [connect, stopPoll]);

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------
  const sendWs = (msg: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  };

  const handleStart = async () => {
    await startService();
    const st = await fetchStatus();
    setStatus(st);
  };

  const handleStop = async () => {
    await stopService();
    const st = await fetchStatus();
    setStatus(st);
  };

  const handleTriggerScan = async () => {
    try {
      await triggerScan();
      const st = await fetchStatus();
      setStatus(st);
      if (st.scan_progress) {
        setProgress(st.scan_progress);
      }
    } catch (e: any) {
      setError(e.message || "Failed to trigger scan");
    }
  };

  const handleConfigUpdate = async (cfg: Partial<MAConfig>) => {
    const newCfg = await updateConfig(cfg);
    setStatus((prev) => (prev ? { ...prev, config: newCfg } : prev));
    sendWs({ action: "update_config", config: cfg });
  };

  const requestSnapshot = () => sendWs({ action: "get_snapshot" });

  return {
    crossovers,
    nearing,
    status,
    connected,
    error,
    progress,
    handleStart,
    handleStop,
    handleTriggerScan,
    handleConfigUpdate,
    requestSnapshot,
    refresh: pollRest,
  };
}
