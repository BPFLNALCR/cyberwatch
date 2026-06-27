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


@router.get("/topology")
async def topology(
    asn: Optional[int] = Query(None, description="Starting ASN for exploration"),
    depth: int = Query(1, ge=1, le=3, description="Exploration depth (1-3 hops)"),
    limit: int = Query(20, ge=1, le=100, description="Max ASNs to return"),
    sort_by: str = Query("traffic", description="Sort by: traffic, rtt, neighbors, country"),
    country: Optional[str] = Query(None, description="Filter by country code"),
    pool: asyncpg.Pool = Depends(pg_dep),
):
    """
    Get enriched ASN topology data for visualization.
    
    If no ASN is provided, returns top ASNs by traffic volume.
    If ASN is provided, returns that ASN and its neighbors up to specified depth.
    """
    driver = await _get_driver_if_available()
    
    # If specific ASN requested, explore from that ASN
    if asn is not None:
        return await _get_topology_from_asn(asn, depth, limit, pool, driver)
    
    # Otherwise, get top ASNs by traffic
    return await _get_top_asns_by_traffic(limit, sort_by, country, pool, driver)


async def _get_topology_from_asn(
    start_asn: int, 
    depth: int, 
    limit: int, 
    pool: asyncpg.Pool, 
    driver: Optional[AsyncDriver]
) -> dict:
    """Get topology starting from a specific ASN."""
    if driver is not None:
        try:
            return await _get_topology_from_neo4j(start_asn, depth, limit, driver, pool)
        except Exception as e:
            logger.warning(f"Neo4j topology query failed: {e}")
    
    # Fallback to PostgreSQL
    return await _get_topology_from_pg(start_asn, depth, limit, pool)


async def _get_topology_from_neo4j(
    start_asn: int,
    depth: int,
    limit: int,
    driver: AsyncDriver,
    pool: asyncpg.Pool
) -> dict:
    """Get topology from Neo4j with enriched data."""
    query = """
    MATCH (start:AS {asn: $start_asn})
    CALL {
        WITH start
        MATCH path = (start)-[:ROUTE*1..%d]-(neighbor:AS)
        RETURN DISTINCT neighbor
        LIMIT $limit
    }
    WITH start, neighbor
    OPTIONAL MATCH (neighbor)-[r:ROUTE]-(connected:AS)
    WHERE connected.asn IN [start.asn] + [n.asn | n IN collect(neighbor)]
    RETURN 
        neighbor.asn AS asn,
        neighbor.org_name AS org_name,
        neighbor.country AS country,
        neighbor.first_seen AS first_seen,
        neighbor.last_seen AS last_seen,
        collect(DISTINCT {
            neighbor_asn: connected.asn,
            observed_count: r.observed_count,
            min_rtt: r.min_rtt,
            max_rtt: r.max_rtt
        }) AS connections
    """ % depth
    
    async with driver.session() as session:
        result = await session.run(query, start_asn=start_asn, limit=limit)
        records = await result.data()
    
    # Enrich with PostgreSQL data (measurement counts, DNS queries)
    asns = [start_asn] + [rec["asn"] for rec in records]
    enrichment_data = await _get_enrichment_data(asns, pool)
    
    nodes = []
    edges = []
    
    # Add starting ASN
    start_data = enrichment_data.get(start_asn, {})
    nodes.append({
        "asn": start_asn,
        "org_name": start_data.get("org_name", f"AS{start_asn}"),
        "country": start_data.get("country"),
        "measurement_count": start_data.get("measurement_count", 0),
        "dns_query_count": start_data.get("dns_query_count", 0),
        "avg_rtt": start_data.get("avg_rtt"),
        "neighbor_count": start_data.get("neighbor_count", 0),
        "first_seen": start_data.get("first_seen"),
        "last_seen": start_data.get("last_seen"),
    })
    
    # Add discovered ASNs and connections
    for rec in records:
        asn_num = rec["asn"]
        enrich = enrichment_data.get(asn_num, {})
        
        nodes.append({
            "asn": asn_num,
            "org_name": rec["org_name"] or enrich.get("org_name", f"AS{asn_num}"),
            "country": rec["country"] or enrich.get("country"),
            "measurement_count": enrich.get("measurement_count", 0),
            "dns_query_count": enrich.get("dns_query_count", 0),
            "avg_rtt": enrich.get("avg_rtt"),
            "neighbor_count": enrich.get("neighbor_count", 0),
            "first_seen": rec["first_seen"],
            "last_seen": rec["last_seen"],
        })
        
        # Add edges
        for conn in rec["connections"]:
            if conn["neighbor_asn"] is not None:
                edges.append({
                    "source": asn_num,
                    "target": conn["neighbor_asn"],
                    "observed_count": conn["observed_count"],
                    "min_rtt": conn["min_rtt"],
                    "max_rtt": conn["max_rtt"],
                })
    
    return ok({
        "nodes": nodes,
        "edges": edges,
        "source": "neo4j",
        "start_asn": start_asn,
        "depth": depth,
    })


