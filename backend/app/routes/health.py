from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "OptionGreek API"
    }


@router.get("/ready")
async def readiness_check():
    """Readiness check endpoint."""
    return {
        "status": "ready",
        "dependencies": {
            "fyers_api": "pending",  # Will be updated when connected
            "grok_api": "pending",   # Will be updated when connected
        }
    }
