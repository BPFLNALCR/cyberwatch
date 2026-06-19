# Feature Specification: Stabilization Baseline

**Feature Branch**: `chore/init-spec-kit`

**Created**: 2026-06-19

**Status**: Draft

**Input**: User description: "Create a stabilization specification for cyberWatch before any new feature work or Spec Kit constitution work."

## Problem Statement

cyberWatch is intended to run as an autonomous internet measurement and topology mapping node with this pipeline: DNS collector -> Redis target queue -> measurement workers -> PostgreSQL -> ASN enrichment -> Neo4j graph -> FastAPI/UI/Grafana.

The repository currently has several baseline risks that make new feature work unsafe: the enrichment scheduler entrypoint appears to reference stale names after refactor, automated tests and lightweight CI are not established, queue key naming is inconsistent between docs and code, destructive settings endpoints can be called directly without a server-side confirmation guard, and the DNS privacy posture in architecture does not match the current DNS schema and collector behavior.

This stabilization pass exists to make the current project safe to develop further without redesigning the architecture or adding product features.

## Goals

- Restore confirmed broken startup/import/runtime behavior in the enrichment scheduler.
- Establish a minimal automated test baseline that future work can extend.
- Add lightweight repository CI so regressions are visible before merge.
- Resolve Redis target queue key naming drift so producers, consumers, health checks, and docs agree.
- Add a minimal server-side guardrail around destructive settings operations.
- Document the current DNS privacy posture and add a small, configurable improvement for new DNS ingestion if it can be done without schema churn.
- Preserve the existing intended pipeline and service boundaries.

## Non-Goals

- Do not implement the Spec Kit constitution in this pass.
- Do not add new product capabilities, analytics, topology features, measurement modes, or dashboard behavior.
- Do not redesign the DNS collector, queue, worker, enrichment, graph, API, UI, or database architecture.
- Do not require live Redis, PostgreSQL, Neo4j, Pi-hole, traceroute, or scamper for the default automated test suite.
- Do not scrub or migrate existing historical DNS rows unless a later explicit data-migration task is approved.
- Do not introduce a full authentication or authorization system for settings; this pass only adds a minimal accidental-use guardrail.

## Repository Inspection Findings

- Confirmed: `systemd/cyberWatch-enrichment.service` starts `python -m cyberWatch.enrichment.run_enrichment`.
- Confirmed: `cyberWatch/enrichment/run_enrichment.py` references `Queue(redis_url)` but no `Queue` symbol is imported or defined; the repository queue class is `TargetQueue` in `cyberWatch/scheduler/queue.py`.
- Confirmed: `run_enrichment.py` references `datetime.utcnow()` but does not import `datetime`.
- Confirmed with adjustment: `get_enrichment_settings(pool)` does exist in `cyberWatch/db/settings.py`, but `run_enrichment.py` does not import it.
- Confirmed with adjustment: `cyberWatch/enrichment/asn_expander.py` exposes `AsnExpanderConfig`, `expand_asn(...)`, and `run_once(...)`; `run_enrichment.py` references `expand_asns(...)`, which was not found.
- Confirmed: there is a manual `test_logging.py`, but no normal pytest scaffold or `tests/` directory was found.
- Confirmed: `.github` exists, but no `.github/workflows/` CI workflow was found.
- Confirmed: docs and operator examples mention Redis list `cyberwatch:targets`, while `TargetQueue` defaults to `cyberWatch:targets`.
- Confirmed: `/settings/clear-measurements`, `/settings/clear-dns`, `/settings/clear-graph`, and `/settings/clear-all` exist and perform destructive actions; the UI uses browser confirmation dialogs, but the API route itself has no explicit confirmation guard.
- Confirmed: architecture says DNS-derived data should avoid client-identifying fields, while `dns_queries.client_ip`, `dns_targets.last_client_ip`, and the collector persistence path store client IP values when source data provides them.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stabilize Enrichment Startup (Priority: P1)

As an operator, I need the existing enrichment service to start from its documented systemd/module entrypoint without immediate stale-name failures, so the measurement pipeline can progress from stored measurements to ASN enrichment and graph building.

