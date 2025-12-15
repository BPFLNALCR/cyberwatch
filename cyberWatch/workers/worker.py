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


# Pattern to match traceroute output lines with multiple RTT values
# e.g., "  1  192.168.1.1  0.456 ms  0.412 ms  0.398 ms"
TRACEROUTE_PATTERN = re.compile(
    r"^\s*(?P<hop>\d+)\s+"
    r"(?P<ip>\S+)\s+"
    r"(?P<rtt1>[0-9.]+)\s*ms"
    r"(?:\s+(?P<rtt2>[0-9.*]+)\s*ms)?"
    r"(?:\s+(?P<rtt3>[0-9.*]+)\s*ms)?"
)

# Pattern for scamper warts text output
SCAMPER_HOP_PATTERN = re.compile(
    r"^\s*(?P<hop>\d+)\s+(?P<ip>\S+)\s+(?P<rtt>[0-9.]+)\s*ms"
)


async def _run_subprocess(cmd: Sequence[str], stdin_data: Optional[str] = None) -> Tuple[int, str]:
    """Run a subprocess and capture stdout. Optionally pass stdin data."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    stdin_bytes = stdin_data.encode("utf-8") if stdin_data else None
    stdout, _ = await process.communicate(input=stdin_bytes)
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    return process.returncode or 0, output


def _pick_tool() -> str:
    """Choose scamper if available, otherwise traceroute."""
    if shutil.which("scamper"):
        return "scamper"
    if shutil.which("traceroute"):
        return "traceroute"
    raise RuntimeError("Neither scamper nor traceroute is available on PATH")


def _parse_traceroute_hops(output: str) -> List[HopModel]:
    """Parse standard traceroute output into hop records.
    
    Handles formats like:
      1  192.168.1.1  0.456 ms  0.412 ms  0.398 ms
      2  * * *
      3  10.0.0.1 (10.0.0.1)  5.123 ms  4.987 ms  5.001 ms
    """
    hops: List[HopModel] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("traceroute"):
            continue
        
        match = TRACEROUTE_PATTERN.match(line)
        if match:
            hop_num = int(match.group("hop"))
            ip_raw = match.group("ip").strip()
            # Handle hostnames with IP in parens: "host.example.com (1.2.3.4)"
            if "(" in ip_raw:
                # Extract just the part before the paren
                ip_raw = ip_raw.split("(")[0].strip()
            ip = None if "*" in ip_raw or ip_raw == "*" else ip_raw
            
            # Average the RTT values if multiple are present
            rtt_values = []
            for rtt_key in ("rtt1", "rtt2", "rtt3"):
                rtt_str = match.group(rtt_key)
                if rtt_str and "*" not in rtt_str:
                    try:
                        rtt_values.append(float(rtt_str))
                    except ValueError:
                        pass
            
            rtt = sum(rtt_values) / len(rtt_values) if rtt_values else None
            hops.append(HopModel(hop=hop_num, ip=ip, rtt_ms=rtt))
        else:
            # Try to handle "* * *" timeout lines
            parts = line.split()
            if parts and parts[0].isdigit():
                hop_num = int(parts[0])
                if all(p == "*" for p in parts[1:]):
                    hops.append(HopModel(hop=hop_num, ip=None, rtt_ms=None))
    return hops


def _parse_scamper_hops(output: str) -> List[HopModel]:
    """Parse scamper trace output into hop records.
    
    Scamper output format varies but typically:
      trace to 8.8.8.8
      1  192.168.1.1  0.456 ms
      2  10.0.0.1  5.123 ms
    """
    hops: List[HopModel] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("trace") or line.startswith("scamper"):
            continue
        
        match = SCAMPER_HOP_PATTERN.match(line)
        if match:
            hop_num = int(match.group("hop"))
            ip_raw = match.group("ip").strip()
            ip = None if "*" in ip_raw else ip_raw
            try:
                rtt = float(match.group("rtt"))
            except ValueError:
                rtt = None
            hops.append(HopModel(hop=hop_num, ip=ip, rtt_ms=rtt))
    return hops


async def run_traceroute(target: str) -> MeasurementResult:
    """Run traceroute/scamper and normalize output."""
    tool = _pick_tool()
    started_at = datetime.utcnow()
    
    if tool == "scamper":
        # scamper can read targets from stdin with -f -
        cmd = ["scamper", "-c", "trace -P icmp", "-O", "text", "-i", target]
        code, output = await _run_subprocess(cmd)
        hops = _parse_scamper_hops(output)
    else:
        # Standard traceroute with numeric output
        cmd = ["traceroute", "-n", target]
        code, output = await _run_subprocess(cmd)
        hops = _parse_traceroute_hops(output)
    
    success = code == 0 and len(hops) > 0
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
