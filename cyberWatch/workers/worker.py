"""Async worker: pulls targets, runs traceroute, stores results."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from pydantic import BaseModel, IPvAnyAddress

from cyberWatch.db.pg import create_pool, insert_measurement
from cyberWatch.db.settings import get_worker_settings_with_defaults, apply_cache_settings
from cyberWatch.scheduler.queue import TargetQueue, TargetTask
from cyberWatch.logging_config import get_logger

logger = get_logger("worker")

# Default task timeout (can be overridden by settings)
DEFAULT_TASK_TIMEOUT_SECONDS = 300

class HopModel(BaseModel):
    hop: int
    ip: Optional[str]
    rtt_ms: Optional[float]


class MeasurementResult(BaseModel):
    target: str  # Can be IP or domain
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
    cmd_str = " ".join(cmd)
    logger.debug(
        f"Executing subprocess command",
        extra={
            "command": cmd_str,
            "has_stdin": stdin_data is not None,
        }
    )
    
    start_time = time.time()
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    stdin_bytes = stdin_data.encode("utf-8") if stdin_data else None
    stdout, _ = await process.communicate(input=stdin_bytes)
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    returncode = process.returncode or 0
    duration = time.time() - start_time
    
    logger.info(
        f"Subprocess completed",
        extra={
            "command": cmd_str,
            "exit_code": returncode,
            "duration": round(duration * 1000, 2),
            "output_length": len(output),
            "outcome": "success" if returncode == 0 else "error",
        }
    )
    
    if returncode != 0:
        logger.warning(
            f"Subprocess exited with non-zero code",
            extra={
                "command": cmd_str,
                "exit_code": returncode,
                "stderr_output": output[:500],  # First 500 chars
            }
        )
    
    return returncode, output


def _pick_tool() -> str:
    """Choose scamper if available, otherwise traceroute."""
    if shutil.which("scamper"):
        logger.debug("Selected scamper for traceroute measurements")
        return "scamper"
    if shutil.which("traceroute"):
        logger.debug("Selected traceroute for measurements")
        return "traceroute"
    logger.error("No traceroute tool available", extra={"outcome": "error"})
    raise RuntimeError("Neither scamper nor traceroute is available on PATH")


def _parse_traceroute_hops(output: str) -> List[HopModel]:
    """Parse standard traceroute output into hop records.
    
    Handles formats like:
      1  192.168.1.1  0.456 ms  0.412 ms  0.398 ms
      2  * * *
      3  10.0.0.1 (10.0.0.1)  5.123 ms  4.987 ms  5.001 ms
    """
    hops: List[HopModel] = []
    lines_parsed = 0
    lines_matched = 0
    
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("traceroute"):
            continue
        
        lines_parsed += 1
        match = TRACEROUTE_PATTERN.match(line)
        if match:
            lines_matched += 1
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
                    lines_matched += 1
    
    logger.debug(
        "Parsed traceroute output",
        extra={
            "tool": "traceroute",
            "lines_parsed": lines_parsed,
            "lines_matched": lines_matched,
            "hops_found": len(hops),
        }
    )
    
    return hops


def _parse_scamper_hops(output: str) -> List[HopModel]:
    """Parse scamper trace output into hop records.
    
    Scamper output format varies but typically:
      trace to 8.8.8.8
      1  192.168.1.1  0.456 ms
      2  10.0.0.1  5.123 ms
    """
    hops: List[HopModel] = []
    lines_parsed = 0
    lines_matched = 0
    
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("trace") or line.startswith("scamper"):
            continue
        
        lines_parsed += 1
        match = SCAMPER_HOP_PATTERN.match(line)
        if match:
            lines_matched += 1
            hop_num = int(match.group("hop"))
            ip_raw = match.group("ip").strip()
            ip = None if "*" in ip_raw else ip_raw
            try:
                rtt = float(match.group("rtt"))
            except ValueError:
                rtt = None
            hops.append(HopModel(hop=hop_num, ip=ip, rtt_ms=rtt))
    
    logger.debug(
        "Parsed scamper output",
        extra={
            "tool": "scamper",
            "lines_parsed": lines_parsed,
            "lines_matched": lines_matched,
            "hops_found": len(hops),
        }
    )
    
    return hops


async def run_traceroute(target: str) -> MeasurementResult:
    """Run traceroute/scamper and normalize output."""
    logger.info(
        "Starting traceroute",
        extra={
            "target": target,
            "action": "traceroute_start",
        }
    )
    
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
    
    logger.info(
        "Traceroute completed",
        extra={
            "target": target,
            "tool": tool,
            "success": success,
            "hop_count": len(hops),
            "exit_code": code,
            "outcome": "success" if success else "failed",
        }
    )
    
    return MeasurementResult(
        target=target,
        timestamp=started_at,
        tool=tool,
        success=success,
        hops=hops,
        raw_output=output,
    )


class Worker:
    """Measurement worker loop with rate limiting and task timeout."""

    def __init__(self) -> None:
        self.queue = TargetQueue()
        dsn = os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch")
        self.pg_dsn = dsn
        self.rate_limit_per_minute = 30  # Default
        self.max_concurrent = 5  # Default
        self.task_timeout_seconds = DEFAULT_TASK_TIMEOUT_SECONDS
        self.semaphore: Optional[asyncio.Semaphore] = None
        self.rate_limiter_tokens: List[float] = []  # Token bucket timestamps

    async def _apply_rate_limit(self) -> None:
        """Token bucket rate limiter."""
        now = time.time()
        # Remove tokens older than 60 seconds
        self.rate_limiter_tokens = [t for t in self.rate_limiter_tokens if now - t < 60]
        
        if len(self.rate_limiter_tokens) >= self.rate_limit_per_minute:
            # Wait until oldest token expires
            oldest = min(self.rate_limiter_tokens)
            wait_time = 60 - (now - oldest) + 0.1  # Add small buffer
            logger.debug(
                f"Rate limit reached, waiting {wait_time:.2f}s",
                extra={"tokens_used": len(self.rate_limiter_tokens), "limit": self.rate_limit_per_minute}
            )
            await asyncio.sleep(wait_time)
            # Re-check after waiting
            await self._apply_rate_limit()
        else:
            # Add token
            self.rate_limiter_tokens.append(now)

    async def run(self) -> None:
        logger.info(
            "Worker starting",
            extra={
                "component": "worker",
                "state": "starting",
                "pg_dsn": self.pg_dsn.split("@")[-1] if "@" in self.pg_dsn else "local",
            }
        )
        
        pool = await create_pool(self.pg_dsn)
        
        # Apply cache settings for enrichment modules
        await apply_cache_settings(pool)
        
        # Load settings from database with defaults
        settings = await get_worker_settings_with_defaults(pool)
        self.rate_limit_per_minute = settings.get("rate_limit_per_minute", 30)
        self.max_concurrent = settings.get("max_concurrent_traceroutes", 5)
        self.task_timeout_seconds = settings.get("task_timeout_seconds", DEFAULT_TASK_TIMEOUT_SECONDS)
        
        logger.info(
            "Worker settings loaded",
            extra={
                "rate_limit": self.rate_limit_per_minute,
                "max_concurrent": self.max_concurrent,
                "task_timeout": self.task_timeout_seconds,
            }
        )
        
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        
        logger.info(
            "Worker ready",
            extra={
                "component": "worker",
                "state": "ready",
                "rate_limit_per_minute": self.rate_limit_per_minute,
                "max_concurrent": self.max_concurrent,
                "task_timeout_seconds": self.task_timeout_seconds,
            }
        )
        
        try:
            while True:
                task = await self.queue.dequeue(timeout=5)
                if task is None:
                    logger.debug("No tasks in queue, waiting...")
                    continue
                
                # Apply rate limiting before processing
                await self._apply_rate_limit()
                
                # Process task with concurrency control
                asyncio.create_task(self._handle_task_with_semaphore(pool, task))
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user", extra={"state": "interrupted"})
        except Exception as exc:
            logger.error(
                f"Worker error: {str(exc)}",
                exc_info=True,
                extra={"outcome": "error", "error_type": type(exc).__name__}
            )
        finally:
            logger.info("Worker shutting down", extra={"state": "shutdown"})
            await pool.close()
            await self.queue.close()
            logger.info("Worker stopped", extra={"state": "stopped"})

    async def _handle_task_with_semaphore(self, pool, task: TargetTask) -> None:
        """Handle task with semaphore to limit concurrency and timeout to prevent hangs."""
        async with self.semaphore:
            try:
                await asyncio.wait_for(
                    self.handle_task(pool, task),
                    timeout=self.task_timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Task timed out",
                    extra={
                        "target": str(task.target_ip),
                        "source": task.source,
                        "timeout_seconds": self.task_timeout_seconds,
                        "outcome": "timeout",
                    }
                )
            except Exception as exc:
                logger.error(
                    f"Task failed with unexpected error: {exc}",
                    exc_info=True,
                    extra={
                        "target": str(task.target_ip),
                        "source": task.source,
                        "outcome": "error",
                        "error_type": type(exc).__name__,
                    }
                )

    async def handle_task(self, pool, task: TargetTask) -> None:
        task_id = str(uuid.uuid4())
        
        logger.info(
            "Processing task",
            extra={
                "task_id": task_id,
                "target": str(task.target_ip),
                "source": task.source,
                "action": "task_start",
            }
        )
        
        try:
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
            
            logger.info(
                "Task completed successfully",
                extra={
                    "task_id": task_id,
                    "target": str(task.target_ip),
                    "tool": result.tool,
                    "hop_count": len(result.hops),
                    "success": result.success,
                    "outcome": "success",
                }
            )
        except Exception as exc:
            logger.error(
                f"Task failed: {str(exc)}",
                exc_info=True,
                extra={
                    "task_id": task_id,
                    "target": str(task.target_ip),
                    "outcome": "error",
                    "error_type": type(exc).__name__,
                }
            )


async def main() -> None:
    worker = Worker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