**Why this priority**: The enrichment scheduler is part of the intended core pipeline, and a broken entrypoint blocks topology building and safe development on top of the current runtime.

**Independent Test**: Can be tested by running an automated startup/import check for the enrichment scheduler with external services mocked or isolated, then exercising one scheduler iteration far enough to prove the queue, settings, and ASN expansion references are valid.

**Acceptance Scenarios**:

1. **Given** the enrichment scheduler module is started through the documented module entrypoint, **When** its startup path reaches queue construction, settings loading, and ASN expansion scheduling, **Then** it does not fail due to undefined or stale symbols.
2. **Given** ASN expansion is enabled and due to run, **When** the scheduler invokes ASN expansion, **Then** it uses the repository's current ASN expansion contract and enqueues discovered targets through the same target queue interface used elsewhere.
3. **Given** Neo4j is unavailable at startup, **When** the scheduler starts, **Then** the existing degraded behavior remains bounded to graph building and does not mask unrelated startup/import defects.

---

### User Story 2 - Establish Development Safety Checks (Priority: P1)

As a maintainer, I need a minimal automated test suite and lightweight CI, so future changes cannot silently reintroduce the confirmed stabilization defects.

**Why this priority**: Without a repeatable baseline, stabilization work can regress immediately and new feature work remains risky.

**Independent Test**: Can be tested by running the default automated test command locally and by observing the same checks in repository CI without requiring live infrastructure services.

**Acceptance Scenarios**:

1. **Given** a clean development checkout, **When** the default automated test command is run, **Then** it completes without requiring live Redis, PostgreSQL, Neo4j, Pi-hole, traceroute, or scamper.
2. **Given** a pull request or push changes project code, **When** CI runs, **Then** the minimal automated checks report pass/fail for the stabilization baseline.
3. **Given** a future change reintroduces the confirmed enrichment stale-name behavior, queue key drift, missing destructive-operation guard, or DNS privacy regression, **When** the automated checks run, **Then** at least one check fails.

---

### User Story 3 - Prevent Accidental Destructive Operations (Priority: P2)

As an operator, I need destructive settings endpoints to require explicit confirmation at the server boundary, so accidental clicks, scripts, or casual HTTP requests cannot clear measurement, DNS, or graph data.

**Why this priority**: The current endpoints can delete substantial project data. UI confirmation alone does not protect direct API calls.

**Independent Test**: Can be tested by calling each destructive operation with no confirmation, invalid confirmation, and valid confirmation, then verifying rejection or success behavior without relying on browser dialogs.

**Acceptance Scenarios**:

1. **Given** a caller sends a destructive settings request without the required confirmation, **When** the API handles the request, **Then** no data is cleared and the response clearly indicates confirmation is required.
2. **Given** a caller sends an incorrect confirmation, **When** the API handles the request, **Then** no data is cleared and the response is rejected.
3. **Given** a caller sends the required confirmation, **When** the API handles the request, **Then** the existing clear behavior remains available and the response includes the same kind of outcome summary as before.

---

### User Story 4 - Align DNS Privacy Posture (Priority: P2)

As an operator of a local measurement node, I need DNS-derived data handling to match the documented privacy intent as closely as a small stabilization pass allows, so the node can avoid storing client-identifying DNS fields for new ingested data when configured that way.

**Why this priority**: DNS-derived targets are useful, but client identifiers are sensitive and the current implementation contradicts the architecture's stated privacy direction.

**Independent Test**: Can be tested by running DNS ingestion persistence logic with privacy-protective configuration enabled and disabled, then verifying whether client-identifying fields are stored for newly processed records.

**Acceptance Scenarios**:

1. **Given** DNS privacy protection for client identifiers is enabled, **When** new DNS queries and DNS targets are persisted, **Then** client-identifying fields are omitted or stored as empty values while domain-to-target measurement behavior still works.
2. **Given** DNS privacy protection is explicitly disabled for a deployment that accepts the risk, **When** new DNS records are processed, **Then** current client field behavior can be preserved.
3. **Given** existing historical rows already contain client identifiers, **When** this stabilization pass is completed, **Then** documentation clearly states that this pass does not automatically scrub those rows.

