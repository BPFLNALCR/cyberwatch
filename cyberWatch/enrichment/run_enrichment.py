"""Coordinator to run enrichment then graph builder in sequence."""
from __future__ import annotations

import asyncio
import os

from rich.console import Console

from cyberWatch.db import pg
from cyberWatch.db.neo4j import get_driver
from cyberWatch.enrichment import enricher, graph_builder

console = Console()


async def main() -> None:
    pg_dsn = os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch")
    sleep_seconds = int(os.getenv("CYBERWATCH_ENRICH_INTERVAL", "10"))

    pool = await pg.create_pool(pg_dsn)
    driver = get_driver()
    console.print("[cyan]Starting enrichment scheduler")
    try:
        while True:
            enriched = await enricher.run_once(pool)
            built = await graph_builder.run_once(pool, driver)
            if not enriched and not built:
                await asyncio.sleep(sleep_seconds)
    finally:
        await pool.close()
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
