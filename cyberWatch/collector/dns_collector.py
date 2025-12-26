"""DNS-driven target collector for cyberWatch."""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, cast

import dns.asyncresolver
from rich.console import Console
from rich.traceback import install as install_rich_traceback

from cyberWatch.collector.config import DNSCollectorConfig, PiholeConfig
from cyberWatch.collector.models import DNSQuery, ResolvedTarget
from cyberWatch.collector.sources import DNSSource, build_source
from cyberWatch.db.pg import create_pool
from cyberWatch.db.pg_dns import (
    DNSQueryRecord,
    DNSTargetRecord,
    insert_dns_queries,
    touch_target,
    upsert_dns_targets,
)
from cyberWatch.db.settings import get_pihole_settings, ensure_settings_table
from cyberWatch.scheduler.queue import TargetQueue, TargetTask
from cyberWatch.logging_config import get_logger

install_rich_traceback()
console = Console()
logger = get_logger("collector")


async def resolve_domain(
    resolver: dns.asyncresolver.Resolver,
    query: DNSQuery,
    *,
    max_ips: int,
    timeout: float,
) -> List[ResolvedTarget]:
    """Resolve a domain into IPs (A/AAAA)."""
    qtypes: Sequence[str]
    if query.qtype and query.qtype.upper() in {"A", "AAAA"}:
        qtypes = [query.qtype.upper()]
    else:
        qtypes = ["A", "AAAA"]

    results: List[ResolvedTarget] = []
    for qtype in qtypes:
        try:
            answers = await asyncio.wait_for(resolver.resolve(query.domain, qtype), timeout=timeout)
        except Exception:
            continue
        for rdata in answers:
            ip_text = rdata.to_text()
            if any(res.ip == ip_text for res in results):
                continue
            results.append(
                ResolvedTarget(
                    domain=query.domain,
                    ip=ip_text,
                    queried_at=query.timestamp,
                    client_ip=query.client_ip,
                    qtype=query.qtype,
                )
            )
            if len(results) >= max_ips:
                return results
    return results


def _ignore_query(cfg: DNSCollectorConfig, query: DNSQuery) -> bool:
    domain = query.domain.lower().rstrip(".")
    if cfg.filters.max_domain_length and len(domain) > cfg.filters.max_domain_length:
        logger.debug(f"Ignoring domain due to length: {domain}")
        return True
    if domain.endswith((".in-addr.arpa", ".ip6.arpa")):
        return True
    for suffix in cfg.filters.ignore_domains_suffix:
        if domain.endswith(suffix.lower()):
            logger.debug(f"Ignoring domain due to suffix filter: {domain}")
            return True
    if cfg.filters.ignore_qtypes and query.qtype:
        if query.qtype.upper() in {q.upper() for q in cfg.filters.ignore_qtypes}:
            return True
    if cfg.filters.ignore_clients and query.client_ip:
        if query.client_ip in cfg.filters.ignore_clients:
            return True
    return False


async def _resolve_batch(cfg: DNSCollectorConfig, queries: List[DNSQuery]) -> List[ResolvedTarget]:
    if not cfg.dns_resolution.enabled:
        logger.info("DNS resolution disabled in config")
        return []
    
    logger.info(
        "Starting DNS resolution batch",
        extra={"batch_size": len(queries), "action": "dns_resolve"}
    )
    
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = cfg.dns_resolution.timeout_seconds
    sem = asyncio.Semaphore(20)

    async def _resolve_one(query: DNSQuery) -> List[ResolvedTarget]:
        async with sem:
            return await resolve_domain(
                resolver,
                query,
                max_ips=cfg.dns_resolution.max_ips_per_domain,
                timeout=cfg.dns_resolution.timeout_seconds,
            )

    tasks = [_resolve_one(q) for q in queries]
    results_nested = await asyncio.gather(*tasks, return_exceptions=True)
    resolved: List[ResolvedTarget] = []
    errors = 0
    
    for item in results_nested:
        if isinstance(item, Exception):
            errors += 1
            continue
        resolved.extend(cast(List[ResolvedTarget], item))
    
    logger.info(
        "DNS resolution batch completed",
        extra={
            "queries": len(queries),
            "resolved": len(resolved),
            "errors": errors,
            "outcome": "success",
        }
    )
    
    return resolved


