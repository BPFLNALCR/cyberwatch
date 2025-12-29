"""Redis-backed target queue for measurement tasks."""
from __future__ import annotations

from typing import Optional
import json
import os
import time

import redis.asyncio as aioredis
from pydantic import BaseModel, Field, IPvAnyAddress

from cyberWatch.logging_config import get_logger

logger = get_logger("queue")


class TargetTask(BaseModel):
    """Minimal target task stored in Redis."""
    target_ip: IPvAnyAddress
    source: str = Field(default="static")
    domain: Optional[str] = Field(default=None, description="Original domain if derived from DNS")
    priority: int = Field(default=0, ge=0)


class TargetQueue:
    """Simple FIFO queue using Redis lists."""

    def __init__(self, redis_url: Optional[str] = None, queue_key: str = "cyberWatch:targets"):
        self.redis_url = redis_url or os.getenv("CYBERWATCH_REDIS_URL", "redis://localhost:6379/0")
        self.queue_key = queue_key
        self._client: Optional[aioredis.Redis] = None
        self._connected: bool = False

    async def connect(self) -> aioredis.Redis:
        if self._client is None:
            try:
                self._client = aioredis.from_url(self.redis_url, decode_responses=True)
                # Test connection
                await self._client.ping()
                if not self._connected:
                    logger.info(
                        "Connected to Redis queue",
                        extra={
                            "queue_key": self.queue_key,
                            "outcome": "success"
                        }
                    )
                    self._connected = True
            except Exception as exc:
                logger.error(
                    f"Failed to connect to Redis: {exc}",
                    extra={
                        "redis_url": self.redis_url.split("@")[-1] if "@" in self.redis_url else self.redis_url,
                        "outcome": "error",
                        "error_type": type(exc).__name__
                    }
                )
                raise
        return self._client

    async def enqueue(self, task: TargetTask) -> None:
        """Add a task to the queue."""
        start_time = time.time()
        try:
            client = await self.connect()
            await client.rpush(self.queue_key, task.model_dump_json())
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.debug(
                "Task enqueued",
                extra={
                    "target": str(task.target_ip),
                    "source": task.source,
                    "duration": duration_ms,
                    "outcome": "success"
                }
            )
        except Exception as exc:
            logger.error(
                f"Failed to enqueue task: {exc}",
                extra={
                    "target": str(task.target_ip),
                    "source": task.source,
                    "outcome": "error",
                    "error_type": type(exc).__name__
                }
            )
            raise

    async def dequeue(self, timeout: int = 1) -> Optional[TargetTask]:
        """Remove and return a task from the queue, blocking up to timeout seconds."""
        try:
            client = await self.connect()
            item = await client.blpop(self.queue_key, timeout=timeout)
            if item is None:
                return None
            _, payload = item
            data = json.loads(payload)
            task = TargetTask(**data)
            logger.debug(
                "Task dequeued",
                extra={
                    "target": str(task.target_ip),
                    "source": task.source,
                    "outcome": "success"
                }
            )
            return task
        except Exception as exc:
            logger.error(
                f"Failed to dequeue task: {exc}",
                extra={
                    "outcome": "error",
                    "error_type": type(exc).__name__
                }
            )
            raise

    async def length(self) -> int:
        """Return the current queue length."""
        try:
            client = await self.connect()
            return await client.llen(self.queue_key)
        except Exception as exc:
            logger.warning(
                f"Failed to get queue length: {exc}",
                extra={"outcome": "error", "error_type": type(exc).__name__}
            )
            return 0

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            try:
                await self._client.close()
                logger.info("Redis queue connection closed", extra={"outcome": "success"})
            except Exception as exc:
                logger.warning(
                    f"Error closing Redis connection: {exc}",
                    extra={"outcome": "error", "error_type": type(exc).__name__}
                )
            finally:
                self._client = None
                self._connected = False
