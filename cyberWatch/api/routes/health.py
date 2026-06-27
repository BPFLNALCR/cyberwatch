"""Health and dependency status endpoints."""
from __future__ import annotations

import os

import asyncpg
from fastapi import APIRouter, Depends, Request
from neo4j import AsyncDriver

from cyberWatch.api.models import ok
from cyberWatch.api.utils.db import neo4j_dep, pg_dep
from cyberWatch.workers.worker import _pick_tool
from cyberWatch.logging_config import get_logger
from cyberWatch.scheduler.queue import TargetQueue

logger = get_logger("api")
router = APIRouter(prefix="/health", tags=["health"])


async def _check_traceroute() -> dict:
    """Check if traceroute tool is available."""
    try:
        tool = _pick_tool()
        return {"status": "healthy", "tool": tool, "message": f"Using {tool}"}
    except Exception as exc:
        return {"status": "unhealthy", "tool": None, "message": str(exc)}


async def _check_postgres(pool: asyncpg.Pool) -> dict:
    """Check PostgreSQL connectivity and basic query."""
    try:
        val = await pool.fetchval("SELECT 1")
        if val == 1:
            return {"status": "healthy", "message": "Connected"}
        return {"status": "degraded", "message": "Unexpected response"}
    except Exception as exc:
        return {"status": "unhealthy", "message": str(exc)[:100]}


async def _check_neo4j(driver: AsyncDriver) -> dict:
    """Check Neo4j connectivity."""
    try:
        async with driver.session() as session:
            result = await session.run("RETURN 1 AS ok")
            record = await result.single()
            val = record["ok"] if record else None
        if val:
            return {"status": "healthy", "message": "Connected"}
        return {"status": "degraded", "message": "Unexpected response"}
    except Exception as exc:
        # Simplify error message for display
        error_str = str(exc)
        if "Failed to establish connection" in error_str or "Connect call failed" in error_str:
            return {"status": "unhealthy", "message": "Not running (using PostgreSQL fallback)"}
        elif "localhost" in error_str or "7687" in error_str:
            return {"status": "unhealthy", "message": "Cannot connect to Neo4j service"}
        else:
            # Truncate long error messages
            return {"status": "unhealthy", "message": error_str[:100] + "..." if len(error_str) > 100 else error_str}


async def _check_redis() -> dict:
    """Check Redis connectivity and queue depth."""
    try:
        queue = TargetQueue()
        await queue.connect()
        length = await queue.length()
        await queue.close()
        return {
            "status": "healthy",
            "message": "Connected",
            "queue_depth": length,
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "message": str(exc)[:100],
            "queue_depth": None,
        }


@router.get("")
async def health(  # pragma: no cover - simple orchestration
    request: Request,
    pool: asyncpg.Pool = Depends(pg_dep),
    driver: AsyncDriver = Depends(neo4j_dep),
):
    """
    Comprehensive health check for all dependencies.
    
    Returns status of:
    - PostgreSQL database
    - Redis queue
    - Neo4j graph database
    - Traceroute tool availability
    """
    traceroute = await _check_traceroute()
    postgres = await _check_postgres(pool)
    redis = await _check_redis()
    neo4j = await _check_neo4j(driver)
    
    # Determine overall status
    checks = [postgres, redis, traceroute]  # Core dependencies
    optional_checks = [neo4j]  # Optional dependencies
    
    core_healthy = all(c.get("status") == "healthy" for c in checks)
    any_unhealthy = any(c.get("status") == "unhealthy" for c in checks)
    
    if any_unhealthy:
        overall_status = "unhealthy"
    elif core_healthy:
        overall_status = "healthy"
    else:
        overall_status = "degraded"
    
    logger.info(
        "Health check performed",
        extra={
            "overall_status": overall_status,
            "postgres": postgres.get("status"),
            "redis": redis.get("status"),
            "neo4j": neo4j.get("status"),
            "traceroute": traceroute.get("status"),
            "outcome": "success",
        }
    )
    
    return ok(
        {
            "status": overall_status,
            "api_base": str(request.base_url).rstrip("/"),
            "checks": {
                "postgres": postgres,
                "redis": redis,
                "neo4j": neo4j,
                "traceroute": traceroute,
            }
        }
    )
