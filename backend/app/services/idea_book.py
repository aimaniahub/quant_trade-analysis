"""
Active Idea book.

Holds per-symbol snapshot rings and locked process trades.
Refresh spam cannot mint persistence. Ideas stay locked until invalidated.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

from app.services.execution import plan_execution
from app.services.idea_engine import (
    EXIT_COMPOSITE,
    FlowSnapshot,
    SNAPSHOT_MIN_GAP_SECONDS,
    SNAPSHOT_N,
    evaluate_candidate,
    lifecycle_action,
    parse_ts,
)
from app.utils.market_hours import IST

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_OUTCOME_PATH = os.path.normpath(os.path.join(_DATA_DIR, "idea_outcomes.jsonl"))

MAX_RING = 24


def _iso(ts: Optional[float] = None) -> str:
    if ts is None:
        return datetime.now(IST).isoformat()
    return datetime.fromtimestamp(ts, tz=IST).isoformat()


class IdeaBook:
    def __init__(self, hydrate: bool = True, persist: bool = True) -> None:
        self._lock = threading.RLock()
        self._rings: Dict[str, Deque[FlowSnapshot]] = {}
        self._ideas: Dict[str, Dict[str, Any]] = {}
        self._persist_enabled = persist
        if hydrate:
            self._hydrate_redis()

    # ── snapshot ring ────────────────────────────────────────────

    def _ring(self, symbol: str) -> Deque[FlowSnapshot]:
        if symbol not in self._rings:
            self._rings[symbol] = deque(maxlen=MAX_RING)
        return self._rings[symbol]

    def push_snapshot(self, snap: FlowSnapshot) -> FlowSnapshot:
        """
        Down-sample: if last snapshot is < 45s old, mutate it in place.
        Persistence counts *time*, not refresh clicks.
        """
        with self._lock:
            ring = self._ring(snap.symbol)
            if ring:
                last = ring[-1]
                if snap.ts - last.ts < SNAPSHOT_MIN_GAP_SECONDS:
                    # Same-direction refresh updates numbers; opposite flicker is ignored.
                    if snap.direction == last.direction or last.direction == "NEUTRAL":
                        keep_ts = last.ts
                        snap.ts = keep_ts
                        ring[-1] = snap
                        return snap
                    return last
            ring.append(snap)
            return snap

    # ── ingest ───────────────────────────────────────────────────

    def ingest(
        self,
        snap: FlowSnapshot,
        full_map: Dict[str, Any],
        candles_5m: Optional[List[Dict[str, Any]]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = now or datetime.now(IST)
        snap = self.push_snapshot(snap)
        with self._lock:
            ring = list(self._ring(snap.symbol))
            ev = evaluate_candidate(snap=snap, snapshots=ring, full_map=full_map, now=now)
            prev = self._ideas.get(snap.symbol)
            transition = "snapshot"
            idea = prev

            if prev and prev.get("status") == "ACTIVE":
                # Refresh cluster health on the remembered plan (entry/stop/T stay locked).
                ev["execution"] = plan_execution(
                    direction=str(prev.get("direction") or snap.direction),
                    spot=snap.spot,
                    day=full_map.get("day") or prev.get("day") or {},
                    session=full_map.get("session") or prev.get("session") or {},
                    structure=full_map.get("structure") or prev.get("structure") or {},
                    chain=full_map.get("chain") or [],
                    locked=True,
                    prior=prev.get("execution") or prev,
                    allowed_side=None,
                )
                life = lifecycle_action(
                    idea=prev, snap=snap, evald=ev, candles_5m=candles_5m
                )
                if life["action"] == "KILL":
                    idea = self._kill(
                        prev, snap, ev, life["reason"] or "INVALIDATED", now,
                        frame=life.get("frame"),
                    )
                    transition = "invalidated"
                elif life["action"] == "DOWNGRADE":
                    idea = self._downgrade(
                        prev, snap, ev, life["reason"] or "1H_STRUCTURE_BREAK", now,
                        frame=life.get("frame") or "H1",
                    )
                    transition = "downgraded"
                else:
                    idea = self._hold(prev, snap, ev, now)
                    transition = "held"
            elif ev["can_promote"]:
                idea = self._promote(snap, ev, full_map, now)
                transition = "promoted"
            else:
                idea = self._watch(snap, ev, full_map, now, prev)
                transition = "watch"

            self._ideas[snap.symbol] = idea
            self._persist_redis()
            return {
                "transition": transition,
                "idea": idea,
                "eval": ev,
            }

    def ingest_neutral(self, symbol: str, spot: float, now: Optional[datetime] = None) -> None:
        """Decay persistence when a scan finds no directional fuel."""
        now = now or datetime.now(IST)
        snap = FlowSnapshot(
            ts=now.timestamp(),
            symbol=symbol,
            direction="NEUTRAL",
            strike=0.0,
            opt_type="",
            label="Neutral/Inconclusive",
            signal="NEUTRAL",
            lis=0.0,
            grade="C",
            composite_raw=0.0,
            unusual_score=0.0,
            atm_dist_pct=0.0,
            delta=0.0,
            dte=None,
            opposing=False,
            spot=spot,
            oi_change_pct=0.0,
            vol_spike_ratio=0.0,
            premium_notional=0.0,
        )
        self.push_snapshot(snap)
        with self._lock:
            idea = self._ideas.get(symbol)
            if idea and idea.get("status") == "ACTIVE":
                # Neutral tape does not instantly kill. Decay composite softly.
                idea["composite"] = round(float(idea.get("composite") or 0) * 0.90, 1)
                idea["last_snapshot_at"] = _iso(now.timestamp())
                comp = float(idea["composite"])
                if comp <= EXIT_COMPOSITE:
                    ev = {
                        "composite": comp,
                        "persist": {"score": 0, "same": 0, "flips": 0},
                        "location": {},
                        "futures": {},
                        "levels": {},
                        "recipe": idea.get("recipe") or {},
                        "prominence": 0,
                        "dual_side": False,
                    }
                    self._ideas[symbol] = self._kill(idea, snap, ev, "COMPOSITE_DECAY", now, frame="FLOW")
            self._persist_redis()

    # ── state transitions ────────────────────────────────────────

    def _promote(
        self,
        snap: FlowSnapshot,
        ev: Dict[str, Any],
        full_map: Dict[str, Any],
        now: datetime,
    ) -> Dict[str, Any]:
        levels = ev.get("levels") or {}
        loc = ev.get("location") or {}
        recipe = ev.get("recipe") or {}
        ex = ev.get("execution") or {}
        thesis = self._thesis(snap, loc, recipe, ev.get("futures") or {}, ev.get("vwap") or {})
        idea = {
            "status": "ACTIVE",
            "symbol": snap.symbol,
            "name": snap.symbol.split(":")[-1].replace("-EQ", "").replace("-INDEX", ""),
            "direction": snap.direction,
            "side": "LONG" if snap.direction == "BULLISH" else "SHORT",
            "strike": snap.strike,
            "opt_type": snap.opt_type,
            "label": snap.label,
            "signal": snap.signal,
            "grade": snap.grade,
            "lis": snap.lis,
            "spot": snap.spot,
            "spot_at_open": snap.spot,
            "locked_at": _iso(now.timestamp()),
            "locked_ts": now.timestamp(),
            "last_snapshot_at": _iso(now.timestamp()),
            "updated_at": _iso(now.timestamp()),
            "hold_seconds": 0,
            "instrument_hint": None,
            "recipe": recipe,
            "thesis": thesis,
            "location_score": loc.get("score"),
            "location_tags": loc.get("tags") or [],
            "pivot_side": loc.get("pivot_side"),
            "camarilla_regime": loc.get("camarilla_regime"),
            "wall_side": loc.get("wall_side"),
            "zone": loc.get("zone"),
            "persist": ev.get("persist"),
            "composite": ev.get("composite"),
            "prominence": ev.get("prominence"),
            "futures": ev.get("futures"),
            "invalidation": ex.get("invalidation") if ex.get("invalidation") is not None else levels.get("invalidation"),
            "stop": ex.get("stop") if ex.get("stop") is not None else levels.get("stop"),
            "target": ex.get("target") if ex.get("target") is not None else levels.get("target"),
            "target_2": ex.get("target_2") if ex.get("target_2") is not None else levels.get("target_2"),
            "target_label": ex.get("target_label") or levels.get("target_label"),
            "target_2_label": ex.get("target_2_label") or levels.get("target_2_label"),
            "entry": ex.get("entry") if ex.get("entry") is not None else levels.get("entry"),
            "entry_label": ex.get("entry_label") or levels.get("entry_label"),
            "risk_pts": levels.get("risk_pts"),
            "execution": ex,
            "tag_roles": ev.get("tag_roles"),
            "trade_opt_type": (ex.get("instrument") or {}).get("opt_type"),
            "trade_strike": (ex.get("instrument") or {}).get("strike"),
            "exec_action": ex.get("action"),
            "reward_risk": ex.get("reward_risk"),
            **self._cluster_fields(ex),
            "vetoes": [],
            "structure": {
                "put_wall": (full_map.get("structure") or {}).get("put_wall"),
                "call_wall": (full_map.get("structure") or {}).get("call_wall"),
                "max_pain": (full_map.get("structure") or {}).get("max_pain"),
                "pcr_regime": (full_map.get("structure") or {}).get("pcr_regime"),
                "gamma_wall": (full_map.get("structure") or {}).get("gamma_wall"),
            },
            "day": {
                "pdh": (full_map.get("day") or {}).get("pdh"),
                "pdl": (full_map.get("day") or {}).get("pdl"),
                "p": ((full_map.get("day") or {}).get("pivots") or {}).get("P"),
                "s1": ((full_map.get("day") or {}).get("pivots") or {}).get("S1"),
                "r1": ((full_map.get("day") or {}).get("pivots") or {}).get("R1"),
                "atr": (full_map.get("day") or {}).get("atr"),
                "daily_bias": (full_map.get("day") or {}).get("daily_bias"),
                "cpr": (full_map.get("day") or {}).get("cpr"),
                "camarilla": {
                    "S3": ((full_map.get("day") or {}).get("camarilla") or {}).get("S3"),
                    "R3": ((full_map.get("day") or {}).get("camarilla") or {}).get("R3"),
                    "S4": ((full_map.get("day") or {}).get("camarilla") or {}).get("S4"),
                    "R4": ((full_map.get("day") or {}).get("camarilla") or {}).get("R4"),
                },
            },
            "session": {
                "vwap": (full_map.get("session") or {}).get("vwap"),
                "orh": (full_map.get("session") or {}).get("orh"),
                "orl": (full_map.get("session") or {}).get("orl"),
                "vwap_side": (full_map.get("session") or {}).get("vwap_side"),
            },
            "vwap_agree": bool((ev.get("vwap") or {}).get("agree")),
            "vwap_side": (ev.get("vwap") or {}).get("side"),
            "vwap_dev_pct": (ev.get("vwap") or {}).get("dev_pct"),
            "kill_reason": None,
            "kill_frame": None,
            **self._mtf_fields(ev),
        }
        self._log_event("PROMOTE", idea, snap)
        return idea

    def _hold(
        self,
        prev: Dict[str, Any],
        snap: FlowSnapshot,
        ev: Dict[str, Any],
        now: datetime,
    ) -> Dict[str, Any]:
        idea = dict(prev)
        idea["last_snapshot_at"] = _iso(now.timestamp())
        idea["updated_at"] = _iso(now.timestamp())
        idea["hold_seconds"] = int(now.timestamp() - float(prev.get("locked_ts") or now.timestamp()))
        idea["spot"] = snap.spot
        idea["lis"] = snap.lis
        idea["grade"] = snap.grade
        idea["composite"] = ev.get("composite")
        idea["prominence"] = ev.get("prominence")
        idea["persist"] = ev.get("persist")
        idea["location_score"] = (ev.get("location") or {}).get("score")
        idea["location_tags"] = (ev.get("location") or {}).get("tags") or idea.get("location_tags")
        idea["futures"] = ev.get("futures")
        idea.update(self._mtf_fields(ev))
        # Refresh action / cluster health only — entry/stop/targets stay locked
        locked_plan = ev.get("execution") or {}
        prior_ex = prev.get("execution") or {}
        if locked_plan.get("entry") or prior_ex.get("entry"):
            idea["execution"] = locked_plan or prior_ex
            idea["exec_action"] = idea["execution"].get("action")
            idea["reward_risk"] = idea["execution"].get("reward_risk")
            idea["trade_opt_type"] = (idea["execution"].get("instrument") or {}).get("opt_type")
            idea["trade_strike"] = (idea["execution"].get("instrument") or {}).get("strike")
            idea.update(self._cluster_fields(idea["execution"]))
        elif locked_plan:
            idea["execution"] = locked_plan
            idea["exec_action"] = locked_plan.get("action")
            idea["reward_risk"] = locked_plan.get("reward_risk")
            idea.update(self._cluster_fields(locked_plan))
        if ev.get("tag_roles"):
            idea["tag_roles"] = ev.get("tag_roles")
        # Quiet instrument update — same thesis, nearby strike
        step = float(ev.get("step") or 10)
        if (
            snap.direction == idea.get("direction")
            and snap.strike
            and abs(float(snap.strike) - float(idea.get("strike") or 0)) > 1e-6
        ):
            if abs(float(snap.strike) - float(idea.get("strike") or 0)) <= step * 2:
                idea["instrument_hint"] = {
                    "strike": snap.strike,
                    "opt_type": snap.opt_type,
                    "label": snap.label,
                }
                # Adopt if same family and better LIS
                if snap.lis >= float(idea.get("lis") or 0):
                    idea["strike"] = snap.strike
                    idea["opt_type"] = snap.opt_type
                    idea["label"] = snap.label
                    idea["instrument_hint"] = None
        return idea

    def _watch(
        self,
        snap: FlowSnapshot,
        ev: Dict[str, Any],
        full_map: Dict[str, Any],
        now: datetime,
        prev: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        status = "CONFLICT" if ev.get("dual_side") else "WATCH"
        if snap.direction not in ("BULLISH", "BEARISH"):
            status = "IDLE"
        loc = ev.get("location") or {}
        levels = ev.get("levels") or {}
        recipe = ev.get("recipe") or {}
        ex = ev.get("execution") or {}
        return {
            "status": status,
            "symbol": snap.symbol,
            "name": snap.symbol.split(":")[-1].replace("-EQ", "").replace("-INDEX", ""),
            "direction": snap.direction,
            "side": (
                "LONG" if snap.direction == "BULLISH"
                else "SHORT" if snap.direction == "BEARISH"
                else "FLAT"
            ),
            "strike": snap.strike,
            "opt_type": snap.opt_type,
            "label": snap.label,
            "signal": snap.signal,
            "grade": snap.grade,
            "lis": snap.lis,
            "spot": snap.spot,
            "locked_at": None,
            "locked_ts": None,
            "last_snapshot_at": _iso(now.timestamp()),
            "updated_at": _iso(now.timestamp()),
            "hold_seconds": 0,
            "recipe": recipe,
            "thesis": self._thesis(snap, loc, recipe, ev.get("futures") or {}, ev.get("vwap") or {}),
            "location_score": loc.get("score"),
            "location_tags": loc.get("tags") or [],
            "pivot_side": loc.get("pivot_side"),
            "camarilla_regime": loc.get("camarilla_regime"),
            "wall_side": loc.get("wall_side"),
            "zone": loc.get("zone"),
            "persist": ev.get("persist"),
            "composite": ev.get("composite"),
            "prominence": ev.get("prominence"),
            "futures": ev.get("futures"),
            "invalidation": ex.get("invalidation") if ex.get("invalidation") is not None else levels.get("invalidation"),
            "stop": ex.get("stop") if ex.get("stop") is not None else levels.get("stop"),
            "target": ex.get("target") if ex.get("target") is not None else levels.get("target"),
            "target_2": ex.get("target_2") if ex.get("target_2") is not None else levels.get("target_2"),
            "target_label": ex.get("target_label") or levels.get("target_label"),
            "target_2_label": ex.get("target_2_label") or levels.get("target_2_label"),
            "entry": ex.get("entry") if ex.get("entry") is not None else levels.get("entry"),
            "entry_label": ex.get("entry_label") or levels.get("entry_label"),
            "risk_pts": levels.get("risk_pts"),
            "execution": ex,
            "tag_roles": ev.get("tag_roles"),
            "trade_opt_type": (ex.get("instrument") or {}).get("opt_type"),
            "trade_strike": (ex.get("instrument") or {}).get("strike"),
            "exec_action": ex.get("action"),
            "reward_risk": ex.get("reward_risk"),
            **self._cluster_fields(ex),
            "vetoes": ev.get("vetoes") or [],
            "structure": {
                "put_wall": (full_map.get("structure") or {}).get("put_wall"),
                "call_wall": (full_map.get("structure") or {}).get("call_wall"),
                "max_pain": (full_map.get("structure") or {}).get("max_pain"),
                "pcr_regime": (full_map.get("structure") or {}).get("pcr_regime"),
            },
            "day": {
                "pdh": (full_map.get("day") or {}).get("pdh"),
                "pdl": (full_map.get("day") or {}).get("pdl"),
                "p": ((full_map.get("day") or {}).get("pivots") or {}).get("P"),
                "atr": (full_map.get("day") or {}).get("atr"),
                "daily_bias": (full_map.get("day") or {}).get("daily_bias"),
            },
            "session": {
                "vwap": (full_map.get("session") or {}).get("vwap"),
                "vwap_side": (full_map.get("session") or {}).get("vwap_side"),
            },
            "vwap_agree": bool((ev.get("vwap") or {}).get("agree")),
            "vwap_side": (ev.get("vwap") or {}).get("side"),
            "vwap_dev_pct": (ev.get("vwap") or {}).get("dev_pct"),
            "kill_reason": None,
            "kill_frame": None,
            "prev_status": (prev or {}).get("status"),
            **self._mtf_fields(ev),
        }

    def _kill(
        self,
        prev: Dict[str, Any],
        snap: FlowSnapshot,
        ev: Dict[str, Any],
        reason: str,
        now: datetime,
        frame: Optional[str] = None,
    ) -> Dict[str, Any]:
        idea = dict(prev)
        idea["status"] = "DEAD"
        idea["kill_reason"] = reason
        idea["kill_frame"] = frame or "FLOW"
        idea["killed_at"] = _iso(now.timestamp())
        idea["updated_at"] = _iso(now.timestamp())
        idea["hold_seconds"] = int(now.timestamp() - float(prev.get("locked_ts") or now.timestamp()))
        idea["spot_at_kill"] = snap.spot
        idea["composite"] = ev.get("composite")
        idea.update(self._mtf_fields(ev))
        self._log_event("KILL", idea, snap)
        return idea

    def _downgrade(
        self,
        prev: Dict[str, Any],
        snap: FlowSnapshot,
        ev: Dict[str, Any],
        reason: str,
        now: datetime,
        frame: str = "H1",
    ) -> Dict[str, Any]:
        idea = dict(prev)
        idea["status"] = "WATCH"
        idea["campaign"] = "WATCH"
        idea["kill_reason"] = None
        idea["downgrade_reason"] = reason
        idea["downgrade_frame"] = frame
        idea["downgraded_at"] = _iso(now.timestamp())
        idea["locked_at"] = None
        idea["locked_ts"] = None
        idea["updated_at"] = _iso(now.timestamp())
        idea["hold_seconds"] = int(now.timestamp() - float(prev.get("locked_ts") or now.timestamp()))
        idea.update(self._mtf_fields(ev))
        self._log_event("DOWNGRADE", idea, snap)
        return idea

    @staticmethod
    def _cluster_fields(ex: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        ex = ex or {}
        plan = ex.get("cluster_plan") or {}
        return {
            "entry_zone": ex.get("entry_zone") or plan.get("entry_zone"),
            "cluster_plan": plan or None,
            "cluster_health": ex.get("cluster_health") or plan.get("cluster_health"),
            "exit_warnings": ex.get("exit_warnings") or plan.get("exit_warnings") or [],
            "entry_quality": ex.get("entry_quality") or plan.get("entry_quality"),
            "locked_cluster": ex.get("locked_cluster") or plan.get("supporting_cluster"),
        }

    @staticmethod
    def _mtf_fields(ev: Dict[str, Any]) -> Dict[str, Any]:
        mtf = ev.get("mtf") or {}
        if not mtf and not ev.get("vwap_oc_ready"):
            return {}
        hq = bool(mtf.get("hq_pullback"))
        campaign = mtf.get("campaign")
        # VWAP + option fuel is a confirmed process trade, not a 4H-mixed sit-out.
        if ev.get("vwap_oc_ready") and not hq:
            campaign = "CONFIRMED"
        packed_mtf = dict(mtf) if mtf else {}
        if packed_mtf:
            packed_mtf = {
                "daily_bias": mtf.get("daily_bias"),
                "h4_bias": mtf.get("h4_bias"),
                "h1_bias": mtf.get("h1_bias"),
                "m15_bias": mtf.get("m15_bias"),
                "align_score": mtf.get("align_score"),
                "align_label": mtf.get("align_label"),
                "allowed_side": mtf.get("allowed_side"),
                "campaign": campaign,
                "hq_pullback": hq,
                "turning": mtf.get("turning"),
                "m15_trigger": mtf.get("m15_trigger"),
                "momentum_now": mtf.get("momentum_now"),
                "daily_veto": mtf.get("daily_veto"),
                "h1_structure": mtf.get("h1_structure"),
                "h4_structure": mtf.get("h4_structure"),
            }
        return {
            "mtf": packed_mtf or None,
            "campaign": campaign,
            "hq_pullback": hq,
            "align_score": mtf.get("align_score"),
            "align_label": mtf.get("align_label"),
            "allowed_side": mtf.get("allowed_side"),
        }

    @staticmethod
    def _thesis(
        snap: FlowSnapshot,
        loc: Dict[str, Any],
        recipe: Dict[str, Any],
        futures: Dict[str, Any],
        vwap: Optional[Dict[str, Any]] = None,
    ) -> str:
        side = "Long" if snap.direction == "BULLISH" else "Short" if snap.direction == "BEARISH" else "Flat"
        bits = [f"{side} process"]
        vw = vwap or {}
        if vw.get("agree"):
            bits.append(f"VWAP {vw.get('side') or 'ok'}")
        elif vw.get("ok") and not vw.get("agree"):
            bits.append("against VWAP")
        if recipe.get("name") and recipe.get("id") != "NONE":
            bits.append(recipe["name"])
        tags = loc.get("tags") or []
        if tags:
            bits.append(", ".join(tags[:3]))
        if snap.label:
            bits.append(snap.label)
        if futures.get("label") and futures.get("state") not in (None, "UNKNOWN", "CHURN"):
            bits.append(str(futures["label"]))
        return " · ".join(bits)

    # ── queries ──────────────────────────────────────────────────

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            idea = self._ideas.get(symbol)
            return dict(idea) if idea else None

    def board(self, limit: int = 8) -> Dict[str, Any]:
        with self._lock:
            ideas = [dict(v) for v in self._ideas.values()]
        active = [i for i in ideas if i.get("status") == "ACTIVE"]
        pullbacks = [i for i in active if i.get("hq_pullback")]
        confirmed = [i for i in active if not i.get("hq_pullback")]
        watch = [i for i in ideas if i.get("status") == "WATCH"]
        conflict = [i for i in ideas if i.get("status") == "CONFLICT"]

        def _rank(row: Dict[str, Any]) -> float:
            return float(row.get("prominence") or row.get("composite") or 0)

        def _is_bull(row: Dict[str, Any]) -> bool:
            d = str(row.get("direction") or row.get("side") or "").upper()
            return d in ("BULLISH", "LONG")

        def _is_bear(row: Dict[str, Any]) -> bool:
            d = str(row.get("direction") or row.get("side") or "").upper()
            return d in ("BEARISH", "SHORT")

        confirmed.sort(key=_rank, reverse=True)
        pullbacks.sort(key=_rank, reverse=True)
        watch.sort(key=_rank, reverse=True)
        conflict.sort(key=_rank, reverse=True)
        bullish = [i for i in confirmed if _is_bull(i)]
        bearish = [i for i in confirmed if _is_bear(i)]
        top_n = 3
        headline = bullish[:top_n] + bearish[:top_n] + pullbacks[:top_n]
        return {
            "active": headline[: max(limit, 9)],
            "confirmed": confirmed[:limit],
            "bullish": bullish[:top_n],
            "bearish": bearish[:top_n],
            "pullbacks": pullbacks[:top_n],
            "watch": watch[:top_n],
            "conflict": conflict[:top_n],
            "ideas_bullish": bullish[:top_n],
            "ideas_bearish": bearish[:top_n],
            "counts": {
                "active": len(active),
                "confirmed": len(confirmed),
                "bullish": len(bullish),
                "bearish": len(bearish),
                "pullbacks": len(pullbacks),
                "watch": len(watch),
                "conflict": len(conflict),
                "tracked": len(ideas),
            },
        }

    def attach_to_contract(self, symbol: str, contract: Dict[str, Any]) -> Dict[str, Any]:
        idea = self.get(symbol)
        if not idea:
            return contract
        contract["idea_status"] = idea.get("status")
        contract["idea"] = {
            "status": idea.get("status"),
            "direction": idea.get("direction"),
            "side": idea.get("side"),
            "locked_at": idea.get("locked_at"),
            "hold_seconds": idea.get("hold_seconds"),
            "thesis": idea.get("thesis"),
            "recipe": idea.get("recipe"),
            "location_score": idea.get("location_score"),
            "location_tags": idea.get("location_tags"),
            "composite": idea.get("composite"),
            "prominence": idea.get("prominence"),
            "invalidation": idea.get("invalidation"),
            "stop": idea.get("stop"),
            "target": idea.get("target"),
            "target_2": idea.get("target_2"),
            "target_label": idea.get("target_label"),
            "target_2_label": idea.get("target_2_label"),
            "entry": idea.get("entry"),
            "entry_label": idea.get("entry_label"),
            "execution": idea.get("execution"),
            "tag_roles": idea.get("tag_roles"),
            "trade_opt_type": idea.get("trade_opt_type"),
            "trade_strike": idea.get("trade_strike"),
            "exec_action": idea.get("exec_action"),
            "reward_risk": idea.get("reward_risk"),
            "vetoes": idea.get("vetoes"),
            "persist": idea.get("persist"),
            "futures": idea.get("futures"),
            "zone": idea.get("zone"),
            "pivot_side": idea.get("pivot_side"),
            "camarilla_regime": idea.get("camarilla_regime"),
            "wall_side": idea.get("wall_side"),
            "instrument_hint": idea.get("instrument_hint"),
            "kill_reason": idea.get("kill_reason"),
            "kill_frame": idea.get("kill_frame"),
            "downgrade_reason": idea.get("downgrade_reason"),
            "downgrade_frame": idea.get("downgrade_frame"),
            "structure": idea.get("structure"),
            "day": idea.get("day"),
            "session": idea.get("session"),
            "mtf": idea.get("mtf"),
            "campaign": idea.get("campaign"),
            "hq_pullback": idea.get("hq_pullback"),
            "vwap_agree": idea.get("vwap_agree"),
            "vwap_side": idea.get("vwap_side"),
            "vwap_dev_pct": idea.get("vwap_dev_pct"),
            "align_score": idea.get("align_score"),
            "align_label": idea.get("align_label"),
            "allowed_side": idea.get("allowed_side"),
            "entry_zone": idea.get("entry_zone"),
            "cluster_plan": idea.get("cluster_plan"),
            "cluster_health": idea.get("cluster_health"),
            "exit_warnings": idea.get("exit_warnings"),
            "entry_quality": idea.get("entry_quality"),
            "locked_cluster": idea.get("locked_cluster"),
        }
        # Locked idea owns the headline direction
        if idea.get("status") == "ACTIVE":
            contract["process_locked"] = True
            contract["process_direction"] = idea.get("direction")
        else:
            contract["process_locked"] = False
        return contract

    # ── outcome log ──────────────────────────────────────────────

    def _log_event(self, event: str, idea: Dict[str, Any], snap: FlowSnapshot) -> None:
        rec = {
            "event": event,
            "at": _iso(),
            "symbol": idea.get("symbol"),
            "direction": idea.get("direction"),
            "strike": idea.get("strike"),
            "opt_type": idea.get("opt_type"),
            "status": idea.get("status"),
            "recipe": (idea.get("recipe") or {}).get("id"),
            "location_score": idea.get("location_score"),
            "composite": idea.get("composite"),
            "lis": idea.get("lis"),
            "spot_at_open": idea.get("spot_at_open"),
            "spot": snap.spot,
            "invalidation": idea.get("invalidation"),
            "target": idea.get("target"),
            "kill_reason": idea.get("kill_reason"),
            "kill_frame": idea.get("kill_frame"),
            "downgrade_reason": idea.get("downgrade_reason"),
            "downgrade_frame": idea.get("downgrade_frame"),
            "align_score": idea.get("align_score"),
            "align_label": idea.get("align_label"),
            "campaign": idea.get("campaign"),
            "hq_pullback": idea.get("hq_pullback"),
            "hold_seconds": idea.get("hold_seconds"),
            "thesis": idea.get("thesis"),
        }
        try:
            os.makedirs(os.path.dirname(_OUTCOME_PATH), exist_ok=True)
            with open(_OUTCOME_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
        except Exception as exc:
            logger.debug("idea outcome log failed: %s", exc)

    # ── redis ────────────────────────────────────────────────────

    def _persist_redis(self) -> None:
        if not self._persist_enabled:
            return
        try:
            from app.services import redis_client as rc

            if not rc.is_available():
                return
            payload = {
                "ideas": self._ideas,
                "rings": {
                    k: [s.to_dict() for s in list(v)[-SNAPSHOT_N:]]
                    for k, v in self._rings.items()
                },
            }
            rc.set_json(rc.key("radar", "idea_book"), payload, ttl=8 * 3600)
        except Exception:
            pass

    def _hydrate_redis(self) -> None:
        try:
            from app.services import redis_client as rc

            if not rc.is_available():
                return
            raw = rc.get_json(rc.key("radar", "idea_book"))
            if not raw or not isinstance(raw, dict):
                return
            ideas = raw.get("ideas") or {}
            if isinstance(ideas, dict):
                self._ideas = ideas
            rings = raw.get("rings") or {}
            for sym, rows in rings.items():
                dq: Deque[FlowSnapshot] = deque(maxlen=MAX_RING)
                for r in rows or []:
                    try:
                        dq.append(FlowSnapshot(**{
                            k: r.get(k) for k in FlowSnapshot.__dataclass_fields__
                        }))
                    except Exception:
                        continue
                self._rings[sym] = dq
        except Exception:
            pass


_book: Optional[IdeaBook] = None


def get_idea_book() -> IdeaBook:
    global _book
    if _book is None:
        _book = IdeaBook()
    return _book


def snapshot_from_contract(row: Dict[str, Any], *, opposing: bool = False) -> FlowSnapshot:
    sig = row.get("signal") or {}
    if not isinstance(sig, dict):
        sig = {}
    gq = row.get("greek_quality") or {}
    expiry = row.get("expiry")
    dte = None
    if expiry:
        try:
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%Y%m%d"):
                try:
                    exp_dt = datetime.strptime(str(expiry)[:11].strip(), fmt)
                    dte = max((exp_dt.date() - datetime.now(IST).date()).days, 0)
                    break
                except ValueError:
                    continue
        except Exception:
            dte = None
    ltp = float(row.get("ltp") or 0)
    vol = float(row.get("volume") or 0)
    return FlowSnapshot(
        ts=parse_ts(row.get("timestamp")),
        symbol=str(row.get("symbol") or ""),
        direction=(row.get("direction") or sig.get("direction") or "NEUTRAL").upper(),
        strike=float(row.get("strike") or 0),
        opt_type=str(row.get("type") or ""),
        label=str(sig.get("label") or ""),
        signal=str(sig.get("signal") or ""),
        lis=float(row.get("lis") or 0),
        grade=str(row.get("grade") or "C"),
        composite_raw=float(row.get("composite_score") or 0),
        unusual_score=float(row.get("unusual_score") or 0),
        atm_dist_pct=float(row.get("atm_dist_pct") or 0),
        delta=float(gq.get("abs_delta") or row.get("delta") or 0),
        dte=dte,
        opposing=opposing,
        spot=float(row.get("spot") or 0),
        oi_change_pct=float(row.get("oi_change_pct") or 0),
        vol_spike_ratio=float(row.get("vol_spike_ratio") or 0),
        premium_notional=round(ltp * vol, 2),
    )
