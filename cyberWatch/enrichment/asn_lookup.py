"""ASN lookup utilities (Team Cymru WHOIS / DNS)."""
from __future__ import annotations

import asyncio
import ipaddress
import time
from typing import Dict, Optional

import dns.asyncresolver
from pydantic import BaseModel

CACHE_TTL_SECONDS = 3600


class AsnInfo(BaseModel):
    asn: Optional[int]
    prefix: Optional[str]
    org_name: Optional[str]
    country: Optional[str]


_cache: Dict[str, tuple[float, AsnInfo]] = {}


def _cache_get(ip: str) -> Optional[AsnInfo]:
    entry = _cache.get(ip)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > CACHE_TTL_SECONDS:
        _cache.pop(ip, None)
        return None
    return value


def _cache_set(ip: str, info: AsnInfo) -> None:
    _cache[ip] = (time.time(), info)


async def lookup_asn(ip: str) -> AsnInfo:
    cached = _cache_get(ip)
    if cached:
        return cached

    info = await _lookup_whois(ip)
    if info.asn is None:
        info = await _lookup_dns(ip)
    _cache_set(ip, info)
    return info


async def _lookup_whois(ip: str) -> AsnInfo:
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
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)

    stdout, _ = await process.communicate()
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
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return AsnInfo(asn=None, prefix=None, org_name=None, country=None)

    if addr.version == 4:
        reversed_ip = ".".join(reversed(ip.split(".")))
    else:
        # nibble-reverse IPv6
        reversed_ip = ".".join(reversed(addr.exploded.replace(":", "")))
    query = f"{reversed_ip}.origin.asn.cymru.com"

    try:
        answers = await dns.asyncresolver.resolve(query, "TXT")
    except Exception:
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
