"""
Redis (or in-memory) per-symbol market store.

One harvest writer fills `optiongreek:sym:{SYMBOL}` with spot + option chain +
15m/D history + derived fields. Every strategy page reads this document.

Never crash if Redis is down — same fallback pattern as redis_client.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.utils.market_hours import IST

logger = logging.getLogger(__name__)

SNAPSHOT_TTL = 14400  # 4 hours
STALE_SOFT = 90
STALE_HARD = 300
OC_TTL = 120
QUOTES_TTL = 15
HISTORY_15_TTL = 900

HARVEST_OC_STRIKES = 14
HARVEST_OC_STRIKES_INDEX = 20
HARVEST_HISTORY_15_DAYS = 40
HARVEST_HISTORY_D_DAYS = 30

_harvest_depth = 0
_harvest_lock = threading.Lock()

_store_lock = threading.RLock()
_mem_docs: Dict[str, Dict[str, Any]] = {}
_mem_quotes: Dict[str, Dict[str, Any]] = {}
_mem_meta: Optional[Dict[str, Any]] = None
_mem_hv: Optional[Dict[str, Any]] = None
_mem_symbols: set[str] = set()

reader_hits = 0
reader_misses = 0
writer_puts = 0


def _settings():
    from app.core.config import get_settings
    return get_settings()


def _cfg_int(name: str, default: int) -> int:
    try:
        return int(getattr(_settings(), name, default) or default)
    except Exception:
        return default


def snapshot_ttl() -> int:
    return _cfg_int("symbol_store_ttl_secs", SNAPSHOT_TTL)


def oc_ttl() -> int:
    return _cfg_int("harvest_oc_ttl_secs", OC_TTL)


def quotes_ttl() -> int:
    return _cfg_int("harvest_quotes_ttl_secs", QUOTES_TTL)


def history_15_ttl() -> int:
    return _cfg_int("harvest_history_15_ttl_secs", HISTORY_15_TTL)


def stale_soft() -> int:
    return _cfg_int("stale_soft_secs", STALE_SOFT)


def stale_hard() -> int:
    return _cfg_int("stale_hard_secs", STALE_HARD)


def harvest_oc_strikes_eq() -> int:
    return _cfg_int("harvest_oc_strikes", HARVEST_OC_STRIKES)


def harvest_oc_strikes_index() -> int:
    return _cfg_int("harvest_oc_strikes_index", HARVEST_OC_STRIKES_INDEX)


def harvest_history_15_days() -> int:
    return _cfg_int("harvest_history_15_days", HARVEST_HISTORY_15_DAYS)


def harvest_history_d_days() -> int:
    return _cfg_int("harvest_history_d_days", HARVEST_HISTORY_D_DAYS)


@contextmanager
def harvest_writer():
    """Mark this process as the universe Fyers writer (cross-thread)."""
    global _harvest_depth
    with _harvest_lock:
        _harvest_depth += 1
    try:
        yield
    finally:
        with _harvest_lock:
            _harvest_depth = max(0, _harvest_depth - 1)


def is_harvest_writer() -> bool:
    return _harvest_depth > 0


def is_index_symbol(symbol: str) -> bool:
    u = (symbol or "").upper()
    return "INDEX" in u or u.endswith("-IDX")


def canonical_strike_count(symbol: str) -> int:
    return harvest_oc_strikes_index() if is_index_symbol(symbol) else harvest_oc_strikes_eq()


def _now() -> float:
    return time.time()


def _iso(ts: Optional[float] = None) -> str:
    t = ts if ts is not None else _now()
    return datetime.fromtimestamp(t, tz=IST).isoformat()


def _ist_today() -> str:
    return datetime.now(IST).date().isoformat()


def _rc():
    from app.services import redis_client as rc
    return rc


def _sym_key(symbol: str) -> str:
    return _rc().key("sym", symbol)


def _meta_key() -> str:
    return _rc().key("meta", "harvest")


def _quotes_key() -> str:
    return _rc().key("idx", "quotes")


def _symbols_key() -> str:
    return _rc().key("idx", "symbols")


def _stale_key() -> str:
    return _rc().key("idx", "stale")


def _hv_key() -> str:
    return _rc().key("idx", "hv")


def _deep_merge(base: Optional[Dict[str, Any]], patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base or {})
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def _name_of(symbol: str) -> str:
    part = (symbol or "").split(":")[-1]
    return part.replace("-EQ", "").replace("-INDEX", "")


def _kind_of(symbol: str) -> str:
    return "INDEX" if is_index_symbol(symbol) else "EQ"


def empty_snapshot(symbol: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "name": _name_of(symbol),
        "kind": _kind_of(symbol),
        "harvest_ts": 0.0,
        "harvest_iso": None,
        "source": "radar_harvest",
        "spot": {},
        "chain": {},
        "history": {},
        "futures": {},
        "derived": {},
    }


def get(symbol: str) -> Optional[Dict[str, Any]]:
    if not symbol:
        return None
    rc = _rc()
    if rc.is_available():
        try:
            doc = rc.get_json(_sym_key(symbol))
            if isinstance(doc, dict) and doc.get("symbol"):
                return doc
        except Exception as exc:
            logger.debug("symbol_store get redis %s: %s", symbol, exc)
    with _store_lock:
        doc = _mem_docs.get(symbol)
        return dict(doc) if doc else None


def get_many(symbols: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        doc = get(sym)
        if doc:
            out[sym] = doc
    return out


def put(symbol: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge patch into the per-symbol document and persist."""
    global writer_puts
    if not symbol:
        return {}
    now = _now()
    existing = get(symbol) or empty_snapshot(symbol)
    merged = _deep_merge(existing, patch)
    merged["symbol"] = symbol
    merged["name"] = merged.get("name") or _name_of(symbol)
    merged["kind"] = merged.get("kind") or _kind_of(symbol)
    merged["harvest_ts"] = now
    merged["harvest_iso"] = _iso(now)
    merged["source"] = patch.get("source") or existing.get("source") or "radar_harvest"

    rc = _rc()
    wrote_redis = False
    if rc.is_available():
        try:
            wrote_redis = bool(rc.set_json(_sym_key(symbol), merged, ttl=snapshot_ttl()))
            rc.zadd(_stale_key(), {symbol: now})
            # keep a cheap JSON list of the universe
            names = list_symbols()
            if symbol not in names:
                names.append(symbol)
                rc.set_json(_symbols_key(), names, ttl=snapshot_ttl())
        except Exception as exc:
            logger.debug("symbol_store put redis %s: %s", symbol, exc)
            wrote_redis = False

    with _store_lock:
        _mem_docs[symbol] = merged
        _mem_symbols.add(symbol)
        writer_puts += 1

    if not wrote_redis:
        logger.debug("symbol_store put memory-only %s", symbol)
    return merged


