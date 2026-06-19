# Quickstart: Stabilization Baseline Validation

## Prerequisites

- Python 3.11 or newer.
- Repository checkout at the cyberWatch root.
- No live PostgreSQL, Redis, Neo4j, Pi-hole, traceroute, scamper, or internet access is required for the default validation.

## Install Dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r cyberWatch\requirements.txt
```

## Run Automated Baseline

```powershell
python -m pytest
```

Expected outcome:

- import smoke tests pass
- parser tests pass
- DNS filter tests pass
- queue key test passes
- destructive settings guard tests pass
- DNS privacy tests pass

## Focused Smoke Checks

```powershell
python -c "import importlib; importlib.import_module('cyberWatch.enrichment.run_enrichment')"
python -c "from cyberWatch.scheduler.queue import TargetQueue; assert TargetQueue().queue_key == 'cyberwatch:targets'"
```

Expected outcome:

- no import error from `run_enrichment`
- queue key assertion succeeds

## Optional Runtime Checks

Only run these when the corresponding services exist locally:

```powershell
redis-cli LLEN cyberwatch:targets
python -m cyberWatch.enrichment.run_enrichment
```

Expected outcome:

- Redis command checks the lowercase queue key
- enrichment service starts past import/name resolution; any later PostgreSQL/Neo4j/Redis connection failure should be a real environment dependency, not a stale local symbol

## Destructive Guard Manual Check

With default environment:

```powershell
curl -X POST http://localhost:8000/settings/clear-dns
```

Expected outcome:

- request is rejected with a clear disabled/403-style error
- no DNS clear work runs

With explicit operator opt-in:

```powershell
$env:CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS="true"
```

Expected outcome:

- destructive routes are available again, subject to existing database/graph availability

## DNS Privacy Manual Check

Default behavior:

```powershell
$env:CYBERWATCH_DNS_STORE_CLIENT_IPS="false"
```

Expected outcome:

- newly prepared DNS query and target records omit client IP values
- DNS target resolution/enqueue behavior remains unchanged

Lab opt-in:

```powershell
$env:CYBERWATCH_DNS_STORE_CLIENT_IPS="true"
```

Expected outcome:

- new DNS records may persist client IP fields as before
- existing historical rows are not modified by toggling this variable

