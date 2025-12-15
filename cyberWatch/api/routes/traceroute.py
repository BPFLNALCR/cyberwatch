"""On-demand traceroute and mtr endpoints."""
from __future__ import annotations

import asyncio
import shutil
from typing import List

from fastapi import APIRouter, HTTPException, status

from cyberWatch.api.models import TracerouteRequest, ok
from cyberWatch.workers.worker import run_traceroute
from cyberWatch.enrichment.asn_lookup import lookup_asn

router = APIRouter(prefix="/traceroute", tags=["traceroute"])


def _http_error(code: int, message: str) -> None:
    raise HTTPException(status_code=code, detail={"status": "error", "message": message})


async def _lookup_hop_asns(hops) -> List[int]:
    ips = [hop.ip for hop in hops if getattr(hop, "ip", None)]
    if not ips:
        return []
    tasks = [lookup_asn(ip) for ip in ips]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen = set()
    ordered: List[int] = []
    for res in results:
        if isinstance(res, Exception) or getattr(res, "asn", None) is None:
            continue
        asn_val = int(res.asn)
        if asn_val not in seen:
            seen.add(asn_val)
            ordered.append(asn_val)
    return ordered


async def _run_mtr(target: str) -> dict:
    if shutil.which("mtr") is None:
        raise RuntimeError("mtr not installed")
    # -n: numeric only, -c 5: 5 pings per hop, -r: report mode, -w: wide output
    cmd = ["mtr", "-n", "-c", "5", "-r", "-w", target]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    hops: List[dict] = []
    
    # MTR report format:
    # Start: 2024-01-01T12:00:00+0000
    # HOST: hostname                    Loss%   Snt   Last   Avg  Best  Wrst StDev
    #   1.|-- 192.168.1.1               0.0%     5    0.5   0.4   0.3   0.5   0.1
    #   2.|-- ???                      100.0     5    0.0   0.0   0.0   0.0   0.0
    
    import re
    mtr_hop_pattern = re.compile(
        r"^\s*(?P<hop>\d+)\.\|--\s+(?P<ip>\S+)\s+"
        r"(?P<loss>[0-9.]+)%?\s+"
        r"(?P<snt>\d+)\s+"
        r"(?P<last>[0-9.]+)\s+"
        r"(?P<avg>[0-9.]+)\s+"
        r"(?P<best>[0-9.]+)\s+"
        r"(?P<wrst>[0-9.]+)"
    )
    
    for line in lines:
        if line.startswith("HOST:") or line.startswith("Start:"):
            continue
        match = mtr_hop_pattern.match(line)
        if match:
            hop_num = int(match.group("hop"))
            ip_raw = match.group("ip")
            ip = None if ip_raw == "???" or "*" in ip_raw else ip_raw
            try:
                rtt = float(match.group("avg"))
                if rtt == 0.0 and ip is None:
                    rtt = None  # Timeout hop
            except ValueError:
                rtt = None
            hops.append({"hop": hop_num, "ip": ip, "rtt_ms": rtt})
    
    return {"raw": output, "hops": hops}


@router.post("/run")
async def run(req: TracerouteRequest):
    try:
        result = await run_traceroute(req.target)
    except RuntimeError as exc:
        _http_error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        _http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Traceroute failed: {exc}")

    asn_hints = await _lookup_hop_asns(result.hops)
    payload = result.model_dump()
    payload["asn_hints"] = asn_hints
    return ok(payload)


@router.post("/mtr/run")
async def run_mtr(req: TracerouteRequest):
    try:
        data = await _run_mtr(req.target)
    except Exception as exc:
        _http_error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return ok(data)
