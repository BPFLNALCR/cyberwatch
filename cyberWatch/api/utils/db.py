"""API-scoped database and driver utilities.

Start failures were caused by hard dependencies on Postgres and Neo4j. We now
try to create these connections opportunistically and downgrade to 503s at
request time instead of crashing the process during startup.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator, Optional

import asyncpg
from fastapi import Depends, HTTPException, status
from neo4j import AsyncDriver, AsyncGraphDatabase

from cyberWatch.logging_config import get_logger

logger = get_logger("db")


def _clean(val: str | None, default: str) -> str:
    """
    Clean environment variable values that may have spurious quotes or brackets.
    
    This handles Windows environment parsing issues where values may be wrapped
    in quotes or have trailing brackets from shell expansion.
    """
    if not val:
        return default
    cleaned = val.strip().strip("\"").strip("'").rstrip("]").rstrip("\"")
    return cleaned or default


PG_DSN = _clean(os.getenv("CYBERWATCH_PG_DSN"), "postgresql://postgres:postgres@localhost:5432/cyberWatch")
NEO4J_URI = _clean(os.getenv("NEO4J_URI"), "bolt://localhost:7687")
NEO4J_USER = _clean(os.getenv("NEO4J_USER"), "neo4j")
NEO4J_PASSWORD = _clean(os.getenv("NEO4J_PASSWORD"), "neo4j")

_pool: Optional[asyncpg.Pool] = None
_driver: Optional[AsyncDriver] = None


async def init_resources() -> None:
    """Initialize shared database resources without failing app startup."""
    global _pool, _driver

    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(PG_DSN)
        except Exception as exc:  # pragma: no cover - connection bootstrap
            logger.warning("PostgreSQL pool init failed: %s", exc)
            _pool = None

    if _driver is None:
        try:
            _driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        except Exception as exc:  # pragma: no cover - connection bootstrap
            logger.warning("Neo4j driver init failed: %s", exc)
            _driver = None


async def close_resources() -> None:
    """Close shared resources."""
    global _pool, _driver
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _driver is not None:
        await _driver.close()
        _driver = None


async def pg_dep() -> asyncpg.Pool:
    if _pool is None:
        await init_resources()
    if _pool is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL unavailable")
    return _pool


async def neo4j_dep() -> AsyncDriver:
    if _driver is None:
        await init_resources()
    if _driver is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Neo4j unavailable")
    return _driver


def get_pg_pool() -> Optional[asyncpg.Pool]:
    """Return the current PostgreSQL pool, or None if not initialized."""
    return _pool
