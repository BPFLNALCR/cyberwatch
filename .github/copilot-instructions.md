# CyberWatch AI Coding Instructions

## Design Philosophy

This codebase follows UNIX programming principles. When making design or implementation decisions, prefer clarity, modularity, composability, and diagnosability over cleverness or premature optimization.

**Core Principles:**

| Principle | Application in CyberWatch |
|-----------|---------------------------|
| **Modularity** | Single-responsibility modules: workers probe, enrichers enrich, API serves. No hidden coupling. |
| **Readability** | Clear naming, straightforward async/await flow. Avoid clever constructs. |
| **Composition** | Pipeline architecture: DNS → Queue → Workers → DB → Enrichment → Graph. Compose, don't monolith. |
| **Mechanism vs Policy** | Settings in `settings` table (policy), code provides capabilities (mechanism). |
| **Simplicity** | Solve the current problem. No speculative abstractions. |
| **Smallness** | Functions/modules small enough to understand, test, replace. Split when they grow. |
| **Transparency** | Explicit state, structured JSONL logging, traceable request IDs. No magic. |
| **Robustness** | Validate inputs, handle errors explicitly, fail safely with clear messages. |
| **Data over Logic** | Express complexity in schemas (`asns` table), config (YAML/JSONB), not nested logic. |
| **Diagnosable Failure** | Actionable error messages, `outcome` field in logs, meaningful exit codes. |
| **Minimal Output** | JSONL logs are machine-parsable. Console output is intentional and stable. |
| **Automation** | Systemd templates (`worker@.service`), schema files, install scripts—don't repeat manually. |
| **Prototyping First** | Run code to test assumptions. Expect iteration. Early implementations may be revised. |
| **Extensibility** | New enrichment sources, API routes, worker tools designed for future extension. |

**Key tradeoff**: Developer time > machine time. Optimize only when performance constraints are measured.

## Architecture Overview

CyberWatch is an autonomous internet measurement and topology mapping system with a multi-service architecture:

```
DNS Collector → Redis Queue → Worker Pool → PostgreSQL → Enrichment → Neo4j Graph
                                                ↓
                                    FastAPI + Jinja UI + Grafana
```

**Key services** (all Python async, managed by systemd):
- **Workers** (`cyberWatch/workers/worker.py`): Pull targets from Redis, run traceroute/scamper, store hops
- **Enrichment** (`cyberWatch/enrichment/`): Poll unenriched hops, lookup ASN from 5+ sources, build Neo4j graph
- **API** (`cyberWatch/api/server.py`): FastAPI on port 8000, routes in `cyberWatch/api/routes/`
- **UI** (`cyberWatch/ui/server.py`): Jinja2 templates on port 8080, calls API internally
- **DNS Collector** (`cyberWatch/collector/dns_collector.py`): Ingests Pi-hole queries, enqueues targets

## Code Patterns

### Logging
All components use structured JSONL logging via `cyberWatch/logging_config.py`:
```python
from cyberWatch.logging_config import get_logger, setup_logging
logger = get_logger("component_name")  # or setup_logging("component") for initial setup
logger.info("Message", extra={"target": ip, "outcome": "success", "duration": ms})
```
**Required extra fields**: `outcome` ("success"/"error"), `action` for operations, `duration` for timed ops.

### Database Access
Use `asyncpg` pools from `cyberWatch/db/pg.py`. Pattern:
```python
from cyberWatch.db.pg import create_pool
pool = await create_pool(os.getenv("CYBERWATCH_PG_DSN"))
async with pool.acquire() as conn:
    await conn.fetch("SELECT ...")
```
Settings are stored as JSONB in `settings` table—use helpers in `cyberWatch/db/settings.py`.

### Redis Queue
Target tasks flow through Redis list `cyberwatch:targets`. Use `TargetQueue` from `cyberWatch/scheduler/queue.py`:
```python
from cyberWatch.scheduler.queue import TargetQueue, TargetTask
queue = TargetQueue()
await queue.enqueue(TargetTask(target_ip="1.1.1.1", source="api"))
task = await queue.dequeue(timeout=5)
```

### Pydantic Models
All API request/response models in `cyberWatch/api/models.py`. Wrap responses with `ok()` helper:
```python
from cyberWatch.api.models import ok
return ok({"asn": 13335, "org_name": "Cloudflare"})
```

### Enrichment Pipeline
Multi-source ASN lookup in order of preference:
1. Team Cymru WHOIS (`cyberWatch/enrichment/asn_lookup.py`)
2. PeeringDB API (`cyberWatch/enrichment/peeringdb.py`)
3. External: RIPE RIS, ip-api, ipinfo (`cyberWatch/enrichment/external_sources.py`)

