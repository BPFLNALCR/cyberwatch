"""DNS-driven target collector for cyberWatch."""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from typing import List, Sequence, cast

import dns.asyncresolver
from rich.console import Console
from rich.traceback import install as install_rich_traceback

from cyberWatch.collector.config import DNSCollectorConfig
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
from cyberWatch.scheduler.queue import TargetQueue, TargetTask

install_rich_traceback()
console = Console()


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
        return True
    if domain.endswith((".in-addr.arpa", ".ip6.arpa")):
        return True
    for suffix in cfg.filters.ignore_domains_suffix:
        if domain.endswith(suffix.lower()):
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
        return []
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
    for item in results_nested:
        if isinstance(item, Exception):
            continue
        resolved.extend(cast(List[ResolvedTarget], item))
    return resolved


async def process_cycle(
    cfg: DNSCollectorConfig,
    source: DNSSource,
    pool,
    queue: TargetQueue,
) -> dict:
    queries_raw = await source.fetch_new()
    filtered = [q for q in queries_raw if not _ignore_query(cfg, q)]

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

    return {
        "raw": len(queries_raw),
        "filtered": len(filtered),
        "resolved": len(resolved),
        "enqueued": enqueued,
    }


async def run_collector(config_path: str) -> None:
    cfg = DNSCollectorConfig.load(config_path)
    if not cfg.enabled:
        console.print("[yellow]DNS collector disabled in config; exiting.")
        return

    source = await build_source(cfg.source, cfg.pihole, cfg.logfile)
    pool = await create_pool(os.getenv("CYBERWATCH_PG_DSN", "postgresql://postgres:postgres@localhost:5432/cyberWatch"))
    queue = TargetQueue()

    console.print("[green]Starting cyberWatch DNS collector", highlight=False)
    try:
        while True:
            try:
                stats = await process_cycle(cfg, source, pool, queue)
                console.log(
                    f"queries={stats['raw']} filtered={stats['filtered']} resolved={stats['resolved']} enqueued={stats['enqueued']}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                console.log(f"[red]Cycle error:[/red] {exc}")
            await asyncio.sleep(cfg.poll_interval)
    finally:
        if hasattr(source, "close"):
            close_fn = getattr(source, "close")
            if asyncio.iscoroutinefunction(close_fn):
                await close_fn()  # type: ignore[arg-type]
            else:
                close_fn()  # type: ignore[misc]
        await queue.close()
        await pool.close()


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
