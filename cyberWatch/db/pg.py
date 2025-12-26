"""Async PostgreSQL helper functions for measurement storage and enrichment."""
from __future__ import annotations

import asyncpg
import time
from asyncpg import Connection, Pool
from typing import Iterable, List, Optional, Sequence
from datetime import datetime

from cyberWatch.logging_config import get_logger

logger = get_logger("db")


async def create_pool(dsn: str) -> Pool:
    """Initialize an asyncpg connection pool."""
    # Sanitize DSN for logging (remove password)
    dsn_parts = dsn.split("@")
    sanitized_dsn = dsn_parts[-1] if "@" in dsn else "local"
    
    logger.info(
        "Creating PostgreSQL connection pool",
        extra={"dsn_host": sanitized_dsn, "action": "pool_create"}
    )
    
    try:
        pool = await asyncpg.create_pool(dsn)
        logger.info(
            "PostgreSQL pool created successfully",
            extra={"dsn_host": sanitized_dsn, "outcome": "success"}
        )
        return pool
    except Exception as exc:
        logger.error(
            f"Failed to create PostgreSQL pool: {str(exc)}",
            exc_info=True,
            extra={"dsn_host": sanitized_dsn, "outcome": "error"}
        )
        raise


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
    start_time = time.time()
    hops_list = list(hops)
    
    logger.info(
        "Inserting measurement",
        extra={
            "target": target_ip,
            "tool": tool,
            "hop_count": len(hops_list),
            "success": success,
            "action": "measurement_insert",
        }
    )
    
    try:
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
                for hop_number, hop_ip, rtt_ms in hops_list:
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
                
                duration = time.time() - start_time
                logger.info(
                    "Measurement inserted successfully",
                    extra={
                        "measurement_id": measurement_id,
                        "target": target_ip,
                        "target_id": target_id,
                        "hop_count": len(hops_list),
                        "rows_affected": len(hops_list) + 2,  # measurement + hops + target update
                        "duration": round(duration * 1000, 2),
                        "outcome": "success",
                    }
                )
                
                return int(measurement_id)
    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            f"Failed to insert measurement: {str(exc)}",
            exc_info=True,
            extra={
                "target": target_ip,
                "tool": tool,
                "hop_count": len(hops_list),
                "duration": round(duration * 1000, 2),
                "outcome": "error",
            }
        )
        raise


