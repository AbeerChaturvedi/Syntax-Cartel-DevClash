import asyncio
from fastapi import APIRouter, HTTPException

from ingestion.simulator import simulator
from models.ensemble import ensemble
from utils.logger import api_log
from globals import _replay_state

router = APIRouter()

@router.post("/api/replay/start")
async def start_replay(request: dict):
    """Start historical replay through the live pipeline using the simulator."""
    global _replay_state

    if _replay_state["running"]:
        raise HTTPException(status_code=409, detail="Replay already running")

    start_date = request.get("start_date", "2008-09-10")
    end_date = request.get("end_date", "2008-09-20")
    speed_mult = request.get("speed_multiplier", 60)

    # Simulate N days of tick data
    from datetime import datetime
    d0 = datetime.strptime(start_date, "%Y-%m-%d")
    d1 = datetime.strptime(end_date, "%Y-%m-%d")
    n_days = max(1, (d1 - d0).days)
    total_frames = n_days * 390 * 4  # 4Hz × 390 min/day
    delay = max(0.001, 0.25 / speed_mult)

    _replay_state["running"] = True
    _replay_state["progress"] = 0
    _replay_state["frames_processed"] = 0
    _replay_state["total_frames"] = total_frames

    async def _run_replay():
        try:
            # Simulate a crisis ramp during replay
            for frame in range(total_frames):
                if not _replay_state["running"]:
                    break

                progress = frame / total_frames
                # Ramp crisis intensity: 0→peak→decay
                if progress < 0.3:
                    intensity = 0.0
                elif progress < 0.7:
                    intensity = min(0.9, (progress - 0.3) * 2.5)
                else:
                    intensity = max(0, 0.9 - (progress - 0.7) * 3)

                if intensity > 0.05:
                    simulator.activate_crisis(intensity=intensity)
                else:
                    simulator.deactivate_crisis()

                tick = simulator.generate_tick()
                await ensemble.process_tick(tick)

                _replay_state["frames_processed"] = frame + 1
                _replay_state["progress"] = (frame + 1) / total_frames

                if frame % 20 == 0:
                    await asyncio.sleep(delay)

            simulator.deactivate_crisis()
        except Exception as e:
            api_log.error(f"Replay failed: {e}")
        finally:
            _replay_state["running"] = False

    asyncio.create_task(_run_replay())
    return {"ok": True, "status": _replay_state}

@router.get("/api/replay/status")
async def get_replay_status():
    """Get replay progress."""
    return _replay_state

@router.post("/api/replay/stop")
async def stop_replay():
    """Stop ongoing replay."""
    global _replay_state
    _replay_state["running"] = False
    simulator.deactivate_crisis()
    return {"ok": True}
