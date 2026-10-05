"""Paper Trade Watch — 1-lot dummy desk.

At 09:23 IST dump AI-chain + bullish/bearish board + news + option chains,
ask the model for up to 2 high-conviction option buys, enter 1 lot at the
print on the book, then mark-to-market with SL/TP plus AI exit updates.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import get_settings
from app.services.lot_sizes import lot_size
from app.utils.market_hours import IST, last_session_date, session_is_open

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "trade_watch.json"
ENTRY_TIME = dt_time(9, 23)
FLAT_TIME = dt_time(15, 15)
MAX_TRADES = 2
MARK_SECS = 180
MAX_CANDIDATES = 12
CHAIN_BAND = 4

PICK_PROMPT = """You are an NSE F&O options desk. Paper-trade ONLY.

You receive a DUMP: AI-chain news picks, bullish board, bearish board, headlines,
and live option-chain legs (ltp/oi/vol/iv) for those names.

Task: choose up to TWO high-conviction directional option BUY trades for TODAY.
Entry is 1 lot at the current premium on the chain (09:23 print). Dummy fill.

HARD RULES:
1. Return JSON only. No markdown, no prose.
2. trades length is 0, 1, or 2. Prefer 2 only if BOTH are high conviction.
3. symbol MUST be copied from DUMP (full NSE:… form). Never invent a ticker.
4. strike MUST exist on that symbol's CHAINS legs. side is CE or PE.
5. BUY only (we do not short options). Bullish process → CE. Bearish → PE.
6. Prefer liquid legs: high volume + OI, near ATM (±2 strikes), premium not a ₹1 lottery.
7. sl_premium and tp_premium are option LTP levels, not spot. SL < entry for a long; TP > entry.
8. thesis ≤ 40 words: why THIS strike from the chain + news/flow. invalidation ≤ 20 words.
9. If the book is mixed/quiet, return trades: [] and say why in skip_reason.

JSON shape:
{"trades":[{"symbol":"NSE:SBIN-EQ","side":"CE","strike":800,"thesis":"...","invalidation":"...","sl_premium":12.4,"tp_premium":21.0}],"skip_reason":""}
"""

EXIT_PROMPT = """You manage open 1-lot NSE option paper trades.

DUMP has each open trade (entry, sl, tp, current ltp, chain snippet) plus latest board row.

Return JSON only:
{"updates":[{"id":"...","action":"HOLD|EXIT|TIGHTEN","sl_premium":0,"tp_premium":0,"reason":"..."}]}

