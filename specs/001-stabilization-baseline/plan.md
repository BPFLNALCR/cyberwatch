# Implementation Plan: Stabilization Baseline

**Branch**: `chore/init-spec-kit` | **Date**: 2026-06-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-stabilization-baseline/spec.md`

## Summary

Stabilize cyberWatch before feature or constitution work by fixing the enrichment scheduler's stale refactor references, adding a small pytest/CI baseline, making the Redis queue key lowercase and consistent, disabling destructive settings endpoints by default, and adding a minimal DNS client-IP persistence toggle. The approach is intentionally narrow: change only the existing service, queue, collector, settings-route, docs, and validation surfaces needed to make future development safer.

## Technical Context

**Language/Version**: Python 3.11+ for runtime services; shell installer targets Debian-like systems.

**Primary Dependencies**: FastAPI, asyncpg, redis asyncio client, pydantic, rich, dnspython, PyYAML, neo4j, uvicorn, pytest.

**Storage**: PostgreSQL for measurements/settings/DNS records, Redis list for target queue, Neo4j for graph data. No database migration is planned for this stabilization pass; DNS client fields remain nullable.

**Testing**: pytest unit/smoke tests only, with no live PostgreSQL, Redis, Neo4j, Pi-hole, traceroute, scamper, or internet dependency.

**Target Platform**: Debian-based VM/systemd runtime; tests and CI should run on GitHub-hosted Linux runners and local Windows/PowerShell development shells.

**Project Type**: Multi-service Python web/API/background-worker project with systemd deployment templates.

**Performance Goals**: Keep the default local validation command under 5 minutes after dependencies are installed; keep CI under 10 minutes for the stabilization baseline.

**Constraints**: Preserve current service loop behavior and public operator workflow; avoid architecture redesign; avoid live external services in tests; default destructive API behavior must be safe.

**Scale/Scope**: Stabilization-only pass across one Python package, one installer, documentation, CI, and focused tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution file is still a placeholder and has not been ratified, so no concrete project governance gates can be evaluated. The plan follows the stabilization spec's explicit scope limits instead:

- No Spec Kit constitution implementation.
- No new product features.
- No architecture redesign.
- No live service requirement for the default test suite.
- Existing runtime pipeline remains DNS collector -> queue -> workers -> PostgreSQL -> enrichment -> Neo4j -> API/UI/Grafana.

Initial gate result: PASS, because no ratified constitution rules are violated and the stabilization scope remains bounded.

## Project Structure

### Documentation (this feature)

```text
specs/001-stabilization-baseline/
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- contracts/
|   |-- destructive-settings.md
|   |-- dns-privacy.md
|   `-- queue-key.md
|-- checklists/
|   `-- requirements.md
`-- tasks.md
```

`tasks.md` is intentionally not created by this command; it belongs to `/speckit-tasks`.

### Source Code (repository root)

```text
cyberWatch/
|-- api/
|   |-- routes/settings.py
|   `-- server.py
|-- collector/
|   |-- config.py
|   `-- dns_collector.py
|-- db/
|   |-- dns_schema.sql
|   `-- settings.py
|-- enrichment/
|   |-- asn_expander.py
|   `-- run_enrichment.py
|-- scheduler/
|   `-- queue.py
|-- workers/
|   `-- worker.py
`-- requirements.txt

tests/
|-- test_dns_filters.py
|-- test_dns_privacy.py
|-- test_imports.py
|-- test_queue.py
|-- test_settings_guard.py
`-- test_worker_parsers.py

.github/
|-- copilot-instructions.md
`-- workflows/ci.yml

