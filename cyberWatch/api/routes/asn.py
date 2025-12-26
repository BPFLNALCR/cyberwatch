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


async def _get_asn_from_db(pool: asyncpg.Pool, asn: int) -> Optional[dict]:
    """Get ASN info from PostgreSQL hop data if available."""
    row = await pool.fetchrow(
        """
        SELECT asn, org_name, country_code as country
        FROM hops
        WHERE asn = $1 AND org_name IS NOT NULL
        LIMIT 1
        """,
        asn,
    )
    if row:
        # Get unique neighbor ASNs from measurement paths
        neighbors_rows = await pool.fetch(
            """
            SELECT DISTINCT h2.asn as neighbor_asn
            FROM hops h1
            JOIN hops h2 ON h1.measurement_id = h2.measurement_id
            WHERE h1.asn = $1 AND h2.asn != $1 AND h2.asn IS NOT NULL
            AND ABS(h1.hop_number - h2.hop_number) = 1
            LIMIT 50
            """,
            asn,
        )
        neighbors = [r["neighbor_asn"] for r in neighbors_rows]
        
        # Get unique prefixes for this ASN
        prefix_rows = await pool.fetch(
            """
            SELECT DISTINCT prefix
            FROM hops
            WHERE asn = $1 AND prefix IS NOT NULL
            ORDER BY prefix
            LIMIT 100
            """,
            asn,
        )
        prefixes = [str(r["prefix"]) for r in prefix_rows]
        
        return {
            "asn": row["asn"],
            "org_name": row["org_name"],
            "country": row["country"],
            "neighbors": neighbors,
            "prefixes": prefixes,
            "source": "postgresql",
        }
    return None


@router.get("/{asn}")
async def get_asn(asn: int, pool: asyncpg.Pool = Depends(pg_dep), request: Request = None):
    """Get ASN information with graceful fallback when Neo4j is unavailable."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "ASN lookup requested",
        extra={"request_id": request_id, "user_input": {"asn": asn}}
    )
    
    # Try Neo4j first
    neo4j_data = None
    try:
        from cyberWatch.api.utils.db import _driver
        if _driver is not None:
            neo4j_data = await _fetch_asn_from_neo4j(_driver, asn)
            if neo4j_data:
                # Enrich Neo4j data with prefixes from PostgreSQL
                try:
                    prefix_rows = await pool.fetch(
                        """
                        SELECT DISTINCT prefix
                        FROM hops
                        WHERE asn = $1 AND prefix IS NOT NULL
                        ORDER BY prefix
                        LIMIT 100
                        """,
                        asn,
                    )
                    neo4j_data["prefixes"] = [str(r["prefix"]) for r in prefix_rows]
                except Exception:
                    pass  # Keep empty prefixes if query fails
                
                return ok(neo4j_data)
    except Exception as e:
        logger.debug(f"Neo4j lookup failed: {e}")
        pass  # Neo4j unavailable, continue to fallback
    
    # Try PostgreSQL data
    pg_data = await _get_asn_from_db(pool, asn)
    if pg_data:
        return ok(pg_data)
    
    # Fallback to external sources
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
