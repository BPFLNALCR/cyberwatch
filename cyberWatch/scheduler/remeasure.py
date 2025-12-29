"""Periodic remeasurement scheduler - re-enqueue old targets for fresh measurements."""
from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime

from cyberWatch.db.pg import create_pool, get_targets_for_remeasurement, touch_target
from cyberWatch.db.settings import get_remeasurement_settings
from cyberWatch.scheduler.queue import TargetQueue, TargetTask
from cyberWatch.logging_config import get_logger

logger = get_logger("remeasure")


async def run_remeasurement_cycle(pool, queue: TargetQueue, config: dict) -> int:
    """
    Run one remeasurement cycle.
    Returns number of targets re-enqueued.
    """
    if not config.get("enabled", True):
        logger.info("Remeasurement disabled in settings")
        return 0
    
    interval_hours = config.get("interval_hours", 24)
    batch_size = config.get("batch_size", 100)
    targets_per_run = config.get("targets_per_run", 500)
    
    logger.info(
        "Starting remeasurement cycle",
        extra={
            "interval_hours": interval_hours,
            "batch_size": batch_size,
            "targets_per_run": targets_per_run,
            "action": "remeasure_start",
        }
    )
    
    # Get targets that need remeasurement
    targets = await get_targets_for_remeasurement(
        pool,
        older_than_hours=interval_hours,
        limit=targets_per_run,
    )
    
    if not targets:
        logger.info("No targets need remeasurement")
        return 0
    
    logger.info(
        f"Found {len(targets)} targets for remeasurement",
        extra={"target_count": len(targets)}
    )
    
    # Shuffle to avoid always measuring same targets first
    shuffled = list(targets)
    random.shuffle(shuffled)
    
    # Enqueue in batches
    enqueued = 0
    for i in range(0, len(shuffled), batch_size):
        batch = shuffled[i:i+batch_size]
        
        for target in batch:
            try:
                ip = str(target["target_ip"])
                await touch_target(pool, ip, source="remeasurement", seen_at=datetime.utcnow())
                await queue.enqueue(TargetTask(target_ip=ip, source="remeasurement"))
                enqueued += 1
            except Exception as exc:
                logger.warning(
                    f"Failed to enqueue target for remeasurement: {str(exc)}",
                    extra={"target": str(target["target_ip"]), "outcome": "error"}
                )
        
        # Small delay between batches to avoid overwhelming the queue
        await asyncio.sleep(1)
    
    logger.info(
        f"Remeasurement cycle complete: enqueued {enqueued} targets",
        extra={
            "targets_found": len(targets),
            "targets_enqueued": enqueued,
            "outcome": "success",
        }
    )
    
    return enqueued


async def main_loop() -> None:
    """Main loop for remeasurement scheduler."""
    dsn = os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch")
    redis_url = os.getenv("CYBERWATCH_REDIS_URL", "redis://localhost:6379/0")
    
    logger.info(
        "Remeasurement scheduler starting",
        extra={"component": "remeasure", "state": "starting"}
    )
    
    pool = await create_pool(dsn)
    queue = TargetQueue(redis_url)
    
    try:
        while True:
            # Load settings
            settings = await get_remeasurement_settings(pool) or {
                "enabled": True,
                "interval_hours": 24,
                "batch_size": 100,
                "targets_per_run": 500,
            }
            
            if settings.get("enabled", True):
                try:
                    await run_remeasurement_cycle(pool, queue, settings)
                except Exception as exc:
                    logger.error(
                        f"Remeasurement cycle failed: {str(exc)}",
                        exc_info=True,
                        extra={"outcome": "error"}
                    )
            
            # Sleep until next cycle (with some randomization to avoid thundering herd)
            sleep_hours = settings.get("interval_hours", 24)
            jitter_minutes = random.randint(-30, 30)  # +/- 30 minutes
            sleep_seconds = (sleep_hours * 3600) + (jitter_minutes * 60)
            
            logger.info(
                f"Sleeping for {sleep_seconds/3600:.2f} hours until next cycle",
                extra={"sleep_hours": sleep_seconds/3600}
            )
            
            await asyncio.sleep(sleep_seconds)
    except KeyboardInterrupt:
        logger.info("Remeasurement scheduler interrupted", extra={"state": "interrupted"})
    except Exception as exc:
        logger.error(
            f"Remeasurement scheduler error: {str(exc)}",
            exc_info=True,
            extra={"outcome": "error"}
        )
    finally:
        logger.info("Remeasurement scheduler shutting down", extra={"state": "shutdown"})
        await pool.close()
        await queue.close()
        logger.info("Remeasurement scheduler stopped", extra={"state": "stopped"})


if __name__ == "__main__":
    asyncio.run(main_loop())