def put_spot(symbol: str, spot: Dict[str, Any]) -> None:
    clean = _normalize_spot(symbol, spot)
    if not clean:
        return
    put(symbol, {"spot": clean})
    set_quote(symbol, clean)


def put_chain(symbol: str, oc: Dict[str, Any]) -> None:
    if not oc or not oc.get("success", True):
        return
    rows = oc.get("chain") or oc.get("rows") or []
    atm = oc.get("atm_strike")
    body = {
        "strike_count": chain_width(rows, atm),
        "spot_price": oc.get("spot_price"),
        "atm_strike": atm,
        "pcr": oc.get("pcr"),
        "expiries": oc.get("expiries") or [],
        "india_vix": oc.get("india_vix"),
        "total_call_oi": oc.get("total_call_oi"),
        "total_put_oi": oc.get("total_put_oi"),
        "rows": rows,
        "ts": _now(),
    }
    patch: Dict[str, Any] = {"chain": body}
    spot_px = oc.get("spot_price")
    if spot_px:
        existing_spot = (get(symbol) or {}).get("spot") or {}
        if not existing_spot.get("ltp"):
            patch["spot"] = _normalize_spot(symbol, {"ltp": spot_px, **existing_spot})
    put(symbol, patch)


def put_history(symbol: str, resolution: str, candles: List[Dict[str, Any]], days: int) -> None:
    res = _hist_key(resolution)
    put(
        symbol,
        {
            "history": {
                res: {
                    "days": days,
                    "candles": candles or [],
                    "ts": _now(),
                    "count": len(candles or []),
                }
            }
        },
    )


def put_futures(symbol: str, fut: Dict[str, Any]) -> None:
    if not fut:
        return
    body = dict(fut)
    body["ts"] = _now()
    put(symbol, {"futures": body})


def put_derived(symbol: str, derived: Dict[str, Any]) -> None:
    if not derived:
        return
    put(symbol, {"derived": derived})


