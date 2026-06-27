# Contract: VM Smoke Command Catalog

## Purpose

This contract defines the required command categories, prerequisites, expected
outcomes, and failure evidence for the Debian 13 VM validation surface. The
implementation may provide these as a documented checklist, a shell script, a
Python wrapper, or a combination, but the observable behavior must match this
contract.

## Status Vocabulary

- `PASS`: Expected outcome observed.
- `FAIL`: Expected outcome not observed.
- `SKIP`: Check intentionally not run because a documented prerequisite is
  missing.
- `WARN`: Check passed but found operator-visible follow-up, such as legacy
  queue entries.

## Required Checks

### VM Baseline

Prerequisites:
- Running inside the dedicated Debian 13 VM.
- A restoreable snapshot exists.
- Codex CLI is installed and authenticated before Codex runs lifecycle commands.

Expected outcome:
- Result records OS version, snapshot label or operator confirmation, Codex
  authentication status, and repository path.

Failure evidence:
- OS release output, missing snapshot note, or Codex auth failure output.

### Install

Command surface:
- Run `install-cyberWatch.sh` from the repository checkout.

Expected outcome:
- Installer completes or returns actionable failure output.
- `/etc/cyberwatch/cyberwatch.env` exists when configuration is created.
- Service unit templates are installed through systemd.

Failure evidence:
- Installer exit status, last installer log lines, and relevant service status.

### Service Status

Command surface:
- Inspect PostgreSQL, Redis, Neo4j, `cyberWatch-api.service`,
  `cyberWatch-ui.service`, `cyberWatch-enrichment.service`,
  `cyberWatch-dns-collector.service`, `cyberWatch-remeasure.service`, and
  `cyberWatch-worker@*`.

Expected outcome:
- Each service is active/running or intentionally documented as inactive.

Failure evidence:
- `systemctl status` output and recent journal lines for failed services.

### API Root and Health

Command surface:
- Call the configured API root.
- Call the configured API health endpoint.

Expected outcome:
- API root returns a successful response.
- Health returns dependency status and API base information.

Failure evidence:
- HTTP status, response body, and API journal lines.

### API/UI Bind Exposure

Command surface:
- Inspect service command lines, environment, or listening sockets.

Expected outcome:
- API and UI bind addresses are reported as localhost-only or all-interfaces.
- Any all-interfaces bind is explicit in smoke output.

Failure evidence:
- Service command line or socket listing.

### Destructive Endpoint Guardrail

Command surface:
- Call `/settings/clear-dns` with default configuration.

Expected outcome:
- HTTP 403 by default.
- DNS data remains unchanged.

Failure evidence:
- HTTP status, response body, pre/post DNS row counts where available, and API
  logs.

### Pure Test Command

Command surface:
- Run `python -m pytest`.

Expected outcome:
- Tests pass without live PostgreSQL, Redis, Neo4j, internet access,
  traceroute/scamper, Pi-hole, root, or systemd.

Failure evidence:
- pytest summary and failing test names.

### Enrichment Import and Startup

Command surface:
- Import `cyberWatch.enrichment.run_enrichment`.
- Start or inspect enrichment service long enough to distinguish immediate crash
  from external dependency unavailability.

Expected outcome:
- Import succeeds.
- Service does not crash immediately due to Python errors.
- Neo4j unavailability is reported as dependency failure, not as an import or
  service crash.

Failure evidence:
- Python traceback, systemd status, and enrichment journal lines.

### Redis Queue Key

Command surface:
- Inspect `cyberwatch:targets`.
- Inspect legacy `cyberWatch:targets`.

Expected outcome:
- `cyberwatch:targets` is canonical.
- Legacy key state is reported.
- Nonzero legacy depth produces WARN or FAIL with migration guidance.

Failure evidence:
- Redis key existence and depth output.

### Journals

Command surface:
- Inspect recent journal lines for API, UI, workers, enrichment, DNS collector,
  and remeasurement.

Expected outcome:
- Failure output includes service name, exit status or exception, and relevant
  dependency hints.

Failure evidence:
- Recent journal lines for each service.

### Line Endings

Command surface:
- Scan shell scripts and systemd unit files for CRLF.

Expected outcome:
- Zero CRLF violations.
- Any violation blocks privileged lifecycle checks until fixed.

Failure evidence:
- Exact file paths with CRLF.

### Uninstall and Reinstall

Command surface:
- Run default non-purge uninstall.
- Reinstall from the same checkout.

Expected outcome:
- Only declared cyberWatch-owned resources are affected unless explicit
  destructive opt-in is provided.
- Reinstall returns to a service-validatable state.

Failure evidence:
- Uninstall output, affected resource list, reinstall output, and service
  status.

## Result Record

Each check must produce a reviewable result with:

- `check_id`
- `status`
- `command_surface`
- `expected_outcome`
- `observed_outcome`
- `failure_evidence`
- `vm_snapshot_state`
- `timestamp`
