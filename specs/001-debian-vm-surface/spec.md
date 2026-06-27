# Feature Specification: Debian 13 VM Development and Test Surface

**Feature Branch**: `001-debian-vm-surface`

**Created**: 2026-06-27

**Status**: Draft

**Input**: User description: "Create a specification for the cyberWatch Debian 13 VM development and test surface. This is not a product feature. It defines the repeatable environment where Codex develops and validates cyberWatch."

## cyberWatch Alignment *(mandatory)*

**Pipeline Stages Affected**: DNS collector, Redis target queue, measurement workers, PostgreSQL, enrichment, Neo4j graph, API, UI, Grafana-facing data, installer, uninstall workflow, and systemd lifecycle.

**Data Flow**: The surface validates the existing cyberWatch pipeline from a disposable VM: repository checkout and install produce services; services publish logs and health state; smoke checks submit or inspect controlled data; validation confirms queue keys, database access, graph service readiness, and guardrail behavior without introducing product-facing workflow changes.

**Operational Surface**: Debian 13 VM snapshots, Codex CLI authentication, `install-cyberWatch.sh`, `uninstall-cyberWatch.sh`, `systemd/` units, `/etc/cyberwatch/` configuration, service journals, smoke commands, unit tests, Redis queue inspection, API/UI bind configuration, and script/unit line-ending checks.

**DNS Privacy Impact**: DNS data may be exercised only with controlled smoke data. Client-identifying DNS fields must not be retained by default. Any smoke fixture that includes client identifiers must be opt-in, clearly marked, and removed during uninstall or reset validation.

**Safety Impact**: The surface explicitly validates guarded lifecycle and destructive paths. Destructive settings endpoints must be disabled by default, privileged lifecycle commands may run only inside the disposable VM, and install/uninstall/reinstall checks must not touch non-cyberWatch host data.

**Runtime Policy Location**: VM behavior is controlled by repository scripts, systemd units, `/etc/cyberwatch/` environment/config files, documented smoke commands, and the database settings table. Hardcoded runtime policy is out of scope except where it is a safe default under test.

**Default Test Scope**: Pure unit tests run separately from live integration smoke checks. Unit tests must not require PostgreSQL, Redis, Neo4j, internet access, traceroute/scamper, Pi-hole, root privileges, or systemd. VM smoke checks may require those dependencies and must state that explicitly.

**Architecture Impact**: Uses the existing cyberWatch stack and dedicated Debian 13 VM lifecycle. No new framework, queue, database, service manager, or deployment platform is introduced by this specification.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prepare Disposable VM Surface (Priority: P1)

A maintainer or Codex operator needs a snapshot-backed Debian 13 VM where cyberWatch can be installed from the repository, validated, broken safely, uninstalled, and restored without risking non-cyberWatch host data.

**Why this priority**: This is the foundation for all Codex lifecycle work. Without a known disposable surface, privileged install and service commands are unsafe and results are not reproducible.

**Independent Test**: Starting from a clean Debian 13 VM snapshot, the operator can authenticate Codex, run the installer from the repository, observe installed services and configuration, and restore or reinstall without manual cleanup outside cyberWatch-owned paths.

**Acceptance Scenarios**:

1. **Given** a clean Debian 13 VM snapshot with the repository checked out, **When** the operator runs the documented install workflow, **Then** cyberWatch installs without manual edits outside declared cyberWatch paths.
2. **Given** cyberWatch is installed in the VM, **When** the operator runs the documented uninstall workflow without purge-level destructive opt-ins, **Then** cyberWatch services and cyberWatch-owned runtime files are removed or disabled while unrelated host data remains untouched.
3. **Given** the VM has been changed by a failed install or test, **When** the operator restores the pre-test snapshot, **Then** the VM returns to a known baseline suitable for a repeatable install attempt.

---

### User Story 2 - Validate Runtime Services and Logs (Priority: P1)

A maintainer or Codex operator needs repeatable smoke checks proving that the installed cyberWatch services start under systemd, expose health information, use the expected queue key, and produce useful failure diagnostics.

**Why this priority**: cyberWatch is operated as a service pipeline. The VM surface must catch failures that pure unit tests cannot see: service dependencies, journals, ports, queue naming, and lifecycle crashes.

**Independent Test**: After installation, the operator runs the smoke checklist and receives pass/fail evidence for service status, API root, health, enrichment import/start behavior, queue-key state, and journal diagnostics.

**Acceptance Scenarios**:

1. **Given** cyberWatch has been installed, **When** the operator checks the service set, **Then** PostgreSQL, Redis, Neo4j, API, UI, workers, enrichment, DNS collector, and remeasurement services are present with expected enabled/running or intentionally disabled states documented.
2. **Given** API and UI services are installed, **When** the operator runs root and health checks against their configured bind addresses, **Then** API root and health respond and the UI bind behavior is explicit.
3. **Given** a service fails to start, **When** the operator runs the documented journal commands, **Then** the output includes enough failure information to identify the service, command, exit status or exception, and relevant dependency.
4. **Given** Redis is available, **When** the operator inspects queue keys, **Then** `cyberwatch:targets` is the accepted queue key and any old mixed-case queue key is detected, reported, and covered by migration guidance.