Rules:
- action EXIT if the thesis is dead (flow flipped, premium collapsing, wall absorbed).
- action TIGHTEN to raise SL / lower TP toward the market; sl_premium/tp_premium required.
- action HOLD if the process is intact.
- Never invent an id. Never flip CE↔PE. 1-lot stays 1-lot.
- reason ≤ 25 words.
"""

_lock = threading.RLock()
_state: Dict[str, Any] = {}
_last_mark_at = 0.0
_last_px_at = 0.0
_pick_running = False
PX_SECS = 1.5


def _now() -> datetime:
    return datetime.now(IST)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _empty_book() -> Dict[str, Any]:
    return {
        "session_date": None,
        "phase": "idle",
        "entry_at": None,
        "trades": [],
        "events": [],
        "dump_meta": {},
        "skip_reason": None,
        "error": None,
        "updated_at": _iso(),
    }


def _load() -> Dict[str, Any]:
    global _state
    if _state:
        return _state
    try:
        from app.services import redis_client as rc
        if rc.is_available():
            raw = rc.get_json(rc.key("desk", "watch"))
            if isinstance(raw, dict) and (raw.get("trades") or raw.get("phase")):
                _state = raw
                return _state
    except Exception as exc:
        logger.debug("trade_watch redis load: %s", exc)
    if DATA_PATH.exists():
        try:
            raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _state = raw
                return _state
        except Exception as exc:
            logger.debug("trade_watch load: %s", exc)
    _state = _empty_book()
    return _state


def _save(book: Dict[str, Any]) -> None:
    global _state
    book["updated_at"] = _iso()
    _state = book
    blob = json.dumps(book, indent=2, default=str)
    try:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(blob, encoding="utf-8")
    except Exception as exc:
        logger.warning("trade_watch save: %s", exc)
    try:
        from app.services import redis_client as rc
        from app.services.symbol_store import session_snapshot_ttl
        if rc.is_available():
            rc.set_json(rc.key("desk", "watch"), book, ttl=session_snapshot_ttl())
    except Exception as exc:
        logger.debug("trade_watch redis save: %s", exc)


def _event(book: Dict[str, Any], kind: str, message: str, extra: Optional[Dict] = None) -> None:
    row = {"ts": _iso(), "kind": kind, "message": message}
    if extra:
        row.update(extra)
    ev = list(book.get("events") or [])
    ev.append(row)
    book["events"] = ev[-80:]


def refresh_open_prices(force: bool = False) -> Dict[str, Any]:
    """Reprice OPEN trades from the stored chain. No AI. Safe to call on every UI poll."""
    global _last_px_at
    now = time.time()
    if not force and (now - _last_px_at) < PX_SECS:
        return snapshot(skip_px=True)
    _last_px_at = now
    with _lock:
        book = _load()
        trades = list(book.get("trades") or [])
        open_trades = [t for t in trades if t.get("status") == "OPEN"]
    if not open_trades:
        return snapshot(skip_px=True)
    for t in open_trades:
        try:
            ltp = _refresh_ltp(t)
            _pnl_fields(t, ltp)
            t["px_at"] = _iso()
        except Exception as exc:
            logger.debug("px %s: %s", t.get("id"), exc)
    with _lock:
        book = _load()
        id_map = {t.get("id"): t for t in trades}
        book["trades"] = [id_map.get(old.get("id"), old) for old in (book.get("trades") or [])]
        book["px_at"] = _iso()
        _save(book)
    return snapshot(skip_px=True)


def snapshot(*, skip_px: bool = False) -> Dict[str, Any]:
    if not skip_px:
        with _lock:
            book0 = _load()
        if any(t.get("status") == "OPEN" for t in book0.get("trades") or []):
            return refresh_open_prices()
    with _lock:
        book = dict(_load())
    book["session_open"] = session_is_open()
    book["entry_time"] = "09:23"
    book["max_trades"] = MAX_TRADES
    now = _now().time()
    book["can_enter"] = session_is_open() and now >= ENTRY_TIME
    trades = list(book.get("trades") or [])
    open_n = sum(1 for t in trades if t.get("status") == "OPEN")
    book["open_count"] = open_n
    book["realized_pnl"] = round(sum(float(t.get("pnl") or 0) for t in trades if t.get("status") == "CLOSED"), 2)
    book["unrealized_pnl"] = round(sum(float(t.get("pnl") or 0) for t in trades if t.get("status") == "OPEN"), 2)
    book["live"] = True
    return book


def _row_slim(h: Dict[str, Any]) -> Dict[str, Any]:
    flags = h.get("flags") or {}
    top = h.get("top_anomaly") or {}
    sess = h.get("session") or {}
    return {
        "symbol": h.get("symbol"),
        "name": h.get("name"),
        "grade": h.get("grade"),
        "bias": h.get("chain_bias"),
        "score": h.get("setup_score"),
        "unique": bool(flags.get("unique")),
        "tags": flags.get("tags") or [],
        "spot": h.get("spot"),
        "put_wall": h.get("put_wall") or (h.get("structure") or {}).get("put_wall"),
        "call_wall": h.get("call_wall") or (h.get("structure") or {}).get("call_wall"),
        "anomaly": top.get("label") or top.get("type"),
        "oi_added": flags.get("oi_added") or top.get("oi_added"),
        "vol": flags.get("opt_volume") or h.get("chain_volume"),
        "vor": flags.get("vor") or h.get("vor"),
        "orh": sess.get("orh"),
        "orl": sess.get("orl"),
        "or_state": sess.get("or_break_state"),
        "why_not": h.get("why_not"),
    }


def _slim_chain(symbol: str) -> Optional[Dict[str, Any]]:
    from app.services import symbol_store as store

    raw = store.get_chain(symbol, CHAIN_BAND) or {}
    rows = list(raw.get("chain") or [])
    if len(rows) < 3:
        return None
    legs = []
    for r in rows:
        call = r.get("call") or {}
        put = r.get("put") or {}
        legs.append({
            "k": r.get("strike_price"),
            "ce": {
                "ltp": call.get("ltp"),
                "oi": call.get("oi"),
                "doi": call.get("oi_change") or call.get("oi_change_pct"),
                "vol": call.get("volume"),
                "iv": call.get("iv"),
                "sym": call.get("symbol"),
            },
            "pe": {
                "ltp": put.get("ltp"),
                "oi": put.get("oi"),
                "doi": put.get("oi_change") or put.get("oi_change_pct"),
                "vol": put.get("volume"),
                "iv": put.get("iv"),
                "sym": put.get("symbol"),
            },
        })
    return {
        "symbol": symbol,
        "spot": raw.get("spot_price"),
        "atm": raw.get("atm_strike"),
        "pcr": raw.get("pcr"),
        "legs": legs,
    }


def build_dump() -> Dict[str, Any]:
    from app.services.ai_chain_job import last_payload
    from app.services.news_scraper import scrape_market_news
    from app.services.option_flow_radar import get_radar_service

    radar = get_radar_service().get_last_scan() or {}
    bull = list(radar.get("bullish") or [])[:MAX_CANDIDATES]
    bear = list(radar.get("bearish") or [])[:MAX_CANDIDATES]
    unique = list(radar.get("unique") or [])[:8]
    ai = last_payload() or {}
    picks = list(ai.get("picks") or [])[:8]
    news, src = scrape_market_news(force=False, limit=12)
    headlines = [
        {"title": a.get("title"), "cat": a.get("category"), "body": str(a.get("body") or "")[:180]}
        for a in news[:12]
    ]

    symbols: List[str] = []
    for row in unique + bull + bear:
        s = row.get("symbol")
        if s and s not in symbols:
            symbols.append(s)
    for p in picks:
        s = p.get("symbol")
        if s and s not in symbols:
            symbols.append(s)
    symbols = symbols[:16]

    chains = {}
    for s in symbols:
        slim = _slim_chain(s)
        if slim:
            chains[s] = slim

    return {
        "as_of": _iso(),
        "session_date": last_session_date().isoformat(),
        "ai_chain": {
            "model": ai.get("model"),
            "picks": [
                {
                    "symbol": p.get("symbol"),
                    "name": p.get("name"),
                    "news": p.get("news"),
                    "intent": p.get("news_intent") or p.get("intent"),
                    "action": p.get("action"),
                    "alignment": p.get("alignment_score"),
                    "chain": p.get("chain") or {},
                }
                for p in picks
            ],
        },
        "unique": [_row_slim(h) for h in unique],
        "bullish": [_row_slim(h) for h in bull],
        "bearish": [_row_slim(h) for h in bear],
        "news": {"source": src, "headlines": headlines},
        "chains": chains,
        "candidate_symbols": symbols,
    }


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _chat(system: str, user: str, max_tokens: int = 900) -> Tuple[Dict[str, Any], str]:
    settings = get_settings()
    grok_key = (settings.grok_api_key or os.environ.get("XAI_API_KEY") or "").strip()
    or_key = (settings.openrouter_api_key or "").strip()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_err: Optional[Exception] = None
    if grok_key:
        base = (settings.grok_api_url or "https://api.x.ai/v1").rstrip("/")
        models = [m for m in ((settings.grok_model or "").strip(), "grok-4.5", "grok-3-mini") if m]
        seen = set()
        for model in models:
            if model in seen:
                continue
            seen.add(model)
            try:
                with httpx.Client(timeout=90.0) as client:
                    r = client.post(
                        f"{base}/chat/completions",
                        headers={"Authorization": f"Bearer {grok_key}", "Content-Type": "application/json"},
                        json={"model": model, "messages": messages, "temperature": 0.15, "max_tokens": max_tokens},
                    )
                if r.status_code >= 400:
                    last_err = RuntimeError(f"xAI HTTP {r.status_code}: {r.text[:200]}")
                    continue
                raw = r.json()
                content = (((raw.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
                parsed = _extract_json(str(content)) or {}
                return parsed, str(raw.get("model") or model)
            except Exception as exc:
                last_err = exc
                continue
    if or_key:
        base = (settings.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
        model = (settings.openrouter_model or "google/gemma-4-31b-it:free").strip()
        try:
            with httpx.Client(timeout=90.0) as client:
                r = client.post(
                    f"{base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {or_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://optiongreek.local",
                        "X-Title": "OptionGreek TradeWatch",
                    },
                    json={"model": model, "messages": messages, "temperature": 0.15, "max_tokens": max_tokens},
                )
            if r.status_code >= 400:
                raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:200]}")
            raw = r.json()
            content = (((raw.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
            parsed = _extract_json(str(content)) or {}
            return parsed, str(raw.get("model") or model)
        except Exception as exc:
            last_err = exc
    raise RuntimeError(str(last_err) if last_err else "No LLM key (GROK_API_KEY / XAI_API_KEY / OPENROUTER_API_KEY)")


def _leg(chain: Dict[str, Any], strike: float, side: str) -> Optional[Dict[str, Any]]:
    key = "ce" if side == "CE" else "pe"
    want = float(strike)
    best = None
    best_d = 1e9
    for row in chain.get("legs") or []:
        k = row.get("k")
        try:
            kf = float(k)
        except (TypeError, ValueError):
            continue
        d = abs(kf - want)
        if d < best_d:
            best_d = d
            best = row.get(key) or {}
            best["_strike"] = kf
    if best is None:
        return None
    tol = max(5.0, abs(want) * 0.008)
    if best_d > tol:
        return None
    return best


def _fill_trade(raw: Dict[str, Any], chains: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = str(raw.get("symbol") or "").strip()
    side = str(raw.get("side") or "").upper()
    if side not in ("CE", "PE") or symbol not in chains:
        return None
    try:
        strike = float(raw.get("strike"))
    except (TypeError, ValueError):
        return None
    chain = chains[symbol]
    leg = _leg(chain, strike, side)
    if not leg:
        return None
    try:
        ltp = float(leg.get("ltp") or 0)
    except (TypeError, ValueError):
        ltp = 0.0
    if ltp <= 0:
        return None
    lot, estimated = lot_size(symbol)
    try:
        sl = float(raw.get("sl_premium") or 0)
    except (TypeError, ValueError):
        sl = 0.0
    try:
        tp = float(raw.get("tp_premium") or 0)
    except (TypeError, ValueError):
        tp = 0.0
    if sl <= 0 or sl >= ltp:
        sl = round(ltp * 0.70, 2)
    if tp <= ltp:
        tp = round(ltp * 1.45, 2)
    strike_px = float(leg.get("_strike") or strike)
    notional = round(ltp * lot, 2)
    name = symbol.split(":")[-1].replace("-EQ", "").replace("-INDEX", "")
    return {
        "id": uuid.uuid4().hex[:10],
        "symbol": symbol,
        "name": name,
        "side": side,
        "strike": strike_px,
        "option_symbol": leg.get("sym"),
        "status": "OPEN",
        "qty_lots": 1,
        "lot_size": lot,
        "lot_estimated": estimated,
        "entry": round(ltp, 2),
        "ltp": round(ltp, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "notional": notional,
        "pnl": 0.0,
        "pnl_pct": 0.0,
        "thesis": str(raw.get("thesis") or "")[:280],
        "invalidation": str(raw.get("invalidation") or "")[:160],
        "exit_reason": None,
        "entered_at": _iso(),
        "exited_at": None,
        "exit": None,
    }


def _pnl_fields(trade: Dict[str, Any], ltp: float) -> None:
    entry = float(trade.get("entry") or 0)
    lot = int(trade.get("lot_size") or 1)
    pnl = round((ltp - entry) * lot, 2)
    trade["ltp"] = round(ltp, 2)
    trade["pnl"] = pnl
    trade["pnl_pct"] = round((ltp - entry) / entry * 100.0, 2) if entry else 0.0
    trade["notional"] = round(ltp * lot, 2)


def _close(trade: Dict[str, Any], ltp: float, reason: str) -> None:
    _pnl_fields(trade, ltp)
    trade["status"] = "CLOSED"
    trade["exit"] = round(ltp, 2)
    trade["exit_reason"] = reason
    trade["exited_at"] = _iso()


def _refresh_ltp(trade: Dict[str, Any]) -> float:
    chain = _slim_chain(str(trade.get("symbol") or "")) or {}
    leg = _leg(chain, float(trade.get("strike") or 0), str(trade.get("side") or "CE"))
    if leg and leg.get("ltp"):
        try:
            return float(leg["ltp"])
        except (TypeError, ValueError):
            pass
    opt = trade.get("option_symbol")
    if opt:
        try:
            from app.services import symbol_store as store
            from app.services.fyers_market import get_market_service

            def _q():
                with store.harvest_writer():
                    return get_market_service().get_quotes([opt])

            res = _q()
            for item in res.get("data") or []:
                v = item.get("v") if isinstance(item.get("v"), dict) else {}
                lp = v.get("lp") or v.get("ltp")
                if lp:
                    return float(lp)
        except Exception as exc:
            logger.debug("trade_watch quote %s: %s", opt, exc)
    return float(trade.get("ltp") or trade.get("entry") or 0)


def run_pick(force: bool = False) -> Dict[str, Any]:
    global _pick_running
    with _lock:
        if _pick_running:
            return snapshot()
        book = _load()
        today = last_session_date().isoformat()
        open_n = sum(1 for t in book.get("trades") or [] if t.get("status") == "OPEN")
        if book.get("session_date") == today and (book.get("trades") or open_n) and not force:
            return snapshot()
        if not force and session_is_open() and _now().time() < ENTRY_TIME:
            book["phase"] = "waiting_923"
            _save(book)
            return snapshot()
        _pick_running = True
        book["phase"] = "picking"
        book["error"] = None
        _save(book)

    try:
        dump = build_dump()
        if not dump.get("chains"):
            with _lock:
                book = _load()
                book["phase"] = "blocked"
                book["session_date"] = dump.get("session_date") or last_session_date().isoformat()
                book["skip_reason"] = "No option chains in the store yet — run a harvest first."
                _event(book, "block", book["skip_reason"])
                _save(book)
            return snapshot()
        user = (
            "ENTRY_CLOCK: 09:23 IST 1-lot dummy BUY\n"
            "MAX_TRADES: 2\n"
            "DUMP:\n"
            + json.dumps(dump, default=str)[:24000]
        )
        parsed, model = _chat(PICK_PROMPT, user)
        raw_trades = parsed.get("trades") if isinstance(parsed, dict) else []
        if not isinstance(raw_trades, list):
            raw_trades = []
        filled: List[Dict[str, Any]] = []
        for row in raw_trades:
            if not isinstance(row, dict):
                continue
            t = _fill_trade(row, dump.get("chains") or {})
            if t:
                filled.append(t)
            if len(filled) >= MAX_TRADES:
                break
        with _lock:
            book = _load()
            book["session_date"] = dump["session_date"]
            book["entry_at"] = _iso()
            book["dump_meta"] = {
                "model": model,
                "candidates": dump.get("candidate_symbols"),
                "ai_picks": len((dump.get("ai_chain") or {}).get("picks") or []),
                "bullish": len(dump.get("bullish") or []),
                "bearish": len(dump.get("bearish") or []),
                "news_n": len(((dump.get("news") or {}).get("headlines") or [])),
                "chains_n": len(dump.get("chains") or {}),
            }
            book["skip_reason"] = parsed.get("skip_reason") if isinstance(parsed, dict) else None
            book["trades"] = filled
            book["phase"] = "open" if filled else "skipped"
            _event(
                book,
                "entry" if filled else "skip",
                (
                    f"Entered {len(filled)} × 1-lot at 09:23 desk"
                    if filled
                    else (book.get("skip_reason") or "Model returned no high-conviction trades")
                ),
                {"model": model},
            )
            for t in filled:
                _event(
                    book,
                    "fill",
                    (
                        f"{t['name']} {int(t['strike'])}{t['side']} @ ₹{t['entry']} "
                        f"× 1 lot ({t['lot_size']}) = ₹{t['notional']:.0f}  ·  {t['thesis']}"
                    ),
                    {"id": t["id"]},
                )
            _save(book)
        return snapshot()
    except Exception as exc:
        logger.exception("trade_watch pick failed")
        with _lock:
            book = _load()
            book["phase"] = "error"
            book["session_date"] = last_session_date().isoformat()
            book["error"] = str(exc)[:240]
            _event(book, "error", book["error"])
            _save(book)
        return snapshot()
    finally:
        _pick_running = False


def mark_and_exit(ask_ai: bool = True) -> Dict[str, Any]:
    with _lock:
        book = _load()
        trades = list(book.get("trades") or [])
        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        if not open_trades:
            if book.get("phase") == "open":
                book["phase"] = "closed"
                _save(book)
            return snapshot()

    newly_closed: List[str] = []
    now_t = _now().time()
    do_flat = session_is_open() and now_t >= FLAT_TIME
    for t in open_trades:
        ltp = _refresh_ltp(t)
        _pnl_fields(t, ltp)
        sl = float(t.get("sl") or 0)
        tp = float(t.get("tp") or 0)
        if do_flat:
            _close(t, ltp, "Squared off at 15:15 session close")
            newly_closed.append(t["id"])
        elif sl and ltp <= sl:
            _close(t, ltp, f"SL hit at ₹{ltp:.2f} (stop {sl:.2f})")
            newly_closed.append(t["id"])
        elif tp and ltp >= tp:
            _close(t, ltp, f"TP hit at ₹{ltp:.2f} (target {tp:.2f})")
            newly_closed.append(t["id"])

    still = [t for t in open_trades if t.get("status") == "OPEN"]
    if ask_ai and still and not do_flat:
        try:
            payload = {
                "trades": [
                    {
                        "id": t["id"],
                        "symbol": t["symbol"],
                        "side": t["side"],
                        "strike": t["strike"],
                        "entry": t["entry"],
                        "ltp": t["ltp"],
                        "sl": t["sl"],
                        "tp": t["tp"],
                        "pnl": t["pnl"],
                        "thesis": t["thesis"],
                    }
                    for t in still
                ],
                "chains": {t["symbol"]: _slim_chain(t["symbol"]) for t in still},
            }
            parsed, model = _chat(EXIT_PROMPT, json.dumps(payload, default=str)[:14000], max_tokens=600)
            updates = parsed.get("updates") if isinstance(parsed, dict) else []
            by_id = {t["id"]: t for t in still}
            if isinstance(updates, list):
                for u in updates:
                    if not isinstance(u, dict):
                        continue
                    tr = by_id.get(str(u.get("id") or ""))
                    if not tr or tr.get("status") != "OPEN":
                        continue
                    action = str(u.get("action") or "HOLD").upper()
                    reason = str(u.get("reason") or "")[:160]
                    if action == "EXIT":
                        _close(tr, float(tr["ltp"]), reason or "AI exit")
                        newly_closed.append(tr["id"])
                    elif action == "TIGHTEN":
                        try:
                            nsl = float(u.get("sl_premium") or tr["sl"])
                            ntp = float(u.get("tp_premium") or tr["tp"])
                        except (TypeError, ValueError):
                            continue
                        if 0 < nsl < float(tr["ltp"]):
                            tr["sl"] = round(nsl, 2)
                        if ntp > float(tr["ltp"]):
                            tr["tp"] = round(ntp, 2)
                        if float(tr["ltp"]) <= float(tr["sl"]):
                            _close(tr, float(tr["ltp"]), f"SL after tighten ({reason})")
                            newly_closed.append(tr["id"])
                        else:
                            with _lock:
                                b = _load()
                                _event(
                                    b,
                                    "tighten",
                                    f"{tr['name']} SL {tr['sl']} TP {tr['tp']} · {reason}",
                                    {"id": tr["id"], "model": model},
                                )
                                _save(b)
        except Exception as exc:
            logger.info("trade_watch exit AI skip: %s", exc)

    with _lock:
        book = _load()
        id_map = {t.get("id"): t for t in trades}
        book["trades"] = [id_map.get(old.get("id"), old) for old in (book.get("trades") or [])]
        still_open = [t for t in book["trades"] if t.get("status") == "OPEN"]
        book["phase"] = "open" if still_open else "closed"
        seen_exit = set()
        for t in book["trades"]:
            tid = t.get("id")
            if tid in newly_closed and tid not in seen_exit:
                seen_exit.add(tid)
                _event(
                    book,
                    "exit",
                    (
                        f"{t.get('name')} {int(t.get('strike') or 0)}{t.get('side')} "
                        f"exit ₹{t.get('exit')}  P&L ₹{t.get('pnl')} ({t.get('pnl_pct')}%) · {t.get('exit_reason')}"
                    ),
                    {"id": tid},
                )
        _save(book)
    return snapshot()


def flatten(reason: str = "Manual square-off") -> Dict[str, Any]:
    with _lock:
        book = _load()
        for t in book.get("trades") or []:
            if t.get("status") == "OPEN":
                ltp = _refresh_ltp(t)
                _close(t, ltp, reason)
        book["phase"] = "closed"
        _event(book, "exit", reason)
        _save(book)
    return snapshot()


def tick() -> None:
    """Called by the scheduler. Enter at 09:23; mark open trades every MARK_SECS."""
    global _last_mark_at
    now = _now()
    book = snapshot()
    today = last_session_date().isoformat()
    if session_is_open() and now.time() >= ENTRY_TIME:
        if book.get("session_date") != today and book.get("phase") not in ("picking",):
            run_pick(force=False)
            return
    open_n = int(book.get("open_count") or 0)
    if open_n and (time.time() - _last_mark_at) >= MARK_SECS:
        _last_mark_at = time.time()
        mark_and_exit(ask_ai=True)
    elif open_n and session_is_open() and now.time() >= FLAT_TIME:
        mark_and_exit(ask_ai=False)
