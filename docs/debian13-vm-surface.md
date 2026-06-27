# Debian 13 VM Development and Test Surface

This document is the operator-facing companion to
`specs/001-debian-vm-surface/quickstart.md`. It describes the dedicated Debian
13 VM surface used by maintainers and Codex to develop, install, uninstall,
reinstall, and smoke-test cyberWatch.

## Scope

Use only the dedicated disposable cyberWatch VM for privileged lifecycle work.
Codex may run install, uninstall, reinstall, `systemctl`, `journalctl`,
Redis queue, API health, and smoke commands inside that VM. Those commands must
remain reproducible from repository scripts and docs.

Do not run privileged lifecycle checks on a shared workstation or production
host.

## Snapshot States

Create or restore snapshots outside cyberWatch with the VM host or hypervisor.
Record the label used for each smoke run.

- `clean-os`: Debian 13 base image before cyberWatch install.
- `pre-install`: repository checked out, Codex authenticated, before install.
- `post-install`: cyberWatch installed and services available for smoke checks.
- `pre-risk-check`: before uninstall/reinstall or destructive guardrail checks.
- `failed-run`: captured after a failed lifecycle command before restore.
- `restored`: verified return to a known baseline.

Before running installer, uninstaller, reinstall, or service-management checks,
set:

```bash
export CYBERWATCH_VM_SNAPSHOT_CONFIRMED=1
export CYBERWATCH_VM_SNAPSHOT_LABEL="pre-install-YYYYMMDD"
```

## Default Pure Tests

The default local test command is:

```bash
python -m pytest
```

This command is for pure/offline tests only. It must not require PostgreSQL,
Redis, Neo4j, internet access, traceroute, scamper, Pi-hole, root, or systemd.

If the VM has no `python` command on PATH yet, activate the repo venv or run the
equivalent venv interpreter while keeping the documented command surface:

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest
```

## Smoke Script

Live service validation is VM-only and is driven by:

```bash
scripts/cyberwatch-vm-smoke.sh --help
```

The script emits one reviewable result line per check with `check_id`, `status`,
`command_surface`, `expected_outcome`, `observed_outcome`, `failure_evidence`,
`vm_snapshot_state`, and `timestamp`.

Status vocabulary:

- `PASS`: expected outcome observed.
- `FAIL`: expected outcome not observed.
- `WARN`: check passed with operator-visible follow-up.
- `SKIP`: check not run because a documented prerequisite is missing.

List the stable check IDs:

```bash
scripts/cyberwatch-vm-smoke.sh --list-checks
```

## Baseline

Run before privileged lifecycle work:

```bash
scripts/cyberwatch-vm-smoke.sh \
  --snapshot-label "$CYBERWATCH_VM_SNAPSHOT_LABEL" \
  --yes-snapshot \
  --run-baseline
```

The baseline verifies Debian 13, snapshot confirmation, Codex CLI presence/auth
evidence, and the repository path.

## Line Ending Protection

Run before install, uninstall, or service lifecycle commands:

```bash
scripts/cyberwatch-vm-smoke.sh --run-line-endings
```

The check scans shell scripts and `systemd/*.service` files for CRLF. Any CRLF
violation blocks lifecycle checks until fixed.

## Install

From the repo checkout:

```bash
scripts/cyberwatch-vm-smoke.sh \
  --snapshot-label "$CYBERWATCH_VM_SNAPSHOT_LABEL" \
  --yes-snapshot \
  --allow-lifecycle \
  --run-install
```

This runs `install-cyberWatch.sh` from the repository under test and captures
installer output on failure.

## Runtime Services and Logs

After installation:

```bash
scripts/cyberwatch-vm-smoke.sh --run-services
scripts/cyberwatch-vm-smoke.sh --run-api
scripts/cyberwatch-vm-smoke.sh --run-bind
scripts/cyberwatch-vm-smoke.sh --run-enrichment
scripts/cyberwatch-vm-smoke.sh --run-journals
```

The service check covers PostgreSQL, Redis, Neo4j, API, UI, enrichment, DNS
collector, remeasurement, and worker instances. The API check calls root and
`/health`. The bind check reports localhost-only versus all-interface exposure.
Journal commands can be listed without running them:

```bash
scripts/cyberwatch-vm-smoke.sh --journal-commands
```

## Redis Queue Key

The canonical target queue is:

```text
cyberwatch:targets
```

The legacy mixed-case key is:

```text
cyberWatch:targets
```

Inspect both:

```bash
scripts/cyberwatch-vm-smoke.sh --run-redis
```

A nonzero legacy depth produces a `WARN` with migration guidance. Do not delete
legacy queue entries blindly.

## Destructive Endpoint Guardrail

Destructive settings endpoints are disabled by default. The guardrail smoke
check expects `/settings/clear-dns` to return HTTP 403:

```bash
scripts/cyberwatch-vm-smoke.sh --run-guardrails
```

To explicitly enable destructive settings endpoints for a controlled lab reset,
use one of these opt-ins:

```bash
export CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS=1
```

or set the PostgreSQL `settings` table key:

```sql
INSERT INTO settings (key, value)
VALUES ('destructive_settings_enabled', '{"destructive_settings_enabled": true}'::jsonb)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
```

Refusals and allowed executions are logged with `action`, `guardrail`, and
`outcome`.

## Uninstall and Reinstall

Default uninstall is bounded to cyberWatch-owned resources:

- cyberWatch systemd unit files and worker template.
- `/etc/cyberwatch`.
- `/var/lib/cyberwatch` and the legacy `/var/lib/cyberWatch` path.
- repo `.venv` and `logs/`.
- Redis keys `cyberwatch:*` and `cyberWatch:*`.

Neo4j graph cleanup is disabled by default and requires `--clear-neo4j` or
`CYBERWATCH_CLEAR_NEO4J=1`. PostgreSQL table drops require
`CYBERWATCH_DROP_DB=1`. Package purge requires `--purge`.

Run the VM-only uninstall/reinstall smoke:

```bash
scripts/cyberwatch-vm-smoke.sh \
  --snapshot-label "$CYBERWATCH_VM_SNAPSHOT_LABEL" \
  --yes-snapshot \
  --allow-lifecycle \
  --run-uninstall-reinstall
```

## Full Non-Lifecycle Smoke Pass

This does not run install or uninstall commands:

```bash
scripts/cyberwatch-vm-smoke.sh --run-all
```

Use lifecycle flags only when snapshot confirmation is current and the VM is
disposable.
