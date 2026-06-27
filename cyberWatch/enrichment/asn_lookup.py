"""ASN lookup utilities (Team Cymru WHOIS / DNS)."""
from __future__ import annotations

import asyncio
import ipaddress
import time
from typing import Any, Dict, Optional

import dns.asyncresolver
from pydantic import BaseModel

from cyberWatch.logging_config import get_logger

logger = get_logger("asn_lookup")

# Default cache TTL - can be overridden via settings
DEFAULT_CACHE_TTL_SECONDS = 3600


class AsnInfo(BaseModel):
    asn: Optional[int]
    prefix: Optional[str]
    org_name: Optional[str]
    country: Optional[str]


# Module-level cache with configurable TTL
_cache: Dict[str, tuple[float, AsnInfo]] = {}
_cache_ttl: float = DEFAULT_CACHE_TTL_SECONDS


def set_cache_ttl(ttl_seconds: float) -> None:
    """Set the cache TTL for ASN lookups. Called from settings initialization."""
    global _cache_ttl
    _cache_ttl = ttl_seconds
    logger.debug(f"ASN lookup cache TTL set to {ttl_seconds}s", extra={"cache_ttl": ttl_seconds})


def _cache_get(ip: str) -> Optional[AsnInfo]:
    entry = _cache.get(ip)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > _cache_ttl:
        _cache.pop(ip, None)
        logger.debug(f"Cache expired for {ip}", extra={"ip": ip, "action": "cache_expire"})
        return None
    return value


def _cache_set(ip: str, info: AsnInfo) -> None:
    _cache[ip] = (time.time(), info)


def _validate_ip(ip_str: str) -> Optional[str]:
    """
    Validate and normalize an IP address string.
    
    Returns the normalized IP string, or None if invalid.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
        return str(addr)
    except ValueError:
        return None


async def lookup_asn(ip: Any) -> AsnInfo:
    """
    Look up ASN information for an IP address.
    
    Args:
        ip: IP address (string or IPvAnyAddress)
        
    Returns:
        AsnInfo with ASN, prefix, org_name, and country (may have None fields)
    """
    ip_str = str(ip)
    
    # Validate IP address early
    normalized_ip = _validate_ip(ip_str)
    if normalized_ip is None:
        logger.warning(
            "Invalid IP address for ASN lookup",
            extra={"ip": ip_str, "outcome": "error", "error": "invalid_ip"}
        )
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)
    
    ip_str = normalized_ip
    
    # Check cache first
    cached = _cache_get(ip_str)
    if cached:
        logger.debug(
            "ASN lookup cache hit",
            extra={"ip": ip_str, "asn": cached.asn, "outcome": "cache_hit"}
        )
        return cached

    start_time = time.time()
    
    # Try WHOIS first
    info = await _lookup_whois(ip_str)
    source = "cymru_whois"
    
    if info.asn is None:
        # Fall back to DNS
        info = await _lookup_dns(ip_str)
        source = "cymru_dns"
    
    duration_ms = round((time.time() - start_time) * 1000, 2)
    
    _cache_set(ip_str, info)
    
    if info.asn is not None:
        logger.info(
            "ASN lookup completed",
            extra={
                "ip": ip_str,
                "asn": info.asn,
                "prefix": info.prefix,
                "org_name": info.org_name,
                "country": info.country,
                "source": source,
                "duration": duration_ms,
                "outcome": "success",
            }
        )
    else:
        logger.warning(
            "ASN lookup returned no result",
            extra={
                "ip": ip_str,
                "source": source,
                "duration": duration_ms,
                "outcome": "no_result",
            }
        )
    
    return info


async def _lookup_whois(ip: str) -> AsnInfo:
    """Look up ASN via Team Cymru WHOIS service."""
    try:
        query = f" -f {ip}"
        process = await asyncio.create_subprocess_exec(
            "whois",
            "-h",
            "whois.cymru.com",
            query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.debug(
            "WHOIS command not found, skipping WHOIS lookup",
            extra={"ip": ip, "outcome": "whois_not_available"}
        )
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)
    except Exception as exc:
        logger.warning(
            f"WHOIS subprocess creation failed: {exc}",
            extra={"ip": ip, "outcome": "error", "error_type": type(exc).__name__}
        )
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning(
            "WHOIS lookup timed out",
            extra={"ip": ip, "outcome": "timeout"}
        )
        try:
            process.kill()
        except Exception:
            pass
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)
    
    text = stdout.decode("utf-8", errors="replace") if stdout else ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Expected format: AS|IP|BGP Prefix|CC|Registry|Allocated|AS Name
    for line in lines:
        if line.lower().startswith("as|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 7:
            continue
        try:
            asn = int(parts[0]) if parts[0].isdigit() else None
        except ValueError:
            asn = None
        prefix = parts[2] or None
        country = parts[3] or None
        org_name = parts[6] or None
        return AsnInfo(asn=asn, prefix=prefix, org_name=org_name, country=country)
    return AsnInfo(asn=None, prefix=None, org_name=None, country=None)


async def _lookup_dns(ip: str) -> AsnInfo:
    """Look up ASN via Team Cymru DNS service."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        logger.debug(
            "Invalid IP for DNS lookup",
            extra={"ip": ip, "outcome": "invalid_ip"}
        )
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)

    if addr.version == 4:
        reversed_ip = ".".join(reversed(ip.split(".")))
        query = f"{reversed_ip}.origin.asn.cymru.com"
    else:
        # nibble-reverse IPv6 and use origin6.asn.cymru.com
        reversed_ip = ".".join(reversed(addr.exploded.replace(":", "")))
        query = f"{reversed_ip}.origin6.asn.cymru.com"

    try:
        answers = await asyncio.wait_for(
            dns.asyncresolver.resolve(query, "TXT"),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        logger.warning(
            "DNS ASN lookup timed out",
            extra={"ip": ip, "query": query, "outcome": "timeout"}
        )
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)
    except dns.asyncresolver.NXDOMAIN:
        logger.debug(
            "No DNS record for IP",
            extra={"ip": ip, "query": query, "outcome": "nxdomain"}
        )
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)
    except Exception as exc:
        logger.debug(
            f"DNS lookup failed: {exc}",
            extra={"ip": ip, "query": query, "outcome": "error", "error_type": type(exc).__name__}
        )
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)

    # TXT format: "ASN | PREFIX | CC | REGISTRY | ALLOCATED | AS NAME"
    for rdata in answers:
        txt = rdata.to_text().replace('"', '').strip()
        parts = [p.strip() for p in txt.split("|")]
        if len(parts) < 2:
            continue
        try:
            asn = int(parts[0].split()[0])
        except ValueError:
            asn = None
        prefix = parts[1] if len(parts) >= 2 else None
        country = parts[2] if len(parts) >= 3 else None
        org_name = parts[5] if len(parts) >= 6 else None
        return AsnInfo(asn=asn, prefix=prefix, org_name=org_name, country=country)

    return AsnInfo(asn=None, prefix=None, org_name=None, country=None)
