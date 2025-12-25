"""Enrichment service: IP -> ASN and org metadata."""
from __future__ import annotations

import asyncio
import os
from typing import Dict, List, Optional, cast

from rich.console import Console

from cyberWatch.db import pg
from cyberWatch.enrichment.asn_lookup import AsnInfo, lookup_asn
from cyberWatch.enrichment.peeringdb import AsnOrg, fetch_asn_org
from cyberWatch.logging_config import get_logger

console = Console()
logger = get_logger("enrichment")


class EnrichmentConfig:
    def __init__(self, poll_interval: int = 10) -> None:
        self.poll_interval = poll_interval
        self.pg_dsn = os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch")


async def enrich_hop(record) -> tuple[int, AsnInfo, Optional[AsnOrg]]:
    hop_id: int = record["id"]
    hop_ip: str = str(record["hop_ip"])
    asn_info = await lookup_asn(hop_ip)
    asn_org: Optional[AsnOrg] = None
    if asn_info.asn is not None:
        try:
            asn_org = await fetch_asn_org(asn_info.asn)
        except Exception:
            asn_org = None
    return hop_id, asn_info, asn_org


async def process_batch(pool, records: List) -> None:
    logger.info(
        "Processing enrichment batch",
        extra={"batch_size": len(records), "action": "enrich_batch"}
    )
    
    # Enrich hops concurrently
    coros = [enrich_hop(rec) for rec in records]
    results: List[tuple[int, AsnInfo, Optional[AsnOrg]] | BaseException] = await asyncio.gather(
        *coros, return_exceptions=True
    )

    # Apply updates sequentially to avoid transaction contention
    success_count = 0
    error_count = 0
    
    for rec, outcome in zip(records, results):
        if isinstance(outcome, BaseException):
            error_count += 1
            logger.warning(
                f"Enrichment failed for hop {rec['id']}: {str(outcome)}",
                extra={"hop_id": rec['id'], "outcome": "error"}
            )
            console.print(f"[yellow]Enrichment failed for hop {rec['id']}: {outcome}")
            continue
        
        hop_id, asn_info, asn_org = cast(tuple[int, AsnInfo, Optional[AsnOrg]], outcome)
        org_name = asn_org.org_name if asn_org and asn_org.org_name else asn_info.org_name
        country = asn_org.country if asn_org and asn_org.country else asn_info.country
        
        await pg.update_hop_enrichment(
            pool,
            hop_id,
            asn=asn_info.asn,
            prefix=asn_info.prefix,
            org_name=org_name,
            country_code=country,
        )
        success_count += 1
    
    logger.info(
        "Enrichment batch completed",
        extra={
            "batch_size": len(records),
            "success_count": success_count,
            "error_count": error_count,
            "outcome": "success",
        }
    )

    # After hop updates, mark measurements when all hops are enriched
    measurement_ids = {int(rec["measurement_id"]) for rec in records}
    for measurement_id in measurement_ids:
        remaining = await pg.remaining_unenriched_hops(pool, measurement_id)
        if remaining == 0:
            await pg.mark_measurement_enriched(pool, measurement_id)
            logger.info(
                "Measurement marked as enriched",
                extra={"measurement_id": measurement_id, "outcome": "success"}
            )
            console.print(f"[green]Marked measurement {measurement_id} as enriched")


async def run_once(pool) -> bool:
    records = await pg.fetch_unenriched_hops(pool)
    if not records:
        return False
    await process_batch(pool, records)
    return True


async def main_loop(config: EnrichmentConfig) -> None:
    logger.info(
        "Enrichment service starting",
        extra={
            "component": "enrichment",
            "state": "starting",
            "poll_interval": config.poll_interval,
        }
    )
    console.print("[cyan]Starting enrichment loop")
    
    pool = await pg.create_pool(config.pg_dsn)
    try:
        while True:
            had_work = await run_once(pool)
            if not had_work:
                logger.debug("No unenriched hops found, sleeping")
                await asyncio.sleep(config.poll_interval)
    except KeyboardInterrupt:
        logger.info("Enrichment service interrupted", extra={"state": "interrupted"})
    except Exception as exc:
        logger.error(
            f"Enrichment service error: {str(exc)}",
            exc_info=True,
            extra={"outcome": "error"}
        )
    finally:
        logger.info("Enrichment service shutting down", extra={"state": "shutdown"})
        await pool.close()
        logger.info("Enrichment service stopped", extra={"state": "stopped"})


if __name__ == "__main__":
    cfg = EnrichmentConfig()
    asyncio.run(main_loop(cfg))