README.md
install-cyberWatch.sh
systemd/cyberWatch-enrichment.service
config/cyberwatch_dns.example.yaml
AGENTS.md
```

**Structure Decision**: Keep the existing single-package repository shape. Add `tests/` at the root for pytest discovery and `.github/workflows/ci.yml` for lightweight CI. Do not introduce a new package manager, service directory, or deployment layer.

## Technical Implementation Plan

### 1. Enrichment Scheduler Fix

**Files to change**

- `cyberWatch/enrichment/run_enrichment.py`

**Exact broken names/imports found**

- `Queue(redis_url)` is referenced but no `Queue` symbol exists in the module or repository queue API.
- `datetime.utcnow()` is referenced but `datetime` is not imported.
- `get_enrichment_settings(pool)` exists in `cyberWatch/db/settings.py` but is not imported.
- `AsnExpanderConfig` exists in `cyberWatch/enrichment/asn_expander.py` but is not imported.
- `expand_asns(...)` is referenced but does not exist; the current batch API is `cyberWatch.enrichment.asn_expander.run_once(pool, queue, config)`.

**Planned edits**

- Add `from datetime import datetime`.
- Add `from cyberWatch.db.settings import get_enrichment_settings`.
- Add `from cyberWatch.scheduler.queue import TargetQueue`.
- Import the ASN expander module or explicit names as `from cyberWatch.enrichment import asn_expander`, then call `asn_expander.AsnExpanderConfig(...)` and `asn_expander.run_once(...)`.
- Replace `queue = Queue(redis_url)` with `queue = TargetQueue(redis_url)`.
- Replace `expanded = await expand_asns(pool, queue, expander_config)` with `expanded = await asn_expander.run_once(pool, queue, expander_config)`.
- Preserve the existing loop cadence, Neo4j degraded behavior, enrichment run, graph builder run, ASN expansion interval logic, and shutdown cleanup.

**Files inspected but likely unchanged**

- `cyberWatch/enrichment/asn_expander.py`: current API already provides `AsnExpanderConfig` and `run_once(...)`.
- `cyberWatch/db/settings.py`: current API already provides `get_enrichment_settings(...)`.
- `systemd/cyberWatch-enrichment.service`: already starts `python -m cyberWatch.enrichment.run_enrichment`; leave as-is and validate the module import succeeds.

### 2. Test Scaffold

**Files to change**

- `cyberWatch/requirements.txt`
- `tests/test_imports.py`
- `tests/test_worker_parsers.py`
- `tests/test_dns_filters.py`
- `tests/test_queue.py`
- `tests/test_settings_guard.py`
- `tests/test_dns_privacy.py`

**Planned edits**

- Add `pytest` to `cyberWatch/requirements.txt`.
- Keep tests as unit/smoke tests using direct function calls, `importlib`, monkeypatching, and small fakes.
- Do not require `pytest-asyncio`; use `asyncio.run(...)` in any async test that is needed.

**Test coverage plan**

- `tests/test_imports.py`
  - Import `cyberWatch.enrichment.run_enrichment`.
  - Import `cyberWatch.workers.worker`.
  - Import `cyberWatch.collector.dns_collector`.
  - Import `cyberWatch.api.routes.settings`.
  - Assert imports do not initialize live services or require network/database connections.

- `tests/test_worker_parsers.py`
  - Cover `_parse_traceroute_hops(...)` with normal hop lines and timeout lines.
  - Cover `_parse_scamper_hops(...)` with normal scamper trace output.
  - Assert hop numbers, IP values, RTT values, and timeout handling.

- `tests/test_dns_filters.py`
  - Cover reverse DNS suffixes: `.in-addr.arpa`, `.ip6.arpa`.
  - Cover Team Cymru enrichment lookups: `.origin.asn.cymru.com`, `.peer.asn.cymru.com`, `.asn.cymru.com`.
  - Cover configured suffix filter such as `.local`.
  - Cover ignored qtype such as `PTR`.
  - Cover ignored client IP from `ignore_clients`.

- `tests/test_queue.py`
  - Assert `TargetQueue().queue_key == "cyberwatch:targets"`.
  - Assert explicit `queue_key` override remains supported.

- `tests/test_settings_guard.py`
  - Assert destructive settings guard is disabled when `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS` is unset or false-like.
  - Assert it is enabled for true-like values.
  - Assert the guard raises a clear forbidden error before route work can continue when disabled.

- `tests/test_dns_privacy.py`
  - Assert DNS client IP storage is disabled by default.
  - Assert env/config opt-in preserves client IP storage for lab deployments.
  - Assert the collector maps stored `DNSQueryRecord.client_ip` and `DNSTargetRecord.last_client_ip` to `None` when privacy is enabled, without changing filtering behavior.

### 3. CI

**Files to add**

- `.github/workflows/ci.yml`

**Planned workflow**

- Trigger on pull requests and pushes.
- Use an Ubuntu runner.
- Set up Python 3.11.
- Install dependencies with:
  - `python -m pip install --upgrade pip`
  - `python -m pip install -r cyberWatch/requirements.txt`
- Run `python -m pytest`.
- Do not provision PostgreSQL, Redis, Neo4j, Pi-hole, traceroute, scamper, or internet-backed integration fixtures.

### 4. Queue Key Drift

**Canonical choice**

- Use lowercase `cyberwatch:targets`.

**Rationale**

- `README.md`, `.github/copilot-instructions.md`, installer output, and architecture/operator examples already use lowercase.
- Lowercase names are less surprising in Redis/operator commands.
- The only confirmed drift in code is the `TargetQueue` default.

**Files to change**

- `cyberWatch/scheduler/queue.py`: default `queue_key` becomes `"cyberwatch:targets"`.
- `README.md`: verify all queue examples remain lowercase.
- `.github/copilot-instructions.md`: verify all queue examples remain lowercase.

**Files inspected but likely unchanged**

- `install-cyberWatch.sh`: already prints `redis-cli LLEN cyberwatch:targets`.
- `cyberWatch/workers/worker.py`, `cyberWatch/collector/dns_collector.py`, `cyberWatch/scheduler/remeasure.py`, `cyberWatch/api/routes/targets.py`, `cyberWatch/api/routes/health.py`: all instantiate `TargetQueue()` or `TargetQueue(redis_url)` and should inherit the canonical default automatically.

### 5. Destructive Endpoint Guardrail

**Files to change**

- `cyberWatch/api/routes/settings.py`
- `install-cyberWatch.sh`
- `README.md`
- `.github/copilot-instructions.md`

**Planned edits**

- Add `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS` support.
- Default behavior: disabled when the variable is unset or false-like.
- Add helper functions in `settings.py`, for example:
  - `destructive_settings_enabled() -> bool`
  - `require_destructive_settings_enabled() -> None`
- Treat true-like values as enabled: `1`, `true`, `yes`, `on`.
- Call the guard at the beginning of:
  - `clear_measurements`
  - `clear_dns`
  - `clear_graph`
  - `clear_all`
- When disabled, return/raise a clear 403-style error before acquiring database/graph resources or running counts/truncates.
- Add default `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS="false"` to the installer-generated `/etc/cyberwatch/cyberwatch.env`.
- Document that the guard is an accidental-use protection, not full authentication/authorization.

**Files inspected but likely unchanged**

- `cyberWatch/api/server.py`: route registration remains unchanged.
- `cyberWatch/ui/templates/settings.html`: existing error rendering should surface the API error; avoid UI redesign in this stabilization pass.

### 6. DNS Privacy Baseline

**Decision**

- Implement a minimal opt-in toggle for storing client IPs, defaulting to privacy-preserving behavior for new ingestion.
- Do not drop columns, migrate historical rows, hash domains, or redesign DNS analytics.

**Files to change**

- `cyberWatch/collector/config.py`
- `cyberWatch/collector/dns_collector.py`
- `config/cyberwatch_dns.example.yaml`
- `cyberWatch/db/dns_schema.sql`
- `install-cyberWatch.sh`
- `README.md`
- `.github/copilot-instructions.md`

**Planned edits**

- Add a small privacy config model, for example `DNSPrivacyConfig`, with `store_client_ips: bool = False`.
- Add `privacy: DNSPrivacyConfig = Field(default_factory=DNSPrivacyConfig)` to `DNSCollectorConfig`.
- Add an environment override `CYBERWATCH_DNS_STORE_CLIENT_IPS`; if set, it wins over YAML config.
- In `dns_collector.py`, centralize the decision in small helpers, for example:
  - `dns_client_ip_storage_enabled(cfg: DNSCollectorConfig) -> bool`
  - `client_ip_for_storage(cfg: DNSCollectorConfig, client_ip: Optional[str]) -> Optional[str]`
- Preserve client IP use for pre-storage filtering, so `ignore_clients` still works.
- Apply the storage helper when building `DNSQueryRecord.client_ip` and `DNSTargetRecord.last_client_ip`.
- Leave `dns_queries.client_ip` and `dns_targets.last_client_ip` nullable for compatibility, but add SQL comments noting they are legacy/lab opt-in fields.
- Add `CYBERWATCH_DNS_STORE_CLIENT_IPS="false"` to installer-generated env.
- Document that existing rows are not scrubbed by this pass.

### 7. Documentation

**Files to change**

- `README.md`
- `.github/copilot-instructions.md`
- `config/cyberwatch_dns.example.yaml`
- `install-cyberWatch.sh`
- `cyberWatch/db/dns_schema.sql`

**Planned README updates**

- Add a "Testing" section:
  - `python -m pip install -r cyberWatch/requirements.txt`
  - `python -m pytest`
- Confirm `redis-cli LLEN cyberwatch:targets` as the queue key example.
- Add environment variables:
  - `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS=false`
  - `CYBERWATCH_DNS_STORE_CLIENT_IPS=false`
- Document destructive endpoints are disabled by default and require explicit env opt-in.
- Document DNS privacy status: new ingestion omits client IPs by default; columns remain for opt-in/lab use; historical rows are not scrubbed.

**Planned `.github/copilot-instructions.md` updates**

- Replace manual `python test_logging.py` as the primary testing guidance with `python -m pytest`, leaving `test_logging.py` as optional/manual if still retained.
- Add guardrail and DNS privacy env vars to the environment table.
- Keep queue examples lowercase.

## Validation Commands

Run after implementation:

```powershell
python -m pip install -r cyberWatch\requirements.txt
python -m pytest
python -c "import importlib; importlib.import_module('cyberWatch.enrichment.run_enrichment')"
python -c "from cyberWatch.scheduler.queue import TargetQueue; assert TargetQueue().queue_key == 'cyberwatch:targets'"
```

Optional service-adjacent validation when live services exist:

```powershell
python -m cyberWatch.enrichment.run_enrichment
redis-cli LLEN cyberwatch:targets
```

Do not require optional live-service validation for CI.

## Complexity Tracking

No constitution-driven complexity violations are present. The plan deliberately avoids new architectural layers, migrations, authentication systems, or live integration test infrastructure.

## Post-Design Constitution Check

Result: PASS. The constitution remains a placeholder, and the design continues to follow the stabilization spec's explicit constraints: no constitution work, no product features, no redesign, no mandatory live services in tests, and safe defaults for destructive operations and DNS client-IP storage.