---

### User Story 3 - Enforce Safety and Test Separation (Priority: P2)

A maintainer needs the VM surface to verify that dangerous API paths remain blocked by default and that pure unit tests stay separate from live integration smoke checks.

**Why this priority**: The VM is allowed to run privileged commands, but cyberWatch history and host safety still depend on explicit guardrails and clear test boundaries.

**Independent Test**: The operator can run a default test command that does not depend on live services, then run VM-only smoke checks that verify destructive endpoint refusal, install/uninstall safety, line endings, and service lifecycle.

**Acceptance Scenarios**:

1. **Given** cyberWatch is installed with default settings, **When** the operator calls `/settings/clear-dns`, **Then** the API returns HTTP 403 and no DNS tables are cleared.
2. **Given** the repository is checked out in the VM, **When** the operator runs the default unit test command, **Then** tests complete without requiring live databases, Redis, Neo4j, Pi-hole, network probing, root, or systemd.
3. **Given** scripts and systemd units are present, **When** the operator runs the line-ending smoke check, **Then** shell scripts and unit files are reported as LF-only and executable files are not blocked by CRLF.
4. **Given** reinstall validation is requested, **When** the operator runs install, uninstall, and reinstall checks, **Then** only cyberWatch-owned services, queues, databases, graph state, logs, virtualenv, and `/etc/cyberwatch/` configuration are affected.

### Edge Cases

- The VM has no usable snapshot before a privileged lifecycle run; the workflow must stop and require snapshot confirmation.
- Codex CLI is installed but not authenticated; the workflow must report that privileged automation cannot proceed.
- API or UI binds to `0.0.0.0`; the smoke result must explicitly call out external exposure rather than assuming localhost-only access.
- The old mixed-case Redis queue key exists with entries while the lowercase key is empty; the smoke result must flag potential stranded work and document the migration decision.
- A destructive settings endpoint returns success under default settings; the smoke result must fail and identify the endpoint as a guardrail regression.
- Installer or uninstall commands encounter CRLF scripts or malformed systemd units; the smoke result must identify the affected file before lifecycle commands continue.
- Neo4j is installed but unavailable or unauthenticated; enrichment and graph smoke checks must distinguish graph dependency failure from a crash in the enrichment service itself.
- Uninstall is run with purge-like options; the workflow must require explicit acknowledgement and must still confine deletion to cyberWatch-owned data and declared packages.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The VM surface MUST require a disposable, snapshot-backed Debian 13 VM before Codex runs privileged install, uninstall, restart, or service-management commands.
- **FR-002**: The VM surface MUST require Codex CLI to be installed and authenticated inside the VM before Codex performs lifecycle validation.
- **FR-003**: The VM surface MUST install cyberWatch from the repository under test and must not depend on unpublished manual edits.
- **FR-004**: The VM surface MUST validate that `install-cyberWatch.sh` completes on Debian 13 or returns actionable failure output.
- **FR-005**: The VM surface MUST validate systemd service presence and startup behavior for API, UI, worker instances, enrichment, DNS collector, and remeasurement, plus required PostgreSQL, Redis, and Neo4j dependencies.
- **FR-006**: The VM surface MUST validate that API root and health endpoints respond after installation.
- **FR-007**: The VM surface MUST make API and UI bind addresses explicit in smoke output, including whether they bind to localhost or all interfaces.
- **FR-008**: The VM surface MUST keep destructive settings endpoints disabled by default and MUST verify `/settings/clear-dns` returns HTTP 403 under default configuration.
- **FR-009**: The VM surface MUST separate pure unit tests from live integration smoke checks.
- **FR-010**: The default unit test command MUST be `python -m pytest` and MUST pass without live PostgreSQL, Redis, Neo4j, internet access, traceroute/scamper, Pi-hole, root privileges, or systemd.
- **FR-011**: Live smoke checks MUST be documented as VM-only checks and MUST include clear prerequisites before using PostgreSQL, Redis, Neo4j, traceroute/scamper, Pi-hole, root, or systemd.
- **FR-012**: The VM surface MUST validate that `cyberWatch.enrichment.run_enrichment` can be imported and that the enrichment service does not crash immediately on startup.
- **FR-013**: The VM surface MUST validate that the canonical Redis queue key is `cyberwatch:targets`.
- **FR-014**: The VM surface MUST detect and document any old mixed-case Redis queue key so queued work is not silently stranded.
- **FR-015**: The VM surface MUST provide log inspection commands that expose useful failure information for all cyberWatch services and worker instances.
- **FR-016**: The VM surface MUST validate CRLF/LF protection for shell scripts and systemd units before lifecycle commands are trusted.
- **FR-017**: The VM surface MUST validate install, uninstall, and reinstall behavior without touching non-cyberWatch host data.
- **FR-018**: The VM surface MUST document which paths, services, packages, databases, queues, logs, and configuration files are considered cyberWatch-owned during cleanup.
- **FR-019**: The VM surface MUST include snapshot expectations: when to create snapshots, when to restore, and what state each snapshot represents.
- **FR-020**: The VM surface MUST record smoke-check outcomes in a form that is reviewable in the repository or attached to the relevant development task.
- **FR-021**: The VM surface MUST fail validation when a lifecycle command requires an undocumented manual step.
- **FR-022**: The VM surface MUST fail validation when any destructive command succeeds without an explicit opt-in.
- **FR-023**: The VM surface MUST include a smoke command catalog covering install, uninstall, reinstall, service status, API root, health, destructive endpoint refusal, pure tests, enrichment import/start, Redis queue key inspection, journal inspection, bind exposure, and line-ending validation.

