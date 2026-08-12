/**
 * Process-wide MA Crossover hub for the browser tab.
 * One WebSocket + REST fallback shared by all React subscribers
 * (prevents multi-tab StrictMode / remount WS storms).
 */

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
} from './ma-crossover';

const WS_URL =
  (process.env.NEXT_PUBLIC_BACKEND_WS_URL ||
    process.env.NEXT_PUBLIC_WS_URL ||
    'ws://localhost:8000') + '/api/v1/ws/ma-crossover';

const MAX_CROSSOVERS = 200;

export type MAProgress = {
  active: boolean;
  current: number;
  total: number;
  percentage: number;
  last_symbol: string;
};

export type MAHubState = {
  crossovers: CrossoverEvent[];
  nearing: CrossoverEvent[];
  status: ServiceStatus | null;
  connected: boolean;
  error: string | null;
  progress: MAProgress | null;
};

type Listener = (state: MAHubState) => void;

class MACrossoverHub {
  private listeners = new Set<Listener>();
  private refCount = 0;
  private started = false;
  private ws: WebSocket | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  private state: MAHubState = {
    crossovers: [],
    nearing: [],
    status: null,
    connected: false,
    error: null,
    progress: null,
  };

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    this.refCount += 1;
    listener(this.state);
    this.ensureStarted();
    return () => {
      this.listeners.delete(listener);
      this.refCount = Math.max(0, this.refCount - 1);
      if (this.refCount === 0) {
        setTimeout(() => {
          if (this.refCount === 0) this.stop();
        }, 1500);
      }
    };
  }

  getSnapshot(): MAHubState {
    return this.state;
  }

  private emit() {
    const snap = this.state;
    this.listeners.forEach(l => l(snap));
  }

  private patch(partial: Partial<MAHubState>) {
    this.state = { ...this.state, ...partial };
    this.emit();
  }

  private ensureStarted() {
    if (this.started) return;
    this.started = true;
    this.intentionalClose = false;
    this.connect();
  }

  private startPoll() {
    this.pollRest();
    if (this.pollTimer) return;
    this.pollTimer = setInterval(() => this.pollRest(), 60_000);
  }

  private stopPoll() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  async pollRest() {
    try {
      const [co, nr, st] = await Promise.all([
        fetchCrossovers(),
        fetchNearing(),
        fetchStatus(),
      ]);
      this.patch({
        crossovers: co,
        nearing: nr,
        status: st,
        progress: st.scan_progress || this.state.progress,
        error: null,
      });
    } catch (e) {
      console.warn('[MACrossoverHub] REST poll error', e);
    }
  }

  private connect() {
    if (
      this.ws?.readyState === WebSocket.OPEN ||
      this.ws?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    try {
      const ws = new WebSocket(WS_URL);
      this.ws = ws;

      ws.onopen = () => {
        this.patch({ connected: true, error: null });
        this.stopPoll();
        this.pollRest();
      };

      ws.onmessage = evt => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'snapshot') {
            this.patch({
              crossovers: msg.crossovers ?? [],
              nearing: msg.nearing ?? [],
              status: msg.status ?? this.state.status,
              progress: msg.status?.scan_progress || this.state.progress,
            });
          } else if (msg.type === 'ma_crossover') {
            const ev: CrossoverEvent = msg.data;
            if (ev.type === 'nearing') {
              const filtered = this.state.nearing.filter(
                x => !(x.symbol === ev.symbol && x.timeframe === ev.timeframe),
              );
              this.patch({
                nearing: [ev, ...filtered].slice(0, 100),
              });
            } else {
              const filtered = this.state.crossovers.filter(
                x =>
                  !(
                    x.symbol === ev.symbol &&
                    x.timeframe === ev.timeframe &&
                    x.type === ev.type
                  ),
              );
              this.patch({
                crossovers: [ev, ...filtered].slice(0, MAX_CROSSOVERS),
              });
            }
          } else if (msg.type === 'scan_progress') {
            this.patch({ progress: msg.data });
          } else if (msg.type === 'config_updated') {
            const prev = this.state.status;
            this.patch({
              status: prev ? { ...prev, config: msg.config } : prev,
            });
          }
        } catch (e) {
          console.error('[MACrossoverHub] WS parse error', e);
        }
      };

      ws.onerror = () => this.patch({ error: 'WebSocket error' });

      ws.onclose = () => {
        this.patch({ connected: false });
        this.ws = null;
        if (this.intentionalClose) return;
        this.startPoll();
        this.reconnectTimer = setTimeout(() => this.connect(), 8_000);
      };
    } catch {
      this.patch({ error: 'Cannot connect to backend' });
      this.startPoll();
    }
  }

  private stop() {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopPoll();
    try {
      this.ws?.close();
    } catch {
      // ignore
    }
    this.ws = null;
    this.started = false;
    this.patch({ connected: false });
  }

  private sendWs(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  async handleStart() {
    await startService();
    const st = await fetchStatus();
    this.patch({ status: st });
  }

  async handleStop() {
    await stopService();
    const st = await fetchStatus();
    this.patch({ status: st });
  }

  async handleTriggerScan() {
    try {
      await triggerScan();
      const st = await fetchStatus();
      this.patch({
        status: st,
        progress: st.scan_progress || this.state.progress,
        error: null,
      });
    } catch (e: any) {
      this.patch({ error: e?.message || 'Failed to trigger scan' });
    }
  }

  async handleConfigUpdate(cfg: Partial<MAConfig>) {
    const newCfg = await updateConfig(cfg);
    const prev = this.state.status;
    this.patch({
      status: prev ? { ...prev, config: newCfg } : prev,
    });
    this.sendWs({ action: 'update_config', config: cfg });
  }

  requestSnapshot() {
    this.sendWs({ action: 'get_snapshot' });
  }

  refresh() {
    return this.pollRest();
  }
}

export const maCrossoverHub = new MACrossoverHub();
