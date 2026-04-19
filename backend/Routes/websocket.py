import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from utils.logger import ws_log
from utils.config import API_KEY
from globals import manager

router = APIRouter()

@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    Live dashboard WebSocket — streams ML scores + market data.

    Auth: when API_KEY is set the client must present it via either:
      · `X-API-Key` request header (preferred — proxies forward it)
      · `?api_key=…` query string (fallback for browser clients that
        cannot set custom headers on `new WebSocket(...)`)

    A bad/missing key closes the socket with policy-violation 1008
    *before* it is registered with the connection manager — so
    unauthenticated clients can't grow our memory footprint.
    """
    if API_KEY:
        provided = (
            websocket.headers.get("x-api-key")
            or websocket.query_params.get("api_key", "")
        )
        if provided != API_KEY:
            ws_log.warning(
                "ws auth rejected",
                extra={"client": websocket.client.host if websocket.client else "?"},
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle client messages
            data = await websocket.receive_text()
            msg = json.loads(data)

            # Handle client commands
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
