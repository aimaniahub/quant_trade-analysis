/**
 * Process-wide alerts hub for the browser tab.
 * Prevents React StrictMode remounts from opening multiple WebSockets.
 */

import { api, WSClient } from './api';

export type AlertType = 'info' | 'warning' | 'signal';

export interface RealtimeAlert {
  id: string;
  type: AlertType;
  message: string;
  timestamp: Date;
  source?: string;
}

type Listener = (state: { alerts: RealtimeAlert[]; connected: boolean }) => void;

let localSeq = 0;

function nextId(prefix = 'local'): string {
  localSeq += 1;
  return `${prefix}-${Date.now()}-${localSeq}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeType(raw?: string): AlertType {
  const value = (raw || '').toLowerCase();
  if (value === 'signal') return 'signal';
  if (value === 'warning') return 'warning';
  return 'info';
}

function normalizeMessage(msg: unknown): string {
  if (typeof msg === 'string') return msg.trim();
  if (msg == null) return '';
  return String(msg).trim();
}

/**
 * Merge alerts with unique React keys.
 * Prefer first occurrence (incoming order wins for freshness).
 * Dedupe by id AND by message+source so REST/WS doubles collapse.
 */
function mergeAlerts(
  prev: RealtimeAlert[],
  incoming: RealtimeAlert[],
  cap = 8,
): RealtimeAlert[] {
  const seenIds = new Set<string>();
  const seenContent = new Set<string>();
  const result: RealtimeAlert[] = [];

  for (const alert of [...incoming, ...prev]) {
    const id = String(alert.id ?? nextId('fix'));
    const message = normalizeMessage(alert.message);
    if (!message) continue;

    const contentKey = `${alert.source || ''}|${message}`;
    if (seenIds.has(id) || seenContent.has(contentKey)) {
      continue;
    }
    seenIds.add(id);
    seenContent.add(contentKey);
    result.push({ ...alert, id, message });
    if (result.length >= cap) break;
  }

  return result;
}

class AlertsHub {
  private listeners = new Set<Listener>();
  private alerts: RealtimeAlert[] = [];
  private connected = false;
  private ws: WSClient | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private subscribeTimer: ReturnType<typeof setTimeout> | null = null;
  private started = false;
  private refCount = 0;

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    this.refCount += 1;
    listener({ alerts: this.alerts, connected: this.connected });
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

  private emit() {
    const snapshot = { alerts: this.alerts, connected: this.connected };
    this.listeners.forEach(l => l(snapshot));
  }

  private ensureStarted() {
    if (this.started) return;
    this.started = true;

    const handleMessage = (message: any) => {
      if (message?.type === 'subscription_status') {
        this.connected =
          message.status === 'active' || message.status === 'success';
        this.emit();
        return;
      }

      if (message?.type === 'alert' && message.data != null) {
        const payload = message.data;
        let text: string;
        if (typeof payload === 'string') {
          text = payload;
        } else if (payload && typeof payload === 'object') {
          text =
            payload.message ||
            payload.reason ||
            payload.description ||
            JSON.stringify(payload);
        } else {
          text = String(payload);
        }
        text = normalizeMessage(text);
        if (!text) return;

        const type = normalizeType(
          typeof payload === 'object' && payload ? payload.type : undefined,
        );
        const source =
          typeof payload === 'object' && payload ? payload.source : undefined;
        // Prefer backend id when present; always ensure uniqueness
        const rawId =
          typeof payload === 'object' && payload?.id != null
            ? String(payload.id)
            : nextId('ws');

        this.alerts = mergeAlerts(this.alerts, [
          {
            id: rawId,
            type,
            message: text,
            timestamp: new Date(),
            source,
          },
        ]);
        this.emit();
      }
    };

    this.ws = new WSClient('/ws/alerts', handleMessage);
    this.ws.connect();
    this.subscribeTimer = setTimeout(() => {
      this.ws?.send({ action: 'subscribe' });
    }, 400);

    const pullRecent = async () => {
      try {
        const data = await api.fetch<{
          success: boolean;
          alerts: Array<{
            id: string;
            type?: string;
            message: string;
            timestamp?: string;
            source?: string;
          }>;
        }>('/alerts/recent?limit=10');

        if (data?.alerts?.length) {
          const mapped: RealtimeAlert[] = data.alerts.map(a => ({
            id: a.id != null ? String(a.id) : nextId('rest'),
            type: normalizeType(a.type),
            message: normalizeMessage(a.message),
            timestamp: a.timestamp ? new Date(a.timestamp) : new Date(),
            source: a.source,
          }));
          this.alerts = mergeAlerts(this.alerts, mapped);
          this.emit();
        }
      } catch {
        // backend down — ignore
      }
    };

    pullRecent();
    this.pollTimer = setInterval(pullRecent, 30_000);
  }

  private stop() {
    if (this.subscribeTimer) {
      clearTimeout(this.subscribeTimer);
      this.subscribeTimer = null;
    }
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.connected = false;
    this.started = false;
  }
}

export const alertsHub = new AlertsHub();
