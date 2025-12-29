"""Additional free ASN enrichment sources: RIPE RIS, ip-api.com, and IPinfo free tier."""
from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

import aiohttp
from pydantic import BaseModel

from cyberWatch.logging_config import get_logger
from cyberWatch.enrichment import get_circuit_breaker, get_rate_limiter

logger = get_logger("external_sources")

# Default cache TTL - can be overridden via settings
DEFAULT_CACHE_TTL_SECONDS = 3600
_cache_ttl: float = DEFAULT_CACHE_TTL_SECONDS
_cache: Dict[str, tuple[float, 'ExternalAsnInfo']] = {}
_session: Optional[aiohttp.ClientSession] = None

# Circuit breakers for external APIs (singleton per service)
_ripe_breaker = get_circuit_breaker("ripe_stat", failure_threshold=5, recovery_time=120.0)
_ipapi_breaker = get_circuit_breaker("ip_api", failure_threshold=5, recovery_time=120.0)
_ipinfo_breaker = get_circuit_breaker("ipinfo", failure_threshold=5, recovery_time=120.0)

# Rate limiter for ip-api.com (45 requests/minute free tier)
_ipapi_limiter = get_rate_limiter("ip_api", max_requests=45, window_seconds=60.0)


def set_cache_ttl(ttl_seconds: float) -> None:
    """Set the cache TTL for external lookups. Called from settings initialization."""
    global _cache_ttl
    _cache_ttl = ttl_seconds
    logger.debug(f"External sources cache TTL set to {ttl_seconds}s", extra={"cache_ttl": ttl_seconds})


class ExternalAsnInfo(BaseModel):
    """Combined ASN info from external sources."""
    asn: Optional[int] = None
    org_name: Optional[str] = None
    country: Optional[str] = None
    prefix: Optional[str] = None
    registry: Optional[str] = None  # ARIN, RIPE, APNIC, LACNIC, AFRINIC
    source: Optional[str] = None  # Which API provided the data


def _cache_get(key: str) -> Optional[ExternalAsnInfo]:
    entry = _cache.get(key)
    if not entry:
        return None
    ts, val = entry
    if time.time() - ts > _cache_ttl:
        _cache.pop(key, None)
        return None
    return val


