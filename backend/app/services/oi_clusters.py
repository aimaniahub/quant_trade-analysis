"""
OI Cluster Engine — spec: OI_Cluster_Engine_Entry_Target_Exit_Spec.md

Direction is an INPUT. This module finds magnets and cluster health.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Tuple

from app.services.option_analytics import _leg, _safe


MIN_CLUSTER_OI = 8_000
MIN_MULT_VS_MEDIAN = 1.55
MERGE_STEPS = 2
TOP_N = 5
RANGE_PCT = 15.0
EXTREME_MULT = 5.0
LIQ_OI_PCT = -8.0
LIQ_PREM_PCT = 1.5
BUILD_OI_PCT = 8.0
BUILD_PREM_PCT = -1.5
FRESH_OI_PCT = 20.0
NEAR_PCT_LO = 0.5
NEAR_PCT_HI = 1.5
AVOID_FAR_PCT = 1.8
VOL_ACTIVE_MULT = 1.2


def _infer_step(strikes: List[float]) -> float:
    uniq = sorted({s for s in strikes if s > 0})
    if len(uniq) < 2:
        return 10.0
    gaps = [uniq[i + 1] - uniq[i] for i in range(len(uniq) - 1) if uniq[i + 1] > uniq[i]]
    return min(gaps) if gaps else 10.0


def _health(oi_chg_pct: float, prem_chg_pct: float, vol_active: bool) -> str:
    if oi_chg_pct <= LIQ_OI_PCT and prem_chg_pct >= LIQ_PREM_PCT:
        return "LIQUIDATING"
    if oi_chg_pct >= FRESH_OI_PCT:
        return "FRESH"
    if oi_chg_pct >= BUILD_OI_PCT and (prem_chg_pct <= BUILD_PREM_PCT or vol_active):
        return "BUILDING"
    if oi_chg_pct >= BUILD_OI_PCT:
        return "ADDING"
    if oi_chg_pct <= LIQ_OI_PCT:
        return "UNWINDING"
    return "STABLE"


def _collect_legs(
    chain: List[Dict[str, Any]],
    side: str,
    spot: float,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in chain or []:
        strike = _safe(row.get("strike_price"))
        if strike <= 0:
            continue
        if spot > 0:
            dist = abs(strike - spot) / spot * 100.0
            # Keep ±15%. Extreme OI far away is allowed later.
            # We still collect all; filter in detect.
        else:
            dist = 0.0
        leg = _leg(row, side)
        oi = _safe(leg.get("oi"))
        if oi <= 0:
            continue
        delta = abs(_safe(leg.get("delta")))
        out.append({
            "strike": strike,
            "oi": oi,
            "oi_change": _safe(leg.get("oi_change")),
            "oi_change_pct": _safe(leg.get("oi_change_pct")),
            "volume": _safe(leg.get("volume")),
            "ltp": _safe(leg.get("ltp")),
            "chg_pct": _safe(leg.get("chg_pct") if leg.get("chg_pct") is not None else leg.get("chg")),
            "delta": delta,
            "dist_pct": dist,
        })
    out.sort(key=lambda x: x["strike"])
    return out


def _is_local_peak(legs: List[Dict[str, Any]], i: int) -> bool:
    oi = legs[i]["oi"]
    left = legs[i - 1]["oi"] if i > 0 else -1
    right = legs[i + 1]["oi"] if i + 1 < len(legs) else -1
    return oi >= left and oi >= right and oi > 0


def _merge_clusters(
    legs: List[Dict[str, Any]],
    *,
    side: str,
    median_oi: float,
    median_vol: float,
    step: float,
    spot: float,
) -> List[Dict[str, Any]]:
    if not legs:
        return []
    floor = max(median_oi * MIN_MULT_VS_MEDIAN, MIN_CLUSTER_OI)
    ranked = sorted(legs, key=lambda x: x["oi"], reverse=True)
    top20_cut = ranked[max(0, int(len(ranked) * 0.2) - 1)]["oi"] if ranked else floor

    hot_ids = set()
    for i, row in enumerate(legs):
        extreme = row["oi"] >= median_oi * EXTREME_MULT
        in_range = row["dist_pct"] <= RANGE_PCT or extreme
        if not in_range:
            continue
        # Deep OTM low-delta junk unless extreme size
        if row["dist_pct"] > 8.0 and row["delta"] and row["delta"] < 0.12 and not extreme:
            continue
        peak = _is_local_peak(legs, i)
        if (
            row["oi"] >= floor
            or (peak and row["oi"] >= max(median_oi, MIN_CLUSTER_OI * 0.5))
            or row["oi"] >= top20_cut
        ):
            hot_ids.add(i)

    if not hot_ids:
        best = max(legs, key=lambda x: x["oi"])
        if best["oi"] <= 0:
            return []
        hot = [best]
    else:
        hot = [legs[i] for i in sorted(hot_ids)]

    window = step * MERGE_STEPS + 0.01
    groups: List[List[Dict[str, Any]]] = []
    cur = [hot[0]]
    for row in hot[1:]:
        if row["strike"] - cur[-1]["strike"] <= window:
            cur.append(row)
        else:
            groups.append(cur)
            cur = [row]
    groups.append(cur)

    clusters: List[Dict[str, Any]] = []
    for g in groups:
        tot = sum(x["oi"] for x in g)
        if tot <= 0:
            continue
        peak = max(g, key=lambda x: x["oi"])
        wstrike = sum(x["strike"] * x["oi"] for x in g) / tot
        w_oi_chg = sum(x["oi_change_pct"] * x["oi"] for x in g) / tot
        w_prem = sum(x["chg_pct"] * x["oi"] for x in g) / tot
        vol = sum(x["volume"] for x in g)
        vol_active = vol >= max(median_vol * VOL_ACTIVE_MULT, 1.0)
        health = _health(w_oi_chg, w_prem, vol_active)
        oi_norm = tot / max(median_oi, 1.0)
        fresh = max(w_oi_chg, 0.0) / 40.0
        vol_norm = vol / max(median_vol, 1.0)
        rank = min(100.0, oi_norm * 14.0 + min(fresh, 1.0) * 25.0 + min(vol_norm, 4.0) * 6.0)
        if health == "BUILDING" or health == "FRESH":
            rank = min(100.0, rank + 12.0)
        if health == "LIQUIDATING":
            rank = max(0.0, rank - 22.0)
        clusters.append({
            "side": side,
            "type": "CE" if side == "CALL" else "PE",
            "role": "RESISTANCE" if side == "CALL" else "SUPPORT",
            "peak_strike": peak["strike"],
            "strike": peak["strike"],
            "center": round(wstrike, 2),
            "low": g[0]["strike"],
            "high": g[-1]["strike"],
            "oi": round(tot, 0),
            "oi_change_pct": round(w_oi_chg, 2),
            "premium_change_pct": round(w_prem, 2),
            "volume": round(vol, 0),
            "volume_active": vol_active,
            "health": health,
            "state": health,
            "strength": round(rank, 1),
            "rank_score": round(rank, 1),
            "strikes": [x["strike"] for x in g],
        })
    clusters.sort(key=lambda c: (c["rank_score"], c["oi"]), reverse=True)
    return clusters[:TOP_N]


def detect_oi_clusters(chain: List[Dict[str, Any]], spot: float) -> Dict[str, Any]:
    calls = _collect_legs(chain, "call", spot)
    puts = _collect_legs(chain, "put", spot)
    all_oi = [x["oi"] for x in calls + puts if x["oi"] > 0]
    all_vol = [x["volume"] for x in calls + puts if x["volume"] > 0]
    median = float(statistics.median(all_oi)) if all_oi else 1.0
    median_vol = float(statistics.median(all_vol)) if all_vol else 1.0
    step = _infer_step([x["strike"] for x in calls + puts])
    call_cs = _merge_clusters(
        calls, side="CALL", median_oi=median, median_vol=median_vol, step=step, spot=spot
    )
    put_cs = _merge_clusters(
        puts, side="PUT", median_oi=median, median_vol=median_vol, step=step, spot=spot
    )
    return {
        "ok": bool(call_cs or put_cs),
        "median_oi": round(median, 0),
        "median_vol": round(median_vol, 0),
        "step": step,
        "call_clusters": call_cs,
        "put_clusters": put_cs,
        "dual_liquidating": _dual_liquidating(call_cs, put_cs),
    }


def _dual_liquidating(calls: List[Dict[str, Any]], puts: List[Dict[str, Any]]) -> bool:
    def dying(cs: List[Dict[str, Any]]) -> bool:
        if not cs:
            return False
        top = cs[0]
        return top.get("health") in ("LIQUIDATING", "UNWINDING") and float(top.get("oi_change_pct") or 0) <= LIQ_OI_PCT

    return dying(calls) and dying(puts)


def _px(c: Optional[Dict[str, Any]]) -> float:
    if not c:
        return 0.0
    return float(c.get("peak_strike") or c.get("center") or c.get("strike") or 0)


def _nearest(
    clusters: List[Dict[str, Any]],
    spot: float,
    *,
    below: bool,
    allow_liquidating: bool = False,
) -> Optional[Dict[str, Any]]:
    eps = max(abs(spot) * 0.0004, 0.05)
    pool = []
    for c in clusters:
        px = _px(c)
        if px <= 0:
            continue
        if not allow_liquidating and c.get("health") == "LIQUIDATING":
            continue
        if below and px <= spot + eps:
            pool.append((c, px, spot - px))
        elif not below and px >= spot - eps:
            pool.append((c, px, px - spot))
    if not pool:
        return None
    pool.sort(key=lambda x: (x[2], -float(x[0].get("rank_score") or x[0].get("oi") or 0)))
    return pool[0][0]


def _entry_zone(cluster: Dict[str, Any], side: str, atr: float, spot: float) -> Dict[str, Any]:
    peak = _px(cluster)
    lo = float(cluster.get("low") or peak)
    hi = float(cluster.get("high") or peak)
    pad = max(atr * 0.35, abs(peak) * 0.004, 1.0)
    if side == "LONG":
        # just above put cluster (demand)
        z_from = min(lo, peak)
        z_to = max(hi, peak + pad)
        reason = f"Demand / reclaim of Put cluster {int(lo)}–{int(hi)}"
    else:
        # just below call cluster (supply)
        z_from = min(lo, peak - pad)
        z_to = max(hi, peak)
        reason = f"Rejection from Call cluster {int(lo)}–{int(hi)}"
    return {
        "from": round(z_from, 2),
        "to": round(z_to, 2),
        "reason": reason,
    }


def _dist_pct(spot: float, px: float) -> float:
    if spot <= 0:
        return 99.0
    return abs(px - spot) / spot * 100.0


def entry_quality(spot: float, cluster: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not cluster:
        return {"score": 0, "label": "NONE"}
    d = _dist_pct(spot, _px(cluster))
    score = 0
    if NEAR_PCT_LO <= d <= NEAR_PCT_HI or d <= NEAR_PCT_LO:
        score += 40
    elif d <= AVOID_FAR_PCT:
        score += 20
    if cluster.get("health") in ("BUILDING", "FRESH", "STABLE", "ADDING"):
        score += 30
    if cluster.get("volume_active"):
        score += 20
    if cluster.get("health") == "LIQUIDATING":
        score = max(0, score - 40)
    label = "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW"
    return {"score": score, "label": label, "dist_pct": round(d, 3)}


def pick_cluster_plan(
    *,
    direction: str,
    spot: float,
    clusters: Dict[str, Any],
    atr: float = 0.0,
) -> Dict[str, Any]:
    """
    Long:  entry = nearest PUT cluster at/below spot. Target = next CALL cluster above.
    Short: entry = nearest CALL cluster at/above spot. Target = next PUT cluster below.
    """
    d = (direction or "").upper()
    puts = list(clusters.get("put_clusters") or [])
    calls = list(clusters.get("call_clusters") or [])
    empty = {
        "entry_cluster": None,
        "target_cluster": None,
        "target_2_cluster": None,
        "support_liquidating": False,
        "avoid_entry": True,
        "avoid_reason": "NO_SIDE",
        "entry_zone": None,
        "opposing_weak": False,
        "opposing_absorbed": False,
        "entry_quality": {"score": 0, "label": "NONE"},
    }
    if d not in ("BULLISH", "BEARISH"):
        return empty

    atr = atr or max(abs(spot) * 0.008, 1.0)
    if d == "BULLISH":
        entry = _nearest(puts, spot, below=True)
        opposing_near = _nearest(calls, spot, below=False, allow_liquidating=True)
        if not opposing_near:
            # Price just punched through the call wall — still the absorb/T1 magnet.
            punched = _nearest(calls, spot, below=True, allow_liquidating=True)
            if punched and _dist_pct(spot, _px(punched)) <= 0.8:
                opposing_near = punched
        tgt = opposing_near
        tgt2 = None
        if tgt:
            rest = [c for c in calls if c is not tgt and _px(c) > _px(tgt)]
            tgt2 = _nearest(rest, _px(tgt), below=False, allow_liquidating=True)
        liq = bool(entry and entry.get("health") == "LIQUIDATING")
        if liq:
            alt = [c for c in puts if c is not entry]
            entry2 = _nearest(alt, spot, below=True)
            if entry2:
                entry, liq = entry2, entry2.get("health") == "LIQUIDATING"
        # Avoid: sitting in a call wall with no nearby put base
        avoid, avoid_reason = False, None
        if not entry:
            avoid, avoid_reason = True, "NO_SUPPORTING_PUT_CLUSTER"
        elif _dist_pct(spot, _px(entry)) > AVOID_FAR_PCT:
            avoid, avoid_reason = True, "FAR_FROM_PUT_CLUSTER"
        elif opposing_near and _dist_pct(spot, _px(opposing_near)) + 0.05 < _dist_pct(spot, _px(entry)):
            if _dist_pct(spot, _px(opposing_near)) <= 0.6:
                avoid, avoid_reason = True, "INTO_CALL_WALL"
    else:
        entry = _nearest(calls, spot, below=False)
        opposing_near = _nearest(puts, spot, below=True, allow_liquidating=True)
        if not opposing_near:
            punched = _nearest(puts, spot, below=False, allow_liquidating=True)
            if punched and _dist_pct(spot, _px(punched)) <= 0.8:
                opposing_near = punched
        tgt = opposing_near
        tgt2 = None
        if tgt:
            rest = [c for c in puts if c is not tgt and _px(c) < _px(tgt)]
            tgt2 = _nearest(rest, _px(tgt), below=True, allow_liquidating=True)
        liq = bool(entry and entry.get("health") == "LIQUIDATING")
        if liq:
            alt = [c for c in calls if c is not entry]
            entry2 = _nearest(alt, spot, below=False)
            if entry2:
                entry, liq = entry2, entry2.get("health") == "LIQUIDATING"
        avoid, avoid_reason = False, None
        if not entry:
            avoid, avoid_reason = True, "NO_SUPPORTING_CALL_CLUSTER"
        elif _dist_pct(spot, _px(entry)) > AVOID_FAR_PCT:
            avoid, avoid_reason = True, "FAR_FROM_CALL_CLUSTER"
        elif opposing_near and _dist_pct(spot, _px(opposing_near)) + 0.05 < _dist_pct(spot, _px(entry)):
            if _dist_pct(spot, _px(opposing_near)) <= 0.6:
                avoid, avoid_reason = True, "INTO_PUT_WALL"

    opposing_weak = bool(tgt and tgt.get("health") in ("LIQUIDATING", "UNWINDING"))
    # Absorbed: opposing OI falling while price has pushed through / into it
    opposing_absorbed = False
    if tgt and float(tgt.get("oi_change_pct") or 0) <= LIQ_OI_PCT:
        tpx = _px(tgt)
        if d == "BULLISH" and spot >= tpx * 0.998:
            opposing_absorbed = True
        if d == "BEARISH" and spot <= tpx * 1.002:
            opposing_absorbed = True

    zone = _entry_zone(entry, "LONG" if d == "BULLISH" else "SHORT", atr, spot) if entry else None
    return {
        "entry_cluster": entry,
        "target_cluster": tgt,
        "target_2_cluster": tgt2,
        "support_liquidating": liq,
        "avoid_entry": avoid,
        "avoid_reason": avoid_reason,
        "entry_zone": zone,
        "opposing_weak": opposing_weak,
        "opposing_absorbed": opposing_absorbed,
        "entry_quality": entry_quality(spot, entry),
    }


def match_cluster(
    prior: Optional[Dict[str, Any]],
    clusters: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Find the same remembered cluster in a fresh map (by side + strike)."""
    if not prior:
        return None
    side = str(prior.get("side") or "").upper()
    typ = str(prior.get("type") or "").upper()
    if not side:
        side = "CALL" if typ == "CE" else "PUT" if typ == "PE" else ""
    pool = (
        clusters.get("put_clusters")
        if side == "PUT"
        else clusters.get("call_clusters")
        if side == "CALL"
        else list(clusters.get("put_clusters") or []) + list(clusters.get("call_clusters") or [])
    ) or []
    want = _px(prior)
    if want <= 0:
        return prior
    band = max(abs(want) * 0.004, 1.0)
    for c in pool:
        if abs(_px(c) - want) <= band:
            return c
    return prior


