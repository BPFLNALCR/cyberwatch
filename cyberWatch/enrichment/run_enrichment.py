"""Coordinator to run enrichment then graph builder in sequence."""
from __future__ import annotations

import asyncio
import os

from rich.console import Console
from neo4j.exceptions import ServiceUnavailable, AuthError

from cyberWatch.db import pg
from cyberWatch.db.neo4j import get_driver
from cyberWatch.enrichment import enricher, graph_builder
from cyberWatch.logging_config import get_logger

console = Console()
logger = get_logger("enrichment")


async def get_neo4j_driver_with_retry(max_retries: int = 5, initial_delay: float = 2.0) -> object:
    """Get Neo4j driver with exponential backoff retry for connection failures.
    
    Args:
        max_retries: Maximum number of connection attempts
        initial_delay: Initial delay in seconds before first retry
        
    Returns:
        Neo4j driver instance
        
    Raises:
        ServiceUnavailable: If Neo4j cannot be reached after all retries
        AuthError: If authentication fails
    """
    delay = initial_delay
    last_error = None
    
    for attempt in range(1, max_retries + 1):
        try:
            driver = get_driver()
            # Test the connection
            await driver.verify_connectivity()
            logger.info(
                f"Neo4j connection established on attempt {attempt}",
                extra={"attempt": attempt, "outcome": "success"}
            )
            return driver
        except AuthError as exc:
            # Don't retry on auth errors - these won't resolve themselves
            logger.error(
                f"Neo4j authentication failed: {exc}",
                exc_info=True,
                extra={"outcome": "auth_error"}
            )
            raise
        except (ServiceUnavailable, Exception) as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(
                    f"Neo4j connection attempt {attempt}/{max_retries} failed, retrying in {delay:.1f}s: {exc}",
                    extra={"attempt": attempt, "delay": delay, "outcome": "retry"}
                )
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                logger.error(
                    f"Neo4j connection failed after {max_retries} attempts",
                    exc_info=True,
                    extra={"attempts": max_retries, "outcome": "failure"}
                )
    
    # All retries exhausted
    raise last_error


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
    
    # Initialize Neo4j with retry logic
    try:
        driver = await get_neo4j_driver_with_retry(max_retries=5, initial_delay=2.0)
    except Exception as exc:
        logger.error(
            f"Failed to initialize Neo4j driver: {exc}",
            exc_info=True,
            extra={"outcome": "fatal_error"}
        )
        console.print("[red]ERROR: Could not connect to Neo4j. Graph building will be disabled.")
        console.print("[yellow]Run ASN enrichment will continue, but graph features won't work.")
        console.print("[yellow]Check Neo4j service: sudo systemctl status neo4j")
        driver = None
    
    try:
        while True:
            enriched = await enricher.run_once(pool)
            
            # Only attempt graph building if Neo4j is available
            built = False
            if driver is not None:
                try:
                    built = await graph_builder.run_once(pool, driver)
                except ServiceUnavailable as exc:
                    logger.warning(
                        f"Neo4j unavailable during graph building: {exc}",
                        extra={"outcome": "neo4j_unavailable"}
                    )
                    # Continue enrichment even if graph building fails
            
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
        if driver is not None:
            await driver.close()
        logger.info("Enrichment scheduler stopped", extra={"state": "stopped"})


if __name__ == "__main__":
    asyncio.run(main())
