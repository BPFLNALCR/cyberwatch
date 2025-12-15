"""Graph builder: project enriched measurements into Neo4j."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import List, Optional, Sequence

from asyncpg import Record
from neo4j import AsyncDriver
from pydantic import BaseModel
from rich.console import Console

from cyberWatch.db.neo4j import get_driver
from cyberWatch.db import pg

console = Console()


class HopNode(BaseModel):
    asn: int
    org_name: Optional[str]
    country: Optional[str]
    rtt_ms: Optional[float]


class EdgeModel(BaseModel):
    a: HopNode
    b: HopNode
    observed_at: datetime
    rtt_ms: Optional[float]


def _build_edges(hops: Sequence[Record], observed_at: datetime) -> List[EdgeModel]:
    edges: List[EdgeModel] = []
    prev: Optional[HopNode] = None
    for hop in hops:
        if hop["asn"] is None:
            continue
        node = HopNode(
            asn=int(hop["asn"]),
            org_name=hop["org_name"],
            country=hop["country_code"],
            rtt_ms=hop["rtt_ms"],
        )
        if prev is not None and node.asn != prev.asn:
            rtt_candidates = [x for x in (prev.rtt_ms, node.rtt_ms) if x is not None]
            rtt_value = max(rtt_candidates) if rtt_candidates else None
            edges.append(EdgeModel(a=prev, b=node, observed_at=observed_at, rtt_ms=rtt_value))
        prev = node
    return edges


async def _merge_edge(session, edge: EdgeModel) -> None:
    """Merge AS nodes and ROUTE relationship into Neo4j."""
    query = """
        MERGE (a:AS {asn: $asn_a})
          ON CREATE SET a.org_name = $org_a, a.country = $country_a, a.first_seen = $ts
          ON MATCH SET a.org_name = coalesce(a.org_name, $org_a), a.country = coalesce(a.country, $country_a), a.last_seen = $ts
        MERGE (b:AS {asn: $asn_b})
          ON CREATE SET b.org_name = $org_b, b.country = $country_b, b.first_seen = $ts
          ON MATCH SET b.org_name = coalesce(b.org_name, $org_b), b.country = coalesce(b.country, $country_b), b.last_seen = $ts
        WITH a, b
        MERGE (a)-[r:ROUTE]->(b)
          ON CREATE SET r.observed_count = 1, r.min_rtt = $rtt, r.max_rtt = $rtt, r.last_seen = $ts
          ON MATCH SET r.observed_count = coalesce(r.observed_count, 0) + 1,
                       r.min_rtt = CASE WHEN r.min_rtt IS NULL OR $rtt IS NULL THEN r.min_rtt ELSE LEAST(r.min_rtt, $rtt) END,
                       r.max_rtt = CASE WHEN r.max_rtt IS NULL OR $rtt IS NULL THEN r.max_rtt ELSE GREATEST(r.max_rtt, $rtt) END,
                       r.last_seen = $ts
        """
    await session.run(
        query,
        asn_a=edge.a.asn,
        org_a=edge.a.org_name,
        country_a=edge.a.country,
        asn_b=edge.b.asn,
        org_b=edge.b.org_name,
        country_b=edge.b.country,
        rtt=edge.rtt_ms,
        ts=edge.observed_at,
    )


async def process_measurement(pool, driver: AsyncDriver, measurement_id: int, observed_at: datetime) -> None:
    hops = await pg.fetch_hops_for_measurement(pool, measurement_id)
    if not hops:
        await pg.mark_measurement_graph_built(pool, measurement_id)
        return
    edges = _build_edges(hops, observed_at)
    if not edges:
        await pg.mark_measurement_graph_built(pool, measurement_id)
        return

    async with driver.session() as session:
        # Ensure deterministic direction: order ASN pair
        for edge in edges:
            a, b = edge.a, edge.b
            if a.asn > b.asn:
                edge = EdgeModel(a=b, b=a, observed_at=edge.observed_at, rtt_ms=edge.rtt_ms)
            await _merge_edge(session, edge)
    await pg.mark_measurement_graph_built(pool, measurement_id)
    console.print(f"[green]Graph updated for measurement {measurement_id}")


async def run_once(pool, driver: AsyncDriver) -> bool:
    measurements = await pg.fetch_measurements_for_graph(pool)
    if not measurements:
        return False
    for row in measurements:
        await process_measurement(pool, driver, int(row["id"]), row["started_at"])
    return True


async def main_loop() -> None:
    console.print("[cyan]Starting graph builder")
    pg_dsn = os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch")
    pool = await pg.create_pool(pg_dsn)
    driver: AsyncDriver = get_driver()
    try:
        while True:
            had_work = await run_once(pool, driver)
            if not had_work:
                await asyncio.sleep(10)
    finally:
        await pool.close()
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main_loop())
