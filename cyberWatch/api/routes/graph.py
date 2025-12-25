"""Graph path and neighbor endpoints."""
from __future__ import annotations

from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from neo4j import AsyncDriver

from cyberWatch.api.models import ok
from cyberWatch.api.utils.db import pg_dep
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/graph", tags=["graph"])


async def _get_driver_if_available() -> Optional[AsyncDriver]:
    """Get Neo4j driver if available, None otherwise."""
    try:
        from cyberWatch.api.utils.db import _driver
        return _driver
    except Exception:
        return None


async def _get_neighbors_from_neo4j(driver: AsyncDriver, asn: int) -> Optional[List[dict]]:
    """Try to get neighbors from Neo4j."""
    try:
        query = """
        MATCH (a:AS {asn: $asn})-[r:ROUTE]-(b:AS)
        RETURN b.asn AS neighbor, r.observed_count AS observed_count, 
               r.min_rtt AS min_rtt, r.max_rtt AS max_rtt, r.last_seen AS last_seen
        """
        async with driver.session() as session:
            result = await session.run(query, asn=asn)
            records = await result.data()
        return [
            {
                "neighbor_asn": rec["neighbor"],
                "observed_count": rec["observed_count"],
                "min_rtt": rec["min_rtt"],
                "max_rtt": rec["max_rtt"],
                "last_seen": rec["last_seen"],
            }
            for rec in records
        ]
    except Exception:
        return None


async def _get_neighbors_from_pg(pool: asyncpg.Pool, asn: int) -> List[dict]:
    """Get neighbor ASNs from PostgreSQL hop adjacency data."""
    rows = await pool.fetch(
        """
        SELECT 
            h2.asn as neighbor_asn,
            COUNT(*) as observed_count,
            MIN(GREATEST(h1.rtt_ms, h2.rtt_ms)) as min_rtt,
            MAX(GREATEST(h1.rtt_ms, h2.rtt_ms)) as max_rtt,
            MAX(h1.created_at) as last_seen
        FROM hops h1
        JOIN hops h2 ON h1.measurement_id = h2.measurement_id
        WHERE h1.asn = $1 
          AND h2.asn != $1 
          AND h2.asn IS NOT NULL
          AND ABS(h1.hop_number - h2.hop_number) = 1
        GROUP BY h2.asn
        ORDER BY observed_count DESC
        LIMIT 50
        """,
        asn,
    )
    return [
        {
            "neighbor_asn": row["neighbor_asn"],
            "observed_count": row["observed_count"],
            "min_rtt": row["min_rtt"],
            "max_rtt": row["max_rtt"],
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        }
        for row in rows
    ]


@router.get("/neighbors/{asn}")
async def neighbors(asn: int, pool: asyncpg.Pool = Depends(pg_dep)):
    """Get neighbor ASNs with graceful fallback to PostgreSQL."""
    driver = await _get_driver_if_available()
    
    if driver is not None:
        neo4j_data = await _get_neighbors_from_neo4j(driver, asn)
        if neo4j_data is not None:
            return ok({"asn": asn, "neighbors": neo4j_data, "source": "neo4j"})
    
    # Fallback to PostgreSQL
    pg_data = await _get_neighbors_from_pg(pool, asn)
    return ok({"asn": asn, "neighbors": pg_data, "source": "postgresql"})


@router.get("/path")
async def shortest_path(
    src_asn: int = Query(...),
    dst_asn: int = Query(...),
    pool: asyncpg.Pool = Depends(pg_dep),
):
    """Get shortest path between two ASNs."""
    driver = await _get_driver_if_available()
    
    if driver is not None:
        try:
            query = """
            MATCH (src:AS {asn: $src}), (dst:AS {asn: $dst})
            MATCH p=shortestPath((src)-[:ROUTE*..10]-(dst))
            RETURN [n IN nodes(p) | n.asn] AS asns, length(p) AS length
            """
            async with driver.session() as session:
                result = await session.run(query, src=src_asn, dst=dst_asn)
                record = await result.single()
            if record is not None:
                return ok({"asns": record["asns"], "length": record["length"], "source": "neo4j"})
        except Exception:
            pass  # Fallback to message
    
    # Neo4j unavailable or no path found
    return ok({
        "asns": [],
        "length": 0,
        "source": "unavailable",
        "message": "Graph path queries require Neo4j. Please ensure Neo4j is running and connected."
    })
