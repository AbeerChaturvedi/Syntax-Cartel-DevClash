import asyncio
from fastapi import APIRouter

from globals import _finnhub
from utils.logger import api_log

router = APIRouter()

@router.get("/api/finnhub/status")
async def finnhub_status():
    """Get Finnhub WebSocket connection status and live data metrics."""
    if not _finnhub:
        return {"enabled": False, "reason": "No Finnhub API key configured"}
    return {"enabled": True, **_finnhub.get_status()}

@router.post("/api/historical/backfill")
async def trigger_backfill(
    start_date: str = "2019-01-01",
    end_date: str = None,
):
    """
    Trigger historical data backfill from Polygon.io.
    Runs in background; check status via GET /api/historical/status.
    """
    from ingestion.historical_loader import historical_loader

    async def _run_backfill():
        try:
            await historical_loader.backfill(start_date=start_date, end_date=end_date)
        except Exception as e:
            api_log.error(f"Backfill error: {e}")

    asyncio.create_task(_run_backfill())
    return {"ok": True, "message": "Backfill started in background", "start_date": start_date}


@router.get("/api/historical/status")
async def historical_status():
    """Get historical data cache status."""
    from ingestion.historical_loader import historical_loader
    return historical_loader.get_status()
