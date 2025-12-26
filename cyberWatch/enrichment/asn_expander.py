"""ASN IP discovery and expansion - discover additional IPs within interesting ASNs."""
from __future__ import annotations

import asyncio
import ipaddress
import random
from typing import List, Optional, Set

from asyncpg import Pool

from cyberWatch.db import pg
from cyberWatch.enrichment.peeringdb import fetch_asn_org
from cyberWatch.logging_config import get_logger
from cyberWatch.scheduler.queue import Queue, TargetTask

logger = get_logger("asn_expander")


class AsnExpanderConfig:
    def __init__(
        self,
        *,
        min_neighbor_count: int = 5,  # Only expand ASNs with this many neighbors
        max_ips_per_asn: int = 10,  # Max IPs to sample per ASN
        max_asns_per_run: int = 20,  # Max ASNs to expand per run
    ) -> None:
        self.min_neighbor_count = min_neighbor_count
        self.max_ips_per_asn = max_ips_per_asn
        self.max_asns_per_run = max_asns_per_run


async def get_interesting_asns(pool: Pool, config: AsnExpanderConfig) -> List[int]:
    """
    Get ASNs worth expanding based on neighbor count and recent activity.
    Prioritizes ASNs that are:
    - Well-connected (many neighbors)
    - Recently seen
    - Haven't been expanded recently
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT asn, neighbor_count, last_seen
            FROM asns
            WHERE neighbor_count >= $1
              AND (enrichment_completed_at IS NULL
                   OR enrichment_completed_at < NOW() - INTERVAL '7 days')
            ORDER BY neighbor_count DESC, last_seen DESC
            LIMIT $2
            """,
            config.min_neighbor_count,
            config.max_asns_per_run,
        )
    return [row["asn"] for row in rows]


async def get_prefixes_for_asn(asn: int) -> List[str]:
    """
    Fetch announced prefixes for an ASN from PeeringDB.
    Returns list of CIDR prefixes.
    """
    try:
        asn_org = await fetch_asn_org(asn)
        prefixes = asn_org.prefixes_v4 + asn_org.prefixes_v6
        
        # PeeringDB may return IXP IPs, not prefixes
        # We need to construct /24 prefixes from the IPs
        prefix_cidrs = []
        for ip_str in prefixes:
            try:
                ip = ipaddress.ip_address(ip_str)
                if ip.version == 4:
                    # Create /24 prefix
                    network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
                    prefix_cidrs.append(str(network))
                else:
                    # Create /64 prefix for IPv6
                    network = ipaddress.IPv6Network(f"{ip}/64", strict=False)
                    prefix_cidrs.append(str(network))
            except ValueError:
                # Already a CIDR
                prefix_cidrs.append(ip_str)
        
        logger.info(
            f"Found {len(prefix_cidrs)} prefixes for AS{asn}",
            extra={"asn": asn, "prefix_count": len(prefix_cidrs)}
        )
        return prefix_cidrs
    except Exception as exc:
        logger.warning(
            f"Failed to fetch prefixes for AS{asn}: {str(exc)}",
            extra={"asn": asn, "outcome": "error"}
        )
        return []


async def sample_ips_from_prefix(prefix: str, max_samples: int = 5) -> List[str]:
    """
    Sample random IPs from a CIDR prefix.
    Avoids network/broadcast addresses.
    """
    try:
        network = ipaddress.ip_network(prefix, strict=False)
        
        # For small networks, sample all usable hosts
        usable_hosts = list(network.hosts())
        if not usable_hosts:
            # Network too small (like /32 or /31)
            return [str(network.network_address)]
        
        # Sample random IPs
        sample_size = min(max_samples, len(usable_hosts))
        sampled = random.sample(usable_hosts, sample_size)
        return [str(ip) for ip in sampled]
    except ValueError as exc:
        logger.warning(f"Invalid prefix {prefix}: {exc}")
        return []


async def expand_asn(
    pool: Pool,
    queue: Queue,
    asn: int,
    config: AsnExpanderConfig,
) -> int:
    """
    Expand an ASN by discovering and enqueueing IPs from its prefixes.
    Returns number of IPs enqueued.
    """
    logger.info(
        f"Expanding AS{asn}",
        extra={"asn": asn, "action": "asn_expand"}
    )
    
    # Get prefixes
    prefixes = await get_prefixes_for_asn(asn)
    if not prefixes:
        logger.warning(
            f"No prefixes found for AS{asn}",
            extra={"asn": asn, "outcome": "no_prefixes"}
        )
        return 0
    
    # Sample IPs from prefixes
    all_ips: Set[str] = set()
    ips_per_prefix = max(1, config.max_ips_per_asn // len(prefixes))
    
    for prefix in prefixes:
        ips = await sample_ips_from_prefix(prefix, ips_per_prefix)
        all_ips.update(ips)
        if len(all_ips) >= config.max_ips_per_asn:
            break
    
    # Filter out IPs we've already measured recently
    async with pool.acquire() as conn:
        existing_targets = await conn.fetch(
            """
            SELECT target_ip FROM targets
            WHERE target_ip = ANY($1)
              AND last_seen > NOW() - INTERVAL '7 days'
            """,
            list(all_ips),
        )
        existing_ips = {str(row["target_ip"]) for row in existing_targets}
    
    new_ips = all_ips - existing_ips
    
    # Enqueue new IPs for measurement
    enqueued = 0
    for ip in new_ips:
        try:
            await pg.touch_target(pool, ip, source="asn_expansion")
            await queue.enqueue(TargetTask(target_ip=ip, source="asn_expansion"))
            enqueued += 1
        except Exception as exc:
            logger.warning(
                f"Failed to enqueue {ip} for AS{asn}: {str(exc)}",
                extra={"asn": asn, "ip": ip, "outcome": "error"}
            )
    
    # Mark ASN as enriched
    await pg.mark_asn_enrichment_completed(pool, asn)
    
    logger.info(
        f"Expanded AS{asn}: enqueued {enqueued} new IPs",
        extra={
            "asn": asn,
            "prefixes": len(prefixes),
            "ips_discovered": len(all_ips),
            "ips_enqueued": enqueued,
            "outcome": "success",
        }
    )
    
    return enqueued


async def run_once(
    pool: Pool,
    queue: Queue,
    config: AsnExpanderConfig,
) -> int:
    """
    Run one iteration of ASN expansion.
    Returns total number of IPs enqueued.
    """
    asns = await get_interesting_asns(pool, config)
    if not asns:
        logger.debug("No interesting ASNs found for expansion")
        return 0
    
    logger.info(
        f"Expanding {len(asns)} ASNs",
        extra={"asn_count": len(asns), "action": "expansion_batch"}
    )
    
    total_enqueued = 0
    for asn in asns:
        try:
            enqueued = await expand_asn(pool, queue, asn, config)
            total_enqueued += enqueued
        except Exception as exc:
            logger.error(
                f"Failed to expand AS{asn}: {str(exc)}",
                exc_info=True,
                extra={"asn": asn, "outcome": "error"}
            )
    
    return total_enqueued
