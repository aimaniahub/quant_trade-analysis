"""
Market Hours Utility
Returns True only between 09:15-15:30 IST on BSE/NSE trading days.
Hardcoded holidays for 2025 and 2026.
"""

from datetime import datetime, date, time
import pytz

IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# NSE/BSE holiday list (dd-mm-yyyy → date objects)
_HOLIDAYS = {
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramadan Eid)
    date(2025, 4, 10),   # Shri Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti
    date(2025, 10, 2),   # Dussehra
    date(2025, 10, 20),  # Diwali – Laxmi Puja
    date(2025, 10, 21),  # Diwali – Balipratipada
    date(2025, 11, 5),   # Prakash Gurpurb
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Mahashivratri
    date(2026, 3, 20),   # Holi
    date(2026, 3, 31),   # Id-Ul-Fitr
    date(2026, 4, 2),    # Ram Navami
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 17),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 8),   # Dussehra
    date(2026, 10, 28),  # Diwali – Laxmi Puja
    date(2026, 11, 25),  # Prakash Gurpurb
    date(2026, 12, 25),  # Christmas
}


def is_trading_day(dt: date | None = None) -> bool:
    """Return True if *dt* (default: today IST) is a BSE/NSE trading day."""
    if dt is None:
        dt = datetime.now(IST).date()
    # Weekends
    if dt.weekday() >= 5:
        return False
    # Public holidays
    if dt in _HOLIDAYS:
        return False
    return True


def is_market_open(now: datetime | None = None) -> bool:
    """Return True if the market is currently open (09:15–15:30 IST)."""
    if now is None:
        now = datetime.now(IST)
    elif now.tzinfo is None:
        now = IST.localize(now)

    today = now.date()
    if not is_trading_day(today):
        return False

    current_time = now.time().replace(tzinfo=None)
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def seconds_to_market_open() -> float:
    """Return seconds until next market open (0 if already open)."""
    now = datetime.now(IST)
    if is_market_open(now):
        return 0.0

    # Try today first
    candidate = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if candidate <= now:
        # Already past today's open; try tomorrow
        from datetime import timedelta
        candidate = candidate + timedelta(days=1)

    # Advance to a trading day
    while not is_trading_day(candidate.date()):
        from datetime import timedelta
        candidate = candidate + timedelta(days=1)

    return max(0.0, (candidate - now).total_seconds())


def market_open_time_ist() -> str:
    """Return human-readable next market open time string."""
    now = datetime.now(IST)
    if is_market_open(now):
        return "Market is OPEN"
    secs = seconds_to_market_open()
    hrs, rem = divmod(int(secs), 3600)
    mins, secs2 = divmod(rem, 60)
    return f"Market opens in {hrs}h {mins}m {secs2}s"
