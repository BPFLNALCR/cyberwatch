"""Example script to enqueue a few static targets."""
from __future__ import annotations

import asyncio
from typing import Sequence

from .queue import TargetQueue, TargetTask


STATIC_TARGETS: Sequence[str] = [
    "1.1.1.1",
    "8.8.8.8",
    "9.9.9.9",
]


async def main() -> None:
    queue = TargetQueue()
    for target_ip in STATIC_TARGETS:
        task = TargetTask(target_ip=target_ip, source="example")
        await queue.enqueue(task)
    await queue.close()


if __name__ == "__main__":
    asyncio.run(main())
