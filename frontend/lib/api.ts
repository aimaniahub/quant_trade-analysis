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
            throw new Error(errorData.detail || `Request failed with status ${response.status}`);
        }

        return response.json();
    },

    /**
     * Authentication methods
     */
    auth: {
        getLoginUrl: () => api.fetch<{ login_url: string }>('/auth/login'),
        getStatus: () => api.fetch<{ authenticated: boolean; has_token: boolean; is_valid: boolean; user_info: any }>('/auth/status'),
        autoLogin: () => api.fetch('/auth/auto-login', { method: 'POST' }),
        refreshToken: () => api.fetch('/auth/refresh', { method: 'POST' }),
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
        scanStocks: (limit = 20, tradableOnly = false, topOnly = true) =>
            api.fetch(`/market/stocks/scan?limit=${limit}&tradable_only=${tradableOnly}&top_only=${topOnly}`),

        // High Volume Scanner methods
        getFnoStocks: () => api.fetch('/market/fno-stocks'),
        scanHighVolume: (timeframe = '15', topCount = 5) =>
            api.fetch(`/market/high-volume-scan?timeframe=${timeframe}&top_count=${topCount}`),
        bulkOCAnalysis: (symbols: string[]) =>
            api.fetch('/market/bulk-oc-analysis', {
                method: 'POST',
                body: JSON.stringify({ symbols })
            }),

        // Quant Dashboard methods
        getNiftySentiment: () => api.fetch('/market/nifty-sentiment'),
        getLiveTradeSignal: (symbol: string) => api.fetch(`/market/live-trade-signal/${symbol}`),
        getGreeksHeatmap: (symbol: string, strikeCount = 15) =>
            api.fetch(`/market/greeks-heatmap/${symbol}?strike_count=${strikeCount}`),
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

    constructor(path: string, onMessage: (data: any) => void) {
        this.url = `${WS_BASE_URL}${path}`;
        this.onMessage = onMessage;
    }

    connect() {
        try {
            this.ws = new WebSocket(this.url);

            this.ws.onopen = () => {
                console.log(`Connected to WebSocket: ${this.url}`);
                this.reconnectAttempts = 0;
            };

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.onMessage(data);
            };

            this.ws.onclose = () => {
                console.log('WebSocket connection closed');
                this.attemptReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        } catch (error) {
            console.error('Failed to connect to WebSocket:', error);
        }
    }

    private attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Attempting reconnect ${this.reconnectAttempts}/${this.maxReconnectAttempts}...`);
            setTimeout(() => this.connect(), this.reconnectInterval);
        }
    }

    send(data: any) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
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
        if (this.ws) {
            this.ws.close();
        }
    }
}