async def _get_topology_from_pg(
    start_asn: int,
    depth: int,
    limit: int,
    pool: asyncpg.Pool
) -> dict:
    """Get topology from PostgreSQL (limited to depth=1)."""
    # PostgreSQL can only efficiently do 1-hop neighbors
    actual_depth = min(depth, 1)
    
    rows = await pool.fetch(
        """
        SELECT 
            h2.asn as neighbor_asn,
            h2.org_name,
            h2.country_code as country,
            COUNT(DISTINCT h1.measurement_id) as observed_count,
            MIN(GREATEST(h1.rtt_ms, h2.rtt_ms)) as min_rtt,
            MAX(GREATEST(h1.rtt_ms, h2.rtt_ms)) as max_rtt,
            AVG(GREATEST(h1.rtt_ms, h2.rtt_ms)) as avg_rtt,
            MIN(h1.created_at) as first_seen,
            MAX(h1.created_at) as last_seen
        FROM hops h1
        JOIN hops h2 ON h1.measurement_id = h2.measurement_id
        WHERE h1.asn = $1 
          AND h2.asn != $1 
          AND h2.asn IS NOT NULL
          AND ABS(h1.hop_number - h2.hop_number) = 1
        GROUP BY h2.asn, h2.org_name, h2.country_code
        ORDER BY observed_count DESC
        LIMIT $2
        """,
        start_asn,
        limit,
    )
    
    asns = [start_asn] + [row["neighbor_asn"] for row in rows]
    enrichment_data = await _get_enrichment_data(asns, pool)
    
    nodes = []
    edges = []
    
    # Add starting ASN
    start_data = enrichment_data.get(start_asn, {})
    nodes.append({
        "asn": start_asn,
        "org_name": start_data.get("org_name", f"AS{start_asn}"),
        "country": start_data.get("country"),
        "measurement_count": start_data.get("measurement_count", 0),
        "dns_query_count": start_data.get("dns_query_count", 0),
        "avg_rtt": start_data.get("avg_rtt"),
        "neighbor_count": len(rows),
        "first_seen": start_data.get("first_seen"),
        "last_seen": start_data.get("last_seen"),
    })
    
    # Add neighbors and edges
    for row in rows:
        asn_num = row["neighbor_asn"]
        enrich = enrichment_data.get(asn_num, {})
        
        nodes.append({
            "asn": asn_num,
            "org_name": row["org_name"] or enrich.get("org_name", f"AS{asn_num}"),
            "country": row["country"] or enrich.get("country"),
            "measurement_count": enrich.get("measurement_count", 0),
            "dns_query_count": enrich.get("dns_query_count", 0),
            "avg_rtt": row["avg_rtt"],
            "neighbor_count": enrich.get("neighbor_count", 0),
            "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        })
        
        edges.append({
            "source": start_asn,
            "target": asn_num,
            "observed_count": row["observed_count"],
            "min_rtt": row["min_rtt"],
            "max_rtt": row["max_rtt"],
        })
    
    return ok({
        "nodes": nodes,
        "edges": edges,
        "source": "postgresql",
        "start_asn": start_asn,
        "depth": actual_depth,
    })


async def _get_top_asns_by_traffic(
    limit: int,
    sort_by: str,
    country_filter: Optional[str],
    pool: asyncpg.Pool,
    driver: Optional[AsyncDriver]
) -> dict:
    """Get top ASNs by traffic/activity with their immediate neighbors."""
    # Build WHERE clause for country filter
    where_clause = ""
    params = [limit]
    if country_filter:
        where_clause = "AND country_code = $2"
        params.append(country_filter.upper())
    
    # Get top ASNs by measurement count (traffic proxy) - simplified query
    query = f"""
    SELECT 
        asn,
        MAX(org_name) as org_name,
        MAX(country_code) as country,
        COUNT(DISTINCT measurement_id) as measurement_count,
        AVG(rtt_ms) as avg_rtt,
        MIN(created_at) as first_seen,
        MAX(created_at) as last_seen
    FROM hops
    WHERE asn IS NOT NULL {where_clause}
    GROUP BY asn
    """
    
    # Add sorting
    if sort_by == "rtt":
        query += " ORDER BY avg_rtt ASC NULLS LAST"
    elif sort_by == "country":
        query += " ORDER BY country ASC, measurement_count DESC"
    else:  # Default to traffic or neighbors
        query += " ORDER BY measurement_count DESC"
    
    query += " LIMIT $1"
    
    rows = await pool.fetch(query, *params)
    
    if not rows:
        logger.warning("No ASN data found in database")
        return ok({
            "nodes": [],
            "edges": [],
            "source": "postgresql",
            "message": "No ASN data available. Please run some traceroutes first.",
        })
    
    asns = [row["asn"] for row in rows]
    logger.info(f"Found {len(asns)} ASNs, getting enrichment data")
    
    enrichment_data = await _get_enrichment_data(asns, pool)
    
    # Get connections between top ASNs
    edges_query = """
    SELECT 
        h1.asn as source,
        h2.asn as target,
        COUNT(*) as observed_count,
        MIN(LEAST(COALESCE(h1.rtt_ms, 0), COALESCE(h2.rtt_ms, 0))) as min_rtt,
        MAX(GREATEST(COALESCE(h1.rtt_ms, 0), COALESCE(h2.rtt_ms, 0))) as max_rtt
    FROM hops h1
    JOIN hops h2 ON h1.measurement_id = h2.measurement_id
    WHERE h1.asn = ANY($1::int[])
      AND h2.asn = ANY($1::int[])
      AND h1.asn != h2.asn
      AND ABS(h1.hop_number - h2.hop_number) = 1
    GROUP BY h1.asn, h2.asn
    """
    
    try:
        edge_rows = await pool.fetch(edges_query, asns)
        logger.info(f"Found {len(edge_rows)} edges between ASNs")
    except Exception as e:
        logger.error(f"Failed to get edges: {e}")
        edge_rows = []
    
    nodes = []
    for row in rows:
        asn_num = row["asn"]
        enrich = enrichment_data.get(asn_num, {})
        
        nodes.append({
            "asn": asn_num,
            "org_name": row["org_name"] or enrich.get("org_name") or f"AS{asn_num}",
            "country": row["country"] or enrich.get("country"),
            "measurement_count": row["measurement_count"],
            "dns_query_count": 0,  # Simplified - not critical
            "avg_rtt": float(row["avg_rtt"]) if row["avg_rtt"] else None,
            "neighbor_count": enrich.get("neighbor_count", 0),
            "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        })
    
    edges = [
        {
            "source": row["source"],
            "target": row["target"],
            "observed_count": row["observed_count"],
            "min_rtt": float(row["min_rtt"]) if row["min_rtt"] and row["min_rtt"] > 0 else None,
            "max_rtt": float(row["max_rtt"]) if row["max_rtt"] and row["max_rtt"] > 0 else None,
        }
        for row in edge_rows
    ]
    
    logger.info(f"Returning {len(nodes)} nodes and {len(edges)} edges")
    
    return ok({
        "nodes": nodes,
        "edges": edges,
        "source": "postgresql",
        "sort_by": sort_by,
        "country_filter": country_filter,
    })


async def _get_enrichment_data(asns: List[int], pool: asyncpg.Pool) -> dict:
    """Get enrichment data (measurement counts, DNS queries, etc.) for ASNs."""
    if not asns:
        return {}
    
    # Get measurement counts per ASN
    measurement_query = """
    SELECT 
        asn,
        COUNT(DISTINCT measurement_id) as measurement_count,
        AVG(rtt_ms) as avg_rtt,
        MAX(org_name) as org_name,
        MAX(country_code) as country,
        MIN(created_at) as first_seen,
        MAX(created_at) as last_seen
    FROM hops
    WHERE asn = ANY($1::int[])
    GROUP BY asn
    """
    
    rows = await pool.fetch(measurement_query, asns)
    
    result = {}
    for row in rows:
        asn = row["asn"]
        result[asn] = {
            "measurement_count": row["measurement_count"],
            "avg_rtt": float(row["avg_rtt"]) if row["avg_rtt"] else None,
            "org_name": row["org_name"],
            "country": row["country"],
            "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
            "neighbor_count": 0,
            "dns_query_count": 0,
        }
    
    # Get neighbor counts - simplified
    neighbor_query = """
    SELECT 
        h1.asn,
        COUNT(DISTINCT h2.asn) as neighbor_count
    FROM hops h1
    JOIN hops h2 ON h1.measurement_id = h2.measurement_id
    WHERE h1.asn = ANY($1::int[])
      AND h2.asn IS NOT NULL
      AND h2.asn != h1.asn
      AND ABS(h1.hop_number - h2.hop_number) = 1
    GROUP BY h1.asn
    """
    
    try:
        neighbor_rows = await pool.fetch(neighbor_query, asns)
        for row in neighbor_rows:
            asn = row["asn"]
            if asn in result:
                result[asn]["neighbor_count"] = row["neighbor_count"]
    except Exception as e:
        logger.warning(f"Failed to get neighbor counts: {e}")
    
    return result
