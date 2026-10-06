'use client';

import { useState, useEffect } from 'react';
import { getMarketHoursInfo, NON_MARKET_REFRESH_MS, type MarketTimeInfo } from '../market-hours';

export function useMarketPolling(marketHoursIntervalMs: number = 30000, enabled: boolean = true) {
  const [marketInfo, setMarketInfo] = useState<MarketTimeInfo>(() => getMarketHoursInfo(marketHoursIntervalMs));

  useEffect(() => {
    // Check market state once per minute
    const timer = setInterval(() => {
      setMarketInfo(getMarketHoursInfo(marketHoursIntervalMs));
    }, 60000);

    return () => clearInterval(timer);
  }, [marketHoursIntervalMs]);

  // When enabled is false (e.g. unauthenticated), interval is false (no polling)
  // When market is closed: 15 minutes (900,000 ms)
  // When market is open: marketHoursIntervalMs (e.g. 20s-30s)
  const interval: number | false = enabled
    ? marketInfo.isOpen
      ? marketHoursIntervalMs
      : NON_MARKET_REFRESH_MS
    : false;

  return {
    ...marketInfo,
    interval,
    nonMarketInterval: NON_MARKET_REFRESH_MS,
  };
}
