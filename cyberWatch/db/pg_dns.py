"""Async helpers for DNS query ingestion and aggregation."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Sequence

import asyncpg
from asyncpg import Pool

from cyberWatch.logging_config import get_logger

logger = get_logger("db")


@dataclass
class DNSQueryRecord:
    domain: str
    queried_at: datetime
    client_ip: Optional[str] = None
    qtype: Optional[str] = None


@dataclass
class DNSTargetRecord:
    domain: str
    ip: str
    first_seen: datetime
    last_seen: datetime
    query_count: int = 1
    last_client_ip: Optional[str] = None
    last_qtype: Optional[str] = None


# SQL statements
SQL_INSERT_QUERIES = """
INSERT INTO dns_queries (domain, client_ip, qtype, queried_at)
VALUES ($1, $2, $3, $4)
"""


SQL_UPSERT_TARGETS = """
INSERT INTO dns_targets (domain, ip, first_seen, last_seen, query_count, last_client_ip, last_qtype)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (domain, ip) DO UPDATE
SET last_seen = EXCLUDED.last_seen,
    first_seen = LEAST(dns_targets.first_seen, EXCLUDED.first_seen),
    query_count = dns_targets.query_count + EXCLUDED.query_count,
    last_client_ip = COALESCE(EXCLUDED.last_client_ip, dns_targets.last_client_ip),
    last_qtype = COALESCE(EXCLUDED.last_qtype, dns_targets.last_qtype)
"""


SQL_TOUCH_TARGET = """
INSERT INTO targets (target_ip, source, last_seen)
VALUES ($1, $2, $3)
ON CONFLICT (target_ip) DO UPDATE
SET last_seen = COALESCE(EXCLUDED.last_seen, targets.last_seen),
    source = COALESCE(targets.source, EXCLUDED.source)
"""


SQL_TOP_DOMAINS = """
SELECT domain,
       SUM(query_count) AS total_queries,
       COUNT(*) AS unique_ips,
       MAX(last_seen) AS last_seen
FROM dns_targets
GROUP BY domain
ORDER BY total_queries DESC
LIMIT $1
"""


SQL_TOP_TARGETS = """
SELECT domain, ip, query_count, last_seen, last_client_ip, last_qtype
FROM dns_targets
ORDER BY query_count DESC, last_seen DESC
LIMIT $1
"""


SQL_RECENT_QUERIES = """
SELECT domain, client_ip, qtype, queried_at
FROM dns_queries
ORDER BY queried_at DESC
LIMIT $1
"""


SQL_DISTINCT_TARGET_IPS = """
SELECT DISTINCT ip
FROM dns_targets
ORDER BY ip
LIMIT $1
"""


async def insert_dns_queries(pool: Pool, queries: Sequence[DNSQueryRecord]) -> None:
    """Persist a batch of DNS queries."""
    if not queries:
        return
    
    logger.info(
        "Inserting DNS queries batch",
        extra={"batch_size": len(queries), "action": "dns_insert"}
    )
    
    start_time = time.time()
    records = [(q.domain, q.client_ip, q.qtype, q.queried_at) for q in queries]
    
    try:
        async with pool.acquire() as conn:
            await conn.executemany(SQL_INSERT_QUERIES, records)
        
        duration = time.time() - start_time
        logger.info(
            "DNS queries inserted",
            extra={
                "rows_affected": len(records),
                "duration": round(duration * 1000, 2),
                "outcome": "success",
            }
        )
    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            f"Failed to insert DNS queries: {str(exc)}",
            exc_info=True,
            extra={
                "batch_size": len(queries),
                "duration": round(duration * 1000, 2),
                "outcome": "error",
            }
        )
        raise


async def upsert_dns_targets(pool: Pool, targets: Sequence[DNSTargetRecord]) -> None:
    """Upsert DNS targets aggregated by domain+IP."""
    if not targets:
        return
    
    logger.info(
        "Upserting DNS targets batch",
        extra={"batch_size": len(targets), "action": "dns_upsert"}
    )
    
    start_time = time.time()
    records = [
        (
            t.domain,
            t.ip,
            t.first_seen,
            t.last_seen,
            t.query_count,
            t.last_client_ip,
            t.last_qtype,
        )
        for t in targets
    ]
    
    try:
        async with pool.acquire() as conn:
            await conn.executemany(SQL_UPSERT_TARGETS, records)
        
        duration = time.time() - start_time
        logger.info(
            "DNS targets upserted",
            extra={
                "rows_affected": len(records),
                "duration": round(duration * 1000, 2),
                "outcome": "success",
            }
        )
    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            f"Failed to upsert DNS targets: {str(exc)}",
            exc_info=True,
            extra={
                "batch_size": len(targets),
                "duration": round(duration * 1000, 2),
                "outcome": "error",
            }
        )
        raise


async def touch_target(pool: Pool, target_ip: str, *, source: str = "dns", seen_at: Optional[datetime] = None) -> None:
    """Ensure a target exists in the main targets table."""
    async with pool.acquire() as conn:
        await conn.execute(SQL_TOUCH_TARGET, target_ip, source, seen_at or datetime.utcnow())


async def fetch_top_domains(pool: Pool, limit: int = 20) -> List[asyncpg.Record]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(SQL_TOP_DOMAINS, limit)
        return list(rows)


async def fetch_top_targets(pool: Pool, limit: int = 50) -> List[asyncpg.Record]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(SQL_TOP_TARGETS, limit)
        return list(rows)


async def fetch_recent_queries(pool: Pool, limit: int = 100) -> List[asyncpg.Record]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(SQL_RECENT_QUERIES, limit)
        return list(rows)


async def fetch_target_ips(pool: Pool, limit: int = 200) -> List[str]:
    """Return distinct target IPs for downstream aggregation (e.g., ASN lookups)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(SQL_DISTINCT_TARGET_IPS, limit)
    return [r["ip"] for r in rows]
