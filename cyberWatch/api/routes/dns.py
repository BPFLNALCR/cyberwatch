"""DNS analytics endpoints."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Dict, List

import asyncpg
from fastapi import APIRouter, Depends, Query, Request

from cyberWatch.api.models import ok
from cyberWatch.api.utils.db import pg_dep
from cyberWatch.db.pg_dns import fetch_top_domains, fetch_top_targets
from cyberWatch.enrichment.asn_lookup import lookup_asn
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/dns", tags=["dns"])


@router.get("/top-domains")
async def top_domains(limit: int = Query(20, ge=1, le=500), pool: asyncpg.Pool = Depends(pg_dep), request: Request = None):
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Fetching top domains",
        extra={"request_id": request_id, "user_input": {"limit": limit}}
    )
    
    rows = await fetch_top_domains(pool, limit=limit)
    
    logger.info(
        "Top domains fetched",
        extra={"request_id": request_id, "count": len(rows), "outcome": "success"}
    )
    data = [
        {
            "domain": r["domain"],
            "total_queries": int(r["total_queries"] or 0),
            "unique_ips": int(r["unique_ips"] or 0),
            "last_seen": r["last_seen"],
        }
        for r in rows
    ]
    return ok(data)


@router.get("/top-asns")
async def top_asns(limit: int = Query(50, ge=1, le=200), pool: asyncpg.Pool = Depends(pg_dep)):
    targets = await fetch_top_targets(pool, limit=limit)
    if not targets:
        return ok([])

    tasks = {row["ip"]: lookup_asn(row["ip"]) for row in targets}
    lookup_results = await asyncio.gather(*tasks.values())

    counts: Dict[int, int] = defaultdict(int)
    meta: Dict[int, str] = {}
    for row, info in zip(targets, lookup_results):
        if info.asn is None:
            continue
        counts[info.asn] += int(row["query_count"] or 0)
        if info.org_name:
            meta.setdefault(info.asn, info.org_name)

    data = [
        {
            "asn": asn,
            "org": meta.get(asn),
            "total_queries": total,
        }
        for asn, total in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return ok(data)
