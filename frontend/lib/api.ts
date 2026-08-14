/**
 * OptionGreek Frontend API Client
 * 
 * Handles all communication with the FastAPI backend.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/api/v1';

export interface ApiResponse<T = any> {
    success: boolean;
    data?: T;
    error?: string;
    message?: string;
}

export const api = {
    /**
     * Generic fetch wrapper
     */
    async fetch<T = any>(endpoint: string, options: RequestInit = {}): Promise<T> {
        const url = `${API_BASE_URL}${endpoint}`;
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const detail = errorData.detail;
            let message: string;
            if (typeof detail === "string") {
                message = detail;
            } else if (Array.isArray(detail)) {
                message = detail.map((d: any) => d?.msg || JSON.stringify(d)).join("; ");
            } else if (detail && typeof detail === "object") {
                message = JSON.stringify(detail);
            } else {
                message = `Request failed with status ${response.status}`;
            }
            throw new Error(message);
        }

        return response.json();
    },

    /**
     * Authentication methods
     */
    auth: {
        getLoginUrl: () => api.fetch<{ login_url: string }>('/auth/login'),
        getStatus: () => api.fetch<{ authenticated: boolean; has_token: boolean; is_valid: boolean; user_info: any; app_id: string | null }>('/auth/status'),
        autoLogin: () => api.fetch('/auth/auto-login', { method: 'POST' }),
        refreshToken: () => api.fetch('/auth/refresh', { method: 'POST' }),
        submitAuthCode: (authCode: string) =>
            api.fetch<{ status: string; message: string; info: string }>('/auth/token', {
                method: 'POST',
                body: JSON.stringify({ auth_code: authCode }),
            }),
        reloadSettings: () => api.fetch('/auth/reload-settings', { method: 'POST' }),
    },

    /**
     * Market Data methods
     */
    market: {
        getSpotPrice: (symbol: string) => api.fetch(`/market/spot/${symbol}`),
        getIndices: () => api.fetch('/market/indices'),
        getMarketState: () => api.fetch('/market/state'),
        getHistory: (symbol: string, resolution = 'D', days = 30) =>
            api.fetch(`/market/history/${symbol}?resolution=${resolution}&days=${days}`),
        scanStocks: (
            limit = 100,
            tradableOnly = false,
            topOnly = false,
            strikeCount = 10,
            deep = true,
        ) =>
            api.fetch(
                `/market/stocks/scan?limit=${limit}&tradable_only=${tradableOnly}&top_only=${topOnly}&strike_count=${strikeCount}&deep=${deep}`,
            ),
        /** Start background full-universe scan (poll getStockScanJob). */
        startStockScan: (
            limit = 200,
            tradableOnly = false,
            topOnly = false,
            strikeCount = 10,
            deep = true,
            symbols?: string[],
        ) =>
            api.fetch(
                `/market/stocks/scan/start?limit=${limit}&tradable_only=${tradableOnly}&top_only=${topOnly}&strike_count=${strikeCount}&deep=${deep}`,
                {
                    method: 'POST',
                    body: JSON.stringify(symbols?.length ? { symbols } : {}),
                },
            ),
        getStockScanJob: (jobId: string, includeResults = true) =>
            api.fetch(
                `/market/stocks/scan/jobs/${encodeURIComponent(jobId)}?include_results=${includeResults}`,
            ),
        retryFailedStockScan: (jobId: string) =>
            api.fetch(`/market/stocks/scan/jobs/${encodeURIComponent(jobId)}/retry-failed`, {
                method: 'POST',
                body: JSON.stringify({}),
            }),
        listStockScanJobs: (limit = 10) =>
            api.fetch(`/market/stocks/scan/jobs?limit=${limit}`),

        // High Volume Scanner methods
        getFnoStocks: () => api.fetch('/market/fno-stocks'),
        scanHighVolume: (timeframe = '15', topCount = 5) =>
            api.fetch(`/market/high-volume-scan?timeframe=${timeframe}&top_count=${topCount}`),
        startHighVolumeScan: (timeframe = '15', topCount = 5) =>
            api.fetch(
                `/market/high-volume-scan/start?timeframe=${timeframe}&top_count=${topCount}`,
                { method: 'POST', body: JSON.stringify({}) },
            ),
        getHighVolumeScanJob: (jobId: string) =>
            api.fetch(`/market/high-volume-scan/jobs/${encodeURIComponent(jobId)}`),
        bulkOCAnalysis: (symbols: string[]) =>
            api.fetch('/market/bulk-oc-analysis', {
                method: 'POST',
                body: JSON.stringify({ symbols })
            }),

        // Quant Dashboard methods
        getLiveTradeSignal: (symbol: string) => api.fetch(`/market/live-trade-signal/${symbol}`),
        getGreeksHeatmap: (symbol: string, strikeCount = 15) =>
            api.fetch(`/market/greeks-heatmap/${symbol}?strike_count=${strikeCount}`),
        // Nifty sentiment
        getNiftySentiment: () => api.fetch('/market/nifty-sentiment'),
        // Optional Grok news bias
        getNewsBias: (force = false) =>
            api.fetch(`/market/news-bias?force=${force ? 'true' : 'false'}`),
        // VAT Strategy
        scanVAT: (symbol = "NSE:NIFTY50-INDEX") => api.fetch(`/strategies/vat/scan?symbol=${symbol}`),
        // Backend readiness
        getReady: () => api.fetch('/ready'),
        getHealth: () => api.fetch('/health'),
    },

    /**
     * Option Chain methods
     */
    options: {
        getChain: (symbol: string, strikeCount = 10) =>
            api.fetch(`/options/chain/${symbol}?strike_count=${strikeCount}`),
        analyze: (symbol: string) => api.fetch(`/options/analysis/${symbol}`),
        getAdjustments: (symbol: string) => api.fetch(`/options/adjustments/${symbol}`),
    },

    /**
     * MCP (Model Context Protocol) methods
     */
    mcp: {
        getStatus: () => api.fetch('/mcp/status'),
        listTools: () => api.fetch('/mcp/tools'),
        callTool: (name: string, args: any = {}) =>
            api.fetch('/mcp/call', {
                method: 'POST',
                body: JSON.stringify({ name, arguments: args }),
            }),
        batchCall: (calls: { name: string; arguments?: any }[]) =>
            api.fetch('/mcp/batch', {
                method: 'POST',
                body: JSON.stringify({ calls }),
            }),
        getConfig: () => api.fetch('/mcp/config'),
    },

    /**
     * Multi-source confluence
     */
    confluence: {
        get: (minSources = 2, includeNiftyState = true) =>
            api.fetch(
                `/confluence?min_sources=${minSources}&include_nifty_state=${includeNiftyState}`,
            ),
        status: () => api.fetch('/confluence/status'),
        triggerRadar: () =>
            api.fetch('/confluence/radar/scan', { method: 'POST' }),
    },

    /**
     * 15m 7/200 MA Cross + Option Chain Confirmation
     */
    ma7200: {
        /** Start background direct-API scan; poll getScanJob */
        startScan: (
            limit = 200,
            lookback = 12,
            source: 'full' | 'top' = 'full',
            settings?: {
                fast_ma?: number;
                slow_ma?: number;
                window_days?: number;
                vol_mult?: number;
                max_bars_ago?: number;
                history_days?: number;
            },
        ) => {
            const params = new URLSearchParams();
            params.set('limit', String(limit));
            params.set('lookback', String(lookback));
            params.set('source', source);
            if (settings?.fast_ma != null) params.set('fast_ma', String(settings.fast_ma));
            if (settings?.slow_ma != null) params.set('slow_ma', String(settings.slow_ma));
            if (settings?.window_days != null)
                params.set('window_days', String(settings.window_days));
            if (settings?.vol_mult != null) params.set('vol_mult', String(settings.vol_mult));
            if (settings?.max_bars_ago != null)
                params.set('max_bars_ago', String(settings.max_bars_ago));
            if (settings?.history_days != null)
                params.set('history_days', String(settings.history_days));
            return api.fetch(`/strategies/ma7200/scan/start?${params.toString()}`, {
                method: 'POST',
                body: JSON.stringify({}),
            });
        },
        getScanJob: (jobId: string) =>
            api.fetch(`/strategies/ma7200/scan/jobs/${encodeURIComponent(jobId)}`),
        /** Blocking scan (prefer startScan) */
        scan: (
            limit = 200,
            lookback = 12,
            source: 'full' | 'top' = 'full',
            settings?: {
                fast_ma?: number;
                slow_ma?: number;
                window_days?: number;
                vol_mult?: number;
                max_bars_ago?: number;
                history_days?: number;
            },
        ) => {
            const params = new URLSearchParams();
            params.set('limit', String(limit));
            params.set('lookback', String(lookback));
            params.set('source', source);
            if (settings?.fast_ma != null) params.set('fast_ma', String(settings.fast_ma));
            if (settings?.slow_ma != null) params.set('slow_ma', String(settings.slow_ma));
            if (settings?.window_days != null)
                params.set('window_days', String(settings.window_days));
            if (settings?.vol_mult != null) params.set('vol_mult', String(settings.vol_mult));
            if (settings?.max_bars_ago != null)
                params.set('max_bars_ago', String(settings.max_bars_ago));
            if (settings?.history_days != null)
                params.set('history_days', String(settings.history_days));
            return api.fetch(`/strategies/ma7200/scan?${params.toString()}`);
        },
        analyze: (symbol: string, crossType: string, strikeCount = 12) =>
            api.fetch(
                `/strategies/ma7200/analyze?symbol=${encodeURIComponent(symbol)}&cross_type=${crossType}&strike_count=${strikeCount}`,
            ),
    },

    /**
     * Option Flow Radar methods
     */
    radar: {
        getWatchlist: () => api.fetch('/radar/watchlist'),
        getLastScan: () => api.fetch('/radar/last'),
        scan: (minLis = 0, optionType?: string, strikeCount = 12) => {
            const params = new URLSearchParams();
            params.set('min_lis', String(minLis));
            if (optionType) params.set('option_type', optionType);
            params.set('strike_count', String(strikeCount));
            return api.fetch(`/radar/scan?${params.toString()}`);
        },
        startScan: (minLis = 0, optionType?: string, strikeCount = 12) => {
            const params = new URLSearchParams();
            params.set('min_lis', String(minLis));
            if (optionType) params.set('option_type', optionType);
            params.set('strike_count', String(strikeCount));
            return api.fetch(`/radar/scan/start?${params.toString()}`, {
                method: 'POST',
                body: JSON.stringify({}),
            });
        },
        getScanJob: (jobId: string) =>
            api.fetch(`/radar/scan/jobs/${encodeURIComponent(jobId)}`),
        scanCustom: (symbols: string[], minLis = 0, optionType?: string) =>
            api.fetch('/radar/scan', {
                method: 'POST',
                body: JSON.stringify({ symbols, min_lis: minLis, option_type: optionType }),
            }),
        getSymbolFlow: (symbol: string, strikeCount = 14) =>
            api.fetch(`/radar/flow/${encodeURIComponent(symbol)}?strike_count=${strikeCount}`),
        getCandles: (symbol: string, resolution = '5', days = 1) =>
            api.fetch(`/radar/candles/${encodeURIComponent(symbol)}?resolution=${resolution}&days=${days}`),
        backtest: (payload: {
            symbol: string;
            strike: number;
            option_type: string;
            signal_timestamp: string;
            forward_minutes?: number[];
        }) =>
            api.fetch('/radar/backtest', {
                method: 'POST',
                body: JSON.stringify(payload),
            }),
        getIdeas: (limit = 8) => api.fetch(`/radar/ideas?limit=${limit}`),
        getSymbolIdea: (symbol: string) =>
            api.fetch(`/radar/ideas/${encodeURIComponent(symbol)}`),
        getLevels: (symbol: string, strikeCount = 14) =>
            api.fetch(
                `/radar/levels/${encodeURIComponent(symbol)}?strike_count=${strikeCount}`,
            ),
    },
};