def _hist_key(resolution: str) -> str:
    r = str(resolution or "").upper()
    if r in ("D", "1D", "DAY", "DAILY"):
        return "D"
    if r in ("15", "15M"):
        return "15"
    if r in ("60", "60M", "1H"):
        return "60"
    if r in ("240", "240M", "4H"):
        return "240"
    if r in ("5", "5M"):
        return "5"
    return str(resolution)


def _field_ts(snap: Optional[Dict[str, Any]], field: str) -> float:
    if not snap:
        return 0.0
    if field == "spot":
        spot = snap.get("spot") or {}
        return float(spot.get("ts") or snap.get("harvest_ts") or 0)
    if field == "chain":
        ch = snap.get("chain") or {}
        return float(ch.get("ts") or snap.get("harvest_ts") or 0)
    if field.startswith("history."):
        res = field.split(".", 1)[1]
        h = ((snap.get("history") or {}).get(_hist_key(res)) or {})
        return float(h.get("ts") or 0)
    if field == "futures":
        return float((snap.get("futures") or {}).get("ts") or 0)
    return float(snap.get("harvest_ts") or 0)


def age(symbol: str, field: str = "spot") -> Optional[float]:
    snap = get(symbol)
    ts = _field_ts(snap, field)
    if not ts:
        return None
    return max(0.0, _now() - ts)


def is_fresh(symbol: str, field: str, max_age: Optional[float] = None) -> bool:
    a = age(symbol, field)
    if a is None:
        return False
    limit = max_age
    if limit is None:
        if field == "chain":
            limit = oc_ttl()
        elif field == "spot":
            limit = quotes_ttl()
        elif field.startswith("history.15"):
            limit = history_15_ttl()
        elif field.startswith("history.D"):
            # daily: fresh if harvested today IST
            snap = get(symbol)
            h = ((snap or {}).get("history") or {}).get("D") or {}
            iso = h.get("ist_date") or (snap or {}).get("harvest_iso")
            if iso:
                return str(iso)[:10] == _ist_today()
            limit = 20 * 3600
        else:
            limit = stale_soft()
    return a <= float(limit)


def list_symbols() -> List[str]:
    rc = _rc()
    if rc.is_available():
        try:
            raw = rc.get_json(_symbols_key())
            if isinstance(raw, list) and raw:
                return [str(s) for s in raw]
        except Exception:
            pass
    with _store_lock:
        return sorted(_mem_symbols or _mem_docs.keys())


def list_fresh(max_age: Optional[float] = None, field: str = "chain") -> List[str]:
    limit = float(max_age if max_age is not None else oc_ttl())
    out: List[str] = []
    for sym in list_symbols():
        a = age(sym, field)
        if a is not None and a <= limit:
            out.append(sym)
    return out


def get_spot(symbol: str) -> Optional[Dict[str, Any]]:
    snap = get(symbol)
    if not snap:
        return None
    spot = snap.get("spot") or {}
    if spot.get("ltp"):
        return spot
    # fall back to cheap quotes index
    q = get_quote(symbol)
    return q if q and q.get("ltp") else None


