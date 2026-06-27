"""On-demand traceroute and mtr endpoints with enhanced analytics."""
from __future__ import annotations

import asyncio
import re
import shutil
import socket
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from cyberWatch.api.models import TracerouteRequest, ok
from cyberWatch.api.utils.db import pg_dep
from cyberWatch.workers.worker import run_traceroute
from cyberWatch.enrichment.asn_lookup import lookup_asn, AsnInfo
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/traceroute", tags=["traceroute"])


def _http_error(code: int, message: str) -> None:
    raise HTTPException(status_code=code, detail={"status": "error", "message": message})


def _is_ip_address(target: str) -> bool:
    """Check if target is an IP address (IPv4 or IPv6)."""
    try:
        socket.inet_pton(socket.AF_INET, target)
        return True
    except socket.error:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, target)
        return True
    except socket.error:
        pass
    return False


async def _resolve_domain(domain: str) -> Optional[str]:
    """Resolve a domain to its first IP address."""
    try:
        loop = asyncio.get_event_loop()
        # Use getaddrinfo which handles both IPv4 and IPv6
        result = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(domain, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        )
        if result:
            # Return the first IP address found
            return result[0][4][0]
    except socket.gaierror as e:
        logger.warning(f"Failed to resolve domain {domain}: {e}")
    except Exception as e:
        logger.error(f"DNS resolution error for {domain}: {e}")
    return None


async def _enrich_hop(ip: str) -> Dict[str, Any]:
    """Get detailed enrichment for a hop IP."""
    info = await lookup_asn(ip)
    return {
        "ip": ip,
        "asn": info.asn,
        "prefix": info.prefix,
        "org_name": info.org_name,
        "country": info.country,
    }


async def _lookup_hop_details(hops) -> List[Dict[str, Any]]:
    """Enrich all hops with ASN and geolocation data."""
    ips = [hop.ip for hop in hops if getattr(hop, "ip", None)]
    if not ips:
        return []
    
    tasks = [_enrich_hop(ip) for ip in ips]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    enriched = []
    for ip, res in zip(ips, results):
        if isinstance(res, Exception):
            enriched.append({"ip": ip, "asn": None, "prefix": None, "org_name": None, "country": None})
        else:
            enriched.append(res)
    return enriched


def _compute_analytics(hops, enriched_hops: List[Dict]) -> Dict[str, Any]:
    """Compute cyber defense relevant analytics from traceroute results."""
    total_hops = len(hops)
    responding_hops = sum(1 for h in hops if getattr(h, "ip", None))
    timeout_hops = total_hops - responding_hops
    
    # RTT analysis
    rtts = [h.rtt_ms for h in hops if getattr(h, "rtt_ms", None) is not None]
    rtt_stats = {}
    if rtts:
        rtt_stats = {
            "min_ms": round(min(rtts), 2),
            "max_ms": round(max(rtts), 2),
            "avg_ms": round(sum(rtts) / len(rtts), 2),
            "total_ms": round(sum(rtts), 2),
        }
        # Detect latency anomalies (hops with RTT > 2x average)
        avg_rtt = rtt_stats["avg_ms"]
        high_latency_hops = [
            {"hop": h.hop, "ip": h.ip, "rtt_ms": h.rtt_ms}
            for h in hops 
            if getattr(h, "rtt_ms", None) and h.rtt_ms > avg_rtt * 2
        ]
        rtt_stats["high_latency_hops"] = high_latency_hops
    
    # ASN path analysis
    asn_path = []
    unique_asns = set()
    countries_traversed = set()
    organizations = []
    
    for eh in enriched_hops:
        if eh.get("asn"):
            if eh["asn"] not in unique_asns:
                unique_asns.add(eh["asn"])
                asn_path.append({
                    "asn": eh["asn"],
                    "org_name": eh.get("org_name"),
                    "country": eh.get("country"),
                })
                if eh.get("org_name"):
                    organizations.append(eh["org_name"])
        if eh.get("country"):
            countries_traversed.add(eh["country"])
    
    # Network boundary crossings (AS transitions)
    as_transitions = []
    prev_asn = None
    for eh in enriched_hops:
        curr_asn = eh.get("asn")
        if curr_asn and prev_asn and curr_asn != prev_asn:
            as_transitions.append({
                "from_asn": prev_asn,
                "to_asn": curr_asn,
            })
        if curr_asn:
            prev_asn = curr_asn
    
    return {
        "hop_count": total_hops,
        "responding_hops": responding_hops,
        "timeout_hops": timeout_hops,
        "packet_loss_pct": round((timeout_hops / total_hops) * 100, 1) if total_hops > 0 else 0,
        "rtt_stats": rtt_stats,
        "asn_count": len(unique_asns),
        "asn_path": asn_path,
        "as_transitions": as_transitions,
        "countries_traversed": list(countries_traversed),
        "organizations": organizations,
    }


