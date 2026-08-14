"""
Process-trade engine — persistence, hysteresis, recipes, vetoes.

Scan every few seconds. Do not decide every few seconds.

Promotion requires:
  • same direction persisted on wall-clock time (not refresh spam)
  • location confluence at institutional levels
  • directional fuel (Fresh Buying / Writing), not exhaustion
  • no hard veto
  • composite >= ENTER, stay until composite <= EXIT or invalidation
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

import pytz

from app.services.levels import (
    invalidation_and_targets,
    score_location,
)
from app.services.execution import location_tags_for_role, plan_execution
from app.services.mtf_engine import frame_invalidation, mtf_rank
from app.utils.market_hours import IST

# Persistence
SNAPSHOT_N = 4
SNAPSHOT_K = 3
MIN_PERSIST_SECONDS = 180.0
SNAPSHOT_MIN_GAP_SECONDS = 45.0  # refresh spam updates last row, does not count

# Hysteresis
ENTER_COMPOSITE = 70.0
EXIT_COMPOSITE = 45.0
MIN_LOCATION_PROMOTE = 4.0
MIN_LOCATION_A_PLUS_FAST = 6.0  # A+ can promote on 2/3 if location is rich

# Fuel labels that can become a process trade
PROCESS_LABELS = {
    "Fresh Call Buying",
    "Fresh Put Buying",
    "Call Writing",
    "Put Writing",
}
EXHAUSTION_LABELS = {
    "Call Short Covering",
    "Call Long Unwinding",
    "Put Short Covering",
    "Put Long Unwinding",
}

STRONG_FLOW = {"STRONG_BULLISH", "STRONG_BEARISH", "BULLISH", "BEARISH"}


@dataclass
class FlowSnapshot:
    ts: float
    symbol: str
    direction: str
    strike: float
    opt_type: str
    label: str
    signal: str
    lis: float
    grade: str
    composite_raw: float
    unusual_score: float
    atm_dist_pct: float
    delta: float
    dte: Optional[float]
    opposing: bool
    spot: float
    oi_change_pct: float
    vol_spike_ratio: float
    premium_notional: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_ts(ts: Any) -> float:
    if ts is None:
        return datetime.now(IST).timestamp()
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        return dt.timestamp()
    except Exception:
        return datetime.now(IST).timestamp()


def now_ist() -> datetime:
    return datetime.now(IST)


def session_gate(now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Opening 15m: map only, no new lock.
    Last 15m: manage only, no new lock.
    """
    now = now or now_ist()
    if now.tzinfo is None:
        now = IST.localize(now)
    t = now.astimezone(IST).time()
    if t < time(9, 15) or t > time(15, 30):
        return {"allow_new": False, "reason": "MARKET_CLOSED", "window": "closed"}
    if t < time(9, 30):
        return {"allow_new": False, "reason": "OPENING_RANGE", "window": "open15"}
    if t >= time(15, 15):
        return {"allow_new": False, "reason": "LATE_SESSION", "window": "close15"}
    return {"allow_new": True, "reason": None, "window": "trade"}


def infer_strike_step(strike: float, spot: float) -> float:
    """NSE-like step from price level."""
    px = max(spot, strike, 1.0)
    if px >= 20000:
        return 100.0
    if px >= 5000:
        return 50.0
    if px >= 1000:
        return 20.0 if px < 2000 else 25.0
    if px >= 250:
        return 10.0
    if px >= 50:
        return 5.0
    return 2.5


