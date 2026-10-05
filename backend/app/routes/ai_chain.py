"""AI + Chain Analysis job routes."""

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.services.ai_chain_job import job_snapshot, last_payload, start_job

router = APIRouter()


@router.post("/radar/ai-chain")
async def start_ai_chain():
    settings = get_settings()
    if not (settings.openrouter_api_key or "").strip():
        raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY is not set")
    return start_job()


@router.get("/radar/ai-chain/jobs/{job_id}")
async def get_ai_chain_job(job_id: str):
    snap = job_snapshot(job_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Job not found")
    return snap


@router.get("/radar/ai-chain/last")
async def get_ai_chain_last():
    payload = last_payload() or {}
    return {"success": True, "has_data": bool(payload.get("picks")), **payload}
