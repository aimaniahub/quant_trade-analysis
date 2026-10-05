"""Orchestrate scrape → rank → validate → chain analyse. One click, one job."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.ai_ranker import rank_articles, validate_picks
from app.services.news_scraper import prefilter, scrape_market_news
from app.services.scan_jobs import get_scan_job_manager
from app.utils.market_hours import IST

logger = logging.getLogger(__name__)

OUTCOMES = Path(__file__).resolve().parents[1] / "data" / "ai_chain_outcomes.jsonl"

_hot_lock = threading.Lock()
_hot_symbols: List[str] = []
_news_focus: List[Dict[str, Any]] = []
_last_payload: Optional[Dict[str, Any]] = None


def get_hot_symbols() -> List[str]:
    with _hot_lock:
        return list(_hot_symbols)


def get_news_focus() -> List[Dict[str, Any]]:
    with _hot_lock:
        return list(_news_focus)


def last_payload() -> Optional[Dict[str, Any]]:
    with _hot_lock:
        return dict(_last_payload) if _last_payload else None


def _set_hot(picks: List[Dict[str, Any]]) -> None:
    global _hot_symbols, _news_focus
    with _hot_lock:
        _news_focus = list(picks)
        _hot_symbols = [p["symbol"] for p in picks if p.get("symbol")]
    try:
        from app.services.option_flow_radar import get_radar_service

        get_radar_service().set_news_focus(_hot_symbols, picks)
    except Exception as exc:
        logger.debug("radar hot overlay skip: %s", exc)


def _phase(job_id: str, phase: str, **extra: Any) -> None:
    mgr = get_scan_job_manager()
    meta = dict((mgr.get(job_id).meta if mgr.get(job_id) else {}) or {})
    meta["phase"] = phase
    meta["heartbeat_at"] = time.time()
    meta.update(extra)
    mgr.update(job_id, meta=meta)


def _analyse_symbol(symbol: str) -> Dict[str, Any]:
    from app.services.chain_desk import evaluate, summarize_report
    from app.services import symbol_store as store
    from app.services.signal_interpreter import interpret_pcr

    chain_resp = store.get_chain(symbol, 14) or {}
    if not chain_resp.get("success") or len(chain_resp.get("chain") or []) < 2:
        return {"grade": None, "error": "no_store_chain"}
    try:
        report = evaluate(symbol, chain_resp, name=symbol.split(":")[-1].replace("-EQ", ""))
        summary = summarize_report(report)
    except Exception as exc:
        return {"grade": None, "error": str(exc)[:120]}
    flags = summary.get("flags") or {}
    explode = "NONE"
    if flags.get("high_vol") or flags.get("high_oi"):
        explode = "EARLY"
    
    struct = report.get("structure") or {}
    oi_pcr = struct.get("oi_pcr")
    pcr_interp = interpret_pcr(oi_pcr)

    return {
        "grade": summary.get("grade"),
        "chain_bias": summary.get("chain_bias"),
        "intent": (summary.get("top_anomaly") or {}).get("type"),
        "top_anomaly_label": (summary.get("top_anomaly") or {}).get("label"),
        "setup_score": summary.get("setup_score"),
        "pcr_regime": pcr_interp.get("regime"),
        "pcr_sentence": pcr_interp.get("sentence"),
        "explode_state": explode,
        "why_not": summary.get("why_not"),
        "trade": summary.get("trade"),
        "flags": {
            "high_oi": bool(flags.get("high_oi")),
            "high_vol": bool(flags.get("high_vol")),
            "support": bool(flags.get("support")),
            "resistance": bool(flags.get("resistance")),
        },
    }


def _fuse(pick: Dict[str, Any], chain: Dict[str, Any]) -> str:
    from app.services.signal_interpreter import compute_news_chain_alignment
    res = compute_news_chain_alignment(pick, chain)
    pick["alignment_score"] = res["alignment_score"]
    pick["alignment_reasons"] = res["reasons"]
    pick["conflict_note"] = res["conflict_note"]
    return res["action"]


def _log_outcome(payload: Dict[str, Any]) -> None:
    try:
        OUTCOMES.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(IST).isoformat(),
            "picks": [
                {
                    "symbol": p.get("symbol"),
                    "news_intent": p.get("news_intent"),
                    "repeat_n": p.get("repeat_n"),
                    "grade": (p.get("chain") or {}).get("grade"),
                    "action": p.get("action"),
                }
                for p in payload.get("picks") or []
            ],
        }
        with OUTCOMES.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("outcome log skip: %s", exc)


def _run(job_id: str) -> None:
    mgr = get_scan_job_manager()
    try:
        mgr.update(job_id, status="running", started_at=datetime.now().isoformat(), completed=0, total=4)
        _phase(job_id, "scraping")
        articles, src = scrape_market_news(force=True, limit=40)
        kept = prefilter(articles)
        _phase(
            job_id,
            "ranking",
            articles_in=len(articles),
            articles_kept=len(kept),
            scrape_source=src,
        )
        mgr.update(job_id, completed=1)

        parsed, model = rank_articles(kept)
        validated = validate_picks(parsed, kept)
        picks = list(validated.get("picks") or [])
        _set_hot(picks)
        _phase(job_id, "analysing", model=model, pick_count=len(picks))
        mgr.update(job_id, completed=2)

        for i, pick in enumerate(picks):
            _phase(job_id, "analysing", current=pick.get("symbol"))
            chain = _analyse_symbol(str(pick.get("symbol")))
            pick["chain"] = chain
            pick["action"] = _fuse(pick, chain)
            mgr.update(job_id, completed=2, current_symbol=pick.get("symbol"))
            _set_hot(picks)

        payload = {
            "success": True,
            "status": "done",
            "asof_ist": datetime.now(IST).isoformat(),
            "model": model,
            "scrape_source": src,
            "articles_in": len(articles),
            "articles_kept": len(kept),
            "picks": picks,
            "index_context": validated.get("index_context") or {},
            "rejected": validated.get("rejected") or [],
        }
        global _last_payload
        with _hot_lock:
            _last_payload = payload
        _log_outcome(payload)
        mgr.update(job_id, completed=4, current_symbol=None)
        mgr.finish(job_id, status="completed", extra_meta={"phase": "done", "payload": payload})
    except Exception as exc:
        logger.exception("ai-chain job failed")
        mgr.finish(job_id, status="failed", error_message=str(exc)[:240], extra_meta={"phase": "failed"})


def start_job() -> Dict[str, Any]:
    mgr = get_scan_job_manager()
    running = mgr.find_running("ai_chain")
    if running:
        return {"success": True, "job_id": running.id, "reused": True, "status": running.status}
    job = mgr.create(kind="ai_chain", total=4, label="AI + Chain", meta={"phase": "queued"})
    mgr.update(job.id, status="running", started_at=datetime.now().isoformat())
    t = threading.Thread(target=_run, args=(job.id,), name=f"ai-chain-{job.id}", daemon=True)
    t.start()
    return {"success": True, "job_id": job.id, "reused": False, "status": "running"}


def job_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
    mgr = get_scan_job_manager()
    snap = mgr.snapshot(job_id, include_results=True)
    if not snap:
        return None
    meta = snap.get("meta") or {}
    payload = meta.get("payload") or {}
    return {
        "success": True,
        "job_id": job_id,
        "status": snap.get("status"),
        "phase": meta.get("phase") or snap.get("status"),
        "completion_pct": snap.get("completion_pct"),
        "error_message": snap.get("error_message"),
        "current_symbol": snap.get("current_symbol") or meta.get("current"),
        **payload,
        "hot_symbols": get_hot_symbols(),
    }
