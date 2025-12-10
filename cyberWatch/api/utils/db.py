"""API-scoped database and driver utilities."""
from __future__ import annotations

import os
from typing import AsyncGenerator, Optional

import asyncpg
from fastapi import Depends
from neo4j import AsyncDriver, AsyncGraphDatabase

PG_DSN = os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")

_pool: Optional[asyncpg.Pool] = None
_driver: Optional[AsyncDriver] = None


async def init_resources() -> None:
    """Initialize shared database resources."""
    global _pool, _driver
    if _pool is None:
        _pool = await asyncpg.create_pool(PG_DSN)
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


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
    assert _pool is not None
    return _pool


async def neo4j_dep() -> AsyncDriver:
    if _driver is None:
        await init_resources()
    assert _driver is not None
    return _driver