async def _save_measurement(
    pool: asyncpg.Pool,
    target: str,
    tool: str,
    started_at: datetime,
    completed_at: datetime,
    success: bool,
    raw_output: str,
    hops: List,
    enriched_hops: List[Dict],
    source: str = "web_ui",
) -> int:
    """Save traceroute measurement to database."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Get or create target
            existing = await conn.fetchrow(
                "SELECT id FROM targets WHERE target_ip = $1",
                target,
            )
            if existing:
                target_id = existing["id"]
            else:
                target_id = await conn.fetchval(
                    "INSERT INTO targets (target_ip, source) VALUES ($1, $2) RETURNING id",
                    target,
                    source,
                )
            
            # Insert measurement
            measurement_id = await conn.fetchval(
                """
                INSERT INTO measurements (target_id, tool, started_at, completed_at, success, raw_output)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                target_id,
                tool,
                started_at,
                completed_at,
                success,
                raw_output,
            )
            
            # Create IP to enrichment lookup
            ip_to_enrichment = {eh["ip"]: eh for eh in enriched_hops}
            
            # Insert hops with enrichment
            for hop in hops:
                hop_ip = getattr(hop, "ip", None)
                enrichment = ip_to_enrichment.get(hop_ip, {}) if hop_ip else {}
                
                await conn.execute(
                    """
                    INSERT INTO hops (measurement_id, hop_number, hop_ip, rtt_ms, asn, prefix, org_name, country_code)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    measurement_id,
                    hop.hop,
                    hop_ip,
                    getattr(hop, "rtt_ms", None),
                    enrichment.get("asn"),
                    enrichment.get("prefix"),
                    enrichment.get("org_name"),
                    enrichment.get("country"),
                )
            
            # Update target last seen
            await conn.execute(
                "UPDATE targets SET last_seen = $1 WHERE id = $2",
                completed_at,
                target_id,
            )
            
            # Mark as enriched if we have data
            if enriched_hops:
                await conn.execute(
                    "UPDATE measurements SET enriched = TRUE, enriched_at = $2 WHERE id = $1",
                    measurement_id,
                    datetime.utcnow(),
                )
            
            return measurement_id


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
                    rtt = None
            except ValueError:
                rtt = None
            hops.append({
                "hop": hop_num, 
                "ip": ip, 
                "rtt_ms": rtt,
                "loss_pct": float(match.group("loss")),
                "sent": int(match.group("snt")),
                "best_ms": float(match.group("best")),
                "worst_ms": float(match.group("wrst")),
            })
    
    return {"raw": output, "hops": hops}


@router.post("/run")
async def run(req: TracerouteRequest, pool: asyncpg.Pool = Depends(pg_dep), request: Request = None):
    """Run traceroute with enhanced analytics and save to database."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    original_target = req.target.strip()
    is_domain = not _is_ip_address(original_target)
    resolved_ip: Optional[str] = None
    
    # If target is a domain, resolve it first for database storage
    if is_domain:
        resolved_ip = await _resolve_domain(original_target)
        if not resolved_ip:
            logger.warning(
                f"Failed to resolve domain: {original_target}",
                extra={
                    "request_id": request_id,
                    "target": original_target,
                    "outcome": "dns_error",
                }
            )
            _http_error(status.HTTP_400_BAD_REQUEST, f"Could not resolve domain: {original_target}")
        logger.info(
            f"Resolved domain {original_target} to {resolved_ip}",
            extra={
                "request_id": request_id,
                "domain": original_target,
                "resolved_ip": resolved_ip,
            }
        )
    
    logger.info(
        "Traceroute requested",
        extra={
            "request_id": request_id,
            "user_input": {"target": original_target},
            "is_domain": is_domain,
            "resolved_ip": resolved_ip,
            "action": "traceroute_start",
        }
    )
    
    started_at = datetime.utcnow()
    
    try:
        # Run traceroute with the original target (domain or IP)
        # The traceroute tool itself will resolve domains
        result = await run_traceroute(original_target)
        logger.info(
            "Traceroute execution completed",
            extra={
                "request_id": request_id,
                "target": original_target,
                "tool": result.tool,
                "success": result.success,
                "hop_count": len(result.hops),
                "outcome": "success",
            }
        )
    except RuntimeError as exc:
        logger.error(
            f"Traceroute tool unavailable: {str(exc)}",
            extra={
                "request_id": request_id,
                "target": original_target,
                "outcome": "error",
                "error_type": "tool_unavailable",
            }
        )
        _http_error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    except Exception as exc:
        logger.error(
            f"Traceroute failed: {str(exc)}",
            exc_info=True,
            extra={
                "request_id": request_id,
                "target": original_target,
                "outcome": "error",
                "error_type": type(exc).__name__,
            }
        )
        _http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Traceroute failed: {exc}")
    
    completed_at = datetime.utcnow()
    
    # Enrich hops with ASN/geo data
    enriched_hops = await _lookup_hop_details(result.hops)
    
    # Compute analytics
    analytics = _compute_analytics(result.hops, enriched_hops)
    
    # Build ASN hints for backwards compatibility
    asn_hints = [eh["asn"] for eh in enriched_hops if eh.get("asn")]
    # Remove duplicates while preserving order
    seen = set()
    asn_hints = [x for x in asn_hints if not (x in seen or seen.add(x))]
    
    # Use resolved IP for database storage (INET column requires IP, not domain)
    target_for_db = resolved_ip if is_domain and resolved_ip else original_target
    
    # Save to database
    try:
        measurement_id = await _save_measurement(
            pool,
            target_for_db,
            result.tool,
            started_at,
            completed_at,
            result.success,
            result.raw_output,
            result.hops,
            enriched_hops,
            source="web_ui",
        )
        logger.info(
            "Measurement saved to database",
            extra={
                "request_id": request_id,
                "measurement_id": measurement_id,
                "target": original_target,
                "target_ip": target_for_db,
                "hop_count": len(result.hops),
                "enriched": len(enriched_hops) > 0,
            }
        )
    except Exception as exc:
        logger.error(
            f"Failed to save measurement: {str(exc)}",
            exc_info=True,
            extra={
                "request_id": request_id,
                "target": req.target,
                "outcome": "db_error",
            }
        )
        measurement_id = None
    
    # Build response
    payload = result.model_dump()
    payload["measurement_id"] = measurement_id
    payload["asn_hints"] = asn_hints
    payload["enriched_hops"] = enriched_hops
    payload["analytics"] = analytics
    payload["timestamp"] = started_at.isoformat()
    payload["duration_ms"] = round((completed_at - started_at).total_seconds() * 1000, 2)
    # Include domain resolution info
    payload["original_target"] = original_target
    payload["is_domain"] = is_domain
    if is_domain and resolved_ip:
        payload["resolved_ip"] = resolved_ip
    
    # Debug: log what we're returning
    logger.debug(
        "Traceroute response payload",
        extra={
            "request_id": request_id,
            "target": original_target,
            "tool": result.tool,
            "success": result.success,
            "hop_count": len(result.hops),
            "raw_output_length": len(result.raw_output) if result.raw_output else 0,
            "raw_output_preview": (result.raw_output[:200] if result.raw_output else "EMPTY"),
        }
    )
    
    return ok(payload)


@router.post("/mtr/run")
async def run_mtr_endpoint(req: TracerouteRequest):
    """Run MTR with enhanced statistics."""
    try:
        data = await _run_mtr(req.target)
    except Exception as exc:
        _http_error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return ok(data)


@router.get("/history")
async def get_history(
    target: Optional[str] = Query(None, description="Filter by target IP/hostname"),
    limit: int = Query(50, ge=1, le=200),
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    """Get traceroute measurement history."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Fetching traceroute history",
        extra={
            "request_id": request_id,
            "user_input": {"target": target, "limit": limit},
        }
    )
    
    if target:
        rows = await pool.fetch(
            """
            SELECT m.id, t.target_ip as target, m.tool, m.started_at, m.completed_at, 
                   m.success, m.enriched,
                   (SELECT COUNT(*) FROM hops WHERE measurement_id = m.id) as hop_count,
                   (SELECT COUNT(DISTINCT asn) FROM hops WHERE measurement_id = m.id AND asn IS NOT NULL) as asn_count
            FROM measurements m
            JOIN targets t ON t.id = m.target_id
            WHERE t.target_ip = $1 OR t.target_ip::text LIKE $2
            ORDER BY m.started_at DESC
            LIMIT $3
            """,
            target,
            f"%{target}%",
            limit,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT m.id, t.target_ip as target, m.tool, m.started_at, m.completed_at, 
                   m.success, m.enriched,
                   (SELECT COUNT(*) FROM hops WHERE measurement_id = m.id) as hop_count,
                   (SELECT COUNT(DISTINCT asn) FROM hops WHERE measurement_id = m.id AND asn IS NOT NULL) as asn_count
            FROM measurements m
            JOIN targets t ON t.id = m.target_id
            ORDER BY m.started_at DESC
            LIMIT $1
            """,
            limit,
        )
    
    return ok([
        {
            "id": row["id"],
            "target": str(row["target"]),
            "tool": row["tool"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            "success": row["success"],
            "enriched": row["enriched"],
            "hop_count": row["hop_count"],
            "asn_count": row["asn_count"],
        }
        for row in rows
    ])


@router.get("/history/{measurement_id}")
async def get_measurement_detail(measurement_id: int, pool: asyncpg.Pool = Depends(pg_dep)):
    """Get detailed traceroute measurement with hops and analytics."""
    measurement = await pool.fetchrow(
        """
        SELECT m.id, t.target_ip as target, m.tool, m.started_at, m.completed_at, 
               m.success, m.raw_output, m.enriched
        FROM measurements m
        JOIN targets t ON t.id = m.target_id
        WHERE m.id = $1
        """,
        measurement_id,
    )
    
    if not measurement:
        raise HTTPException(status_code=404, detail="Measurement not found")
    
    hops = await pool.fetch(
        """
        SELECT hop_number as hop, hop_ip as ip, rtt_ms, asn, prefix, org_name, country_code as country
        FROM hops
        WHERE measurement_id = $1
        ORDER BY hop_number ASC
        """,
        measurement_id,
    )
    
    hops_list = [dict(h) for h in hops]
    
    # Build enriched hops for analytics
    enriched_hops = [
        {
            "ip": str(h["ip"]) if h["ip"] else None,
            "asn": h["asn"],
            "prefix": str(h["prefix"]) if h["prefix"] else None,
            "org_name": h["org_name"],
            "country": h["country"],
        }
        for h in hops_list if h.get("ip")
    ]
    
    # Compute analytics from stored hops
    class HopObj:
        def __init__(self, hop, ip, rtt_ms):
            self.hop = hop
            self.ip = str(ip) if ip else None
            self.rtt_ms = rtt_ms
    
    hop_objects = [HopObj(h["hop"], h["ip"], h["rtt_ms"]) for h in hops_list]
    analytics = _compute_analytics(hop_objects, enriched_hops)
    
    return ok({
        "id": measurement["id"],
        "target": str(measurement["target"]),
        "tool": measurement["tool"],
        "started_at": measurement["started_at"].isoformat() if measurement["started_at"] else None,
        "completed_at": measurement["completed_at"].isoformat() if measurement["completed_at"] else None,
        "success": measurement["success"],
        "raw_output": measurement["raw_output"],
        "hops": hops_list,
        "enriched_hops": enriched_hops,
        "analytics": analytics,
    })
