# cyberWatch

Autonomous internet measurement and topology mapping node.

## Table of Contents
- [Overview](#overview)
- [Key Use Cases](#key-use-cases)
- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Data Model \& What cyberWatch Shows You](#data-model--what-cyberwatch-shows-you)
- [Installation (Debian)](#installation-debian)
- [Configuration](#configuration)
- [Running cyberWatch](#running-cyberwatch)
- [Using the API and UI](#using-the-api-and-ui)
- [Grafana Dashboards](#grafana-dashboards)
- [Uninstallation](#uninstallation)
- [Roadmap / Future Work](#roadmap--future-work)
- [License](#license)

## Overview
cyberWatch runs active network measurements (traceroute, scamper, MTR/ping), stores hop-by-hop results in PostgreSQL, enriches hops with ASN metadata, and projects an AS-level graph into Neo4j. A Redis-backed queue feeds Python workers so probing can be continuous or on-demand.

DNS activity from a local resolver (e.g., Pi-hole) can be turned into measurement targets, allowing the system to follow the destinations that matter to the vantage point. A small FastAPI-based API, a looking-glass style UI, and Grafana dashboards expose paths, AS relationships, latency, and hopcount trends.

## Key Use Cases
- Understand how your network reaches major services: workers in [cyberWatch/workers/worker.py](cyberWatch/workers/worker.py) run traceroute/scamper and store hop RTTs.
- Build a historical map of AS paths from your vantage point: enrichment in [cyberWatch/enrichment/enricher.py](cyberWatch/enrichment/enricher.py) plus graph building in [cyberWatch/enrichment/graph_builder.py](cyberWatch/enrichment/graph_builder.py) populate Neo4j.
- Detect route or latency changes over time: PostgreSQL-backed metrics power Grafana time series (latency/hopcount dashboards).
- Inspect DNS-driven traffic patterns: [cyberWatch/collector/dns_collector.py](cyberWatch/collector/dns_collector.py) ingests resolver logs/API, queues targets, and the API exposes top domains/ASNs.
- Act as a lightweight looking glass: FastAPI endpoints in [cyberWatch/api](cyberWatch/api) plus the UI in [cyberWatch/ui/server.py](cyberWatch/ui/server.py) provide on-demand traceroute and ASN/graph views.

## Features
**Active Measurement**
- traceroute/scamper with hop-by-hop parsing; MTR endpoint for ad-hoc runs when `mtr` is installed.
- Targets pulled from Redis queue; results inserted into PostgreSQL with hop RTTs and raw output.

**Enrichment & Topology**
- IP→ASN lookups via Team Cymru WHOIS/DNS with PeeringDB org metadata caching.
- Neo4j AS graph builder that merges observed AS adjacencies with edge weights (observed_count, min/max RTT, last_seen).

**DNS Integration**
- Optional Pi-hole API or log tail ingestion; filters for suffixes (`.local`, `.lan`), qtypes (PTR), client allow/deny, max domain length.
- Domains resolved to A/AAAA (configurable max IPs) and enqueued as measurement targets; stored in `dns_queries` and `dns_targets` tables.

**APIs & Looking Glass**
- FastAPI service with endpoints for traceroute/MTR, measurements, hops, target enqueue/list, ASN detail, graph neighbors/path, DNS analytics.
- UI pages for traceroute, ASN lookup, and graph neighbors using the same API.

**Dashboards**
- Grafana JSON dashboards for latency, hopcount, and ASN performance sourced from PostgreSQL (`measurements`, `hops`, `targets`).

## Architecture Overview
Core runtime is a Debian VM (or containerized) running Python services plus Redis, PostgreSQL, and Neo4j. Systemd units manage API, UI, enrichment loop, and the DNS collector. Data flow:

```
DNS logs/API → DNS collector → Redis target queue → measurement workers → PostgreSQL
                                ↓                                 ↓
                            targets table                  enrichment (ASN/PeeringDB)
                                ↓                                 ↓
                          enqueue new tasks              Neo4j AS graph builder
                                ↓                                 ↓
                      API / UI / Grafana dashboards consume data
```

See [architecture.md](architecture.md) for the full design and phased goals.

## Data Model & What cyberWatch Shows You
- **Measurements**: `target`, tool used, timestamps, success, raw output.
- **Hops**: hop number, IP, RTT ms, ASN, prefix, org, country.
- **DNS-derived targets**: domains/IPs with first/last seen, query counts, last client/qtype.
- **AS graph edges** (Neo4j): AS nodes with org/country, `ROUTE` edges holding observed_count, min/max RTT, last_seen.

How it appears:
- API: `/measurements/latest?target=1.1.1.1`, `/measurements/hops/{id}`, `/traceroute/run`, `/asn/{asn}`, `/graph/path?src_asn=64512&dst_asn=15169`, `/dns/top-domains`, `/dns/top-asns`.
- UI: traceroute form shows JSON hops; ASN view shows org/country plus neighbors; graph view lists neighbor edges.
- Grafana: latency time series (mean, P95), hopcount distribution and over time, RTT by ASN and observed edge counts.

## Installation (Debian)
Assumed platform: Debian 12+ (VM/LXC on Proxmox or similar). The installer is idempotent and will prompt before applying schemas.

1) Clone the repo and enter it:
```bash
git clone <repo-url>
cd cyberwatch
```
2) Run the installer (installs system packages, creates venv, installs Python deps, applies schemas if approved, installs systemd units):
```bash
./install-cyberWatch.sh
```
3) Installer actions (from [install-cyberWatch.sh](install-cyberWatch.sh)):
- Installs apt packages: python3.11/venv/pip, redis-server, postgresql-client, libpq-dev, traceroute, scamper, mtr-tiny, curl, jq.
- Creates `.venv` and installs [cyberWatch/requirements.txt](cyberWatch/requirements.txt).
- Optionally applies PostgreSQL schemas [cyberWatch/db/schema.sql](cyberWatch/db/schema.sql) and [cyberWatch/db/dns_schema.sql](cyberWatch/db/dns_schema.sql) to DSN `CYBERWATCH_PG_DSN` (default `postgresql://postgres:postgres@localhost:5432/cyberWatch`).
- Installs DNS config to `/etc/cyberwatch/dns.yaml` from [config/cyberwatch_dns.example.yaml](config/cyberwatch_dns.example.yaml) if absent.
- Installs/enables systemd units: [systemd/cyberWatch-api.service](systemd/cyberWatch-api.service), [systemd/cyberWatch-ui.service](systemd/cyberWatch-ui.service), [systemd/cyberWatch-enrichment.service](systemd/cyberWatch-enrichment.service), [systemd/cyberWatch-dns-collector.service](systemd/cyberWatch-dns-collector.service).

## Configuration
- DNS collector config lives at `/etc/cyberwatch/dns.yaml` (installed from [config/cyberwatch_dns.example.yaml](config/cyberwatch_dns.example.yaml)). Key fields:
  - `enabled`: toggle collector.
  - `source`: `pihole` (HTTP API) or `logfile` (tail FTL logs).
  - `poll_interval_seconds`: per-source polling cadence.
  - `filters`: suffix ignore list (`.local`, `.lan`), qtypes to drop (e.g., `PTR`), clients to ignore, `max_domain_length`.
  - `dns_resolution`: enable/disable resolution, timeout, `max_ips_per_domain`.
- Core environment variables (defaults in systemd units):
  - `CYBERWATCH_PG_DSN`, `CYBERWATCH_REDIS_URL` (queue), `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` for API/enrichment/collector.
  - `CYBERWATCH_API_BASE` for the UI to reach the API.
  - `CYBERWATCH_DNS_CONFIG` to point the collector to a non-default config path.

## Running cyberWatch
**Systemd (installed by the script)**
- API: `sudo systemctl status|start|stop cyberWatch-api.service` (FastAPI on port 8000).
- UI: `sudo systemctl status|start|stop cyberWatch-ui.service` (Uvicorn on port 8080).
- Enrichment loop: `sudo systemctl status|start|stop cyberWatch-enrichment.service` (ASN enrichment + graph builder).
- DNS collector (optional): `sudo systemctl status|start|stop cyberWatch-dns-collector.service`.

**Manual/dev mode**
```bash
# Activate virtualenv
source .venv/bin/activate
# Run API (reload optional)
uvicorn cyberWatch.api.server:app --host 0.0.0.0 --port 8000
# Run UI
CYBERWATCH_API_BASE=http://localhost:8000 uvicorn cyberWatch.ui.server:app --host 0.0.0.0 --port 8080
# Run enrichment loop
python -m cyberWatch.enrichment.run_enrichment
# Run DNS collector
python -m cyberWatch.collector.dns_collector --config /etc/cyberwatch/dns.yaml
# Run a worker manually
python -m cyberWatch.workers.worker
```

## Using the API and UI
Example API calls:
```bash
# On-demand traceroute
curl -X POST http://localhost:8000/traceroute/run -H "Content-Type: application/json" -d '{"target":"8.8.8.8"}'

# Latest measurement for a target
curl "http://localhost:8000/measurements/latest?target=8.8.8.8"

# Hops for a measurement
curl http://localhost:8000/measurements/hops/1

# Enqueue a target
curl -X POST http://localhost:8000/targets/enqueue -H "Content-Type: application/json" -d '{"target":"1.1.1.1","source":"api"}'

# ASN detail
curl http://localhost:8000/asn/13335

# Graph neighbors
curl http://localhost:8000/graph/neighbors/13335

# Shortest AS path
curl "http://localhost:8000/graph/path?src_asn=13335&dst_asn=15169"

# DNS analytics
curl http://localhost:8000/dns/top-domains
curl http://localhost:8000/dns/top-asns
```
UI (serving on `http://<host>:8080`):
- Traceroute: enter target, JSON hops returned.
- ASN Explorer: enter ASN, see org/country and neighbor list.
- Graph View: list neighbors for an ASN with edge stats.

## Grafana Dashboards
Dashboard JSON lives in [grafana/dashboards](grafana/dashboards):
- [latency_overview.json](grafana/dashboards/latency_overview.json): RTT mean and P95 per target over time.
- [hopcount_overview.json](grafana/dashboards/hopcount_overview.json): hopcount distribution and hopcount time series.
- [asn_performance.json](grafana/dashboards/asn_performance.json): RTT by ASN and observed edge counts.

Import into Grafana and configure a PostgreSQL datasource pointing at the cyberWatch database. Queries expect tables `targets`, `measurements`, and `hops` with timestamps in `started_at` and RTT in `rtt_ms`.

## Uninstallation
Use [uninstall-cyberWatch.sh](uninstall-cyberWatch.sh):
```bash
./uninstall-cyberWatch.sh            # prompts before dropping tables or removing DNS config
./uninstall-cyberWatch.sh --purge    # additionally purges redis-server, postgresql-client, traceroute, scamper
```
What it does:
- Stops/disables systemd units (API, UI, enrichment, DNS collector) and removes their unit files.
- Removes `.venv` and cleans `/var/lib/cyberWatch` if present.
- Optional prompt to drop PostgreSQL tables (`dns_queries`, `dns_targets`, `hops`, `measurements`, `targets`).
- Optional prompt to remove `/etc/cyberwatch/dns.yaml`.

## Roadmap / Future Work
From [architecture.md](architecture.md):
- Privacy hardening for DNS-derived targets (hashing/anonymization), TLS, and access controls.
- Richer scheduling/rate limiting and expanded probe set (MTR/ping integration beyond ad-hoc).
- Broader metadata ingestion (BGP/IXP datasets) to deepen the AS graph.
- Monitoring/security hardening (network isolation, auth for UI/Grafana, encrypted channels).

## License
License: TBD (no LICENSE file present).
