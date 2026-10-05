"""
Market Hours Utility
Returns True only between 09:15-15:30 IST on BSE/NSE trading days.
Hardcoded holidays for 2025 and 2026.
"""

from datetime import datetime, date, time
import pytz

from app.core.config import get_settings

IST = pytz.timezone("Asia/Kolkata")


def allow_off_hours_scan() -> bool:
    """Allow live/old cached scans outside normal market hours for debugging."""
    return bool(get_settings().allow_off_hours_scan)

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


def session_is_open(now: datetime | None = None) -> bool:
    """True only during 09:15–15:30 IST on a trading day. Ignores debug override."""
    if now is None:
        now = datetime.now(IST)
    elif now.tzinfo is None:
        now = IST.localize(now)

    today = now.date()
    if not is_trading_day(today):
        return False

    current_time = now.time().replace(tzinfo=None)
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_market_open(now: datetime | None = None) -> bool:
    """Return True if the market is currently open (09:15–15:30 IST).

    A debug override can force this path on outside market hours so cached/live
    board analysis can be inspected without waiting for the next session.
    """
    if allow_off_hours_scan():
        return True
    return session_is_open(now)


def seconds_to_market_open() -> float:
    """Return seconds until next market open (0 if already open)."""
    if allow_off_hours_scan():
        return 0.0

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


def last_session_date(now: datetime | None = None) -> date:
    """Most recent NSE session date (today if that session has started)."""
    if now is None:
        now = datetime.now(IST)
    elif now.tzinfo is None:
        now = IST.localize(now)
    d = now.date()
    if is_trading_day(d) and now.time().replace(tzinfo=None) >= MARKET_OPEN:
        return d
    from datetime import timedelta
    d = d - timedelta(days=1)
    while not is_trading_day(d):
        d = d - timedelta(days=1)
    return d


def session_snapshot_ttl_seconds(now: datetime | None = None) -> int:
    """Keep last-session board/quotes until the next open (weekend-safe)."""
    try:
        from app.core.config import get_settings
        configured = int(getattr(get_settings(), "session_snapshot_ttl_secs", 259200) or 259200)
    except Exception:
        configured = 259200
    until_open = int(seconds_to_market_open()) + 3600
    return max(int(configured), until_open, 18 * 3600)


def data_mode(now: datetime | None = None) -> str:
    """UI freshness label. Debug off-hours harvest still shows as last_close."""
    return "live" if session_is_open(now) else "last_close"
