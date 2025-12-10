"""ASN and topology info endpoints."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from neo4j import AsyncDriver

from cyberWatch.api.models import ok
from cyberWatch.api.utils.db import neo4j_dep

router = APIRouter(prefix="/asn", tags=["asn"])


async def _fetch_asn(driver: AsyncDriver, asn: int) -> dict:
    query = """
    MATCH (a:AS {asn: $asn})
    OPTIONAL MATCH (a)-[r:ROUTE]-(n:AS)
    RETURN a.asn AS asn, a.org_name AS org_name, a.country AS country,
           collect(distinct n.asn) AS neighbors
    """
    async with driver.session() as session:
        record = await session.execute_read(lambda tx: tx.run(query, asn=asn).single())
        if record is None:
            raise HTTPException(status_code=404, detail="ASN not found")
        return {
            "asn": record["asn"],
            "org_name": record["org_name"],
            "country": record["country"],
            "neighbors": record["neighbors"] or [],
            "prefixes": [],
        }


@router.get("/{asn}")
async def get_asn(asn: int, driver: AsyncDriver = Depends(neo4j_dep)):
    data = await _fetch_asn(driver, asn)
    return ok(data)
