"""ASN and topology info endpoints."""
from __future__ import annotations

import asyncio
from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from neo4j import AsyncDriver

from cyberWatch.api.models import ok
from cyberWatch.api.utils.db import neo4j_dep, pg_dep
from cyberWatch.enrichment.asn_lookup import lookup_asn
from cyberWatch.enrichment.peeringdb import fetch_asn_org
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/asn", tags=["asn"])


def _http_error(code: int, message: str) -> None:
    raise HTTPException(status_code=code, detail={"status": "error", "message": message})


async def _fetch_asn_from_neo4j(driver: AsyncDriver, asn: int) -> Optional[dict]:
    """Try to fetch ASN info from Neo4j graph database."""
    try:
        query = """
        MATCH (a:AS {asn: $asn})
        OPTIONAL MATCH (a)-[r:ROUTE]-(n:AS)
        RETURN a.asn AS asn, a.org_name AS org_name, a.country AS country,
               collect(distinct n.asn) AS neighbors,
               [] AS prefixes
        """
        async with driver.session() as session:
            result = await session.run(query, asn=asn)
            record = await result.single()
            if record is None or record["asn"] is None:
                return None
            
            # Neo4j doesn't store prefixes, so we'll leave them empty
            # They can be enriched from PostgreSQL if needed
            return {
                "asn": record["asn"],
                "org_name": record["org_name"],
                "country": record["country"],
                "neighbors": [n for n in (record["neighbors"] or []) if n is not None],
                "prefixes": record["prefixes"] or [],
                "source": "neo4j",
            }
    except Exception:
        return None


async def _fetch_asn_from_external(asn: int) -> dict:
    """Fetch ASN info from external sources (PeeringDB, Team Cymru)."""
    org_info = await fetch_asn_org(asn)
    return {
        "asn": asn,
        "org_name": org_info.org_name if org_info else None,
        "country": org_info.country if org_info else None,
        "neighbors": [],
        "prefixes": [],
        "source": "peeringdb",
    }


async def _get_asn_from_postgres(pool: asyncpg.Pool, asn: int) -> Optional[dict]:
    """Get ASN info from PostgreSQL asns table."""
    row = await pool.fetchrow(
        "SELECT * FROM asns WHERE asn = $1",
        asn,
    )
    if row:
        return {
            "asn": row["asn"],
            "org_name": row["org_name"],
            "country": row["country_code"],
            "prefix_count": row["prefix_count"],
            "neighbor_count": row["neighbor_count"],
            "facility_count": row["facility_count"],
            "peering_policy": row["peering_policy"],
            "traffic_levels": row["traffic_levels"],
            "irr_as_set": row["irr_as_set"],
            "total_measurements": row["total_measurements"],
            "avg_rtt_ms": row["avg_rtt_ms"],
            "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
            "source": row["source"],
            "neighbors": [],  # Will be populated from Neo4j if available
            "prefixes": [],   # Will be populated from hops if needed
        }
    return None


async def _get_asn_neighbors_from_neo4j(driver: AsyncDriver, asn: int) -> List[int]:
    """Get neighbor ASNs from Neo4j graph."""
    try:
        query = """
        MATCH (a:AS {asn: $asn})-[:ROUTE]-(n:AS)
        RETURN DISTINCT n.asn AS neighbor_asn
        ORDER BY neighbor_asn
        """
        async with driver.session() as session:
            result = await session.run(query, asn=asn)
            records = await result.list()
            return [r["neighbor_asn"] for r in records if r["neighbor_asn"] is not None]
    except Exception:
        return []


async def _get_asn_prefixes_from_hops(pool: asyncpg.Pool, asn: int, limit: int = 100) -> List[str]:
    """Get prefixes for an ASN from hop data."""
    try:
        rows = await pool.fetch(
            """
            SELECT DISTINCT prefix
            FROM hops
            WHERE asn = $1 AND prefix IS NOT NULL
            ORDER BY prefix
            LIMIT $2
            """,
            asn,
            limit,
        )
        return [str(r["prefix"]) for r in rows]
    except Exception:
        return []


@router.get("/{asn}")
async def get_asn(asn: int, pool: asyncpg.Pool = Depends(pg_dep), request: Request = None):
    """Get comprehensive ASN information from asns table with neighbors from Neo4j."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "ASN lookup requested",
        extra={"request_id": request_id, "user_input": {"asn": asn}}
    )
    
    # Primary source: PostgreSQL asns table
    asn_data = await _get_asn_from_postgres(pool, asn)
    
    if asn_data:
        # Enrich with neighbors from Neo4j if available
        try:
            from cyberWatch.api.utils.db import _driver
            if _driver is not None:
                neighbors = await _get_asn_neighbors_from_neo4j(_driver, asn)
                asn_data["neighbors"] = neighbors
                # Update neighbor count to match actual Neo4j data
                if neighbors:
                    asn_data["neighbor_count"] = len(neighbors)
        except Exception as e:
            logger.debug(f"Neo4j neighbor lookup failed: {e}")
        
        # Add prefixes from hops if not zero
        if asn_data.get("prefix_count", 0) > 0:
            prefixes = await _get_asn_prefixes_from_hops(pool, asn, limit=100)
            asn_data["prefixes"] = prefixes
        
        return ok(asn_data)
    
    # Fallback 1: Try Neo4j graph data
    try:
        from cyberWatch.api.utils.db import _driver
        if _driver is not None:
            neo4j_data = await _fetch_asn_from_neo4j(_driver, asn)
            if neo4j_data:
                # Enrich with prefixes
                neo4j_data["prefixes"] = await _get_asn_prefixes_from_hops(pool, asn, limit=100)
                return ok(neo4j_data)
    except Exception as e:
        logger.debug(f"Neo4j fallback failed: {e}")
    
    # Fallback 2: External sources (PeeringDB, etc.)
    external_data = await _fetch_asn_from_external(asn)
    return ok(external_data)


@router.get("/lookup/{ip}")
async def lookup_ip_asn(ip: str, pool: asyncpg.Pool = Depends(pg_dep)):
    """Lookup ASN for a specific IP address."""
    try:
        info = await lookup_asn(ip)
        if info.asn is None:
            raise HTTPException(status_code=404, detail="ASN not found for IP")
        return ok({
            "ip": ip,
            "asn": info.asn,
            "prefix": info.prefix,
            "org_name": info.org_name,
            "country": info.country,
        })
    except HTTPException:
        raise
    except Exception as exc:
        _http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, f"ASN lookup failed: {exc}")
