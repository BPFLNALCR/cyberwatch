"""PeeringDB lookups for ASN organization metadata."""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional

import aiohttp
from pydantic import BaseModel

from cyberWatch.logging_config import get_logger

logger = get_logger("peeringdb")

CACHE_TTL_SECONDS = 86400
API_ROOT = "https://www.peeringdb.com/api"


class AsnOrg(BaseModel):
    asn: int
    org_name: Optional[str]
    country: Optional[str]
    # Extended PeeringDB fields
    peeringdb_id: Optional[int] = None
    facility_count: int = 0
    peering_policy: Optional[str] = None  # 'Open', 'Selective', 'Restrictive', 'No'
    traffic_levels: Optional[str] = None
    irr_as_set: Optional[str] = None
    prefixes_v4: List[str] = []
    prefixes_v6: List[str] = []


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
    """Fetch comprehensive ASN metadata from PeeringDB."""
    cached = _cache_get(asn)
    if cached:
        return cached

    session = await _get_session()
    url = f"{API_ROOT}/net"
    params = {"asn": asn, "depth": 2}  # depth=2 includes related objects
    
    org_name: Optional[str] = None
    country: Optional[str] = None
    peeringdb_id: Optional[int] = None
    facility_count: int = 0
    peering_policy: Optional[str] = None
    traffic_levels: Optional[str] = None
    irr_as_set: Optional[str] = None
    prefixes_v4: List[str] = []
    prefixes_v6: List[str] = []

    try:
        async with session.get(url, params=params, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                records = data.get("data") or []
                if records:
                    rec = records[0]
                    peeringdb_id = rec.get("id")
                    org_name = rec.get("name") or rec.get("org_name")
                    country = rec.get("country")
                    peering_policy = rec.get("policy_general")
                    traffic_levels = rec.get("info_traffic")
                    irr_as_set = rec.get("irr_as_set")
                    
                    # Count facilities (netfac relationships)
                    netfac_set = rec.get("netfac_set") or []
                    facility_count = len(netfac_set)
                    
                    # Extract prefixes (netixlan for IXP prefixes, or fetch separately)
                    netixlan_set = rec.get("netixlan_set") or []
                    for netixlan in netixlan_set:
                        v4 = netixlan.get("ipaddr4")
                        v6 = netixlan.get("ipaddr6")
                        if v4:
                            prefixes_v4.append(v4)
                        if v6:
                            prefixes_v6.append(v6)
                    
                    logger.info(
                        f"Fetched PeeringDB data for AS{asn}",
                        extra={
                            "asn": asn,
                            "org_name": org_name,
                            "facility_count": facility_count,
                            "outcome": "success"
                        }
                    )
            else:
                logger.warning(
                    f"PeeringDB returned status {resp.status} for AS{asn}",
                    extra={"asn": asn, "status": resp.status}
                )
    except asyncio.TimeoutError:
        logger.warning(
            f"PeeringDB timeout for AS{asn}",
            extra={"asn": asn, "outcome": "timeout"}
        )
    except Exception as exc:
        logger.error(
            f"PeeringDB fetch failed for AS{asn}: {str(exc)}",
            exc_info=True,
            extra={"asn": asn, "outcome": "error"}
        )

    # Fetch additional prefix data from /netixlan endpoint if needed
    if not prefixes_v4 and not prefixes_v6:
        try:
            prefix_url = f"{API_ROOT}/netixlan"
            prefix_params = {"asn": asn}
            async with session.get(prefix_url, params=prefix_params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    records = data.get("data") or []
                    for rec in records:
                        v4 = rec.get("ipaddr4")
                        v6 = rec.get("ipaddr6")
                        if v4 and v4 not in prefixes_v4:
                            prefixes_v4.append(v4)
                        if v6 and v6 not in prefixes_v6:
                            prefixes_v6.append(v6)
        except Exception:
            pass  # Non-critical

    org = AsnOrg(
        asn=asn,
        org_name=org_name,
        country=country,
        peeringdb_id=peeringdb_id,
        facility_count=facility_count,
        peering_policy=peering_policy,
        traffic_levels=traffic_levels,
        irr_as_set=irr_as_set,
        prefixes_v4=prefixes_v4,
        prefixes_v6=prefixes_v6,
    )
    _cache_set(asn, org)
    return org


async def close_session() -> None:
    """Close the aiohttp session."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None
