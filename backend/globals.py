import json
from collections import deque
from typing import List, Optional
from fastapi import WebSocket

from utils.config import DEFAULT_TICK_RATE, DATA_MODE
from utils.logger import ws_log
from utils.model_persistence import CHECKPOINT_VERSION

class ConnectionManager:
    """Manages WebSocket connections for live dashboard broadcasting."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        ws_log.info("Client connected", extra={"client_count": len(self.active_connections)})

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            ws_log.info("Client disconnected", extra={"client_count": len(self.active_connections)})

    async def broadcast(self, data: dict):
        """Broadcast to all connected clients — serialize once, fan out."""
        if not self.active_connections:
            return
        
        message = json.dumps(data, default=str)
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                dead_connections.append(connection)
                ws_log.warning(f"Failed to send to client: {e}")
        
        for dead in dead_connections:
            self.disconnect(dead)

# Global variables moved from main.py
manager = ConnectionManager()

_asset_id_cache = {}
_db_pool = None
_db_available = False

_pipeline_task = None
_checkpoint_task = None
_pipeline_running = False
_tick_rate = DEFAULT_TICK_RATE
_data_mode = DATA_MODE  # "simulator" | "finnhub" | "hybrid"
_finnhub = None
_last_crisis_ckpt_ts = 0.0

_news_cache = {"data": None, "timestamp": 0.0}

import time
_system_metrics = {
    "start_time": time.time(),
    "total_ticks_processed": 0,
    "db_writes": 0,
    "crisis_events": 0,
    "pipeline_errors": 0,
    "db_errors": 0,
    "latency_ms_p95": 0.0,
    "latency_hist": deque(maxlen=1000),
    "peak_ciss": 0.0,
    "peak_combined": 0.0,
    "total_broadcasts": 0,
    "avg_pipeline_latency_ms": 0.0,
    "pipeline_latency_samples": [],
}

_active_model_version = CHECKPOINT_VERSION
_active_checkpoint_hash = "cold-start"

_backtest_state = {"running": False, "progress": 0, "results": None}
_replay_state = {"running": False, "progress": 0, "frames_processed": 0, "total_frames": 0}
_replay_engine = None
