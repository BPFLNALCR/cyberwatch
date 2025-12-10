"""PeeringDB lookups for ASN organization metadata."""
from __future__ import annotations

import time
from typing import Dict, Optional

import aiohttp
from pydantic import BaseModel

CACHE_TTL_SECONDS = 86400
API_ROOT = "https://www.peeringdb.com/api"


class AsnOrg(BaseModel):
    asn: int
    org_name: Optional[str]
    country: Optional[str]


_cache: Dict[int, tuple[float, AsnOrg]] = {}
_session: Optional[aiohttp.ClientSession] = None


def _cache_get(asn: int) -> Optional[AsnOrg]:
    entry = _cache.get(asn)
    if not entry:
        return None
    ts, val = entry
    if time.time() - ts > CACHE_TTL_SECONDS:
        _cache.pop(asn, None)
        return None
    return val


def _cache_set(asn: int, org: AsnOrg) -> None:
    _cache[asn] = (time.time(), org)


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def fetch_asn_org(asn: int) -> AsnOrg:
    cached = _cache_get(asn)
    if cached:
        return cached

    session = await _get_session()
    url = f"{API_ROOT}/asn/{asn}"
    org_name: Optional[str] = None
    country: Optional[str] = None

    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                records = data.get("data") or []
                if records:
                    rec = records[0]
                    org_name = rec.get("name") or rec.get("org_name")
                    country = rec.get("country")
    except Exception:
        org_name = None
        country = None

    org = AsnOrg(asn=asn, org_name=org_name, country=country)
    _cache_set(asn, org)
    return org
