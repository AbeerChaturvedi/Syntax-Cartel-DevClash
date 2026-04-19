import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ingestion.simulator import simulator
from utils.logger import api_log
from utils.config import CRISIS_PRESETS, ENABLE_SIMULATOR

router = APIRouter()

class StressTestRequest(BaseModel):
    intensity: float = Field(default=0.8, ge=0.1, le=1.0)
    duration_seconds: int = Field(default=30, ge=5, le=300)

class CrisisPresetRequest(BaseModel):
    scenario: str
    intensity: float = Field(default=0.8, ge=0.1, le=1.0)
    duration_seconds: int = Field(default=45, ge=5, le=300)

@router.get("/api/crisis-presets")
async def get_crisis_presets():
    """Get available crisis simulation presets."""
    return CRISIS_PRESETS

@router.post("/api/stress-test/activate")
async def activate_stress_test(request: StressTestRequest):
    """
    Activate crisis simulation.
    Injects 2008-style correlation breakdown and volatility spike.
    Requires ENABLE_SIMULATOR=true.
    """
    if not ENABLE_SIMULATOR:
        raise HTTPException(status_code=400, detail="Crisis simulation requires ENABLE_SIMULATOR=true")
    simulator.activate_crisis(intensity=request.intensity)
    
    # Auto-deactivate after duration
    async def auto_deactivate():
        await asyncio.sleep(request.duration_seconds)
        simulator.deactivate_crisis()
    
    asyncio.create_task(auto_deactivate())

    api_log.info(
        f"Stress test activated: intensity={request.intensity}, duration={request.duration_seconds}s",
    )

    return {
        "status": "crisis_activated",
        "intensity": request.intensity,
        "duration_seconds": request.duration_seconds,
        "message": f"Stress test active. Correlations spiking to {request.intensity:.0%}. "
                   f"Auto-deactivating in {request.duration_seconds}s.",
    }

@router.post("/api/stress-test/preset")
async def activate_crisis_preset(request: CrisisPresetRequest):
    """Activate a named crisis scenario preset."""
    if not ENABLE_SIMULATOR:
        raise HTTPException(status_code=400, detail="Crisis simulation requires ENABLE_SIMULATOR=true")
    preset = CRISIS_PRESETS.get(request.scenario)
    if not preset and request.scenario != "custom":
        raise HTTPException(status_code=400, detail=f"Unknown preset: {request.scenario}")

    intensity = request.intensity if request.scenario == "custom" else preset["intensity"]
    duration = request.duration_seconds if request.scenario == "custom" else preset["duration_seconds"]

    simulator.activate_crisis(intensity=intensity)

    async def auto_deactivate():
        await asyncio.sleep(duration)
        simulator.deactivate_crisis()

    asyncio.create_task(auto_deactivate())

    return {
        "status": "crisis_activated",
        "scenario": request.scenario,
        "name": preset["name"] if preset else "Custom",
        "description": preset["description"] if preset else "User-defined parameters",
        "intensity": intensity,
        "duration_seconds": duration,
    }

@router.post("/api/stress-test/deactivate")
async def deactivate_stress_test():
    """Manually deactivate crisis simulation."""
    simulator.deactivate_crisis()
    return {"status": "crisis_deactivated", "message": "Markets returning to normal conditions."}
