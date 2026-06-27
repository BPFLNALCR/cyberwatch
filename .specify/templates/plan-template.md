# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.x on the dedicated Debian 13 cyberWatch VM or NEEDS CLARIFICATION

**Primary Dependencies**: FastAPI, asyncpg, Redis client, Neo4j driver, Pydantic, systemd units, traceroute/scamper, or NEEDS CLARIFICATION

**Storage**: PostgreSQL for measurements/settings/DNS records, Redis for the target queue, Neo4j for AS graph state, or N/A

**Testing**: Unit tests for pure logic; documented VM smoke scripts for live PostgreSQL/Redis/Neo4j/traceroute/Pi-hole/systemd checks

**Target Platform**: Debian 13 VM with systemd-managed cyberWatch services

**Project Type**: Multi-service internet measurement pipeline

**Performance Goals**: Preserve configured measurement rate limits, bounded worker concurrency, responsive API/UI queries, and operator-visible progress

**Constraints**: Default tests avoid live infrastructure; DNS privacy is default; destructive operations are opt-in; runtime policy stays in config/env/settings

**Scale/Scope**: Single cyberWatch vantage-point VM, 2-4+ worker instances, local Redis/PostgreSQL/Neo4j, API/UI/Grafana consumers, or NEEDS CLARIFICATION

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Record PASS/FAIL/WAIVED for each gate. Any FAIL blocks implementation unless
the plan records a specific exception and accepted risk.

- **Pipeline Integrity**: Identify affected stages among DNS collector, Redis
  target queue, measurement workers, PostgreSQL, enrichment, Neo4j graph,
  API/UI, and Grafana. Data flow remains explicit.
- **Debian/Systemd Realism**: Installer, `systemd/` units, environment files,
  restart behavior, ports, and `journalctl` diagnostics are updated when runtime
  behavior changes.
- **Diagnosability**: Structured logs expose component, action, outcome, IDs,
  counts, durations, and explicit errors for the new behavior.
- **Safe Operations**: Any delete/truncate/reset/restart/reconfigure path is
  gated, opt-in, documented, and logged with affected counts where practical.
- **DNS Privacy**: DNS-derived client identifiers are avoided by default; any
  retention is opt-in and documented.
- **Test-First Stabilization**: Pure logic has unit tests; default tests do not
  require PostgreSQL, Redis, Neo4j, internet, traceroute/scamper, Pi-hole, root,
  or systemd.
- **Mechanism Versus Policy**: Operator choices live in config, environment
  variables, or the `settings` table rather than hardcoded policy.
- **Minimal Architecture**: No new frameworks, queues, databases, service
  managers, or broad rewrites without measured need and a written spec.
- **VM-Controlled Lifecycle**: Deployment/lifecycle changes include a
  reproducible Debian 13 VM smoke path.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
cyberWatch/
├── api/                 # FastAPI server and routes
├── collector/           # DNS ingestion and target enqueueing
├── workers/             # Measurement worker loop and parsing
├── enrichment/          # ASN lookup, metadata merge, graph projection
├── scheduler/           # Redis queue and remeasurement scheduling
├── db/                  # PostgreSQL/Neo4j access and schemas
└── ui/                  # Looking-glass UI

config/                  # Example operator configuration
systemd/                 # Debian/systemd unit templates
grafana/dashboards/      # PostgreSQL-backed dashboards
tests/                   # Create or extend for default offline tests
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
