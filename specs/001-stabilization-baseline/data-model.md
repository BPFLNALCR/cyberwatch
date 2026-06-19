# Data Model: Stabilization Baseline

## Target Queue

**Purpose**: Shared measurement-task buffer used by DNS collection, manual target enqueue, workers, remeasurement, health checks, and ASN expansion.

**Fields**

- `redis_url`: Redis connection URL, defaulting from `CYBERWATCH_REDIS_URL`.
- `queue_key`: Redis list key. Canonical default is `cyberwatch:targets`.
- `payload`: Serialized target task containing target IP, source, optional domain, and priority.

**Validation Rules**

- Default queue key must be lowercase `cyberwatch:targets`.
- Explicit queue key overrides must still work for tests or special deployments.

## Enrichment Scheduler Runtime

**Purpose**: Periodically enrich measurements, update graph data when available, and run ASN expansion.

**Fields**

- `pg_dsn`: PostgreSQL DSN from `CYBERWATCH_PG_DSN`.
- `redis_url`: Redis URL from `CYBERWATCH_REDIS_URL`.
- `sleep_seconds`: fallback scheduler interval from `CYBERWATCH_ENRICH_INTERVAL`.
- `settings`: optional enrichment settings loaded from PostgreSQL.
- `last_asn_expansion`: timestamp of last ASN expansion attempt.
- `driver`: optional Neo4j driver; may be absent when graph storage is unavailable.

**Validation Rules**

- Module import must not require live PostgreSQL, Redis, Neo4j, or internet.
- Startup path must use `TargetQueue` and current ASN expander APIs.
- Neo4j unavailability must not be confused with local import/name failures.

## Destructive Settings Guard

**Purpose**: Prevent accidental use of destructive settings routes.

**Fields**

- `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS`: env variable controlling route availability.
- `enabled`: boolean derived from true-like env values.
- `blocked_error`: clear forbidden response explaining how to opt in.

**Validation Rules**

- Missing env var means disabled.
- False-like values mean disabled.
- True-like values `1`, `true`, `yes`, and `on` mean enabled.
- Guard must run before database or graph clear work starts.

## DNS Privacy Policy

**Purpose**: Control whether DNS client identifiers are persisted for new ingestion.

**Fields**

- `privacy.store_client_ips`: YAML config value, default false.
- `CYBERWATCH_DNS_STORE_CLIENT_IPS`: env override, optional.
- `DNSQueryRecord.client_ip`: nullable persisted query client field.
- `DNSTargetRecord.last_client_ip`: nullable persisted aggregate target client field.

**Validation Rules**

- Default behavior omits client IP values from new persisted rows.
- Env override wins over YAML config.
- Source client IPs remain available before persistence for `ignore_clients` filtering.
- Existing historical rows are not modified.

## Automated Validation Baseline

**Purpose**: Repeatable local and CI safety checks.

**Fields**

- `pytest` dependency.
- `tests/` files for imports, parsers, DNS filters, queue key, destructive guard, and DNS privacy.
- `.github/workflows/ci.yml` workflow.

**Validation Rules**

- Default tests must pass without live PostgreSQL, Redis, Neo4j, Pi-hole, traceroute, scamper, or internet.
- CI must run the same pytest baseline.