def supporting_cluster_dying(
    *,
    direction: str,
    spot: float,
    clusters: Dict[str, Any],
    locked_entry: Optional[float] = None,
    locked_cluster: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    d = (direction or "").upper()
    if d == "BULLISH":
        pool = clusters.get("put_clusters") or []
        below = True
        default_type = "PE"
    elif d == "BEARISH":
        pool = clusters.get("call_clusters") or []
        below = False
        default_type = "CE"
    else:
        return None
    want = None
    if locked_cluster:
        want = _px(locked_cluster) or None
    if want is None and locked_entry:
        want = float(locked_entry)
    hit = None
    if want:
        band = max(abs(spot or want) * 0.004, 1.0)
        for c in pool:
            if abs(_px(c) - want) <= band:
                hit = c
                break
        if hit is None and locked_cluster:
            # Remembered cluster dropped off the map — sponsorship is gone.
            return {
                "dying": True,
                "cluster": {
                    "peak_strike": want,
                    "type": (locked_cluster or {}).get("type") or default_type,
                    "health": "GONE",
                    "oi_change_pct": None,
                },
                "reason": "SUPPORT_CLUSTER_LIQUIDATING",
            }
    if hit is None:
        hit = _nearest(pool, spot, below=below, allow_liquidating=True)
    if not hit:
        return None
    if hit.get("health") in ("LIQUIDATING", "UNWINDING"):
        return {
            "dying": True,
            "cluster": hit,
            "reason": (
                "SUPPORT_CLUSTER_LIQUIDATING"
                if hit["health"] == "LIQUIDATING"
                else "SUPPORT_CLUSTER_UNWINDING"
            ),
        }
    return None


def price_through_support(
    *,
    direction: str,
    spot: float,
    cluster: Optional[Dict[str, Any]],
) -> bool:
    if not cluster:
        return False
    d = (direction or "").upper()
    lo = float(cluster.get("low") or _px(cluster))
    hi = float(cluster.get("high") or _px(cluster))
    if d == "BULLISH":
        return spot < lo
    if d == "BEARISH":
        return spot > hi
    return False
