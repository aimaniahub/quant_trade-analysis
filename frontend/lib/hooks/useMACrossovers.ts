/**
 * useMACrossovers – React hook for the MA Crossover dashboard.
 *
 * Uses a process-wide hub so multiple mounts / StrictMode only open
 * one WebSocket to /ws/ma-crossover (same pattern as alerts-hub).
 */

"use client";

import { useEffect, useState } from "react";
import type { MAConfig } from "@/lib/ma-crossover";
import {
  maCrossoverHub,
  type MAHubState,
  type MAProgress,
} from "@/lib/ma-crossover-hub";

export function useMACrossovers() {
  const [state, setState] = useState<MAHubState>(() => maCrossoverHub.getSnapshot());

  useEffect(() => maCrossoverHub.subscribe(setState), []);

  return {
    crossovers: state.crossovers,
    nearing: state.nearing,
    status: state.status,
    connected: state.connected,
    error: state.error,
    progress: state.progress as MAProgress | null,
    handleStart: () => maCrossoverHub.handleStart(),
    handleStop: () => maCrossoverHub.handleStop(),
    handleTriggerScan: () => maCrossoverHub.handleTriggerScan(),
    handleConfigUpdate: (cfg: Partial<MAConfig>) =>
      maCrossoverHub.handleConfigUpdate(cfg),
    requestSnapshot: () => maCrossoverHub.requestSnapshot(),
    refresh: () => maCrossoverHub.refresh(),
  };
}
