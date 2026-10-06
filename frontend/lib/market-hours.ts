/**
 * Indian Market Hours & Auto-Refresh Rate Controller (NSE/BSE)
 * 
 * Rules:
 * - Market Hours: Mon-Fri 09:15 to 15:30 IST
 * - In Market Hours: Active dynamic refresh (safe rate limit shield)
 * - Outside Market Hours (Evenings, Nights, Weekends): 15-minute auto refresh (900,000 ms)
 */

export interface MarketTimeInfo {
  isOpen: boolean;
  isPreOpen: boolean;
  isWeekend: boolean;
  statusText: 'MARKET OPEN' | 'PRE-OPEN' | 'MARKET CLOSED';
  sessionDate: string;
  istTimeStr: string;
  recommendedRefreshMs: number;
}

export const NON_MARKET_REFRESH_MS = 15 * 60 * 1000; // 15 minutes = 900,000 ms

/**
 * Returns current date/time converted to Indian Standard Time (UTC+5:30)
 */
export function getISTNow(): Date {
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  return new Date(utc + 5.5 * 3600000);
}

/**
 * Check if Indian markets are currently in trading hours
 */
export function getMarketHoursInfo(marketHoursActiveMs: number = 30000): MarketTimeInfo {
  const ist = getISTNow();
  const day = ist.getDay(); // 0 = Sunday, 6 = Saturday
  const hours = ist.getHours();
  const minutes = ist.getMinutes();
  const timeInMinutes = hours * 60 + minutes;

  const isWeekend = day === 0 || day === 6;
  const isPreOpen = !isWeekend && timeInMinutes >= 9 * 60 && timeInMinutes < 9 * 60 + 15; // 09:00 - 09:15
  const isOpen = !isWeekend && timeInMinutes >= 9 * 60 + 15 && timeInMinutes < 15 * 60 + 30; // 09:15 - 15:30

  let statusText: 'MARKET OPEN' | 'PRE-OPEN' | 'MARKET CLOSED' = 'MARKET CLOSED';
  if (isOpen) {
    statusText = 'MARKET OPEN';
  } else if (isPreOpen) {
    statusText = 'PRE-OPEN';
  }

  const hoursStr = String(hours).padStart(2, '0');
  const minsStr = String(minutes).padStart(2, '0');
  const istTimeStr = `${hoursStr}:${minsStr} IST`;
  const sessionDate = ist.toISOString().split('T')[0];

  return {
    isOpen,
    isPreOpen,
    isWeekend,
    statusText,
    sessionDate,
    istTimeStr,
    recommendedRefreshMs: isOpen ? Math.max(10000, marketHoursActiveMs) : NON_MARKET_REFRESH_MS,
  };
}
