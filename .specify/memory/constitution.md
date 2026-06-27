<!--
Sync Impact Report
Version change: unratified template -> 1.0.0
Modified principles:
- Template placeholders -> I. Pipeline Integrity
- Template placeholders -> II. Debian/Systemd Realism
- Template placeholders -> III. Diagnosability
- Template placeholders -> IV. Safe Operations
- Template placeholders -> V. DNS Privacy
- Template placeholders -> VI. Test-First Stabilization
- Template placeholders -> VII. Mechanism Versus Policy
- Template placeholders -> VIII. Minimal Architecture
- Template placeholders -> IX. VM-Controlled Lifecycle
Added sections:
- Operational Requirements
- Review Gates
- Testing Requirements
- Operational Safety Requirements
Removed sections:
- Placeholder template guidance
Templates requiring updates:
- .specify/templates/plan-template.md - updated
- .specify/templates/spec-template.md - updated
- .specify/templates/tasks-template.md - updated
- .specify/templates/commands/*.md - not present in this Spec Kit install
Follow-up TODOs: None
-->
# cyberWatch Constitution

## Core Principles

### I. Pipeline Integrity
cyberWatch is a measurement pipeline: DNS collector -> Redis target queue ->
measurement workers -> PostgreSQL -> enrichment -> Neo4j graph ->
API/UI/Grafana. Changes MUST preserve component ownership and explicit data
flow. DNS collectors emit targets, workers run probes and persist raw
measurements, enrichment adds ASN and metadata, graph builders project enriched
observations, and API/UI/Grafana expose data. A change that bypasses, duplicates,
or hides a stage MUST include a written spec explaining why the existing boundary
is insufficient.

Rationale: cyberWatch's value is a traceable history of measurements from one
vantage point. Hidden coupling or cross-stage writes make path history, graph
state, and operational debugging unreliable.

### II. Debian/Systemd Realism
The primary deployment target is the dedicated Debian 13 VM running systemd
services. Installer behavior, unit files, environment files under
`/etc/cyberwatch/`, restart policies, service dependencies, and `journalctl`
diagnostics are first-class project surfaces. Any feature that changes runtime
startup, shutdown, logging paths, credentials, service dependencies, worker
scaling, or ports MUST update the installer, `systemd/` units, and operator
documentation together.

Rationale: cyberWatch is operated as a VM service stack, not just as importable
Python modules. A change is incomplete if it works only in an ad hoc shell.

### III. Diagnosability
Every long-running service MUST emit structured, actionable JSONL logs through
the shared logging configuration or an equivalent compatible path. Operational
logs MUST include enough context to answer what happened, where it happened, and
whether it succeeded: `component`, `action`, `outcome`, relevant IDs, counts,
durations, and explicit error details. Failures MUST be observable and testable;
silent broad exception handling is only acceptable when the fallback is logged
with a specific reason.

Rationale: the pipeline spans active probing, external metadata sources,
databases, and graph projection. Operators need request IDs, task IDs, counts,
and outcomes to diagnose failures from logs and journals without attaching a
debugger.

### IV. Safe Operations
Destructive operations MUST be gated, disabled by default, explicit, logged, and
documented. Clearing PostgreSQL tables, deleting Neo4j data, purging DNS-derived
records, resetting credentials, stopping services, or reinitializing state MUST
require an intentional operator action and MUST report what will be affected.
Automated and non-interactive paths MUST default to preserving data unless an
explicit environment variable, API field, CLI flag, or documented prompt opts in.

Rationale: cyberWatch stores historical measurements, DNS-derived targets, and
graph state. Convenience resets are acceptable only when the blast radius is
clear and reviewable.

### V. DNS Privacy
DNS-derived data MUST minimize client-identifying fields. Domain, qtype, IP
target, timestamps, and aggregate counts are valid measurement inputs; client IPs
or other client identifiers MUST NOT be stored, logged, indexed, or surfaced
unless retention is opt-in, documented, and covered by a specific review gate.
Features touching Pi-hole ingestion, log tailing, DNS schemas, DNS analytics, or
target enqueueing MUST state how client-identifying data is removed, ignored,
aggregated, hashed, or intentionally retained.

Rationale: DNS activity can reveal local user behavior. The measurement value is
in destination selection and aggregate topology, not in identifying the local
client that caused a lookup.

### VI. Test-First Stabilization
Pure logic MUST have automated unit tests before or with the implementation.
Parsing, filtering, settings defaults, redaction, rate limiting, graph edge
construction, API serialization, and safety guards are pure logic unless a spec
proves otherwise. Default test commands MUST NOT require live PostgreSQL, Redis,
Neo4j, internet access, traceroute/scamper, Pi-hole, root privileges, or systemd.
Live integration checks belong in documented smoke scripts or quickstarts that
are explicit about VM prerequisites.

Rationale: cyberWatch depends on external services that are expensive and noisy
to require for every change. Keeping pure behavior under fast tests lets the VM
smoke surface validate deployment without replacing unit coverage.

### VII. Mechanism Versus Policy
Code MUST provide mechanisms; runtime policy MUST live in config files,
environment variables, or the PostgreSQL `settings` table. Rate limits,
concurrency, DNS filters, source selection, polling intervals, retention
behavior, log levels, service credentials, and feature toggles MUST NOT be
hardcoded when they are operator policy. Defaults MUST be conservative and
documented where the operator will actually configure them.

Rationale: cyberWatch runs in different networks and measurement budgets. The
same code must support cautious home deployments and broader lab runs without
forking behavior.

### VIII. Minimal Architecture
The existing stack is Python async services, FastAPI, Redis, PostgreSQL, Neo4j,
Grafana, Debian packaging assumptions, and systemd lifecycle. New frameworks,
queues, databases, service managers, broad rewrites, or alternate deployment
models MUST NOT be added without a written spec, a measured need, and a simpler
alternative considered and rejected. Refactors MUST preserve current behavior
unless the spec explicitly changes it.

Rationale: the project is already a multi-service measurement system. Extra
architecture has real operator cost and can obscure the pipeline.

### IX. VM-Controlled Lifecycle
The dedicated Debian 13 cyberWatch VM is the authoritative development and
deployment smoke surface. Codex may run installer, systemd, service restart,
journal, queue-depth, API health, and smoke-check commands on that VM when those
commands are relevant to the change. VM state MUST NOT replace reviewable repo
changes: lifecycle changes must be reproducible from committed scripts,
configuration, docs, or Spec Kit artifacts.

Rationale: cyberWatch's failure modes are often operational. The VM catches real
systemd, package, service, and network assumptions while Git history preserves
how to reproduce them.

## Operational Requirements

- Pipeline changes MUST name the affected stages and data contracts:
  DNS collector, Redis target queue, workers, PostgreSQL, enrichment, Neo4j,
  API/UI, and Grafana.
- Service changes MUST include Debian/systemd impact: unit dependencies,
  `EnvironmentFile`, restart behavior, log destinations, ports, and operator
  diagnostics.
- Runtime policy MUST be expressed through `config/`, `/etc/cyberwatch/`,
  environment variables, or the `settings` table rather than embedded constants.
- DNS ingestion changes MUST document privacy behavior for domains, targets,
  query metadata, and client identifiers.
- Destructive or state-resetting behavior MUST include confirmation, audit logs,
  pre-action counts where practical, and documented recovery or rollback limits.
- Operator-facing docs MUST remain consistent with the installer, unit files,
  and the actual Python entry points.

## Review Gates

Every feature plan and implementation review MUST answer these gates:

- Pipeline Gate: Which pipeline stage owns the change, and does data still flow
  explicitly to the next stage?
- Operations Gate: Are installer, systemd units, environment files, logs,
  restart behavior, and `journalctl` diagnostics updated if runtime behavior
  changed?
- Diagnosability Gate: Are success, failure, counts, durations, and IDs visible
  in structured logs or API responses?
- Safety Gate: Can any path delete, truncate, reset, reconfigure, or restart
  service state, and is that path opt-in, documented, and logged?
- DNS Privacy Gate: Does the change avoid client-identifying DNS data by
  default, or does it document an opt-in retention reason?
- Testing Gate: Are pure logic tests added, and are live dependencies kept out
  of default tests?
- Policy Gate: Are operator choices in config, environment variables, or the
  `settings` table instead of hardcoded policy?
- Architecture Gate: Does the change stay within the existing stack, or does a
  spec justify new infrastructure with measured need?
- VM Gate: Is there a reproducible Debian 13 VM smoke path for lifecycle or
  deployment changes?

Unresolved gate failures block implementation unless a written spec records the
exception and the project owner accepts the risk.

## Testing Requirements

- Unit tests are required for pure logic, regressions, parsers, filters,
  serializers, redaction, rate limiting, graph edge construction, settings
  defaulting, and safety guards.
- Default automated tests MUST run without PostgreSQL, Redis, Neo4j, internet
  access, traceroute/scamper, Pi-hole, root privileges, or systemd.
- API and database behavior that cannot be isolated MUST be covered by
  documented smoke checks with explicit VM prerequisites and expected outcomes.
- Bug fixes MUST include a failing test or a documented smoke reproduction
  before the fix is considered complete.
- Logging changes MUST verify structured fields and sensitive-data redaction.
- Destructive-operation changes MUST test the guard condition and the refusal
  path, not only the successful deletion path.

## Operational Safety Requirements

- Installer and lifecycle scripts MUST be idempotent where practical and MUST
  prompt or require explicit flags before applying schemas, resetting
  credentials, deleting graph data, or changing persisted configuration.
- API/UI destructive actions MUST require an explicit user action, return counts
  of affected data where practical, and emit structured audit logs.
- Secrets and DSNs MUST be redacted from logs and documentation examples unless
  they are placeholders.
- Service restarts MUST be intentional and visible through systemd status or
  journal output.
- Any change to DNS retention, measurement rate, probe concurrency, enrichment
  source usage, or remeasurement frequency MUST document the operational and
  privacy impact.

## Governance

This constitution supersedes conflicting local practice, generated templates,
and ad hoc implementation preferences. Spec Kit plans, task lists, reviews, and
Codex work for cyberWatch MUST apply these principles before implementation.

Amendments MUST be made through an explicit constitution update, include a Sync
Impact Report, and update dependent Spec Kit templates or operator guidance in
the same change when behavior changes. Principle removals or redefinitions
require a MAJOR version bump. New principles or materially expanded governance
require a MINOR version bump. Clarifications that do not change obligations
require a PATCH version bump.

Compliance review is required for every feature plan and for every change that
touches installer behavior, systemd units, DNS ingestion, data deletion, logging,
settings, measurement execution, enrichment, graph projection, or API/UI
operational controls. A review may waive a gate only by recording the reason,
scope, and follow-up action in the plan or task list.

**Version**: 1.0.0 | **Ratified**: 2026-06-27 | **Last Amended**: 2026-06-27
