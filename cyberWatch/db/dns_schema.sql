-- Schema extension for DNS query ingestion (Phase 4)
CREATE TABLE IF NOT EXISTS dns_queries (
    id              BIGSERIAL PRIMARY KEY,
    domain          TEXT NOT NULL,
    client_ip       INET NULL,
    qtype           TEXT NULL,
    queried_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dns_targets (
    id              BIGSERIAL PRIMARY KEY,
    domain          TEXT NOT NULL,
    ip              INET NOT NULL,
    first_seen      TIMESTAMPTZ NOT NULL,
    last_seen       TIMESTAMPTZ NOT NULL,
    query_count     BIGINT NOT NULL DEFAULT 1,
    last_client_ip  INET NULL,
    last_qtype      TEXT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dns_targets_domain_ip ON dns_targets(domain, ip);
CREATE INDEX IF NOT EXISTS idx_dns_targets_ip ON dns_targets(ip);
CREATE INDEX IF NOT EXISTS idx_dns_queries_domain ON dns_queries(domain);
CREATE INDEX IF NOT EXISTS idx_dns_queries_client_ip ON dns_queries(client_ip);
