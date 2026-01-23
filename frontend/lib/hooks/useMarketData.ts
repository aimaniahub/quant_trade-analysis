'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { WSClient } from '../api';

export function useMarketData(symbols: string[]) {
    const [data, setData] = useState<Record<string, any>>({});
    const [connected, setConnected] = useState(false);
    const wsRef = useRef<WSClient | null>(null);

    useEffect(() => {
        if (symbols.length === 0) return;

        const handleMessage = (message: any) => {
            if (message.type === 'market_update' && message.data) {
                const update = message.data;
                // Fyers symbol updates come with symbol in lowercase/uppercase sometimes
                // or inside a specific key if it's multidimensional
                const symbol = update.symbol || (update.d ? update.s : null);

                if (symbol) {
                    setData(prev => ({
                        ...prev,
                        [symbol]: {
                            ...prev[symbol],
                            ...update,
                            last_updated: new Date().getTime()
                        }
                    }));
                }
            } else if (message.type === 'subscription_status') {
                setConnected(message.status === 'success');
            }
        };

        const ws = new WSClient('/ws/market', handleMessage);
        wsRef.current = ws;
        ws.connect();

        // Small delay to ensure connection is open before subscribing
        const timer = setTimeout(() => {
            ws.subscribe(symbols);
        }, 1000);

        return () => {
            clearTimeout(timer);
            ws.unsubscribe(symbols);
            ws.close();
        };
    }, [symbols]);

    return {
        marketData: data,
        connected,
        ws: wsRef.current
    };
}
