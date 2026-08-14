"""
Execution planner — entry, stop, targets, instrument.

Direction is an INPUT. This module never votes long vs short.
Levels only answer: where to enter, where to die, where to take money,
and which option to buy for that side.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.levels import _f, invalidation_and_targets
from app.services.oi_clusters import (
    detect_oi_clusters,
    match_cluster,
    pick_cluster_plan,
    price_through_support,
    supporting_cluster_dying,
)


def _refresh_cluster(
    prior_c: Optional[Dict[str, Any]],
    clusters: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not prior_c:
        return None
    return match_cluster(prior_c, clusters) or prior_c


def _strike_step(spot: float) -> float:
    px = max(float(spot or 0), 1.0)
    if px >= 20000:
        return 100.0
    if px >= 5000:
        return 50.0
    if px >= 2000:
        return 20.0
    if px >= 1000:
        return 10.0
    if px >= 250:
        return 5.0
    return 2.5


# How close to the entry level counts as "at the zone"
AT_ZONE_ATR = 0.30
# Beyond this past entry toward target = chasing
CHASE_ATR = 0.45


def _rr(spot: float, stop: Optional[float], target: Optional[float], side: str) -> Optional[float]:
    if not stop or not target:
        return None
    if side == "LONG":
        risk = spot - stop
        reward = target - spot
    else:
        risk = stop - spot
        reward = spot - target
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def suggest_instrument(
    *,
    direction: str,
    spot: float,
    entry: Optional[float],
    step: Optional[float] = None,
) -> Dict[str, Any]:
    """
    What we BUY for the process trade.
    Fuel contract (written CE on a short) is not the instrument.
    """
    d = (direction or "").upper()
    opt = "CE" if d == "BULLISH" else "PE" if d == "BEARISH" else None
    px = float(entry or spot or 0)
    st = float(step or _strike_step(spot or px) or 10)
    if st <= 0:
        st = 10.0
    strike = round(px / st) * st
    return {
        "opt_type": opt,
        "strike": round(strike, 2) if opt else None,
        "role": "BUY_CE" if opt == "CE" else "BUY_PE" if opt == "PE" else "NONE",
        "note": (
            "Buy CE — directional long"
            if opt == "CE"
            else "Buy PE — directional short (not the written call)"
            if opt == "PE"
            else "No instrument until direction is set"
        ),
    }


def classify_action(
    *,
    direction: str,
    spot: float,
    entry: Optional[float],
    stop: Optional[float],
    target: Optional[float],
    target_2: Optional[float],
    atr: float,
    locked: bool,
) -> Dict[str, str]:
    d = (direction or "").upper()
    if d not in ("BULLISH", "BEARISH") or not entry:
        return {"action": "NO_PLAN", "label": "No execution plan"}
    band = max(atr * AT_ZONE_ATR, abs(spot) * 0.0015)
    chase = max(atr * CHASE_ATR, band * 1.3)
    long = d == "BULLISH"

    if stop is not None:
        if long and spot <= stop:
            return {"action": "STOPPED", "label": "Through stop — out"}
        if not long and spot >= stop:
            return {"action": "STOPPED", "label": "Through stop — out"}

    if target_2 is not None:
        if long and spot >= target_2:
            return {"action": "HIT_T2", "label": "T2 reached"}
        if not long and spot <= target_2:
            return {"action": "HIT_T2", "label": "T2 reached"}
    if target is not None:
        if long and spot >= target:
            return {"action": "HIT_T1", "label": "T1 reached — bank / trail"}
        if not long and spot <= target:
            return {"action": "HIT_T1", "label": "T1 reached — bank / trail"}

    at_entry = abs(spot - entry) <= band
    if at_entry:
        return {
            "action": "AT_ENTRY",
            "label": "At entry zone — take it" if not locked else "In zone — hold",
        }

    if long:
        # Support is below. Wait for a dip to it. Far above = already ran.
        waiting = spot > entry + band
        ran_away = spot > entry + chase
        between = target is not None and entry < spot < target
    else:
        # Resistance is above. Wait for a rally into it. Far below = already dumped.
        waiting = spot < entry - band
        ran_away = spot < entry - chase
        between = target is not None and target < spot < entry

    if ran_away and not locked:
        return {
            "action": "CHASE",
            "label": "Already ran — do not chase; wait retest",
        }
    if waiting and not locked:
        return {
            "action": "WAIT_FOR_LEVEL",
            "label": (
                "Wait pullback to support"
                if long
                else "Wait rally into resistance"
            ),
        }
    if locked or between:
        return {"action": "IN_TRADE", "label": "Between entry and T1 — hold"}
    return {"action": "WAIT_FOR_LEVEL", "label": "Wait for level"}


def _tech_near(px: Optional[float], session: Dict[str, Any], day: Dict[str, Any], atr: float) -> List[str]:
    """Secondary confirmation only — never the primary magnet."""
    if not px:
        return []
    band = max(atr * 0.25, abs(px) * 0.0015)
    tags: List[str] = []
    checks = {
        "VWAP": (session or {}).get("vwap"),
        "P": ((day or {}).get("pivots") or {}).get("P"),
        "S1": ((day or {}).get("pivots") or {}).get("S1"),
        "R1": ((day or {}).get("pivots") or {}).get("R1"),
        "Cam S3": ((day or {}).get("camarilla") or {}).get("S3"),
        "Cam R3": ((day or {}).get("camarilla") or {}).get("R3"),
    }
    for name, lvl in checks.items():
        if lvl and abs(float(lvl) - float(px)) <= band:
            tags.append(name)
    return tags


def _from_cluster(c: Optional[Dict[str, Any]], role: str) -> Tuple[Optional[float], Optional[str]]:
    if not c:
        return None, None
    px = float(c.get("peak_strike") or c.get("center") or 0)
    if px <= 0:
        return None, None
    label = f"{c.get('side', '')} OI {int(px)}"
    if role == "entry":
        label = f"{'Put' if c.get('side') == 'PUT' else 'Call'} cluster {int(px)}"
    else:
        label = f"{'Call' if c.get('side') == 'CALL' else 'Put'} cluster {int(px)}"
    return px, label


def plan_execution(
    *,
    direction: str,
    spot: float,
    day: Dict[str, Any],
    session: Dict[str, Any],
    structure: Dict[str, Any],
    chain: Optional[List[Dict[str, Any]]] = None,
    locked: bool = False,
    prior: Optional[Dict[str, Any]] = None,
    allowed_side: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build or refresh the execution plan.

    Primary magnets = OI clusters.
    Technicals (VWAP / Cam / pivots) only confirm or fill gaps.

    Locked ideas keep entry / stop / targets (they must not wander).
    Liquidation of the supporting cluster can flip action to TRAIL_EXIT.
    """
    d = (direction or "").upper()
    atr = _f(day.get("atr")) or max(abs(spot) * 0.008, 1.0)
    side = "LONG" if d == "BULLISH" else "SHORT" if d == "BEARISH" else "FLAT"
    allow = (allowed_side or "").upper()
    if allow == "NONE":
        return {
            "role": "EXECUTION",
            "side": "FLAT",
            "action": "NO_PLAN",
            "action_label": "MTF allowed_side is NONE — no entry/target",
            "entry": None,
            "entry_label": None,
            "entry_role": None,
            "stop": None,
            "invalidation": None,
            "target": None,
            "target_label": None,
            "target_2": None,
            "target_2_label": None,
            "reward_risk": None,
            "instrument": suggest_instrument(direction="NEUTRAL", spot=spot, entry=None),
            "take_now": False,
            "magnet_source": None,
            "cluster_health": "NONE",
            "exit_warnings": ["MTF NONE — cluster engine idle"],
            "cluster_plan": None,
        }
    if allow == "LONG":
        d = "BULLISH"
        side = "LONG"
    elif allow == "SHORT":
        d = "BEARISH"
        side = "SHORT"
    clusters = detect_oi_clusters(chain or [], spot) if chain else (prior or {}).get("clusters") or {}
    picked = (
        pick_cluster_plan(direction=d, spot=spot, clusters=clusters or {}, atr=atr)
        if clusters
        else {}
    )
    locked_cluster = (prior or {}).get("locked_cluster") or (
        (prior or {}).get("cluster_plan") or {}
    ).get("supporting_cluster")
    dying = supporting_cluster_dying(
        direction=d,
        spot=spot,
        clusters=clusters or {},
        locked_entry=(prior or {}).get("entry") if locked else None,
        locked_cluster=locked_cluster if locked else None,
    )

    source = "TECH"
    entry_cluster = target_cluster = target_2_cluster = None
    entry_zone = (prior or {}).get("entry_zone") if locked else None

    if prior and locked and prior.get("entry"):
        entry = _f(prior.get("entry"))
        entry_label = prior.get("entry_label") or "Entry"
        stop = prior.get("stop")
        inv = prior.get("invalidation")
        t1 = prior.get("target")
        t1_lab = prior.get("target_label")
        t2 = prior.get("target_2")
        t2_lab = prior.get("target_2_label")
        entry_role = prior.get("entry_role")
        source = prior.get("magnet_source") or "TECH"
        entry_cluster = _refresh_cluster(prior.get("entry_cluster"), clusters or {})
        target_cluster = _refresh_cluster(prior.get("target_cluster"), clusters or {})
        target_2_cluster = _refresh_cluster(prior.get("target_2_cluster"), clusters or {})
        if not entry_zone:
            entry_zone = picked.get("entry_zone")
    else:
        entry_cluster = picked.get("entry_cluster")
        target_cluster = picked.get("target_cluster")
        target_2_cluster = picked.get("target_2_cluster")
        c_entry, c_elab = _from_cluster(entry_cluster, "entry")
        c_t1, c_t1lab = _from_cluster(target_cluster, "target")
        c_t2, c_t2lab = _from_cluster(target_2_cluster, "target")

        tech = invalidation_and_targets(
            spot=spot,
            direction=d,
            day=day if day.get("ok") else day,
            session=session,
            structure=structure,
        )

        if c_entry:
            entry, entry_label, source = c_entry, c_elab, "OI_CLUSTER"
            # Stop lives beyond the supporting cluster, not inside the peak.
            if d == "BULLISH":
                base = float((entry_cluster or {}).get("low") or c_entry)
                stop = round(base - 0.15 * atr, 2)
                inv = base
            else:
                base = float((entry_cluster or {}).get("high") or c_entry)
                stop = round(base + 0.15 * atr, 2)
                inv = base
        else:
            entry = tech.get("entry")
            entry_label = tech.get("entry_label")
            stop = tech.get("stop")
            inv = tech.get("invalidation")
            source = "TECH"

        if c_t1:
            t1, t1_lab = c_t1, c_t1lab
        else:
            t1, t1_lab = tech.get("target"), tech.get("target_label")
        if c_t2:
            t2, t2_lab = c_t2, c_t2lab
        else:
            # Tech T2 only if it sits beyond the primary cluster, never before it.
            tech_t2 = tech.get("target_2")
            t2, t2_lab = None, None
            if tech_t2 is not None and t1 is not None:
                if d == "BULLISH" and float(tech_t2) > float(t1):
                    t2, t2_lab = tech_t2, tech.get("target_2_label")
                elif d == "BEARISH" and float(tech_t2) < float(t1):
                    t2, t2_lab = tech_t2, tech.get("target_2_label")

        entry_role = "SUPPORT" if d == "BULLISH" else "RESISTANCE" if d == "BEARISH" else None
        entry_zone = picked.get("entry_zone")

    inst = suggest_instrument(direction=d, spot=spot, entry=entry)
    act = classify_action(
        direction=d,
        spot=spot,
        entry=entry,
        stop=float(stop) if stop is not None else None,
        target=float(t1) if t1 is not None else None,
        target_2=float(t2) if t2 is not None else None,
        atr=atr,
        locked=locked,
    )
    if dying and dying.get("dying") and act["action"] not in ("STOPPED", "HIT_T1", "HIT_T2"):
        through = price_through_support(direction=d, spot=spot, cluster=entry_cluster)
        if through:
            act = {
                "action": "CLUSTER_BROKEN",
                "label": "Price through supporting cluster — exit",
            }
        else:
            act = {
                "action": "TRAIL_EXIT",
                "label": (
                    "Supporting OI cluster liquidating — tighten / exit"
                    if dying.get("reason") == "SUPPORT_CLUSTER_LIQUIDATING"
                    else "Supporting OI cluster unwinding — trail"
                ),
            }

    dual = bool((clusters or {}).get("dual_liquidating"))
    if dual:
        act = {
            "action": "STAND_ASIDE",
            "label": "Both sides liquidating — no sponsorship",
        }

    if (
        not locked
        and picked.get("avoid_entry")
        and act["action"] == "AT_ENTRY"
    ):
        act = {
            "action": "WAIT_FOR_LEVEL",
            "label": f"Avoid entry ({picked.get('avoid_reason')})",
        }

    if picked.get("opposing_absorbed") and act["action"] == "HIT_T1":
        act = {
            "action": "EXTEND",
            "label": "Opposing cluster absorbed — trail toward T2",
        }

    rr = _rr(spot, float(stop) if stop else None, float(t1) if t1 else None, side)

    if d == "BEARISH" and t1 is not None and not locked and float(t1) >= spot:
        t1, t1_lab = None, None
    if d == "BULLISH" and t1 is not None and not locked and float(t1) <= spot:
        t1, t1_lab = None, None
    if t2 is not None and t1 is not None and not locked:
        if d == "BEARISH" and float(t2) >= float(t1):
            t2, t2_lab = None, None
        if d == "BULLISH" and float(t2) <= float(t1):
            t2, t2_lab = None, None

    tech_tags = _tech_near(entry, session, day, atr)
    warnings: List[str] = []
    if dying and dying.get("dying"):
        cl = dying.get("cluster") or {}
        warnings.append(
            f"Supporting {cl.get('type', '')} cluster {int(_f(cl.get('peak_strike') or entry or 0))} "
            f"OI {cl.get('health', '')} ({cl.get('oi_change_pct')}%)"
        )
    if picked.get("opposing_weak"):
        warnings.append("Opposing cluster weakening — target less reliable")
    if picked.get("opposing_absorbed"):
        warnings.append("Opposing cluster absorbed — can trail to T2")
    if dual:
        warnings.append("Dual-sided OI liquidation")
    if picked.get("avoid_reason") and not locked:
        warnings.append(str(picked["avoid_reason"]))

    if dual:
        health = "CHAOS"
    elif dying and dying.get("reason") == "SUPPORT_CLUSTER_LIQUIDATING":
        health = "WEAKENING"
    elif dying:
        health = "WEAKENING"
    elif source == "OI_CLUSTER":
        health = "HEALTHY"
    else:
        health = "NO_CLUSTER"

    stop_ref = None
    if entry is not None:
        stop_ref = round(entry + 0.15 * atr, 2) if d == "BEARISH" else round(entry - 0.15 * atr, 2)

    cluster_plan = {
        "side": "BEARISH" if d == "BEARISH" else "BULLISH" if d == "BULLISH" else "NONE",
        "entry_zone": entry_zone,
        "supporting_cluster": (
            {
                "strike": (entry_cluster or {}).get("peak_strike"),
                "type": (entry_cluster or {}).get("type"),
                "oi": (entry_cluster or {}).get("oi"),
                "state": (entry_cluster or {}).get("state") or (entry_cluster or {}).get("health"),
            }
            if entry_cluster
            else None
        ),
        "primary_target": (
            {"level": t1, "reason": t1_lab}
            if t1 is not None
            else None
        ),
        "secondary_target": t2,
        "stop_reference": stop if stop is not None else stop_ref,
        "exit_warnings": warnings,
        "cluster_health": health,
        "entry_quality": (
            (prior or {}).get("entry_quality")
            if locked and (prior or {}).get("entry_quality")
            else (picked or {}).get("entry_quality") or (prior or {}).get("entry_quality")
        ),
    }

    return {
        "role": "EXECUTION",
        "side": side,
        "action": act["action"],
        "action_label": act["label"],
        "entry": entry,
        "entry_label": entry_label,
        "entry_role": entry_role,
        "stop": stop,
        "invalidation": inv,
        "target": t1,
        "target_label": t1_lab,
        "target_2": t2,
        "target_2_label": t2_lab,
        "reward_risk": rr,
        "atr": round(atr, 4),
        "instrument": inst,
        "take_now": act["action"] == "AT_ENTRY",
        "magnet_source": source,
        "clusters": clusters,
        "entry_cluster": entry_cluster,
        "target_cluster": target_cluster,
        "target_2_cluster": target_2_cluster,
        "support_dying": bool(dying and dying.get("dying")),
        "support_dying_reason": (dying or {}).get("reason"),
        "tech_confirm": tech_tags,
        "note": (
            f"{side}: enter at {entry_label} {entry} ({source}). "
            f"Stop {stop}. T1 {t1_lab} {t1}. {act['label']}."
        ),
        "entry_zone": entry_zone,
        "cluster_plan": cluster_plan,
        "exit_warnings": warnings,
        "cluster_health": health,
        "entry_quality": cluster_plan.get("entry_quality"),
        "locked_cluster": cluster_plan.get("supporting_cluster"),
    }


def location_tags_for_role(tags: List[str], direction: str) -> Dict[str, List[str]]:
    """Split location tags so resistance is never shown as a short target."""
    d = (direction or "").upper()
    entry_keys = (
        ("PUT_WALL", "PIVOT_SUPPORT", "VWAP_LONG", "CAM:INSIDE_CAM", "INST_ZONE")
        if d == "BULLISH"
        else ("CALL_WALL", "PIVOT_RESIST", "VWAP_SHORT", "CAM:INSIDE_CAM", "INST_ZONE")
    )
    entry, other = [], []
    for t in tags or []:
        if any(k in t for k in entry_keys):
            entry.append(t)
        else:
            other.append(t)
    return {"entry_tags": entry, "context_tags": other}