def _cache_set(key: str, info: ExternalAsnInfo) -> None:
    _cache[key] = (time.time(), info)


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def lookup_ripe_stat(ip_or_asn: str) -> ExternalAsnInfo:
    """
    Lookup ASN info using RIPE Stat API (free, no key required).
    Can accept IP address or ASN number.
    Uses circuit breaker to prevent cascading failures.
    """
    cache_key = f"ripe:{ip_or_asn}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug(
            f"RIPE Stat cache hit for {ip_or_asn}",
            extra={"resource": ip_or_asn, "outcome": "cache_hit"}
        )
        return cached

    # Check circuit breaker
    if _ripe_breaker.is_open():
        logger.debug(
            f"RIPE Stat circuit open, skipping lookup for {ip_or_asn}",
            extra={"resource": ip_or_asn, "circuit": "ripe_stat", "outcome": "circuit_open"}
        )
        return ExternalAsnInfo(source="ripe")

    session = await _get_session()
    
    # Determine if input is ASN or IP
    resource = ip_or_asn
    if ip_or_asn.isdigit():
        resource = f"AS{ip_or_asn}"
    
    url = "https://stat.ripe.net/data/whois/data.json"
    params = {"resource": resource}
    
    asn: Optional[int] = None
    org_name: Optional[str] = None
    country: Optional[str] = None
    prefix: Optional[str] = None
    registry: Optional[str] = None

    start_time = time.time()
    try:
        async with session.get(url, params=params, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                records = data.get("data", {}).get("records", [])
                
                # Parse WHOIS records
                for record in records:
                    for item in record:
                        key = item.get("key", "").lower()
                        value = item.get("value", "")
                        
                        if key == "origin":
                            try:
                                asn = int(value.replace("AS", "").strip())
                            except ValueError:
                                pass
                        elif key in ["netname", "descr", "org-name"]:
                            if not org_name or len(value) > len(org_name):
                                org_name = value
                        elif key == "country":
                            country = value
                        elif key == "route" or key == "route6":
                            prefix = value
                        elif key == "source":
                            registry = value
                
                _ripe_breaker.record_success()
                duration_ms = round((time.time() - start_time) * 1000, 2)
                logger.info(
                    f"RIPE Stat lookup successful for {resource}",
                    extra={
                        "resource": resource,
                        "asn": asn,
                        "duration": duration_ms,
                        "outcome": "success"
                    }
                )
            else:
                _ripe_breaker.record_failure()
                logger.warning(
                    f"RIPE Stat returned status {resp.status} for {resource}",
                    extra={"resource": resource, "status": resp.status, "outcome": "http_error"}
                )
    except asyncio.TimeoutError:
        _ripe_breaker.record_failure()
        logger.warning(
            f"RIPE Stat timeout for {resource}",
            extra={"resource": resource, "outcome": "timeout"}
        )
    except Exception as exc:
        _ripe_breaker.record_failure()
        logger.error(
            f"RIPE Stat lookup failed for {resource}: {str(exc)}",
            extra={"resource": resource, "outcome": "error", "error_type": type(exc).__name__}
        )

    info = ExternalAsnInfo(
        asn=asn,
        org_name=org_name,
        country=country,
        prefix=prefix,
        registry=registry,
        source="ripe"
    )
    _cache_set(cache_key, info)
    return info


async def lookup_ip_api(ip: str) -> ExternalAsnInfo:
    """
    Lookup IP info using ip-api.com (free tier: 45 requests/minute).
    Returns ASN, org, country, etc.
    Uses circuit breaker and rate limiter for resilience.
    """
    cache_key = f"ipapi:{ip}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug(
            f"ip-api.com cache hit for {ip}",
            extra={"ip": ip, "outcome": "cache_hit"}
        )
        return cached

    # Check circuit breaker
    if _ipapi_breaker.is_open():
        logger.debug(
            f"ip-api.com circuit open, skipping lookup for {ip}",
            extra={"ip": ip, "circuit": "ip_api", "outcome": "circuit_open"}
        )
        return ExternalAsnInfo(source="ip-api")
    
    # Check rate limiter
    if not _ipapi_limiter.try_acquire():
        wait_time = _ipapi_limiter.time_until_available()
        logger.debug(
            f"ip-api.com rate limited, need to wait {wait_time:.1f}s",
            extra={"ip": ip, "wait_time": wait_time, "outcome": "rate_limited"}
        )
        # Don't wait, just return empty - caller can retry later
        return ExternalAsnInfo(source="ip-api")

    session = await _get_session()
    url = f"http://ip-api.com/json/{ip}"
    params = {"fields": "status,country,countryCode,as,org"}
    
    asn: Optional[int] = None
    org_name: Optional[str] = None
    country: Optional[str] = None

    start_time = time.time()
    try:
        async with session.get(url, params=params, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("status") == "success":
                    # Format: "AS15169 Google LLC"
                    as_field = data.get("as", "")
                    if as_field:
                        parts = as_field.split(None, 1)
                        if parts:
                            try:
                                asn = int(parts[0].replace("AS", ""))
                            except ValueError:
                                pass
                        if len(parts) > 1:
                            org_name = parts[1]
                    
                    country = data.get("countryCode")
                    
                    _ipapi_breaker.record_success()
                    duration_ms = round((time.time() - start_time) * 1000, 2)
                    logger.info(
                        f"ip-api.com lookup successful for {ip}",
                        extra={
                            "ip": ip,
                            "asn": asn,
                            "duration": duration_ms,
                            "outcome": "success"
                        }
                    )
                else:
                    # API returned fail status (e.g., reserved IP)
                    logger.debug(
                        f"ip-api.com returned fail status for {ip}",
                        extra={"ip": ip, "api_status": data.get("status"), "outcome": "api_fail"}
                    )
            elif resp.status == 429:
                # Rate limited by server
                _ipapi_breaker.record_failure()
                logger.warning(
                    f"ip-api.com rate limit hit (429) for {ip}",
                    extra={"ip": ip, "outcome": "rate_limited_server"}
                )
            else:
                _ipapi_breaker.record_failure()
                logger.warning(
                    f"ip-api.com returned status {resp.status} for {ip}",
                    extra={"ip": ip, "status": resp.status, "outcome": "http_error"}
                )
    except asyncio.TimeoutError:
        _ipapi_breaker.record_failure()
        logger.warning(
            f"ip-api.com timeout for {ip}",
            extra={"ip": ip, "outcome": "timeout"}
        )
    except Exception as exc:
        _ipapi_breaker.record_failure()
        logger.error(
            f"ip-api.com lookup failed for {ip}: {str(exc)}",
            extra={"ip": ip, "outcome": "error", "error_type": type(exc).__name__}
        )

    info = ExternalAsnInfo(
        asn=asn,
        org_name=org_name,
        country=country,
        source="ip-api"
    )
    _cache_set(cache_key, info)
    return info


async def lookup_ipinfo_free(ip: str) -> ExternalAsnInfo:
    """
    Lookup IP info using ipinfo.io free tier (no key, limited to 50k/month).
    Returns ASN and org name.
    Uses circuit breaker for resilience.
    """
    cache_key = f"ipinfo:{ip}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug(
            f"ipinfo.io cache hit for {ip}",
            extra={"ip": ip, "outcome": "cache_hit"}
        )
        return cached

    # Check circuit breaker
    if _ipinfo_breaker.is_open():
        logger.debug(
            f"ipinfo.io circuit open, skipping lookup for {ip}",
            extra={"ip": ip, "circuit": "ipinfo", "outcome": "circuit_open"}
        )
        return ExternalAsnInfo(source="ipinfo")

    session = await _get_session()
    url = f"https://ipinfo.io/{ip}/json"
    
    asn: Optional[int] = None
    org_name: Optional[str] = None
    country: Optional[str] = None

    start_time = time.time()
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                
                # Format: "AS15169 Google LLC"
                org_field = data.get("org", "")
                if org_field:
                    parts = org_field.split(None, 1)
                    if parts:
                        try:
                            asn = int(parts[0].replace("AS", ""))
                        except ValueError:
                            pass
                    if len(parts) > 1:
                        org_name = parts[1]
                
                country = data.get("country")
                
                _ipinfo_breaker.record_success()
                duration_ms = round((time.time() - start_time) * 1000, 2)
                logger.info(
                    f"ipinfo.io lookup successful for {ip}",
                    extra={
                        "ip": ip,
                        "asn": asn,
                        "duration": duration_ms,
                        "outcome": "success"
                    }
                )
            elif resp.status == 429:
                _ipinfo_breaker.record_failure()
                logger.warning(
                    f"ipinfo.io rate limit hit (429) for {ip}",
                    extra={"ip": ip, "outcome": "rate_limited"}
                )
            else:
                _ipinfo_breaker.record_failure()
                logger.warning(
                    f"ipinfo.io returned status {resp.status} for {ip}",
                    extra={"ip": ip, "status": resp.status, "outcome": "http_error"}
                )
    except asyncio.TimeoutError:
        _ipinfo_breaker.record_failure()
        logger.warning(
            f"ipinfo.io timeout for {ip}",
            extra={"ip": ip, "outcome": "timeout"}
        )
    except Exception as exc:
        _ipinfo_breaker.record_failure()
        logger.error(
            f"ipinfo.io lookup failed for {ip}: {str(exc)}",
            extra={"ip": ip, "outcome": "error", "error_type": type(exc).__name__}
        )

    info = ExternalAsnInfo(
        asn=asn,
        org_name=org_name,
        country=country,
        source="ipinfo"
    )
    _cache_set(cache_key, info)
    return info


async def lookup_asn_multi_source(ip: str) -> ExternalAsnInfo:
    """
    Try multiple sources in parallel and return the most complete result.
    Falls back gracefully if some sources fail.
    """
    # Launch all lookups in parallel
    results = await asyncio.gather(
        lookup_ip_api(ip),
        lookup_ipinfo_free(ip),
        lookup_ripe_stat(ip),
        return_exceptions=True
    )
    
    # Merge results, preferring more complete data
    merged = ExternalAsnInfo(source="multi")
    
    for result in results:
        if isinstance(result, Exception):
            continue
        if isinstance(result, ExternalAsnInfo):
            if result.asn and not merged.asn:
                merged.asn = result.asn
            if result.org_name and not merged.org_name:
                merged.org_name = result.org_name
            if result.country and not merged.country:
                merged.country = result.country
            if result.prefix and not merged.prefix:
                merged.prefix = result.prefix
            if result.registry and not merged.registry:
                merged.registry = result.registry
    
    return merged


async def close_session() -> None:
    """Close the aiohttp session."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None
