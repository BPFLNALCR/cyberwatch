"""Health and dependency status endpoints."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Request
from neo4j import AsyncDriver

from cyberWatch.api.models import ok
from cyberWatch.api.utils.db import neo4j_dep, pg_dep
from cyberWatch.workers.worker import _pick_tool
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/health", tags=["health"])


async def _check_traceroute() -> dict:
    try:
        tool = _pick_tool()
        return {"available": True, "tool": tool, "message": f"Using {tool}"}
    except Exception as exc:
        return {"available": False, "tool": None, "message": str(exc)}


async def _check_postgres(pool: asyncpg.Pool) -> dict:
    try:
        val = await pool.fetchval("SELECT 1")
        return {"ok": val == 1, "message": "Connected" if val == 1 else "Unexpected response"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


async def _check_neo4j(driver: AsyncDriver) -> dict:
    try:
        async with driver.session() as session:
            result = await session.run("RETURN 1 AS ok")
            record = await result.single()
            val = record["ok"] if record else None
        return {"ok": bool(val), "message": "Connected" if val else "Unexpected response"}
    except Exception as exc:
        # Simplify error message for display
        error_str = str(exc)
        if "Failed to establish connection" in error_str or "Connect call failed" in error_str:
            return {"ok": False, "message": "Not running (using PostgreSQL fallback)"}
        elif "localhost" in error_str or "7687" in error_str:
            return {"ok": False, "message": "Cannot connect to Neo4j service"}
        else:
            # Truncate long error messages
            return {"ok": False, "message": error_str[:100] + "..." if len(error_str) > 100 else error_str}


@router.get("")
async def health(  # pragma: no cover - simple orchestration
    request: Request,
    pool: asyncpg.Pool = Depends(pg_dep),
    driver: AsyncDriver = Depends(neo4j_dep),
):
    traceroute = await _check_traceroute()
    postgres = await _check_postgres(pool)
    neo4j = await _check_neo4j(driver)
    return ok(
        {
            "api_base": str(request.base_url).rstrip("/"),
            "traceroute": traceroute,
            "postgres": postgres,
            "neo4j": neo4j,
        }
    )
