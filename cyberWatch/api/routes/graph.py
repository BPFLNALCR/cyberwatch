"""Graph path and neighbor endpoints."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import AsyncDriver

from cyberWatch.api.models import ok
from cyberWatch.api.utils.db import neo4j_dep

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/neighbors/{asn}")
async def neighbors(asn: int, driver: AsyncDriver = Depends(neo4j_dep)):
    query = """
    MATCH (a:AS {asn: $asn})-[r:ROUTE]-(b:AS)
    RETURN b.asn AS neighbor, r.observed_count AS observed_count, r.min_rtt AS min_rtt, r.max_rtt AS max_rtt, r.last_seen AS last_seen
    """
    async with driver.session() as session:
        result = await session.run(query, asn=asn)
        records = await result.data()
    data = [
        {
            "neighbor_asn": rec["neighbor"],
            "observed_count": rec["observed_count"],
            "min_rtt": rec["min_rtt"],
            "max_rtt": rec["max_rtt"],
            "last_seen": rec["last_seen"],
        }
        for rec in records
    ]
    return ok({"asn": asn, "neighbors": data})


@router.get("/path")
async def shortest_path(
    src_asn: int = Query(...),
    dst_asn: int = Query(...),
    driver: AsyncDriver = Depends(neo4j_dep),
):
    query = """
    MATCH (src:AS {asn: $src}), (dst:AS {asn: $dst})
    MATCH p=shortestPath((src)-[:ROUTE*..10]-(dst))
    RETURN [n IN nodes(p) | n.asn] AS asns, length(p) AS length
    """
    async with driver.session() as session:
        result = await session.run(query, src=src_asn, dst=dst_asn)
        record = await result.single()
    if record is None:
        raise HTTPException(status_code=404, detail="No path")
    return ok({"asns": record["asns"], "length": record["length"]})