def compute_persistence(
    snapshots: List[FlowSnapshot],
    direction: str,
    strike: float,
    step: float,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    d = (direction or "NEUTRAL").upper()
    now_ts = now_ts if now_ts is not None else datetime.now(IST).timestamp()
    if d not in ("BULLISH", "BEARISH"):
        return {
            "ready": False,
            "score": 0.0,
            "same": 0,
            "family": 0,
            "n": 0,
            "age_seconds": 0.0,
            "flips": 0,
        }
    recent = [s for s in snapshots[-SNAPSHOT_N:] if s.direction in ("BULLISH", "BEARISH", "NEUTRAL")]
    n = len(recent)
    same = sum(1 for s in recent if s.direction == d)
    family = sum(
        1
        for s in recent
        if s.direction == d and abs(float(s.strike) - float(strike)) <= step + 1e-6
    )
    flips = 0
    for i in range(1, len(recent)):
        a, b = recent[i - 1].direction, recent[i].direction
        if a in ("BULLISH", "BEARISH") and b in ("BULLISH", "BEARISH") and a != b:
            flips += 1
    first_same = next((s for s in recent if s.direction == d), None)
    age = (now_ts - first_same.ts) if first_same else 0.0
    score = same / float(SNAPSHOT_N)
    ready = same >= SNAPSHOT_K and age >= MIN_PERSIST_SECONDS and flips == 0
    # Fast path: 2 of last 3 + long enough + no flips (used only with rich location)
    fast = (
        n >= 3
        and same >= 2
        and age >= MIN_PERSIST_SECONDS
        and flips == 0
    )
    return {
        "ready": ready,
        "fast_ok": fast,
        "score": round(score, 3),
        "same": same,
        "family": family,
        "n": n,
        "age_seconds": round(age, 1),
        "flips": flips,
        "window": SNAPSHOT_N,
        "need": SNAPSHOT_K,
    }


def detect_dual_side(snapshots: List[FlowSnapshot], current_opposing: bool) -> bool:
    if current_opposing:
        return True
    recent = snapshots[-SNAPSHOT_N:]
    dirs = {s.direction for s in recent if s.lis >= 50 and s.direction in ("BULLISH", "BEARISH")}
    return len(dirs) >= 2


def classify_recipe(
    *,
    direction: str,
    location: Dict[str, Any],
    label: str,
    cam_regime: str,
) -> Dict[str, Any]:
    tags = set(location.get("tags") or [])
    d = (direction or "").upper()
    loc = float(location.get("score") or 0)

    def hit(*need: str) -> bool:
        return any(any(n in t for n in need) for t in tags)

    if d == "BULLISH" and "Put Writing" in (label or "") and (
        hit("PUT_WALL", "PIVOT_SUPPORT", "INST_ZONE")
    ):
        return {"id": "PUT_WALL_BOUNCE", "name": "Put-wall bounce", "ok": loc >= 4}
    if d == "BEARISH" and "Call Writing" in (label or "") and (
        hit("CALL_WALL", "PIVOT_RESIST", "INST_ZONE")
    ):
        return {"id": "CALL_WALL_REJECT", "name": "Call-wall reject", "ok": loc >= 4}
    if d == "BULLISH" and cam_regime == "TREND_UP" and hit("BREAK_HIGH", "VWAP_LONG"):
        return {"id": "PIVOT_BREAK_TREND", "name": "Break + flow fuel", "ok": loc >= 4}
    if d == "BEARISH" and cam_regime == "TREND_DN" and hit("BREAK_LOW", "VWAP_SHORT"):
        return {"id": "PIVOT_BREAK_TREND", "name": "Break + flow fuel", "ok": loc >= 4}
    if hit("VWAP_LONG", "VWAP_SHORT") and loc >= 4:
        return {"id": "VWAP_RECLAIM", "name": "VWAP reclaim / reject", "ok": True}
    if loc >= MIN_LOCATION_PROMOTE:
        return {"id": "LEVEL_CONFLUENCE", "name": "Level confluence", "ok": True}
    return {"id": "NONE", "name": "No process recipe", "ok": False}


def hard_vetoes(
    *,
    snap: FlowSnapshot,
    location: Dict[str, Any],
    day: Dict[str, Any],
    structure: Dict[str, Any],
    futures: Dict[str, Any],
    persist: Dict[str, Any],
    dual_side: bool,
    now: Optional[datetime] = None,
    for_new_lock: bool = True,
    mtf: Optional[Dict[str, Any]] = None,
) -> List[str]:
    vetoes: List[str] = []
    now = now or now_ist()
    gate = session_gate(now)
    if for_new_lock and not gate["allow_new"]:
        vetoes.append(gate["reason"] or "SESSION")

    if snap.direction not in ("BULLISH", "BEARISH"):
        vetoes.append("NO_DIRECTION")

    label = snap.label or ""
    if label in EXHAUSTION_LABELS:
        vetoes.append("EXHAUSTION_FUEL")
    if label and label not in PROCESS_LABELS and snap.signal not in STRONG_FLOW:
        if snap.signal in ("EXHAUSTION", "NEUTRAL", "ACCUMULATION"):
            vetoes.append("WEAK_FUEL")

    if snap.delta and abs(float(snap.delta)) < 0.20:
        vetoes.append("DELTA_TOO_LOW")
    if snap.atm_dist_pct and snap.atm_dist_pct > 7.0:
        vetoes.append("FAR_OTM")

    if dual_side:
        vetoes.append("DUAL_SIDE_FLOW")

    if location.get("htf_opposes"):
        vetoes.append("HTF_OPPOSE")

    # PCR regime vs direction (structural ceiling / floor)
    pcr_bias = (structure.get("pcr_bias") or "").upper()
    if snap.direction == "BULLISH" and pcr_bias == "BEARISH" and (structure.get("pcr") or 1) <= 0.70:
        vetoes.append("PCR_CEILING")
    if snap.direction == "BEARISH" and pcr_bias == "BULLISH" and (structure.get("pcr") or 1) >= 1.25:
        vetoes.append("PCR_FLOOR")

    # Futures opposite *buildup* (not covering)
    fut_state = (futures.get("state") or "").upper()
    if snap.direction == "BULLISH" and fut_state == "SHORT_BUILDUP":
        vetoes.append("FUTURES_SHORT_BUILDUP")
    if snap.direction == "BEARISH" and fut_state == "LONG_BUILDUP":
        vetoes.append("FUTURES_LONG_BUILDUP")

    # Expiry: new confirms banned at 0–2 DTE (strict). Pin is extra context.
    dte = snap.dte
    if for_new_lock and dte is not None and dte <= 2:
        vetoes.append("EXPIRY_DTE")
    cam = location.get("camarilla_regime")
    pain_dist = structure.get("max_pain_dist_pct")
    if dte is not None and dte <= 2 and cam == "INSIDE_CAM" and pain_dist is not None and pain_dist <= 0.4:
        vetoes.append("EXPIRY_PIN")

    if for_new_lock and mtf and mtf.get("allowed_side"):
        if mtf.get("daily_veto"):
            vetoes.append("DAILY_HARD_VETO")
        allowed = str(mtf.get("allowed_side") or "NONE").upper()
        if snap.direction == "BULLISH" and allowed != "LONG":
            vetoes.append("MTF_SIDE_BLOCK")
        elif snap.direction == "BEARISH" and allowed != "SHORT":
            vetoes.append("MTF_SIDE_BLOCK")
        if not mtf.get("confirmed_ready") and not mtf.get("hq_pullback"):
            vetoes.append("MTF_NOT_READY")

    if for_new_lock and float(location.get("score") or 0) < MIN_LOCATION_PROMOTE:
        vetoes.append("NO_LOCATION")

    if for_new_lock and persist.get("flips", 0) > 0:
        vetoes.append("DIRECTION_FLIPS")

    return vetoes


def compute_composite(
    *,
    persist: Dict[str, Any],
    location_score: float,
    lis: float,
    unusual_score: float,
    futures: Dict[str, Any],
    direction: str,
    grade: str,
) -> float:
    pers = min(max(float(persist.get("score") or 0), 0.0), 1.0)
    loc = min(max(float(location_score) / 11.0, 0.0), 1.0)
    lis_n = min(max(float(lis) / 100.0, 0.0), 1.0)
    uns = min(max(float(unusual_score) / 100.0, 0.0), 1.0)
    fut_pts = 0.0
    d = (direction or "").upper()
    if d == "BULLISH" and futures.get("agree_long"):
        fut_pts = 10.0
    elif d == "BEARISH" and futures.get("agree_short"):
        fut_pts = 10.0
    grade_pts = 4.0 if grade == "A+" else 2.0 if grade == "A" else 0.0
    total = (
        pers * 25.0
        + loc * 30.0
        + lis_n * 25.0
        + uns * 10.0
        + fut_pts
        + grade_pts
    )
    return round(min(100.0, total), 1)


def prominence(
    persist: Dict[str, Any],
    location_score: float,
    lis: float,
    unusual_score: float,
) -> float:
    return round(
        float(persist.get("score") or 0)
        * float(location_score or 0)
        * (min(float(lis or 0), 100.0) / 100.0)
        * (1.0 + min(float(unusual_score or 0), 100.0) / 200.0),
        3,
    )


def evaluate_candidate(
    *,
    snap: FlowSnapshot,
    snapshots: List[FlowSnapshot],
    full_map: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or now_ist()
    day = full_map.get("day") or {}
    session = full_map.get("session") or {}
    structure = full_map.get("structure") or {}
    futures = full_map.get("futures") or {}
    mtf = full_map.get("mtf") or {}
    step = infer_strike_step(snap.strike, snap.spot)
    persist = compute_persistence(snapshots, snap.direction, snap.strike, step, now.timestamp())
    location = score_location(
        spot=snap.spot,
        direction=snap.direction,
        day=day if day.get("ok") else {},
        session=session,
        structure=structure,
    )
    dual = detect_dual_side(snapshots, snap.opposing)
    recipe = classify_recipe(
        direction=snap.direction,
        location=location,
        label=snap.label,
        cam_regime=location.get("camarilla_regime") or "",
    )
    vetoes = hard_vetoes(
        snap=snap,
        location=location,
        day=day,
        structure=structure,
        futures=futures,
        persist=persist,
        dual_side=dual,
        now=now,
        for_new_lock=True,
        mtf=mtf or None,
    )
    levels = invalidation_and_targets(
        spot=snap.spot,
        direction=snap.direction,
        day=day if day.get("ok") else {},
        session=session,
        structure=structure,
    )
    execution = plan_execution(
        direction=snap.direction,
        spot=snap.spot,
        day=day if day.get("ok") else day,
        session=session,
        structure=structure,
        chain=full_map.get("chain") or [],
        locked=False,
        allowed_side=(mtf or {}).get("allowed_side"),
    )
    # Spec: OI clusters are the location. Tech score is secondary only.
    if execution.get("entry_cluster") or execution.get("magnet_source") == "OI_CLUSTER":
        vetoes = [v for v in vetoes if v != "NO_LOCATION"]
        if not recipe.get("ok"):
            recipe = {"id": "OI_CLUSTER", "name": "OI cluster entry", "ok": True}
    tag_roles = location_tags_for_role(location.get("tags") or [], snap.direction)
    composite = compute_composite(
        persist=persist,
        location_score=float(location.get("score") or 0),
        lis=snap.lis,
        unusual_score=snap.unusual_score,
        futures=futures,
        direction=snap.direction,
        grade=snap.grade,
    )
    loc_ok = (
        float(location.get("score") or 0) >= MIN_LOCATION_PROMOTE
        or bool((execution or {}).get("entry_cluster"))
    )
    persist_ok = persist["ready"] or (
        persist.get("fast_ok")
        and float(location.get("score") or 0) >= MIN_LOCATION_A_PLUS_FAST
        and snap.grade in ("A", "A+")
    )
    fuel_ok = snap.label in PROCESS_LABELS or snap.signal in STRONG_FLOW
    can_promote = (
        persist_ok
        and loc_ok
        and fuel_ok
        and recipe.get("ok")
        and composite >= ENTER_COMPOSITE
        and not vetoes
        and snap.direction in ("BULLISH", "BEARISH")
    )
    chain_agree = True
    if mtf:
        if snap.direction == "BULLISH":
            chain_agree = bool(futures.get("agree_long") or fuel_ok)
        elif snap.direction == "BEARISH":
            chain_agree = bool(futures.get("agree_short") or fuel_ok)
    rank = mtf_rank(
        int(mtf.get("align_score") or 0),
        float(location.get("score") or 0),
        float(persist.get("score") or 0),
        momentum_now=str(mtf.get("momentum_now") or "FLAT"),
        hq_pullback=bool(mtf.get("hq_pullback")),
        chain_agree=chain_agree,
    ) if mtf else prominence(persist, float(location.get("score") or 0), snap.lis, snap.unusual_score)
    return {
        "persist": persist,
        "location": location,
        "recipe": recipe,
        "vetoes": vetoes,
        "levels": levels,
        "execution": execution,
        "tag_roles": tag_roles,
        "composite": composite,
        "prominence": rank,
        "dual_side": dual,
        "can_promote": can_promote,
        "fuel_ok": fuel_ok,
        "step": step,
        "mtf": mtf or None,
        "futures": {
            "state": futures.get("state"),
            "direction": futures.get("direction"),
            "label": futures.get("label"),
            "symbol": futures.get("symbol"),
            "agree_long": futures.get("agree_long"),
            "agree_short": futures.get("agree_short"),
        },
    }


def lifecycle_action(
    *,
    idea: Dict[str, Any],
    snap: FlowSnapshot,
    evald: Dict[str, Any],
    candles_5m: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Optional[str]]:
    """
    15m never kills. 1H structure → DOWNGRADE. 4H / Daily hard → KILL.
    """
    mtf = evald.get("mtf") or idea.get("mtf") or {}
    if mtf:
        hit = frame_invalidation(
            idea_direction=str(idea.get("direction") or ""),
            mtf=mtf,
            spot=snap.spot,
        )
        if hit:
            return {
                "action": hit["action"],
                "reason": hit["reason"],
                "frame": hit["frame"],
            }
    ex = evald.get("execution") or {}
    if ex.get("action") == "CLUSTER_BROKEN":
        return {
            "action": "KILL",
            "reason": "CLUSTER_BROKEN",
            "frame": "CHAIN",
        }
    if ex.get("action") == "STAND_ASIDE":
        return {
            "action": "KILL",
            "reason": "DUAL_LIQUIDATION",
            "frame": "CHAIN",
        }
    if ex.get("support_dying") and ex.get("support_dying_reason") == "SUPPORT_CLUSTER_LIQUIDATING":
        return {
            "action": "DOWNGRADE",
            "reason": "SUPPORT_CLUSTER_LIQUIDATING",
            "frame": "CHAIN",
        }
    dead, why = should_invalidate(
        idea=idea, snap=snap, evald=evald, candles_5m=candles_5m
    )
    if dead:
        return {"action": "KILL", "reason": why, "frame": "FLOW"}
    return {"action": "HOLD", "reason": None, "frame": None}


def should_invalidate(
    *,
    idea: Dict[str, Any],
    snap: FlowSnapshot,
    evald: Dict[str, Any],
    candles_5m: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, Optional[str]]:
    """Locked idea dies only on real invalidation, not a prettier snapshot."""
    fut = evald.get("futures") or {}
    if idea.get("direction") == "BULLISH" and fut.get("state") == "SHORT_BUILDUP":
        return True, "FUTURES_FLIP"
    if idea.get("direction") == "BEARISH" and fut.get("state") == "LONG_BUILDUP":
        return True, "FUTURES_FLIP"

    if float(evald.get("composite") or 0) <= EXIT_COMPOSITE:
        return True, "COMPOSITE_DECAY"

    # Other side must itself persist (time + count). One flicker is tape.
    if snap.direction in ("BULLISH", "BEARISH") and snap.direction != idea.get("direction"):
        pers = evald.get("persist") or {}
        if pers.get("same", 0) >= 2 and float(pers.get("age_seconds") or 0) >= MIN_PERSIST_SECONDS:
            return True, "DIRECTION_FLIP"

    inv = (idea.get("invalidation") or (evald.get("levels") or {}).get("invalidation"))
    if inv is not None and candles_5m:
        last = candles_5m[-1]
        try:
            cl = float(last.get("close") or 0)
            if idea.get("direction") == "BULLISH" and cl < float(inv):
                return True, "15M_CLOSE_THROUGH_INVALIDATION"
            if idea.get("direction") == "BEARISH" and cl > float(inv):
                return True, "15M_CLOSE_THROUGH_INVALIDATION"
        except (TypeError, ValueError):
            pass
    # Spot smash through invalidation by > 0.25 ATR even without bar close
    atr = float((evald.get("location") or {}).get("atr") or 0) or None
    if inv is not None and atr:
        if idea.get("direction") == "BULLISH" and snap.spot < float(inv) - 0.25 * atr:
            return True, "SPOT_THROUGH_INVALIDATION"
        if idea.get("direction") == "BEARISH" and snap.spot > float(inv) + 0.25 * atr:
            return True, "SPOT_THROUGH_INVALIDATION"

    return False, None
