"""Async PostgreSQL helper functions for measurement storage and enrichment."""
from __future__ import annotations

import asyncpg
from asyncpg import Connection, Pool
from typing import Iterable, List, Optional, Sequence
from datetime import datetime


async def create_pool(dsn: str) -> Pool:
    """Initialize an asyncpg connection pool."""
    return await asyncpg.create_pool(dsn)


async def _get_or_create_target(
    conn: asyncpg.Connection,
    target_ip: str,
    *,
    source: Optional[str] = None,
) -> int:
    """Return target id, inserting if needed."""
    existing = await conn.fetchrow(
        "SELECT id FROM targets WHERE target_ip = $1",
        target_ip,
    )
    if existing:
        return int(existing["id"])

    inserted = await conn.fetchval(
        "INSERT INTO targets (target_ip, source) VALUES ($1, $2) RETURNING id",
        target_ip,
        source or "static",
    )
    return int(inserted)


async def insert_measurement(
    pool: Pool,
    *,
    target_ip: str,
    tool: str,
    started_at: datetime,
    completed_at: Optional[datetime],
    success: bool,
    raw_output: str,
    hops: Iterable[tuple[int, Optional[str], Optional[float]]],
    source: Optional[str] = None,
) -> int:
    """Insert a measurement and its hops; returns measurement id."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            target_id = await _get_or_create_target(conn, target_ip, source=source)
            measurement_id = await conn.fetchval(
                """
                INSERT INTO measurements (target_id, tool, started_at, completed_at, success, raw_output)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                target_id,
                tool,
                started_at,
                completed_at,
                success,
                raw_output,
            )
            for hop_number, hop_ip, rtt_ms in hops:
                await conn.execute(
                    """
                    INSERT INTO hops (measurement_id, hop_number, hop_ip, rtt_ms)
                    VALUES ($1, $2, $3, $4)
                    """,
                    measurement_id,
                    hop_number,
                    hop_ip,
                    rtt_ms,
                )
            await conn.execute(
                "UPDATE targets SET last_seen = $1 WHERE id = $2",
                completed_at or started_at,
                target_id,
            )
            return int(measurement_id)


async def fetch_unenriched_hops(pool: Pool, limit: int = 200) -> List[asyncpg.Record]:
    """Fetch hops lacking ASN enrichment."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT h.id, h.measurement_id, h.hop_number, h.hop_ip, h.rtt_ms
            FROM hops h
            JOIN measurements m ON m.id = h.measurement_id
            WHERE h.hop_ip IS NOT NULL
              AND h.asn IS NULL
              AND m.success = TRUE
            ORDER BY m.started_at ASC, h.hop_number ASC
            LIMIT $1
            """,
            limit,
        )
        return list(rows)


async def update_hop_enrichment(
    pool: Pool,
    hop_id: int,
    *,
    asn: Optional[int],
    prefix: Optional[str],
    org_name: Optional[str],
    country_code: Optional[str],
) -> None:
    """Persist enrichment details for a hop."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE hops
            SET asn = $2, prefix = $3, org_name = $4, country_code = $5
            WHERE id = $1
            """,
            hop_id,
            asn,
            prefix,
            org_name,
            country_code,
        )


async def mark_measurement_enriched(pool: Pool, measurement_id: int) -> None:
    """Flag a measurement as enriched."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE measurements SET enriched = TRUE, enriched_at = $2 WHERE id = $1",
            measurement_id,
            datetime.utcnow(),
        )


async def remaining_unenriched_hops(pool: Pool, measurement_id: int) -> int:
    """Return count of hops still missing ASN data for a measurement."""
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT COUNT(*) FROM hops WHERE measurement_id = $1 AND asn IS NULL AND hop_ip IS NOT NULL",
            measurement_id,
        )
        return int(value or 0)


async def fetch_measurements_for_graph(pool: Pool, limit: int = 50) -> List[asyncpg.Record]:
    """Fetch enriched measurements that have not yet been built into the graph."""
    async with pool.acquire() as conn:
        return list(
            await conn.fetch(
                """
                SELECT id, started_at
                FROM measurements
                WHERE enriched = TRUE AND graph_built = FALSE
                ORDER BY started_at ASC
                LIMIT $1
                """,
                limit,
            )
        )


async def fetch_hops_for_measurement(pool: Pool, measurement_id: int) -> List[asyncpg.Record]:
    """Retrieve hops for a measurement including ASN data."""
    async with pool.acquire() as conn:
        return list(
            await conn.fetch(
                """
                SELECT hop_number, asn, org_name, country_code, rtt_ms
                FROM hops
                WHERE measurement_id = $1 AND asn IS NOT NULL
                ORDER BY hop_number ASC
                """,
                measurement_id,
            )
        )


async def mark_measurement_graph_built(pool: Pool, measurement_id: int) -> None:
    """Flag a measurement as ingested into the graph layer."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE measurements SET graph_built = TRUE, graph_built_at = $2 WHERE id = $1",
            measurement_id,
            datetime.utcnow(),
        )
