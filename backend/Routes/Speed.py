from fastapi import APIRouter, HTTPException

from utils.config import SPEED_PRESETS
from utils.logger import api_log
import globals as g

router = APIRouter()

@router.post("/api/speed/{mode}")
async def set_pipeline_speed(mode: str):
    """Adjust pipeline tick rate for demo purposes."""
    rate = SPEED_PRESETS.get(mode)
    if rate is None:
        raise HTTPException(status_code=400, detail=f"Unknown speed: {mode}. Use: {list(SPEED_PRESETS.keys())}")
    
    g._tick_rate = rate
    api_log.info(f"Speed changed to {mode} ({round(1/rate, 1)} Hz)")
    return {"speed": mode, "tick_rate_hz": round(1 / rate, 1)}