### Required Smoke Command Coverage

The smoke command catalog MUST include commands or documented equivalents for:

- Installing cyberWatch from the repository with `install-cyberWatch.sh`.
- Uninstalling cyberWatch with default non-purge behavior and reinstalling from the same checkout.
- Inspecting PostgreSQL, Redis, Neo4j, API, UI, workers, enrichment, DNS collector, and remeasurement service status under systemd.
- Calling API root and health through the configured API bind address.
- Calling `/settings/clear-dns` and verifying HTTP 403 by default.
- Running `python -m pytest` as the default pure test command.
- Importing `cyberWatch.enrichment.run_enrichment` and checking enrichment service startup does not crash immediately.
- Inspecting Redis for canonical `cyberwatch:targets` and legacy `cyberWatch:targets` queue state.
- Inspecting service journals for API, UI, workers, enrichment, DNS collector, and remeasurement.
- Reporting API/UI bind addresses and whether they expose all interfaces or localhost only.
- Detecting CRLF line endings in shell scripts and systemd unit files before lifecycle commands proceed.

### Key Entities *(include if feature involves data)*

- **VM Surface**: The disposable Debian 13 environment where Codex and maintainers run privileged lifecycle, install, uninstall, and smoke validation commands.
- **Snapshot Baseline**: A named VM state used to return the environment to a known point before or after lifecycle validation.
- **Lifecycle Workflow**: The ordered install, service validation, uninstall, reinstall, and restore activities that prove cyberWatch can be reproduced from the repository.
- **Service Set**: The expected cyberWatch systemd services and dependencies involved in a full deployment smoke check.
- **Smoke Check**: A documented VM-only validation command or group of commands with prerequisites, expected output, and failure interpretation.
- **Guardrail Check**: A validation that confirms destructive API or lifecycle behavior is disabled by default and requires explicit opt-in.
- **Queue Key Check**: A validation that confirms the lowercase Redis queue key is canonical and flags old mixed-case queue state.
- **Line Ending Check**: A validation that scripts and unit files use LF endings and are safe for Debian/systemd execution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A clean snapshot-backed VM can complete the documented install workflow and reach service validation without undocumented manual edits.
- **SC-002**: The smoke checklist verifies all required cyberWatch services and dependencies, with every service either running or explicitly documented as intentionally inactive.
- **SC-003**: API root and health checks return successful responses during smoke validation.
- **SC-004**: A default request to `/settings/clear-dns` returns HTTP 403 and leaves DNS data unchanged.
- **SC-005**: `python -m pytest` completes successfully as the default pure unit test command without relying on live infrastructure.
- **SC-006**: Enrichment import/start validation distinguishes immediate service crash from external dependency unavailability.
- **SC-007**: Redis queue validation reports `cyberwatch:targets` as canonical and detects any old mixed-case queue key with clear migration guidance.
- **SC-008**: Journal inspection commands for each cyberWatch service expose service name, recent failure lines, exit status or exception text, and dependency hints when failures occur.
- **SC-009**: Line-ending validation reports zero CRLF shell scripts or systemd unit files before lifecycle commands are accepted.
- **SC-010**: Uninstall and reinstall validation affects only declared cyberWatch-owned resources unless an explicit destructive opt-in is provided.

## Assumptions

- The Debian 13 VM is dedicated to cyberWatch development and deployment smoke validation, not shared production infrastructure.
- Snapshot creation and restore are provided by the VM host or hypervisor and are outside cyberWatch code, but their required states are documented by this feature.
- Codex may request or run privileged lifecycle commands only inside this VM and only for cyberWatch-owned resources.
- Smoke checks may use localhost services and controlled test data; they do not require real Pi-hole client traffic.
- The default secure behavior for destructive settings endpoints is refusal with HTTP 403 until an explicit opt-in mechanism is enabled.
- The canonical Redis queue key is lowercase `cyberwatch:targets`; old mixed-case `cyberWatch:targets` state is legacy and must be detected.
- API/UI bind exposure is allowed only when explicitly documented in the smoke output and operator guidance.
