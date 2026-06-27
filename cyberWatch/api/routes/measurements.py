"""Measurement-related endpoints."""
from __future__ import annotations

from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from cyberWatch.api.models import MeasurementDetail, MeasurementSummary, ok, err
from cyberWatch.api.utils.db import pg_dep
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/measurements", tags=["measurements"])


async def _fetch_measurement(pool: asyncpg.Pool, mid: int) -> Optional[asyncpg.Record]:
    return await pool.fetchrow(
        """
        SELECT m.id, t.target_ip as target, m.tool, m.started_at, m.completed_at, m.success, m.raw_output
        FROM measurements m
        JOIN targets t ON t.id = m.target_id
        WHERE m.id = $1
        """,
        mid,
    )


@router.get("/latest")
async def latest_measurement(
    target: str = Query(..., description="IP or domain of target"),
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Fetching latest measurement",
        extra={"request_id": request_id, "user_input": {"target": target}}
    )
    
    row = await pool.fetchrow(
        """
        SELECT m.id, t.target_ip as target, m.tool, m.started_at, m.completed_at, m.success, m.raw_output
        FROM measurements m
        JOIN targets t ON t.id = m.target_id
        WHERE t.target_ip = $1
        ORDER BY m.started_at DESC
        LIMIT 1
        """,
        target,
    )
    if not row:
        raise HTTPException(status_code=404, detail="No measurement for target")
    return ok(MeasurementDetail(**dict(row)))


@router.get("/{measurement_id}")
async def get_measurement(measurement_id: int, pool: asyncpg.Pool = Depends(pg_dep)):
    row = await _fetch_measurement(pool, measurement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Measurement not found")
    return ok(MeasurementDetail(**dict(row)))


@router.get("/hops/{measurement_id}")
async def get_hops(measurement_id: int, pool: asyncpg.Pool = Depends(pg_dep)):
    rows = await pool.fetch(
        """
        SELECT hop_number AS hop, hop_ip AS ip, rtt_ms, asn, org_name AS org
        FROM hops
        WHERE measurement_id = $1
        ORDER BY hop_number ASC
        """,
        measurement_id,
    )
    return ok([dict(r) for r in rows])
