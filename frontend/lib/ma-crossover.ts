/**
 * MA Crossover API client
 * Talks to  /api/v1/ma-crossover/*
 */

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
const API = `${BASE}/api/v1/ma-crossover`;

export interface MAConfig {
  ma_short_type: string;
  ma_short_period: number;
  ma_long_type: string;
  ma_long_period: number;
  ma_trend_type: string;
  ma_trend_period: number;
  timeframes: string[];
  proximity_threshold: number;
  consecutive_candles: number;
  cooldown_minutes: number;
  scan_batch_size: number;
}

export interface CrossoverEvent {
  symbol: string;
  timeframe: string;
  type: "golden_cross" | "death_cross" | "nearing";
  signal?: "BUY" | "SELL";
  direction?: string;
  price: number;
  ma_short: number;
  ma_long: number;
  ma_trend: number;
  distance_pct: number;
  /** % distance from price to 200EMA – key institutional reference */
  price_to_200ema_pct?: number;
  timestamp: number;
  datetime: string;
}

export interface ServiceStatus {
  running: boolean;
  market_open: boolean;
  market_info: string;
  symbols_tracked: number;
  timeframes: string[];
  crossovers_count: number;
  nearing_count: number;
  config: MAConfig;
  authenticated: boolean;
  scan_active: boolean;
  scan_progress?: {
    active: boolean;
    current: number;
    total: number;
    percentage: number;
    last_symbol: string;
  };
}

async function parseJsonOrThrow(r: Response, fallback: string) {
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: fallback }));
    const detail = err?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d?.msg || JSON.stringify(d)).join("; ")
          : fallback,
    );
  }
  return r.json();
}

export async function fetchStatus(): Promise<ServiceStatus> {
  const r = await fetch(`${API}/status`);
  return parseJsonOrThrow(r, "Failed to fetch MA crossover status");
}

export async function fetchCrossovers(limit = 100): Promise<CrossoverEvent[]> {
  const r = await fetch(`${API}/crossovers?limit=${limit}`);
  const d = await parseJsonOrThrow(r, "Failed to fetch crossovers");
  return d.crossovers ?? [];
}

export async function fetchNearing(limit = 50): Promise<CrossoverEvent[]> {
  const r = await fetch(`${API}/nearing?limit=${limit}`);
  const d = await parseJsonOrThrow(r, "Failed to fetch nearing list");
  return d.nearing ?? [];
}

export async function startService(): Promise<void> {
  const r = await fetch(`${API}/start`, { method: "POST" });
  await parseJsonOrThrow(r, "Failed to start MA crossover service");
}

export async function stopService(): Promise<void> {
  const r = await fetch(`${API}/stop`, { method: "POST" });
  await parseJsonOrThrow(r, "Failed to stop MA crossover service");
}

export async function triggerScan(): Promise<void> {
  const r = await fetch(`${API}/scan`, { method: "POST" });
  await parseJsonOrThrow(r, "Failed to trigger scan");
}

export async function updateConfig(cfg: Partial<MAConfig>): Promise<MAConfig> {
  const r = await fetch(`${API}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  const d = await parseJsonOrThrow(r, "Failed to update MA config");
  return d.config;
}