### Edge Cases

- Existing deployments may already have items under `cyberWatch:targets`; the stabilization must avoid silently splitting producers and consumers across two defaults.
- External enrichment sources may be unavailable; tests should distinguish network/service outages from local startup/import regressions.
- CI may not have system measurement tools installed; default tests must not require them.
- Browser confirmation dialogs can be bypassed by direct HTTP calls; the guardrail must be enforced server-side.
- DNS source rows may omit client information already; privacy logic must treat missing client fields as normal.
- DNS privacy mode should not prevent target resolution, aggregation, or enqueueing unless the domain/IP data itself is invalid.
- Existing DNS tables may contain historical client identifiers; documentation must avoid implying that old data was cleaned.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The stabilization MUST make the enrichment scheduler module entrypoint start without undefined or stale symbol references for queue construction, current-time tracking, settings loading, and ASN expansion.
- **FR-002**: The stabilization MUST preserve the intended enrichment sequence: enrich unenriched measurement hops, attempt graph building when graph storage is available, and periodically run ASN expansion when enabled.
- **FR-003**: The stabilization MUST keep all target queue producers, consumers, and queue depth checks aligned to one canonical default Redis queue key.
- **FR-004**: The canonical default Redis queue key MUST be documented consistently across operator docs and code-facing examples.
- **FR-005**: The stabilization MUST include a minimal automated test scaffold that is discoverable by standard project test tooling.
- **FR-006**: The automated test baseline MUST cover the confirmed enrichment scheduler stale references, queue key default, destructive settings guard, and DNS client-identifier privacy behavior.
- **FR-007**: The stabilization MUST add lightweight repository CI that runs the minimal automated test baseline on proposed or pushed code changes.
- **FR-008**: The destructive settings operations MUST require explicit per-request confirmation enforced by the server before clearing measurement, DNS, graph, or all data.
- **FR-009**: The destructive settings operations MUST remain available to intentional operators after the required confirmation is provided.
- **FR-010**: The DNS privacy documentation MUST state the current posture, including the existence of client identifier fields in the schema and the behavior for existing historical rows.
- **FR-011**: The DNS collector path MUST provide a low-risk configuration option for new ingestion to avoid persisting client-identifying DNS fields.
- **FR-012**: The default automated test suite MUST not require live Redis, PostgreSQL, Neo4j, Pi-hole, traceroute, scamper, or internet access.
- **FR-013**: The stabilization MUST NOT implement the Spec Kit constitution, add new product features, or redesign the architecture.

### Key Entities *(include if feature involves data)*

- **Target Queue**: The shared measurement-task buffer used by DNS collection, manual enqueue, remeasurement, ASN expansion, health checks, and workers.
- **Enrichment Cycle**: One scheduler pass that enriches stored measurement data, attempts graph updates, and optionally expands interesting ASNs.
- **Destructive Data Operation**: A settings action that permanently clears measurement, DNS, graph, or combined project data.
- **DNS Query Record**: A persisted DNS observation containing domain, query metadata, timestamp, and currently optional client identifier fields.
- **DNS Target Record**: A persisted domain-to-IP target candidate with aggregation data and currently optional last-client metadata.
- **Automated Validation Baseline**: The minimal local and CI checks that prove the stabilization requirements remain intact.

## Acceptance Criteria

