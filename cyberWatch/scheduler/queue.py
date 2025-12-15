"""Redis-backed target queue for measurement tasks."""
from __future__ import annotations

from typing import Optional
import json
import os

import redis.asyncio as aioredis
from pydantic import BaseModel, Field, IPvAnyAddress


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

    async def connect(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def enqueue(self, task: TargetTask) -> None:
        client = await self.connect()
        await client.rpush(self.queue_key, task.model_dump_json())

    async def dequeue(self, timeout: int = 1) -> Optional[TargetTask]:
        client = await self.connect()
        item = await client.blpop(self.queue_key, timeout=timeout)
        if item is None:
            return None
        _, payload = item
        data = json.loads(payload)
        return TargetTask(**data)

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
