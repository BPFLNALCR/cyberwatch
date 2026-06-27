# Implementation Plan: Debian 13 VM Development and Test Surface

**Branch**: `not-created-by-hook` | **Date**: 2026-06-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-debian-vm-surface/spec.md`

## Summary

Define a repeatable, snapshot-backed Debian 13 VM validation surface where Codex
and maintainers can safely install, uninstall, reinstall, and smoke-test
cyberWatch. The work is not a product feature; it is an operational contract for
how privileged lifecycle validation is performed and recorded. The plan keeps
the existing stack, separates offline unit tests from VM-only smoke checks, and
turns known repo gaps into explicit implementation targets.

## Technical Context

**Language/Version**: Python 3.x on Debian 13; shell scripts and systemd unit
templates are validation surfaces.

**Primary Dependencies**: Existing cyberWatch dependencies only: FastAPI,
asyncpg, Redis client, Neo4j driver, Pydantic, pytest, systemd, PostgreSQL,
Redis, Neo4j, traceroute/scamper, curl, jq, and Codex CLI inside the VM.

**Storage**: PostgreSQL for cyberWatch measurement/settings/DNS tables, Redis
for the target queue, Neo4j for AS graph state, repository artifacts for smoke
catalogs and validation evidence.

**Testing**: `python -m pytest` for default pure/offline tests; Debian 13 VM
smoke commands for live PostgreSQL, Redis, Neo4j, traceroute/scamper, Pi-hole
configuration, root, and systemd behavior.

**Target Platform**: Dedicated disposable Debian 13 VM with systemd and a
snapshot/restore mechanism supplied by the VM host.

**Project Type**: Multi-service internet measurement pipeline plus operational
validation surface.

**Performance Goals**: Smoke checks complete fast enough for iterative Codex
validation, expose service failures within one command pass, and do not increase
measurement rate or worker concurrency beyond configured policy.

**Constraints**: Privileged lifecycle commands run only inside the dedicated VM;
destructive behavior is disabled by default; uninstall/reinstall touches only
declared cyberWatch-owned resources; scripts and units must be LF-safe.

**Scale/Scope**: One authoritative cyberWatch VM surface, expected service set
of PostgreSQL, Redis, Neo4j, API, UI, workers, enrichment, DNS collector, and
remeasurement.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Pipeline Integrity**: PASS. The plan validates the existing pipeline stages
  without adding bypass paths: DNS collector, Redis queue, workers, PostgreSQL,
  enrichment, Neo4j, API/UI, and Grafana-facing data.
- **Debian/Systemd Realism**: PASS. The feature is explicitly about Debian 13,
  systemd lifecycle, installer/uninstaller behavior, journals, and VM snapshots.
- **Diagnosability**: PASS. Smoke commands must expose journal output, HTTP
  responses, service state, queue state, and actionable failure information.
- **Safe Operations**: PASS. Destructive endpoints and lifecycle cleanup must be
  disabled by default or require explicit opt-in; guardrail checks are core
  acceptance criteria.
- **DNS Privacy**: PASS. Smoke data must be controlled, client-identifying DNS
  fields are not retained by default, and any opt-in fixture must be documented
  and removable.
- **Test-First Stabilization**: PASS. The plan separates pure pytest coverage
  from live VM smoke checks and requires guardrail/unit coverage for pure logic.
- **Mechanism Versus Policy**: PASS. Runtime behavior stays in scripts,
  environment/config files, systemd units, or settings-table policy.
- **Minimal Architecture**: PASS. No new framework, queue, database, service
  manager, or broad rewrite is introduced.
- **VM-Controlled Lifecycle**: PASS. The VM is the authoritative smoke surface,
  while all validation rules remain reviewable in repository artifacts.

## Project Structure

### Documentation (this feature)

```text
specs/001-debian-vm-surface/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── smoke-command-catalog.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
install-cyberWatch.sh        # Installer lifecycle surface
uninstall-cyberWatch.sh      # Uninstall/reinstall lifecycle surface
systemd/                     # Service unit templates
cyberWatch/api/              # API root, health, settings guardrails
cyberWatch/scheduler/        # Redis target queue key behavior
cyberWatch/enrichment/       # Enrichment import/start behavior
cyberWatch/collector/        # DNS collector service and privacy behavior
cyberWatch/workers/          # Worker service and traceroute lifecycle
cyberWatch/db/               # PostgreSQL, DNS schema, settings tables
tests/                       # Offline unit tests to be created/extended
docs/ or scripts/            # Future location for VM smoke command catalog
```

**Structure Decision**: Keep planning artifacts under
`specs/001-debian-vm-surface/`. Later implementation should add the actual
smoke catalog/script and tests in repo-native locations selected by tasks, while
preserving existing installer, systemd, and Python service boundaries.

## Complexity Tracking

No constitution violations are required. Current repo gaps are implementation
targets, not approved exceptions:

| Gap | Required Resolution | Simpler Alternative Rejected Because |
|-----|---------------------|--------------------------------------|
| Redis queue key currently has mixed references | Make lowercase `cyberwatch:targets` canonical and detect legacy `cyberWatch:targets` | Ignoring legacy state can strand queued work |
| Destructive settings endpoints currently need default refusal | Add default-disabled guardrails and tests for refusal paths | UI confirmation alone does not protect direct API calls |
| Enrichment runner startup has immediate-crash risk | Add import/start smoke coverage and fix startup defects in implementation | Treating service crash as dependency failure hides real regressions |

## Phase 0 Research Summary

Research decisions are captured in [research.md](./research.md). No unresolved
clarification markers remain.

## Phase 1 Design Summary

Design artifacts:

- [data-model.md](./data-model.md)
- [contracts/smoke-command-catalog.md](./contracts/smoke-command-catalog.md)
- [quickstart.md](./quickstart.md)

## Post-Design Constitution Check

- **Pipeline Integrity**: PASS. The smoke catalog validates existing stages and
  contracts; it does not create alternate data flow.
- **Debian/Systemd Realism**: PASS. Quickstart and contracts center on Debian
  13, systemd, installer/uninstaller, journals, and snapshots.
- **Diagnosability**: PASS. Journal and structured failure evidence are
  required outputs.
- **Safe Operations**: PASS. Guardrail checks require default 403 behavior for
  destructive endpoints and constrained cleanup ownership.
- **DNS Privacy**: PASS. Controlled DNS smoke data and client identifier
  minimization remain explicit.
- **Test-First Stabilization**: PASS. Data model and contract separate offline
  unit tests from live smoke checks.
- **Mechanism Versus Policy**: PASS. Runtime policy remains in config/env/
  settings and documented operator commands.
- **Minimal Architecture**: PASS. Design uses repository docs/scripts/tests
  without new infrastructure.
- **VM-Controlled Lifecycle**: PASS. Snapshot-backed VM smoke validation is the
  authoritative lifecycle surface.