- **AC-001**: The enrichment scheduler entrypoint can be imported and exercised through a controlled startup path without `NameError` or `ImportError` caused by `Queue`, `datetime`, `get_enrichment_settings`, `AsnExpanderConfig`, or `expand_asns` references.
- **AC-002**: ASN expansion from the scheduler uses the repository's existing batch expansion behavior and the shared target queue interface.
- **AC-003**: Producers, consumers, health checks, and docs agree on one default Redis target queue key.
- **AC-004**: A standard local test command runs the stabilization tests without live external services.
- **AC-005**: CI runs the same stabilization baseline and fails if the tests fail.
- **AC-006**: Each destructive settings endpoint rejects missing or incorrect confirmation before data-clearing work begins.
- **AC-007**: Each destructive settings endpoint still succeeds with explicit valid confirmation and returns a clear result summary.
- **AC-008**: DNS privacy mode for new ingestion can be verified to persist no client-identifying DNS fields while preserving DNS-derived target creation.
- **AC-009**: Documentation clearly describes the DNS privacy limitation for existing stored rows and the configured behavior for new rows.
- **AC-010**: The resulting changes are limited to stabilization surfaces and do not include constitution work, new measurement features, or architecture redesign.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A maintainer can verify the stabilization baseline from a clean checkout with one local automated command in under 5 minutes, excluding dependency installation time.
- **SC-002**: 100% of confirmed stabilization concerns in the repository inspection findings are covered by either an automated check or an explicit documentation update.
- **SC-003**: The enrichment scheduler no longer fails immediately from stale local references during controlled validation.
- **SC-004**: 100% of destructive settings requests without valid confirmation are rejected before any clear operation runs.
- **SC-005**: With DNS client-identifier privacy enabled, 100% of newly persisted DNS query and target records omit client-identifying values.
- **SC-006**: CI provides a visible pass/fail result for the stabilization baseline on relevant pushed or proposed code changes in under 10 minutes for the expected repository size.

## Risks

- A deployment may already use the mixed-case Redis key; changing the default without an operator note could strand existing queued items.
- Tests that mock too much of the enrichment scheduler could miss real startup sequencing issues.
- A minimal destructive-operation guard reduces accidental clears but does not replace authentication, authorization, CSRF protection, or network isolation.
- DNS analytics or UI fields that currently display client identifiers may need graceful empty-state behavior when privacy mode omits those values.
- CI dependency installation may expose packaging issues that were hidden by manual local execution.
- Existing documentation may overstate completed privacy hardening; this pass must keep current-state claims honest.

## Assumptions

- The active repository branch is `chore/init-spec-kit`.
- No existing `specs/` directory or current `plan.md` was present at the time this specification was created.
- The placeholder constitution in `.specify/memory/constitution.md` has not been adopted as project governance.
- The lower-case Redis key `cyberwatch:targets` is the preferred canonical default because it is already shown in architecture and README operator examples.
- The lowest-risk DNS privacy improvement is to suppress client-identifying fields for new ingestion through configuration while leaving existing nullable schema columns in place.
- Live service integration tests may be added later, but the first stabilization baseline should run without live infrastructure.

## Files Likely Involved

- `cyberWatch/enrichment/run_enrichment.py`
- `cyberWatch/enrichment/asn_expander.py`
- `cyberWatch/scheduler/queue.py`
- `cyberWatch/workers/worker.py`
- `cyberWatch/scheduler/remeasure.py`
- `cyberWatch/collector/dns_collector.py`
- `cyberWatch/collector/config.py`
- `cyberWatch/db/pg_dns.py`
- `cyberWatch/db/dns_schema.sql`
- `cyberWatch/api/routes/settings.py`
- `cyberWatch/api/routes/health.py`
- `cyberWatch/api/routes/targets.py`
- `cyberWatch/ui/templates/settings.html`
- `cyberWatch/requirements.txt` or a dedicated development/test requirements file
- `.github/workflows/ci.yml`
- `tests/`
- `README.md`
- `architecture.md`
- `docs/dns_integration.md`

## Validation Expectations

- Local automated tests should cover the enrichment scheduler startup/import contract, queue key default consistency, destructive settings guard behavior, and DNS client-identifier privacy behavior.
- The default local test suite should run without Redis, PostgreSQL, Neo4j, Pi-hole, traceroute, scamper, or internet access by using focused unit tests and mocks where needed.
- CI should install the project test dependencies, run the same default test command, and avoid heavyweight integration services.
- Documentation review should confirm that queue key examples and DNS privacy statements match the stabilized behavior.
- Optional manual smoke validation, when services are available, should confirm that a target enqueued by one producer is visible to worker/health queue consumers, and that destructive endpoints reject direct calls without confirmation.