async def process_cycle(
    cfg: DNSCollectorConfig,
    source: DNSSource,
    pool,
    queue: TargetQueue,
) -> dict:
    logger.info("Starting DNS collection cycle", extra={"action": "cycle_start"})
    
    queries_raw = await source.fetch_new()
    filtered = [q for q in queries_raw if not _ignore_query(cfg, q)]
    
    logger.info(
        "Queries filtered",
        extra={
            "raw_count": len(queries_raw),
            "filtered_count": len(filtered),
            "filtered_out": len(queries_raw) - len(filtered),
        }
    )

    await insert_dns_queries(
        pool,
        [
            DNSQueryRecord(
                domain=q.domain,
                client_ip=q.client_ip,
                qtype=q.qtype,
                queried_at=q.timestamp,
            )
            for q in filtered
        ],
    )

    resolved = await _resolve_batch(cfg, filtered)

    target_records: List[DNSTargetRecord] = []
    enqueue_candidates: List[ResolvedTarget] = []
    for item in resolved:
        target_records.append(
            DNSTargetRecord(
                domain=item.domain,
                ip=str(item.ip),
                first_seen=item.queried_at,
                last_seen=item.queried_at,
                query_count=1,
                last_client_ip=item.client_ip,
                last_qtype=item.qtype,
            )
        )
        enqueue_candidates.append(item)

    await upsert_dns_targets(pool, target_records)

    enqueued = 0
    seen_ips: set[str] = set()
    for target in enqueue_candidates:
        ip_str = str(target.ip)
        if ip_str in seen_ips:
            continue
        await touch_target(pool, ip_str, source="dns", seen_at=target.queried_at)
        await queue.enqueue(TargetTask(target_ip=ip_str, source="dns", domain=target.domain))
        seen_ips.add(ip_str)
        enqueued += 1
    
    stats = {
        "raw": len(queries_raw),
        "filtered": len(filtered),
        "resolved": len(resolved),
        "enqueued": enqueued,
    }
    
    logger.info(
        "DNS collection cycle completed",
        extra={
            "queries_raw": stats["raw"],
            "queries_filtered": stats["filtered"],
            "targets_resolved": stats["resolved"],
            "targets_enqueued": stats["enqueued"],
            "outcome": "success",
        }
    )

    return stats


async def run_collector(config_path: str) -> None:
    cfg = DNSCollectorConfig.load(config_path)
    
    # Connect to database to check for UI-configured settings
    pool = await create_pool(os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch"))
    
    # Ensure settings table exists
    await ensure_settings_table(pool)
    
    # Check for database-stored Pi-hole settings (from UI)
    db_settings = await get_pihole_settings(pool)
    
    if db_settings and db_settings.get("base_url"):
        logger.info(
            "Loading Pi-hole settings from database",
            extra={"source": "database", "base_url": db_settings.get("base_url")}
        )
        # Override config with database settings
        cfg.enabled = db_settings.get("enabled", True)
        cfg.source = "pihole"
        cfg.pihole = PiholeConfig(
            base_url=db_settings.get("base_url", ""),
            api_token=db_settings.get("api_token", ""),
            poll_interval_seconds=db_settings.get("poll_interval_seconds", 30),
        )
    else:
        logger.info(
            "Using Pi-hole settings from config file",
            extra={"source": "config_file", "config_path": config_path}
        )
    
    if not cfg.enabled:
        logger.warning("DNS collector disabled in config; exiting")
        console.print("[yellow]DNS collector disabled in config; exiting.")
        await pool.close()
        return

    source = await build_source(cfg.source, cfg.pihole, cfg.logfile)
    queue = TargetQueue()

    logger.info(
        "DNS collector starting",
        extra={
            "component": "collector",
            "state": "starting",
            "poll_interval": cfg.poll_interval,
            "source_type": cfg.source,
        }
    )
    console.print("[green]Starting cyberWatch DNS collector", highlight=False)
    
    try:
        while True:
            try:
                # Re-check database settings each cycle to pick up changes
                db_settings = await get_pihole_settings(pool)
                if db_settings:
                    cfg.enabled = db_settings.get("enabled", True)
                    if not cfg.enabled:
                        logger.info("DNS collector disabled via settings, pausing")
                        await asyncio.sleep(cfg.poll_interval)
                        continue
                
                stats = await process_cycle(cfg, source, pool, queue)
                console.log(
                    f"queries={stats['raw']} filtered={stats['filtered']} resolved={stats['resolved']} enqueued={stats['enqueued']}"
                )
            except asyncio.CancelledError:
                logger.info("DNS collector interrupted", extra={"state": "interrupted"})
                raise
            except Exception as exc:
                logger.error(
                    f"DNS collection cycle error: {str(exc)}",
                    exc_info=True,
                    extra={"outcome": "error", "error_type": type(exc).__name__}
                )
                console.log(f"[red]Cycle error:[/red] {exc}")
            await asyncio.sleep(cfg.poll_interval)
    finally:
        logger.info("DNS collector shutting down", extra={"state": "shutdown"})
        if hasattr(source, "close"):
            close_fn = getattr(source, "close")
            if asyncio.iscoroutinefunction(close_fn):
                await close_fn()  # type: ignore[arg-type]
            else:
                close_fn()  # type: ignore[misc]
        await queue.close()
        await pool.close()
        logger.info("DNS collector stopped", extra={"state": "stopped"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="cyberWatch DNS target collector")
    parser.add_argument(
        "--config",
        default=os.getenv("CYBERWATCH_DNS_CONFIG", "/etc/cyberwatch/dns.yaml"),
        help="Path to DNS collector YAML config",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    await run_collector(args.config)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
