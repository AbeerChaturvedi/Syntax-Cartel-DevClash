import hashlib
import json
from fastapi import APIRouter, HTTPException

from utils.alerting import alert_dispatcher
from utils.model_persistence import get_checkpoint_manager
from ingestion.watermark import watermark
from globals import _db_available, _db_pool, _active_model_version, _active_checkpoint_hash

router = APIRouter()

@router.get("/api/alerting/status")
async def alerting_status():
    return alert_dispatcher.status()

@router.post("/api/alerting/test")
async def alerting_test(severity: str = "HIGH"):
    """Send a synthetic alert through every configured sink."""
    return await alert_dispatcher.test_alert(severity=severity)

@router.post("/api/checkpoint/save")
async def checkpoint_save():
    """Manually snapshot the full ensemble state to disk."""
    try:
        res = get_checkpoint_manager().save()
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/checkpoint/load")
async def checkpoint_load():
    """Restore ensemble state from the latest on-disk checkpoint."""
    try:
        res = get_checkpoint_manager().load()
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/watermark")
async def watermark_status():
    """Event-time watermark + per-source staleness stats."""
    return watermark.status()

@router.get("/api/audit")
async def audit_log(limit: int = 50, event_type: str = None):
    """
    Recent audit_log rows (most recent first).
    Empty result if Postgres is unavailable — callers should treat that
    as "audit unavailable", not "no events".
    """
    if not (_db_available and _db_pool):
        return {"available": False, "rows": []}
    limit = max(1, min(limit, 500))
    async with _db_pool.acquire() as conn:
        if event_type:
            rows = await conn.fetch(
                """
                SELECT audit_id, occurred_at, actor, event_type, severity,
                       model_version, payload, prev_hash, this_hash
                FROM audit_log
                WHERE event_type = $1
                ORDER BY audit_id DESC LIMIT $2
                """,
                event_type, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT audit_id, occurred_at, actor, event_type, severity,
                       model_version, payload, prev_hash, this_hash
                FROM audit_log
                ORDER BY audit_id DESC LIMIT $1
                """,
                limit,
            )
        return {"available": True, "count": len(rows), "rows": [dict(r) for r in rows]}

@router.get("/api/audit/verify")
async def audit_verify(scan_limit: int = 1000):
    """
    Walk the most recent N audit rows and verify the hash chain is intact.
    Returns the first broken row (if any) so an operator can investigate.
    Cheap: pure read, ~O(N) sha256 hashes.
    """
    if not (_db_available and _db_pool):
        return {"available": False}
    scan_limit = max(10, min(scan_limit, 10000))
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT audit_id, actor, event_type, severity, model_version,
                   payload, prev_hash, this_hash
            FROM audit_log
            ORDER BY audit_id ASC
            LIMIT $1
            """,
            scan_limit,
        )
    if not rows:
        return {"available": True, "scanned": 0, "intact": True}

    prev_hash = None
    for r in rows:
        canonical = json.dumps(
            {
                "actor":         r["actor"],
                "event_type":    r["event_type"],
                "severity":      r["severity"],
                "model_version": r["model_version"],
                "payload":       (r["payload"] if isinstance(r["payload"], dict)
                                  else json.loads(r["payload"])),
            },
            sort_keys=True, separators=(",", ":"), default=str,
        )
        h = hashlib.sha256(((prev_hash or "") + canonical).encode("utf-8")).hexdigest()
        if h != r["this_hash"] or r["prev_hash"] != prev_hash:
            return {
                "available": True,
                "scanned": len(rows),
                "intact": False,
                "broken_at_id": r["audit_id"],
                "expected_hash": h,
                "stored_hash":   r["this_hash"],
            }
        prev_hash = r["this_hash"]

    return {"available": True, "scanned": len(rows), "intact": True}

@router.get("/api/lineage")
async def model_lineage_list():
    """Active model versions known to the system."""
    if not (_db_available and _db_pool):
        return {"available": False, "active": {
            "model_version": _active_model_version,
            "checkpoint_hash": _active_checkpoint_hash,
        }}
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT lineage_id, model_version, checkpoint_hash, components,
                   ensemble_weights, activated_at, deactivated_at
            FROM model_lineage
            ORDER BY activated_at DESC
            LIMIT 50
        """)
        return {
            "available": True,
            "active": {
                "model_version": _active_model_version,
                "checkpoint_hash": _active_checkpoint_hash,
            },
            "history": [dict(r) for r in rows],
        }
