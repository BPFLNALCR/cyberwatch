from datetime import datetime

from cyberWatch.collector.config import DNSCollectorConfig, FilterConfig
from cyberWatch.collector.dns_collector import _ignore_query
from cyberWatch.collector.models import DNSQuery


def query(domain: str, *, client_ip: str = "192.168.1.10", qtype: str = "A") -> DNSQuery:
    return DNSQuery(
        domain=domain,
        client_ip=client_ip,
        qtype=qtype,
        timestamp=datetime(2026, 6, 19, 12, 0, 0),
    )


def test_ignores_reverse_dns_queries():
    cfg = DNSCollectorConfig()

    assert _ignore_query(cfg, query("1.0.168.192.in-addr.arpa"))
    assert _ignore_query(cfg, query("0.0.0.0.ip6.arpa"))


def test_ignores_cymru_enrichment_queries():
    cfg = DNSCollectorConfig()

    assert _ignore_query(cfg, query("1.2.3.4.origin.asn.cymru.com"))
    assert _ignore_query(cfg, query("1.2.3.4.peer.asn.cymru.com"))
    assert _ignore_query(cfg, query("1.2.3.4.asn.cymru.com"))


def test_ignores_configured_local_suffix():
    cfg = DNSCollectorConfig(
        filters=FilterConfig(ignore_domains_suffix=[".local"])
    )

    assert _ignore_query(cfg, query("printer.local"))


def test_ignores_configured_qtype():
    cfg = DNSCollectorConfig(
        filters=FilterConfig(ignore_qtypes=["PTR"])
    )

    assert _ignore_query(cfg, query("example.com", qtype="PTR"))


def test_ignores_configured_client():
    cfg = DNSCollectorConfig(
        filters=FilterConfig(ignore_clients=["192.168.1.10"])
    )

    assert _ignore_query(cfg, query("example.com", client_ip="192.168.1.10"))


def test_allows_normal_query():
    cfg = DNSCollectorConfig(
        filters=FilterConfig(
            ignore_domains_suffix=[".local"],
            ignore_qtypes=["PTR"],
            ignore_clients=["192.168.1.99"],
        )
    )

    assert not _ignore_query(cfg, query("example.com", client_ip="192.168.1.10"))
