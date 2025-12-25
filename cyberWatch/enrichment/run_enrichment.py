"""Coordinator to run enrichment then graph builder in sequence."""
from __future__ import annotations

import asyncio
import os

from rich.console import Console

from cyberWatch.db import pg
from cyberWatch.db.neo4j import get_driver
from cyberWatch.enrichment import enricher, graph_builder
from cyberWatch.logging_config import get_logger

console = Console()
logger = get_logger("enrichment")


async def main() -> None:
    pg_dsn = os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch")
    sleep_seconds = int(os.getenv("CYBERWATCH_ENRICH_INTERVAL", "10"))

    logger.info(
        "Enrichment scheduler starting",
        extra={
            "component": "enrichment_scheduler",
            "state": "starting",
            "interval": sleep_seconds,
        }
    )
    console.print("[cyan]Starting enrichment scheduler")
    
    pool = await pg.create_pool(pg_dsn)
    driver = get_driver()
    
    try:
        while True:
            enriched = await enricher.run_once(pool)
            built = await graph_builder.run_once(pool, driver)
            if not enriched and not built:
                logger.debug("No work to do, sleeping")
                await asyncio.sleep(sleep_seconds)
    except KeyboardInterrupt:
        logger.info("Enrichment scheduler interrupted", extra={"state": "interrupted"})
    except Exception as exc:
        logger.error(
            f"Enrichment scheduler error: {str(exc)}",
            exc_info=True,
            extra={"outcome": "error"}
        )
    finally:
        logger.info("Enrichment scheduler shutting down", extra={"state": "shutdown"})
        await pool.close()
        await driver.close()
        logger.info("Enrichment scheduler stopped", extra={"state": "stopped"})


if __name__ == "__main__":
    asyncio.run(main())