Merge priority: PeeringDB > External > Cymru. Always upsert to `asns` table.

## Database Schema

**Core tables** (see `cyberWatch/db/schema.sql`):
- `targets`: IP targets with source tracking
- `measurements`: Traceroute runs with `enriched`/`graph_built` flags
- `hops`: Per-hop data with ASN/prefix/org after enrichment
- `asns`: Comprehensive ASN metadata (org, country, PeeringDB data, stats)
- `settings`: JSONB key-value for runtime config

**Enrichment workflow flags**: `measurements.enriched` → `measurements.graph_built`

## Development Commands

```bash
# Activate virtualenv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Run services manually
uvicorn cyberWatch.api.server:app --reload --port 8000
python -m cyberWatch.workers.worker
python -m cyberWatch.enrichment.run_enrichment

# Check queue depth
redis-cli LLEN cyberwatch:targets

# View logs (JSONL format)
tail -f logs/cyberwatch.jsonl | jq '.'
grep '"outcome":"error"' logs/cyberwatch.jsonl | jq '.'
```

## Key Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CYBERWATCH_PG_DSN` | PostgreSQL connection | `postgresql://postgres:postgres@localhost:5432/cyberWatch` |
| `CYBERWATCH_REDIS_URL` | Redis for queue | `redis://localhost:6379/0` |
| `NEO4J_URI` | Neo4j bolt URI | `bolt://localhost:7687` |
| `CYBERWATCH_LOG_LEVEL` | Log level | `INFO` |
| `CYBERWATCH_API_BASE` | API URL for UI | `http://localhost:8000` |

## Adding New Features

**New API endpoint**: Add route file in `cyberWatch/api/routes/`, register in `server.py` with `app.include_router()`.

**New enrichment source**: Implement lookup function returning dataclass, call from `enricher.py:enrich_hop()`.

**New worker capability**: Extend `Worker` class, add tool detection in `_pick_tool()`, parser in `_parse_*_hops()`.

## Testing

```bash
# Run logging tests
python test_logging.py

# API health check
curl http://localhost:8000/health
curl http://localhost:8000/
```

## DNS Collector Filter Patterns

Config at `/etc/cyberwatch/dns.yaml` (source: `config/cyberwatch_dns.example.yaml`):

```yaml
filters:
  ignore_domains_suffix:   # Skip domains ending with these
    - ".local"
    - ".lan"
  ignore_qtypes:           # Skip these DNS query types
    - "PTR"
  ignore_clients: []       # Client IPs to ignore (empty = allow all)
  max_domain_length: 255   # Reject domains longer than this

dns_resolution:
  enabled: true            # Resolve domains to IPs before enqueuing
  timeout_seconds: 2
  max_ips_per_domain: 4    # Limit IPs per domain (A/AAAA records)
```

**Pi-hole sources**: Set `source: "pihole"` with `base_url` + `api_token`, or `source: "logfile"` to tail `/var/log/pihole.log`.

## Install/Uninstall Scripts

### `install-cyberWatch.sh` (idempotent)
```bash
./install-cyberWatch.sh    # Interactive prompts for schema, Neo4j, settings
```
**What it does:**
1. Installs apt packages: python3, redis-server, postgresql, neo4j, traceroute, scamper, mtr-tiny
2. Creates `.venv` and installs `cyberWatch/requirements.txt`
3. Prompts to apply PostgreSQL schemas (`schema.sql`, `dns_schema.sql`)
4. Creates `/etc/cyberwatch/cyberwatch.env` with DSN, Redis URL, Neo4j credentials
5. Configures Neo4j with secure password, creates graph constraints
6. Initializes default settings in `settings` table (worker rates, enrichment, remeasurement)
7. Installs/enables systemd units: API, UI, enrichment, DNS collector, 2 workers, remeasure

**Non-interactive mode** (CI):
```bash
CYBERWATCH_APPLY_SCHEMA=1 ./install-cyberWatch.sh
```

### `uninstall-cyberWatch.sh`
```bash
./uninstall-cyberWatch.sh          # Interactive cleanup, keeps packages
./uninstall-cyberWatch.sh --purge  # Also removes redis-server, postgresql-client, etc.
```
**What it removes:**
- Stops/disables all cyberWatch systemd units
- Clears Redis queue (`cyberwatch:targets`)
- Optionally drops PostgreSQL tables/database
- Optionally removes Neo4j data
- Removes `.venv`, logs, `/etc/cyberwatch/`

## Systemd Service Pattern

Template unit for workers at `systemd/cyberWatch-worker@.service`. Scale with:
```bash
sudo systemctl start cyberWatch-worker@3.service
```

**View all service status:**
```bash
systemctl list-units 'cyberWatch-*'
sudo journalctl -u 'cyberWatch-*' -f
```
