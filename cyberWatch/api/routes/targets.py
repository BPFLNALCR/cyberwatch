"""Target enqueue and listing endpoints."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from cyberWatch.api.models import TargetEnqueueRequest, ok
from cyberWatch.api.utils.db import pg_dep
from cyberWatch.scheduler.queue import TargetQueue, TargetTask

router = APIRouter(prefix="/targets", tags=["targets"])


@router.post("/enqueue")
async def enqueue_target(req: TargetEnqueueRequest, pool: asyncpg.Pool = Depends(pg_dep)):
    queue = TargetQueue()
    await queue.enqueue(TargetTask(target_ip=req.target, source=req.source))
    await queue.close()
    return ok({"queued": True, "target": str(req.target)})


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
