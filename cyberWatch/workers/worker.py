"""Async worker: pulls targets, runs traceroute, stores results."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from pydantic import BaseModel, IPvAnyAddress

from cyberWatch.db.pg import create_pool, insert_measurement
from cyberWatch.scheduler.queue import TargetQueue, TargetTask

class HopModel(BaseModel):
    hop: int
    ip: Optional[str]
    rtt_ms: Optional[float]


class MeasurementResult(BaseModel):
    target: IPvAnyAddress
    timestamp: datetime
    tool: str
    success: bool
    hops: List[HopModel]
    raw_output: str


TRACEROUTE_PATTERN = re.compile(r"^\s*(?P<hop>\d+)\s+(?P<ip>[0-9.\-:*]+)\s+(?P<rtt>[0-9.]+)\s*ms")


async def _run_subprocess(cmd: Sequence[str], use_shell: bool = False) -> Tuple[int, str]:
    """Run a subprocess and capture stdout."""
    process = await asyncio.create_subprocess_shell(
        " ".join(cmd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    ) if use_shell else await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    stdout, _ = await process.communicate()
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    return process.returncode or 0, output


def _pick_command(target: str) -> Tuple[Sequence[str], bool, str]:
    """Choose scamper if available, otherwise traceroute."""
    if shutil.which("scamper") and shutil.which("bash"):
        cmd = [f"scamper -c \"trace -P icmp\" -i <(printf '{target}\\n')"]
        return cmd, True, "scamper"
    if shutil.which("traceroute"):
        return ["traceroute", "-n", target], False, "traceroute"
    raise RuntimeError("Neither scamper nor traceroute is available on PATH")


def _parse_hops(output: str) -> List[HopModel]:
    """Parse traceroute-like output into hop records."""
    hops: List[HopModel] = []
    for line in output.splitlines():
        match = TRACEROUTE_PATTERN.match(line)
        if not match:
            continue
        hop = int(match.group("hop"))
        ip_raw = match.group("ip").strip()
        ip = None if "*" in ip_raw else ip_raw
        rtt_str = match.group("rtt")
        try:
            rtt = float(rtt_str)
        except ValueError:
            rtt = None
        hops.append(HopModel(hop=hop, ip=ip, rtt_ms=rtt))
    return hops


async def run_traceroute(target: str) -> MeasurementResult:
    """Run traceroute/scamper and normalize output."""
    cmd, use_shell, tool = _pick_command(target)
    started_at = datetime.utcnow()
    code, output = await _run_subprocess(cmd, use_shell=use_shell)
    success = code == 0
    hops = _parse_hops(output)
    return MeasurementResult(
        target=target,
        timestamp=started_at,
        tool=tool,
        success=success,
        hops=hops,
        raw_output=output,
    )


class Worker:
    """Measurement worker loop."""

    def __init__(self) -> None:
        self.queue = TargetQueue()
        dsn = os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch")
        self.pg_dsn = dsn

    async def run(self) -> None:
        pool = await create_pool(self.pg_dsn)
        try:
            while True:
                task = await self.queue.dequeue(timeout=5)
                if task is None:
                    continue
                await self.handle_task(pool, task)
        finally:
            await pool.close()
            await self.queue.close()

    async def handle_task(self, pool, task: TargetTask) -> None:
        result = await run_traceroute(str(task.target_ip))
        hops_payload = [(hop.hop, hop.ip, hop.rtt_ms) for hop in result.hops]
        await insert_measurement(
            pool,
            target_ip=str(result.target),
            tool=result.tool,
            started_at=result.timestamp,
            completed_at=datetime.utcnow(),
            success=result.success,
            raw_output=result.raw_output,
            hops=hops_payload,
            source=task.source,
        )


async def main() -> None:
    worker = Worker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
