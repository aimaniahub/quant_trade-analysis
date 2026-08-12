"""
Background scan job registry with optional Redis durability.

Long F&O scans (stocks quant, radar, high-volume) should not block a single
HTTP request for minutes. Clients start a job, then poll progress until done.

Storage:
- L1: in-process memory (fast, always on)
- L2: Redis when REDIS_ENABLED + connected (survives restarts, multi-worker ready for reads)

Note: active asyncio workers still live in the process that started them.
After a hard restart, running jobs are marked *interrupted* on recovery;
completed job results remain available from Redis.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _settings():
    from app.core.config import get_settings
    return get_settings()


@dataclass
class ScanJob:
    id: str
    kind: str  # stocks_scan | radar | high_volume | bulk_oc
    status: str = "queued"  # queued | running | completed | failed | cancelled | interrupted
    label: str = ""
    total: int = 0
    completed: int = 0
    failed: int = 0
    rate_limited_skips: int = 0
    current_symbol: Optional[str] = None
    completion_pct: float = 0.0
    partial: bool = False
    results: List[Any] = field(default_factory=list)
    errors: List[Any] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    pending_symbols: List[str] = field(default_factory=list)
    failed_symbols: List[str] = field(default_factory=list)

    def to_public(self, include_results: bool = True) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "label": self.label,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "rate_limited_skips": self.rate_limited_skips,
            "current_symbol": self.current_symbol,
            "completion_pct": self.completion_pct,
            "partial": self.partial,
            "error_count": len(self.errors),
            "meta": self.meta,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pending_count": len(self.pending_symbols),
            "failed_symbols": list(self.failed_symbols)[:50],
            "storage": "redis+memory",  # filled by manager when known
        }
        if include_results:
            d["results"] = self.results
            d["errors"] = self.errors if self.errors else None
        return d

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "label": self.label,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "rate_limited_skips": self.rate_limited_skips,
            "current_symbol": self.current_symbol,
            "completion_pct": self.completion_pct,
            "partial": self.partial,
            "results": self.results,
            "errors": self.errors,
            "meta": self.meta,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pending_symbols": self.pending_symbols,
            "failed_symbols": self.failed_symbols,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ScanJob":
        return cls(
            id=d["id"],
            kind=d.get("kind") or "unknown",
            status=d.get("status") or "queued",
            label=d.get("label") or "",
            total=int(d.get("total") or 0),
            completed=int(d.get("completed") or 0),
            failed=int(d.get("failed") or 0),
            rate_limited_skips=int(d.get("rate_limited_skips") or 0),
            current_symbol=d.get("current_symbol"),
            completion_pct=float(d.get("completion_pct") or 0),
            partial=bool(d.get("partial")),
            results=list(d.get("results") or []),
            errors=list(d.get("errors") or []),
            meta=dict(d.get("meta") or {}),
            error_message=d.get("error_message"),
            created_at=d.get("created_at") or _now_iso(),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            pending_symbols=list(d.get("pending_symbols") or []),
            failed_symbols=list(d.get("failed_symbols") or []),
        )


class ScanJobManager:
    """Thread-safe L1 memory + L2 Redis job store + background runner registry."""

    def __init__(self, max_jobs: int = 40, ttl_seconds: float = 3600.0):
        self._jobs: Dict[str, ScanJob] = {}
        self._lock = threading.RLock()
        self._max_jobs = max_jobs
        self._ttl_seconds = float(ttl_seconds)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._last_persist: Dict[str, float] = {}
        self._append_counts: Dict[str, int] = {}
        self._redis_writes = 0
        self._redis_reads = 0
        self._redis_errors = 0

    # ── Redis keys ───────────────────────────────────────────────

    def _job_key(self, job_id: str) -> str:
        from app.services.redis_client import key
        return key("job", job_id)

    def _index_key(self, kind: Optional[str] = None) -> str:
        from app.services.redis_client import key
        return key("jobs", kind or "all")

    def _job_ttl(self) -> int:
        try:
            return int(_settings().redis_job_ttl_seconds or self._ttl_seconds)
        except Exception:
            return int(self._ttl_seconds)

    def _persist_interval(self) -> float:
        try:
            return float(_settings().redis_job_persist_interval or 1.5)
        except Exception:
            return 1.5

    def _persist(self, job: ScanJob, force: bool = False) -> None:
        """Write job to Redis (throttled unless force)."""
        from app.services import redis_client as rc

        if not rc.is_available():
            return
        now = time.time()
        last = self._last_persist.get(job.id, 0.0)
        if not force and (now - last) < self._persist_interval():
            return
        try:
            ok = rc.set_json(self._job_key(job.id), job.to_dict(), ttl=self._job_ttl())
            if ok:
                # Score = created epoch for ordering
                try:
                    score = datetime.fromisoformat(job.created_at).timestamp()
                except Exception:
                    score = now
                rc.zadd(self._index_key("all"), {job.id: score})
                rc.zadd(self._index_key(job.kind), {job.id: score})
                rc.expire(self._index_key("all"), self._job_ttl() + 60)
                rc.expire(self._index_key(job.kind), self._job_ttl() + 60)
                self._last_persist[job.id] = now
                self._redis_writes += 1
            else:
                self._redis_errors += 1
        except Exception as e:
            self._redis_errors += 1
            logger.debug("[scan_jobs] redis persist %s: %s", job.id, e)

    def _load_from_redis(self, job_id: str) -> Optional[ScanJob]:
        from app.services import redis_client as rc

        if not rc.is_available():
            return None
        try:
            raw = rc.get_json(self._job_key(job_id))
            if not raw or not isinstance(raw, dict):
                return None
            self._redis_reads += 1
            return ScanJob.from_dict(raw)
        except Exception as e:
            self._redis_errors += 1
            logger.debug("[scan_jobs] redis load %s: %s", job_id, e)
            return None

    def _purge_old(self) -> None:
        now = time.time()
        dead = []
        for jid, job in self._jobs.items():
            try:
                created = datetime.fromisoformat(job.created_at).timestamp()
            except Exception:
                created = now
            if now - created > self._ttl_seconds:
                dead.append(jid)
        for jid in dead:
            self._jobs.pop(jid, None)
            self._last_persist.pop(jid, None)
            self._append_counts.pop(jid, None)
        if len(self._jobs) > self._max_jobs:
            finished = sorted(
                [
                    (j.finished_at or j.created_at, j.id)
                    for j in self._jobs.values()
                    if j.status in ("completed", "failed", "cancelled", "interrupted")
                ]
            )
            for _, jid in finished[: max(0, len(self._jobs) - self._max_jobs)]:
                self._jobs.pop(jid, None)

    # ── Public API ───────────────────────────────────────────────

    def create(
        self,
        kind: str,
        total: int = 0,
        label: str = "",
        meta: Optional[Dict[str, Any]] = None,
        pending_symbols: Optional[List[str]] = None,
    ) -> ScanJob:
        with self._lock:
            self._purge_old()
            jid = f"{kind}-{uuid.uuid4().hex[:12]}"
            job = ScanJob(
                id=jid,
                kind=kind,
                label=label or kind,
                total=total,
                meta=meta or {},
                pending_symbols=list(pending_symbols or []),
            )
            self._jobs[jid] = job
            self._persist(job, force=True)
            return job

    def get(self, job_id: str) -> Optional[ScanJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return job
            loaded = self._load_from_redis(job_id)
            if loaded:
                self._jobs[job_id] = loaded
            return loaded

    def snapshot(self, job_id: str, include_results: bool = True) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                job = self._load_from_redis(job_id)
                if job:
                    self._jobs[job_id] = job
            if not job:
                return None
            pub = job.to_public(include_results=include_results)
            from app.services import redis_client as rc
            pub["storage"] = "redis+memory" if rc.is_available() else "memory"
            return pub

    def update(self, job_id: str, **fields: Any) -> Optional[ScanJob]:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_from_redis(job_id)
            if not job:
                return None
            self._jobs[job_id] = job
            for k, v in fields.items():
                if hasattr(job, k):
                    setattr(job, k, v)
            if job.total > 0:
                job.completion_pct = round(
                    100.0 * job.completed / max(job.total, 1), 1
                )
            self._persist(job, force=False)
            return job

    def append_result(self, job_id: str, row: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.results.append(row)
            job.completed += 1
            if job.total > 0:
                job.completion_pct = round(
                    100.0 * job.completed / max(job.total, 1), 1
                )
            n = self._append_counts.get(job_id, 0) + 1
            self._append_counts[job_id] = n
            # Force every 5 rows so UI recovery is decent
            self._persist(job, force=(n % 5 == 0))

    def append_error(
        self,
        job_id: str,
        symbol: str,
        error: str,
        rate_limited: bool = False,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.errors.append(
                {"symbol": symbol, "error": error, "rate_limited": rate_limited}
            )
            job.failed += 1
            if rate_limited:
                job.rate_limited_skips += 1
            if symbol not in job.failed_symbols:
                job.failed_symbols.append(symbol)
            if job.total > 0:
                job.completion_pct = round(
                    100.0 * job.completed / max(job.total, 1), 1
                )
            self._persist(job, force=False)

    def set_current(self, job_id: str, symbol: Optional[str]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.current_symbol = symbol
                # progress-only: throttled persist
                self._persist(job, force=False)

    def set_results(self, job_id: str, results: List[Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.results = list(results)
                self._persist(job, force=True)

    def append_result_raw(self, job_id: str, row: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.results.append(row)
                n = self._append_counts.get(job_id, 0) + 1
                self._append_counts[job_id] = n
                self._persist(job, force=(n % 5 == 0))

    def note_error_only(
        self,
        job_id: str,
        symbol: str,
        error: str,
        rate_limited: bool = False,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.errors.append(
                {"symbol": symbol, "error": error, "rate_limited": rate_limited}
            )
            if rate_limited:
                job.rate_limited_skips += 1
            if symbol not in job.failed_symbols:
                job.failed_symbols.append(symbol)
            self._persist(job, force=False)

    def finish(
        self,
        job_id: str,
        status: str = "completed",
        error_message: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            job.finished_at = _now_iso()
            job.current_symbol = None
            job.error_message = error_message
            job.partial = job.completed < job.total and job.total > 0
            if job.total > 0:
                job.completion_pct = round(
                    100.0 * job.completed / max(job.total, 1), 1
                )
            if extra_meta:
                job.meta.update(extra_meta)
            job.pending_symbols = list(job.failed_symbols)
            self._persist(job, force=True)

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "running"
                job.started_at = job.started_at or _now_iso()
                self._persist(job, force=True)

    def list_jobs(self, kind: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        from app.services import redis_client as rc

        with self._lock:
            self._purge_old()
            seen = set()
            out: List[ScanJob] = []

            # Prefer Redis index for durability across restarts
            if rc.is_available():
                ids = rc.zrevrange(self._index_key(kind), 0, max(limit * 2, 20) - 1)
                for jid in ids:
                    if jid in seen:
                        continue
                    job = self._jobs.get(jid) or self._load_from_redis(jid)
                    if job:
                        if kind and job.kind != kind:
                            continue
                        self._jobs[jid] = job
                        seen.add(jid)
                        out.append(job)

            for job in self._jobs.values():
                if job.id in seen:
                    continue
                if kind and job.kind != kind:
                    continue
                out.append(job)
                seen.add(job.id)

            out.sort(key=lambda j: j.created_at, reverse=True)
            pubs = []
            for j in out[:limit]:
                p = j.to_public(include_results=False)
                p["storage"] = "redis+memory" if rc.is_available() else "memory"
                pubs.append(p)
            return pubs

    def register_task(self, job_id: str, task: asyncio.Task) -> None:
        self._running_tasks[job_id] = task

        def _done(_t: asyncio.Task) -> None:
            self._running_tasks.pop(job_id, None)

        task.add_done_callback(_done)

    def cancel(self, job_id: str) -> bool:
        task = self._running_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            self.finish(job_id, status="cancelled", error_message="cancelled by client")
            return True
        return False

    def recover_orphans(self) -> int:
        """
        On startup: any Redis job still 'running'/'queued' has no worker —
        mark interrupted so UI can retry-failed.
        """
        from app.services import redis_client as rc

        if not rc.is_available():
            return 0
        n = 0
        try:
            ids = rc.zrevrange(self._index_key("all"), 0, 99)
            for jid in ids:
                job = self._load_from_redis(jid)
                if not job:
                    continue
                if job.status in ("running", "queued") and jid not in self._running_tasks:
                    job.status = "interrupted"
                    job.error_message = (
                        job.error_message
                        or "Worker lost (process restart). Use Retry failed / re-scan."
                    )
                    job.finished_at = job.finished_at or _now_iso()
                    job.partial = True
                    job.pending_symbols = list(job.failed_symbols) or list(
                        job.pending_symbols or []
                    )
                    with self._lock:
                        self._jobs[jid] = job
                        self._persist(job, force=True)
                    n += 1
                    logger.info("[scan_jobs] marked orphan interrupted: %s", jid)
        except Exception as e:
            logger.warning("[scan_jobs] recover_orphans: %s", e)
        return n

    def stats(self) -> Dict[str, Any]:
        from app.services import redis_client as rc

        with self._lock:
            return {
                "memory_jobs": len(self._jobs),
                "running_workers": len(self._running_tasks),
                "redis": rc.status(),
                "redis_writes": self._redis_writes,
                "redis_reads": self._redis_reads,
                "redis_errors": self._redis_errors,
                "ttl_seconds": self._job_ttl(),
            }


_manager: Optional[ScanJobManager] = None
_mgr_lock = threading.Lock()


def get_scan_job_manager() -> ScanJobManager:
    global _manager
    with _mgr_lock:
        if _manager is None:
            try:
                ttl = float(_settings().redis_job_ttl_seconds or 3600)
            except Exception:
                ttl = 3600.0
            _manager = ScanJobManager(ttl_seconds=ttl)
        return _manager
