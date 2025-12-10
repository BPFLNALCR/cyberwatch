"""On-demand traceroute and mtr endpoints."""
from __future__ import annotations

import asyncio
import shutil
from typing import List

from fastapi import APIRouter, HTTPException

from cyberWatch.api.models import TracerouteRequest, ok, err
from cyberWatch.workers.worker import run_traceroute

router = APIRouter(prefix="/traceroute", tags=["traceroute"])


async def _run_mtr(target: str) -> dict:
    if shutil.which("mtr") is None:
        raise RuntimeError("mtr not installed")
    cmd = ["mtr", "-n", "-c", "5", "-r", target]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    hops: List[dict] = []
    for line in lines:
        if line.startswith("HOST"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        hop_num = parts[0]
        ip = parts[1] if parts[1] != "???" else None
        rtt = float(parts[2]) if len(parts) >= 3 else None
        hops.append({"hop": int(hop_num), "ip": ip, "rtt_ms": rtt})
    return {"raw": output, "hops": hops}


@router.post("/run")
async def run(req: TracerouteRequest):
    result = await run_traceroute(req.target)
    return ok(result.model_dump())


@router.post("/mtr/run")
async def run_mtr(req: TracerouteRequest):
    try:
        data = await _run_mtr(req.target)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return ok(data)
