"""
Multi-source Confluence Engine
==============================
Combines MA crossovers, option-flow radar, F&O intelligence, and the
shared signal bus into a single ranked "trade / no-trade" view.

Rule of thumb:
  • 1 source alone  → WATCH (low conviction)
  • 2+ sources agree on direction → ACTIONABLE
  • Conflicting sources → NO_TRADE / conflict
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pytz

from app.services.fno_stocks import TOP_FNO_STOCKS, FNO_INDICES
from app.services.signal_bus import get_signal_bus
from app.services.strategies.ma_crossover import get_ma_crossover_service
from app.services.option_flow_radar import get_radar_service
from app.services.fyers_market import get_market_service
from app.services.fno_intelligence import get_intelligence_engine, MarketState
from app.services.news_context import get_news_service

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# Weights for composite score (0–100)
WEIGHT_MA = 28
WEIGHT_RADAR = 32
WEIGHT_INTEL = 22
WEIGHT_BUS = 8
WEIGHT_NEWS = 10

BULLISH_TOKENS = {
    "BUY", "GOLDEN", "GOLDEN_CROSS", "BULL", "BULLISH", "LONG",
    "STRONG_BULLISH", "ACCUMULATION", "WEAK_BULLISH", "INTENT",
    "TREND", "CALL", "CE",
}
BEARISH_TOKENS = {
    "SELL", "DEATH", "DEATH_CROSS", "BEAR", "BEARISH", "SHORT",
    "STRONG_BEARISH", "PUT", "PE", "CALL_WRITING",
}


def _dir_from_text(*parts: Any) -> Optional[str]:
    blob = " ".join(str(p or "").upper() for p in parts)
    bull = any(t in blob for t in BULLISH_TOKENS)
    bear = any(t in blob for t in BEARISH_TOKENS)
    if bull and not bear:
        return "BULLISH"
    if bear and not bull:
        return "BEARISH"
    if bull and bear:
        return "MIXED"
    return None


class ConfluenceEngine:
    def __init__(self):
        self.ma = get_ma_crossover_service()
        self.radar = get_radar_service()
        self.market = get_market_service()
        self.intel = get_intelligence_engine()
        self.bus = get_signal_bus()
        self.news = get_news_service()

    def evaluate(
        self,
        symbols: Optional[List[str]] = None,
        min_sources: int = 2,
        include_nifty_state: bool = True,
    ) -> Dict[str, Any]:
        """
        Build confluence cards for the watchlist.
        Uses cached MA / radar / bus data (no full Fyers re-scan required).
        Optionally enriches NIFTY with a live intelligence snapshot.
        """
        watch = symbols or list(dict.fromkeys([*TOP_FNO_STOCKS[:25], *FNO_INDICES]))

        ma_by_sym = self._index_ma()
        radar_by_sym = self._index_radar()
        bus_by_sym = self._index_bus()
        news = self.news.get_market_bias()

        nifty_intel: Optional[Dict[str, Any]] = None
        if include_nifty_state:
            nifty_intel = self._safe_nifty_intel()

        cards: List[Dict[str, Any]] = []
        for sym in watch:
            card = self._score_symbol(
                sym,
                ma_by_sym.get(sym, []),
                radar_by_sym.get(sym),
                bus_by_sym.get(sym, []),
                nifty_intel if "NIFTY" in sym.upper() or "INDEX" in sym.upper() else None,
                news=news,
                min_sources=min_sources,
            )
            if card["sources_count"] > 0 or card.get("status") != "IDLE":
                cards.append(card)

        # Prefer actionable, then higher score
        cards.sort(
            key=lambda c: (
                0 if c["status"] == "ACTIONABLE" else 1 if c["status"] == "WATCH" else 2,
                -c["score"],
            )
        )

        actionable = [c for c in cards if c["status"] == "ACTIONABLE"]
        watch_only = [c for c in cards if c["status"] == "WATCH"]

        summary = {
            "actionable_count": len(actionable),
            "watch_count": len(watch_only),
            "total_scored": len(cards),
            "min_sources": min_sources,
            "bias": self._market_bias(cards, nifty_intel, news),
            "news_bias": news.get("bias"),
            "news_available": bool(news.get("available")),
        }

        # Publish top confluence hits once (deduped by bus)
        for card in actionable[:3]:
            try:
                self.bus.publish(
                    source="confluence",
                    message=(
                        f"{card['direction']} confluence on {card['symbol']} "
                        f"score={card['score']} sources={card['sources_count']}: "
                        f"{', '.join(card['source_names'])}"
                    ),
                    level="signal",
                    symbol=card["symbol"],
                    score=float(card["score"]),
                    meta={"direction": card["direction"], "sources": card["source_names"]},
                )
            except Exception:
                pass

        return {
            "success": True,
            "summary": summary,
            "cards": cards[:40],
            "actionable": actionable[:15],
            "nifty_state": (nifty_intel or {}).get("state"),
            "news": {
                "bias": news.get("bias"),
                "score": news.get("score"),
                "summary": news.get("summary"),
                "available": news.get("available"),
                "cached": news.get("cached"),
            },
            "radar_cache_age": (self.radar.get_last_scan() or {}).get("cache_age_seconds"),
            "timestamp": datetime.now(IST).isoformat(),
        }

    # ── Index helpers ─────────────────────────────────────────────

    def _index_ma(self) -> Dict[str, List[Dict]]:
        out: Dict[str, List[Dict]] = {}
        for c in self.ma.get_crossovers():
            sym = c.get("symbol")
            if not sym:
                continue
            out.setdefault(sym, []).append(c)
        for n in self.ma.get_nearing()[:50]:
            sym = n.get("symbol")
            if not sym:
                continue
            # Nearing is weaker — tag as soft
            item = {**n, "_nearing": True}
            out.setdefault(sym, []).append(item)
        return out

    def _index_radar(self) -> Dict[str, Dict]:
        cached = self.radar.get_last_scan() or self.radar.get_cached_scan(max_age_seconds=1800) or {}
        out: Dict[str, Dict] = {}
        for row in cached.get("flagged") or []:
            sym = row.get("symbol")
            if sym:
                out[sym] = row
        return out

    def _index_bus(self) -> Dict[str, List[Dict]]:
        out: Dict[str, List[Dict]] = {}
        for ev in self.bus.recent(limit=50):
            sym = ev.get("symbol")
            if not sym:
                continue
            # Skip confluence self-echo
            if ev.get("source") == "confluence":
                continue
            out.setdefault(sym, []).append(ev)
        return out

    def _safe_nifty_intel(self) -> Optional[Dict[str, Any]]:
        try:
            chain = self.market.get_option_chain("NSE:NIFTY50-INDEX", strike_count=8)
            if not chain.get("success"):
                return None
            return self.intel.get_analysis_summary(chain, bypass_time_check=True)
        except Exception as exc:
            logger.debug(f"Nifty intel failed: {exc}")
            return None

    # ── Scoring ───────────────────────────────────────────────────

    def _score_symbol(
        self,
        symbol: str,
        ma_events: List[Dict],
        radar_row: Optional[Dict],
        bus_events: List[Dict],
        intel: Optional[Dict],
        news: Optional[Dict],
        min_sources: int,
    ) -> Dict[str, Any]:
        sources: List[Dict[str, Any]] = []
        directions: List[str] = []
        score = 0.0

        # MA
        hard_ma = [e for e in ma_events if not e.get("_nearing") and e.get("type") in ("golden_cross", "death_cross")]
        if hard_ma:
            latest = hard_ma[0]
            d = "BULLISH" if latest.get("type") == "golden_cross" or latest.get("signal") == "BUY" else "BEARISH"
            directions.append(d)
            pts = WEIGHT_MA
            sources.append({
                "name": "ma_crossover",
                "direction": d,
                "detail": f"{latest.get('type')} {latest.get('timeframe')} @ {latest.get('price')}",
                "weight": pts,
            })
            score += pts
        elif ma_events:
            latest = ma_events[0]
            d = _dir_from_text(latest.get("direction"), latest.get("type")) or "MIXED"
            if d != "MIXED":
                directions.append(d)
            pts = WEIGHT_MA * 0.4
            sources.append({
                "name": "ma_nearing",
                "direction": d,
                "detail": f"nearing {latest.get('direction') or latest.get('type')} {latest.get('timeframe')}",
                "weight": pts,
            })
            score += pts

        # Radar
        if radar_row:
            lis = float(radar_row.get("lis") or 0)
            sig = radar_row.get("signal") or {}
            if isinstance(sig, dict):
                sig_label = sig.get("signal") or sig.get("label") or ""
            else:
                sig_label = str(sig)
            d = _dir_from_text(sig_label, radar_row.get("type"))
            # CE-heavy bullish default for accumulation signals
            if not d and radar_row.get("type") == "CE":
                d = "BULLISH"
            elif not d and radar_row.get("type") == "PE":
                d = "BEARISH"
            if d:
                directions.append(d)
            pts = WEIGHT_RADAR * min(lis / 100.0, 1.0)
            sources.append({
                "name": "radar",
                "direction": d or "NEUTRAL",
                "detail": f"LIS {lis:.0f} {radar_row.get('strike')}{radar_row.get('type')} {sig_label}",
                "weight": round(pts, 1),
                "lis": lis,
            })
            score += pts

        # Intelligence (index / stock state)
        if intel:
            state = intel.get("state")
            tradable = bool(intel.get("tradable"))
            adj = (intel.get("adjustment") or {})
            setup = adj.get("trade_setup") or {}
            d = _dir_from_text(
                state,
                setup.get("action"),
                setup.get("bias"),
                (intel.get("strike_guidance") or {}).get("bias"),
            )
            if state in (MarketState.NO_TRADE.value,):
                d = None
            if d:
                directions.append(d)
            conf = float(intel.get("confidence") or 0) / 100.0
            pts = WEIGHT_INTEL * conf * (1.0 if tradable or adj.get("detected") else 0.5)
            if pts > 0 and (tradable or adj.get("detected") or state in (
                MarketState.TREND.value, MarketState.INTENT.value, MarketState.ADJUSTMENT.value
            )):
                sources.append({
                    "name": "intelligence",
                    "direction": d or state or "NEUTRAL",
                    "detail": intel.get("message") or state,
                    "weight": round(pts, 1),
                })
                score += pts

        # Bus residual (other strategies)
        if bus_events:
            latest = bus_events[0]
            d = _dir_from_text(latest.get("message"), latest.get("type"))
            if d:
                directions.append(d)
            pts = WEIGHT_BUS
            sources.append({
                "name": latest.get("source") or "signal_bus",
                "direction": d or "NEUTRAL",
                "detail": latest.get("message"),
                "weight": pts,
            })
            score += pts

        # News bias — soft weight, never sole actionable source
        if news and news.get("available") and news.get("bias") in ("BULLISH", "BEARISH"):
            d = news["bias"]
            directions.append(d)
            conf = abs(float(news.get("score") or 50) - 50) / 50.0  # 0..1 extremity
            pts = WEIGHT_NEWS * max(conf, 0.3)
            sources.append({
                "name": "news",
                "direction": d,
                "detail": (news.get("summary") or "")[:120],
                "weight": round(pts, 1),
            })
            score += pts

        # Aggregate direction
        bulls = directions.count("BULLISH")
        bears = directions.count("BEARISH")
        if bulls > bears:
            direction = "BULLISH"
        elif bears > bulls:
            direction = "BEARISH"
        elif bulls and bears:
            direction = "CONFLICT"
        else:
            direction = "NEUTRAL"

        # Unique source labels for UI keys / display (preserve order)
        source_names: List[str] = []
        for s in sources:
            name = s.get("name") or "unknown"
            if name not in source_names:
                source_names.append(name)
        # News alone does not count toward min_sources gate
        hard_sources = [s for s in sources if s["name"] != "news"]
        sources_count = len(hard_sources) if hard_sources else len(sources)
        total_sources = len(sources)

        # Status — require hard (non-news) sources for ACTIONABLE
        hard_count = len(hard_sources)
        if direction == "CONFLICT":
            status = "CONFLICT"
            score *= 0.4
        elif hard_count >= min_sources and direction in ("BULLISH", "BEARISH") and score >= 40:
            status = "ACTIONABLE"
        elif total_sources >= 1 and direction in ("BULLISH", "BEARISH"):
            status = "WATCH"
        elif total_sources > 0:
            status = "WATCH"
        else:
            status = "IDLE"

        return {
            "symbol": symbol,
            "name": symbol.replace("NSE:", "").replace("-EQ", "").replace("-INDEX", ""),
            "direction": direction,
            "status": status,
            "score": round(min(score, 100), 1),
            "sources_count": hard_count if hard_sources else total_sources,
            "source_names": source_names,
            "sources": sources,
            "tradeable": status == "ACTIONABLE",
        }

    def _market_bias(
        self,
        cards: List[Dict],
        nifty_intel: Optional[Dict],
        news: Optional[Dict] = None,
    ) -> str:
        if nifty_intel:
            d = _dir_from_text(nifty_intel.get("state"), nifty_intel.get("message"))
            if d in ("BULLISH", "BEARISH"):
                return d
        actionable = [c for c in cards if c["status"] == "ACTIONABLE"]
        if actionable:
            bulls = sum(1 for c in actionable if c["direction"] == "BULLISH")
            bears = sum(1 for c in actionable if c["direction"] == "BEARISH")
            if bulls > bears:
                return "BULLISH"
            if bears > bulls:
                return "BEARISH"
        if news and news.get("bias") in ("BULLISH", "BEARISH"):
            return news["bias"]
        return "NEUTRAL"


_engine: Optional[ConfluenceEngine] = None


def get_confluence_engine() -> ConfluenceEngine:
    global _engine
    if _engine is None:
        _engine = ConfluenceEngine()
    return _engine