async def fetch_unenriched_hops(pool: Pool, limit: int = 200) -> List[asyncpg.Record]:
    """Fetch hops lacking ASN enrichment."""
    logger.debug(
        "Fetching unenriched hops",
        extra={"limit": limit, "action": "fetch_unenriched"}
    )
    
    start_time = time.time()
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
        duration = time.time() - start_time
        logger.info(
            "Fetched unenriched hops",
            extra={
                "rows_fetched": len(rows),
                "duration": round(duration * 1000, 2),
                "outcome": "success",
            }
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
    logger.debug(
        "Updating hop enrichment",
        extra={"hop_id": hop_id, "asn": asn, "action": "hop_enrich"}
    )
    
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


# ASN metadata operations
async def upsert_asn(
    pool: Pool,
    asn: int,
    *,
    org_name: Optional[str] = None,
    country_code: Optional[str] = None,
    source: str = "cymru",
    peeringdb_id: Optional[int] = None,
    facility_count: Optional[int] = None,
    peering_policy: Optional[str] = None,
    traffic_levels: Optional[str] = None,
    irr_as_set: Optional[str] = None,
) -> None:
    """Upsert ASN metadata, updating fields only if provided."""
    logger.debug(
        "Upserting ASN metadata",
        extra={"asn": asn, "source": source, "action": "asn_upsert"}
    )
    
    async with pool.acquire() as conn:
        # Check if exists
        existing = await conn.fetchrow("SELECT * FROM asns WHERE asn = $1", asn)
        
        if existing:
            # Update only non-None fields
            updates = []
            values = []
            param_num = 2  # $1 is asn
            
            if org_name is not None:
                updates.append(f"org_name = ${param_num}")
                values.append(org_name)
                param_num += 1
            
            if country_code is not None:
                updates.append(f"country_code = ${param_num}")
                values.append(country_code)
                param_num += 1
            
            if source is not None:
                updates.append(f"source = ${param_num}")
                values.append(source)
                param_num += 1
            
            if peeringdb_id is not None:
                updates.append(f"peeringdb_id = ${param_num}")
                values.append(peeringdb_id)
                param_num += 1
            
            if facility_count is not None:
                updates.append(f"facility_count = ${param_num}")
                values.append(facility_count)
                param_num += 1
            
            if peering_policy is not None:
                updates.append(f"peering_policy = ${param_num}")
                values.append(peering_policy)
                param_num += 1
            
            if traffic_levels is not None:
                updates.append(f"traffic_levels = ${param_num}")
                values.append(traffic_levels)
                param_num += 1
            
            if irr_as_set is not None:
                updates.append(f"irr_as_set = ${param_num}")
                values.append(irr_as_set)
                param_num += 1
            
            if updates:
                updates.append("last_seen = NOW()")
                updates.append("updated_at = NOW()")
                
                query = f"UPDATE asns SET {', '.join(updates)} WHERE asn = $1"
                await conn.execute(query, asn, *values)
        else:
            # Insert new record
            await conn.execute(
                """
                INSERT INTO asns (
                    asn, org_name, country_code, source, peeringdb_id,
                    facility_count, peering_policy, traffic_levels, irr_as_set
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                asn, org_name, country_code, source, peeringdb_id,
                facility_count, peering_policy, traffic_levels, irr_as_set,
            )
        
        logger.info(
            "ASN metadata upserted",
            extra={"asn": asn, "source": source, "outcome": "success"}
        )


async def get_asn(pool: Pool, asn: int) -> Optional[asyncpg.Record]:
    """Retrieve ASN metadata by ASN number."""
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM asns WHERE asn = $1", asn)


async def get_all_asns(
    pool: Pool,
    limit: int = 1000,
    offset: int = 0,
    order_by: str = "last_seen DESC"
) -> List[asyncpg.Record]:
    """Retrieve all ASNs with pagination."""
    # Validate order_by to prevent SQL injection
    valid_orders = [
        "last_seen DESC", "last_seen ASC",
        "prefix_count DESC", "prefix_count ASC",
        "neighbor_count DESC", "neighbor_count ASC",
        "asn ASC", "asn DESC",
        "org_name ASC", "org_name DESC"
    ]
    if order_by not in valid_orders:
        order_by = "last_seen DESC"
    
    async with pool.acquire() as conn:
        query = f"SELECT * FROM asns ORDER BY {order_by} LIMIT $1 OFFSET $2"
        return list(await conn.fetch(query, limit, offset))


async def update_asn_stats(
    pool: Pool,
    asn: int,
    *,
    prefix_count: Optional[int] = None,
    neighbor_count: Optional[int] = None,
    total_measurements: Optional[int] = None,
    avg_rtt_ms: Optional[float] = None,
) -> None:
    """Update ASN statistics."""
    async with pool.acquire() as conn:
        updates = []
        values = []
        param_num = 2  # $1 is asn
        
        if prefix_count is not None:
            updates.append(f"prefix_count = ${param_num}")
            values.append(prefix_count)
            param_num += 1
        
        if neighbor_count is not None:
            updates.append(f"neighbor_count = ${param_num}")
            values.append(neighbor_count)
            param_num += 1
        
        if total_measurements is not None:
            updates.append(f"total_measurements = ${param_num}")
            values.append(total_measurements)
            param_num += 1
        
        if avg_rtt_ms is not None:
            updates.append(f"avg_rtt_ms = ${param_num}")
            values.append(avg_rtt_ms)
            param_num += 1
        
        if updates:
            updates.append("updated_at = NOW()")
            query = f"UPDATE asns SET {', '.join(updates)} WHERE asn = $1"
            await conn.execute(query, asn, *values)


async def get_asns_needing_enrichment(pool: Pool, limit: int = 100) -> List[asyncpg.Record]:
    """Get ASNs that haven't been enriched recently (older than 24 hours or never)."""
    async with pool.acquire() as conn:
        return list(
            await conn.fetch(
                """
                SELECT asn, org_name, country_code, source
                FROM asns
                WHERE enrichment_completed_at IS NULL
                   OR enrichment_completed_at < NOW() - INTERVAL '24 hours'
                ORDER BY last_seen DESC
                LIMIT $1
                """,
                limit,
            )
        )


async def mark_asn_enrichment_attempted(pool: Pool, asn: int) -> None:
    """Mark ASN enrichment as attempted."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE asns SET enrichment_attempted_at = NOW() WHERE asn = $1",
            asn,
        )


async def mark_asn_enrichment_completed(pool: Pool, asn: int) -> None:
    """Mark ASN enrichment as completed."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE asns SET enrichment_completed_at = NOW() WHERE asn = $1",
            asn,
        )


async def touch_target(
    pool: Pool,
    target_ip: str,
    *,
    source: str = "static",
    seen_at: Optional[datetime] = None,
) -> int:
    """Touch a target (update last_seen or insert). Returns target ID."""
    async with pool.acquire() as conn:
        result = await conn.fetchrow(
            """
            INSERT INTO targets (target_ip, source, last_seen)
            VALUES ($1, $2, $3)
            ON CONFLICT (target_ip) DO UPDATE
            SET last_seen = COALESCE(EXCLUDED.last_seen, targets.last_seen)
            RETURNING id
            """,
            target_ip,
            source,
            seen_at or datetime.utcnow(),
        )
        return int(result["id"])


async def get_targets_for_remeasurement(
    pool: Pool,
    older_than_hours: int = 24,
    limit: int = 100,
) -> List[asyncpg.Record]:
    """Get targets that haven't been measured recently."""
    async with pool.acquire() as conn:
        return list(
            await conn.fetch(
                """
                SELECT t.id, t.target_ip, t.source, t.last_seen,
                       MAX(m.completed_at) as last_measurement
                FROM targets t
                LEFT JOIN measurements m ON m.target_id = t.id
                GROUP BY t.id
                HAVING MAX(m.completed_at) IS NULL
                    OR MAX(m.completed_at) < NOW() - ($1 || ' hours')::INTERVAL
                ORDER BY MAX(m.completed_at) ASC NULLS FIRST
                LIMIT $2
                """,
                str(older_than_hours),
                limit,
            )
        )