/**
 * WebSocket manager for real-time data
 */
export class WSClient {
    private ws: WebSocket | null = null;
    private url: string;
    private onMessage: (data: any) => void;
    private reconnectInterval = 3000;
    private maxReconnectAttempts = 5;
    private reconnectAttempts = 0;
    private intentionalClose = false;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    constructor(path: string, onMessage: (data: any) => void) {
        this.url = `${WS_BASE_URL}${path}`;
        this.onMessage = onMessage;
    }

    connect() {
        try {
            this.intentionalClose = false;
            // Avoid stacking sockets
            if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
                return;
            }

            this.ws = new WebSocket(this.url);

            this.ws.onopen = () => {
                console.log(`Connected to WebSocket: ${this.url}`);
                this.reconnectAttempts = 0;
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.onMessage(data);
                } catch (err) {
                    console.error('Failed to parse WebSocket message:', err);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket connection closed');
                if (!this.intentionalClose) {
                    this.attemptReconnect();
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        } catch (error) {
            console.error('Failed to connect to WebSocket:', error);
        }
    }

    private attemptReconnect() {
        if (this.intentionalClose) return;
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Attempting reconnect ${this.reconnectAttempts}/${this.maxReconnectAttempts}...`);
            if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
            this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectInterval);
        }
    }

    send(data: any) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else if (!this.intentionalClose) {
            console.warn('WebSocket is not open. Initializing connection...');
            this.connect();
        }
    }

    subscribe(symbols: string[]) {
        this.send({ action: 'subscribe', symbols });
    }

    unsubscribe(symbols: string[]) {
        this.send({ action: 'unsubscribe', symbols });
    }

    close() {
        this.intentionalClose = true;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.ws) {
            try {
                this.ws.close();
            } catch {
                // ignore
            }
            this.ws = null;
        }
    }
}
