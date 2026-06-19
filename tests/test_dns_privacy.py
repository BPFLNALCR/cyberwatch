from datetime import datetime

from cyberWatch.collector.config import DNSCollectorConfig, DNSPrivacyConfig
from cyberWatch.collector.dns_collector import (
    DNS_STORE_CLIENT_IPS_ENV,
    client_ip_for_storage,
    dns_client_ip_storage_enabled,
    dns_query_record_for_storage,
    dns_target_record_for_storage,
)
from cyberWatch.collector.models import DNSQuery, ResolvedTarget


def test_dns_client_ip_storage_disabled_by_default(monkeypatch):
    monkeypatch.delenv(DNS_STORE_CLIENT_IPS_ENV, raising=False)
    cfg = DNSCollectorConfig()

    assert dns_client_ip_storage_enabled(cfg) is False
    assert client_ip_for_storage(cfg, "192.168.1.10") is None


def test_dns_client_ip_storage_can_be_enabled_by_config(monkeypatch):
    monkeypatch.delenv(DNS_STORE_CLIENT_IPS_ENV, raising=False)
    cfg = DNSCollectorConfig(privacy=DNSPrivacyConfig(store_client_ips=True))

    assert dns_client_ip_storage_enabled(cfg) is True
    assert client_ip_for_storage(cfg, "192.168.1.10") == "192.168.1.10"


def test_dns_client_ip_storage_env_override_wins(monkeypatch):
    cfg = DNSCollectorConfig(privacy=DNSPrivacyConfig(store_client_ips=True))
    monkeypatch.setenv(DNS_STORE_CLIENT_IPS_ENV, "false")

    assert dns_client_ip_storage_enabled(cfg) is False

    cfg = DNSCollectorConfig(privacy=DNSPrivacyConfig(store_client_ips=False))
    monkeypatch.setenv(DNS_STORE_CLIENT_IPS_ENV, "true")

    assert dns_client_ip_storage_enabled(cfg) is True


def test_dns_records_omit_client_ip_by_default(monkeypatch):
    monkeypatch.delenv(DNS_STORE_CLIENT_IPS_ENV, raising=False)
    cfg = DNSCollectorConfig()
    timestamp = datetime(2026, 6, 19, 12, 0, 0)
    query = DNSQuery(
        domain="example.com",
        client_ip="192.168.1.10",
        qtype="A",
        timestamp=timestamp,
    )
    target = ResolvedTarget(
        domain="example.com",
        ip="93.184.216.34",
        queried_at=timestamp,
        client_ip="192.168.1.10",
        qtype="A",
    )

    query_record = dns_query_record_for_storage(cfg, query)
    target_record = dns_target_record_for_storage(cfg, target)

    assert query_record.client_ip is None
    assert target_record.last_client_ip is None


def test_dns_records_preserve_client_ip_when_enabled(monkeypatch):
    monkeypatch.setenv(DNS_STORE_CLIENT_IPS_ENV, "true")
    cfg = DNSCollectorConfig()
    timestamp = datetime(2026, 6, 19, 12, 0, 0)
    query = DNSQuery(
        domain="example.com",
        client_ip="192.168.1.10",
        qtype="A",
        timestamp=timestamp,
    )
    target = ResolvedTarget(
        domain="example.com",
        ip="93.184.216.34",
        queried_at=timestamp,
        client_ip="192.168.1.10",
        qtype="A",
    )

    query_record = dns_query_record_for_storage(cfg, query)
    target_record = dns_target_record_for_storage(cfg, target)

    assert query_record.client_ip == "192.168.1.10"
    assert target_record.last_client_ip == "192.168.1.10"