def get_spots(symbols: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    wanted = list(symbols)
    out: Dict[str, Dict[str, Any]] = {}
    # try the quotes hash first (cheap)
    all_q = get_all_quotes()
    for s in wanted:
        if s in all_q and all_q[s].get("ltp"):
            out[s] = all_q[s]
    missing = [s for s in wanted if s not in out]
    for s in missing:
        sp = get_spot(s)
        if sp:
            out[s] = sp
    return out


def set_quote(symbol: str, spot: Dict[str, Any]) -> None:
    clean = _normalize_spot(symbol, spot)
    if not clean:
        return
    rc = _rc()
    blob = get_all_quotes()
    blob[symbol] = clean
    if rc.is_available():
        try:
            rc.set_json(_quotes_key(), blob, ttl=snapshot_ttl())
        except Exception:
            pass
    with _store_lock:
        _mem_quotes[symbol] = clean


def get_quote(symbol: str) -> Optional[Dict[str, Any]]:
    blob = get_all_quotes()
    return blob.get(symbol)


def get_all_quotes() -> Dict[str, Dict[str, Any]]:
    rc = _rc()
    if rc.is_available():
        try:
            raw = rc.get_json(_quotes_key())
            if isinstance(raw, dict):
                return dict(raw)
        except Exception:
            pass
    with _store_lock:
        return dict(_mem_quotes)


def chain_width(rows: List[Dict[str, Any]], atm: Any) -> int:
    if not rows:
        return 0
    strikes = [r.get("strike_price") for r in rows if r.get("strike_price") is not None]
    if not strikes:
        return max(0, (len(rows) - 1) // 2)
    if atm is None:
        return max(0, (len(strikes) - 1) // 2)
    try:
        atm_f = float(atm)
    except (TypeError, ValueError):
        return max(0, (len(strikes) - 1) // 2)
    below = sum(1 for s in strikes if float(s) < atm_f)
    above = sum(1 for s in strikes if float(s) > atm_f)
    if below and above:
        return int(min(below, above))
    return int(max(below, above))


def slice_chain_rows(
    rows: List[Dict[str, Any]],
    atm: Any,
    strike_count: int,
) -> List[Dict[str, Any]]:
    if not rows or not strike_count or strike_count <= 0:
        return list(rows or [])
    ordered = sorted(rows, key=lambda r: float(r.get("strike_price") or 0))
    if atm is None:
        mid = len(ordered) // 2
    else:
        try:
            atm_f = float(atm)
            mid = min(
                range(len(ordered)),
                key=lambda i: abs(float(ordered[i].get("strike_price") or 0) - atm_f),
            )
        except (TypeError, ValueError, ValueError):
            mid = len(ordered) // 2
    lo = max(0, mid - int(strike_count))
    hi = min(len(ordered), mid + int(strike_count) + 1)
    return ordered[lo:hi]


def get_chain(symbol: str, strike_count: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Return a get_option_chain-shaped dict sliced to strike_count, or None."""
    snap = get(symbol)
    if not snap:
        return None
    ch = snap.get("chain") or {}
    rows = ch.get("rows") or ch.get("chain") or []
    if not rows:
        return None
    want = int(strike_count) if strike_count else chain_width(rows, ch.get("atm_strike"))
    if chain_width(rows, ch.get("atm_strike")) < want:
        # stored chain narrower than requested — still return what we have
        sliced = rows
    else:
        sliced = slice_chain_rows(rows, ch.get("atm_strike"), want)
    return {
        "success": True,
        "symbol": symbol,
        "spot_price": ch.get("spot_price") or (snap.get("spot") or {}).get("ltp"),
        "atm_strike": ch.get("atm_strike"),
        "total_call_oi": ch.get("total_call_oi"),
        "total_put_oi": ch.get("total_put_oi"),
        "pcr": ch.get("pcr"),
        "expiries": ch.get("expiries") or [],
        "india_vix": ch.get("india_vix"),
        "chain": sliced,
        "timestamp": _iso(ch.get("ts") or snap.get("harvest_ts")),
        "_cache": "store",
        "_store": True,
        "_harvest_ts": snap.get("harvest_ts"),
    }


def get_history(
    symbol: str,
    resolution: str,
    min_bars: int = 1,
    days: Optional[int] = None,
) -> Optional[List[Dict[str, Any]]]:
    snap = get(symbol)
    if not snap:
        return None
    res = _hist_key(resolution)
    hist = (snap.get("history") or {}).get(res)
    if not hist:
        # derive 60/240 from stored 15m
        if res in ("60", "240"):
            raw_15 = (snap.get("history") or {}).get("15") or {}
            src = raw_15.get("candles") or []
            if src:
                mins = 60 if res == "60" else 240
                derived = aggregate_ohlcv(src, mins)
                if len(derived) >= min_bars:
                    return derived
        return None
    candles = list(hist.get("candles") or [])
    if days and days > 0 and candles:
        cutoff = _now() - (int(days) + 1) * 86400
        trimmed = [c for c in candles if float(c.get("timestamp") or 0) >= cutoff]
        if trimmed:
            candles = trimmed
    if len(candles) < min_bars:
        return None
    return candles


def history_as_response(
    symbol: str,
    resolution: str,
    candles: List[Dict[str, Any]],
    days: int,
) -> Dict[str, Any]:
    return {
        "success": True,
        "symbol": symbol,
        "resolution": str(resolution),
        "candles": candles,
        "count": len(candles),
        "_cache": "store",
        "_store": True,
    }


def aggregate_ohlcv(candles: List[Dict[str, Any]], bucket_minutes: int) -> List[Dict[str, Any]]:
    if not candles or bucket_minutes <= 0:
        return []
    bucket = int(bucket_minutes) * 60
    groups: Dict[int, Dict[str, Any]] = {}
    order: List[int] = []
    for c in candles:
        try:
            ts = int(c.get("timestamp") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        key = ts - (ts % bucket)
        o = c.get("open")
        h = c.get("high")
        l = c.get("low")
        cl = c.get("close")
        vol = float(c.get("volume") or 0)
        if key not in groups:
            groups[key] = {
                "timestamp": key,
                "datetime": datetime.fromtimestamp(key, tz=IST).isoformat(),
                "open": o,
                "high": h,
                "low": l,
                "close": cl,
                "volume": vol,
            }
            order.append(key)
        else:
            g = groups[key]
            try:
                g["high"] = max(float(g.get("high") or 0), float(h or 0))
            except (TypeError, ValueError):
                pass
            try:
                low_c = float(l or 0)
                prev = float(g.get("low") or low_c)
                g["low"] = min(prev, low_c) if low_c else prev
            except (TypeError, ValueError):
                pass
            g["close"] = cl
            g["volume"] = float(g.get("volume") or 0) + vol
    return [groups[k] for k in order]


def _normalize_spot(symbol: str, spot: Dict[str, Any]) -> Dict[str, Any]:
    if not spot:
        return {}
    ltp = spot.get("ltp") or spot.get("lp") or spot.get("close")
    if ltp is None:
        return {}
    try:
        ltp_f = float(ltp)
    except (TypeError, ValueError):
        return {}
    chg = spot.get("chg") if spot.get("chg") is not None else spot.get("change")
    chg_pct = (
        spot.get("chg_pct")
        if spot.get("chg_pct") is not None
        else spot.get("change_percent") or spot.get("change_pct") or spot.get("chp")
    )
    return {
        "symbol": symbol,
        "ltp": ltp_f,
        "chg": _f(chg),
        "chg_pct": _f(chg_pct),
        "open": _f(spot.get("open") or spot.get("open_price")),
        "high": _f(spot.get("high") or spot.get("high_price")),
        "low": _f(spot.get("low") or spot.get("low_price")),
        "prev_close": _f(
            spot.get("prev_close") or spot.get("close") or spot.get("prev_close_price")
        ),
        "volume": _f(spot.get("volume")),
        "ts": _now(),
    }


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def spot_from_quote_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not item:
        return None
    v = item.get("v") if isinstance(item.get("v"), dict) else item
    symbol = item.get("n") or item.get("symbol") or v.get("symbol")
    if not symbol:
        return None
    return _normalize_spot(
        str(symbol),
        {
            "ltp": v.get("lp") or v.get("ltp"),
            "chg": v.get("ch") or v.get("chg"),
            "chg_pct": v.get("chp") or v.get("chg_pct"),
            "open": v.get("open_price") or v.get("open"),
            "high": v.get("high_price") or v.get("high"),
            "low": v.get("low_price") or v.get("low"),
            "prev_close": v.get("prev_close_price") or v.get("prev_close"),
            "volume": v.get("volume"),
        },
    )


def quotes_response_from_spots(
    symbols: List[str],
    spots: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    data = []
    for s in symbols:
        sp = spots.get(s)
        if not sp:
            continue
        data.append(
            {
                "n": s,
                "s": "ok",
                "v": {
                    "lp": sp.get("ltp"),
                    "ch": sp.get("chg"),
                    "chp": sp.get("chg_pct"),
                    "open_price": sp.get("open"),
                    "high_price": sp.get("high"),
                    "low_price": sp.get("low"),
                    "prev_close_price": sp.get("prev_close"),
                    "volume": sp.get("volume"),
                    "short_name": _name_of(s),
                },
            }
        )
    return {
        "success": bool(data),
        "data": data,
        "timestamp": _iso(),
        "_cache": "store",
        "_store": True,
    }


def spot_response(symbol: str, spot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "success": True,
        "symbol": symbol,
        "ltp": spot.get("ltp"),
        "open": spot.get("open"),
        "high": spot.get("high"),
        "low": spot.get("low"),
        "close": spot.get("prev_close"),
        "change": spot.get("chg"),
        "change_percent": spot.get("chg_pct"),
        "volume": spot.get("volume"),
        "_cache": "store",
        "_store": True,
    }


def set_harvest_meta(patch: Dict[str, Any]) -> Dict[str, Any]:
    global _mem_meta
    current = get_harvest_meta() or {}
    meta = _deep_merge(current, patch)
    meta["updated_at"] = _iso()
    rc = _rc()
    if rc.is_available():
        try:
            rc.set_json(_meta_key(), meta, ttl=snapshot_ttl())
        except Exception:
            pass
    with _store_lock:
        _mem_meta = meta
    return meta


def get_harvest_meta() -> Optional[Dict[str, Any]]:
    rc = _rc()
    if rc.is_available():
        try:
            raw = rc.get_json(_meta_key())
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
    with _store_lock:
        return dict(_mem_meta) if _mem_meta else None


def set_hv_index(payload: Dict[str, Any]) -> None:
    global _mem_hv
    body = dict(payload or {})
    body["ts"] = _now()
    body["iso"] = _iso()
    rc = _rc()
    if rc.is_available():
        try:
            rc.set_json(_hv_key(), body, ttl=snapshot_ttl())
        except Exception:
            pass
    with _store_lock:
        _mem_hv = body


def get_hv_index(max_age: float = 1800.0) -> Optional[Dict[str, Any]]:
    rc = _rc()
    raw = None
    if rc.is_available():
        try:
            raw = rc.get_json(_hv_key())
        except Exception:
            raw = None
    if not isinstance(raw, dict):
        with _store_lock:
            raw = dict(_mem_hv) if _mem_hv else None
    if not raw:
        return None
    ts = float(raw.get("ts") or 0)
    if ts and (_now() - ts) > max_age:
        return None
    return raw


def note_reader_hit(kind: str, symbol: str = "") -> None:
    global reader_hits
    reader_hits += 1
    logger.debug("store.reader_hit %s %s", kind, symbol)


def note_reader_miss(kind: str, symbol: str = "", extra: str = "") -> None:
    global reader_misses
    reader_misses += 1
    logger.warning("store.reader_miss %s %s %s", kind, symbol, extra)


def status() -> Dict[str, Any]:
    rc = _rc()
    redis_ok = False
    try:
        redis_ok = bool(rc.is_available())
    except Exception:
        redis_ok = False
    symbols = list_symbols()
    ages: List[Tuple[str, float]] = []
    chain_fresh = 0
    hist_fresh = 0
    for s in symbols:
        a = age(s, "chain")
        if a is not None:
            ages.append((s, a))
            if a <= oc_ttl():
                chain_fresh += 1
        if is_fresh(s, "history.15"):
            hist_fresh += 1
    freshest = min((a for _, a in ages), default=None)
    oldest = max((a for _, a in ages), default=None)
    meta = get_harvest_meta() or {}
    return {
        "redis": "ok" if redis_ok else "memory",
        "backend": "redis" if redis_ok else "memory",
        "symbols": len(symbols),
        "chain_fresh": chain_fresh,
        "history_15_fresh": hist_fresh,
        "freshest_age": round(freshest, 1) if freshest is not None else None,
        "oldest_age": round(oldest, 1) if oldest is not None else None,
        "harvest": meta,
        "reader_hits": reader_hits,
        "reader_misses": reader_misses,
        "writer_puts": writer_puts,
        "ttl_secs": snapshot_ttl(),
        "oc_ttl_secs": oc_ttl(),
        "stale_soft_secs": stale_soft(),
        "stale_hard_secs": stale_hard(),
    }


class SymbolStore:
    """Thin object wrapper so callers can do store.get / store.put."""

    get = staticmethod(get)
    put = staticmethod(put)
    get_many = staticmethod(get_many)
    list_fresh = staticmethod(list_fresh)
    is_fresh = staticmethod(is_fresh)
    get_chain = staticmethod(get_chain)
    get_history = staticmethod(get_history)
    get_spots = staticmethod(get_spots)
    get_spot = staticmethod(get_spot)
    set_harvest_meta = staticmethod(set_harvest_meta)
    status = staticmethod(status)
    put_spot = staticmethod(put_spot)
    put_chain = staticmethod(put_chain)
    put_history = staticmethod(put_history)
    put_futures = staticmethod(put_futures)
    put_derived = staticmethod(put_derived)


_singleton: Optional[SymbolStore] = None


def get_symbol_store() -> SymbolStore:
    global _singleton
    if _singleton is None:
        _singleton = SymbolStore()
    return _singleton
