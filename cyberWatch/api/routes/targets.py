"""Target enqueue and listing endpoints."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from cyberWatch.api.models import TargetEnqueueRequest, ok
from cyberWatch.api.utils.db import pg_dep
from cyberWatch.scheduler.queue import TargetQueue, TargetTask
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/targets", tags=["targets"])


@router.post("/enqueue")
async def enqueue_target(req: TargetEnqueueRequest, pool: asyncpg.Pool = Depends(pg_dep), request: Request = None):
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Target enqueue requested",
        extra={
            "request_id": request_id,
            "user_input": {"target": str(req.target), "source": req.source},
            "action": "enqueue_target",
        }
    )
    
    try:
        queue = TargetQueue()
        await queue.enqueue(TargetTask(target_ip=req.target, source=req.source))
        await queue.close()
        
        logger.info(
            "Target enqueued successfully",
            extra={
                "request_id": request_id,
                "target": str(req.target),
                "source": req.source,
                "outcome": "success",
            }
        )
        return ok({"queued": True, "target": str(req.target)})
    except Exception as exc:
        logger.error(
            f"Failed to enqueue target: {str(exc)}",
            exc_info=True,
            extra={
                "request_id": request_id,
                "target": str(req.target),
                "outcome": "error",
            }
        )
        raise


@router.get("")
async def list_targets(pool: asyncpg.Pool = Depends(pg_dep)):
    rows = await pool.fetch(
        """
        SELECT id, target_ip, source, last_seen, created_at
        FROM targets
        ORDER BY created_at DESC
        LIMIT 200
        """
    )
    data = [dict(r) for r in rows]
    return ok(data)
