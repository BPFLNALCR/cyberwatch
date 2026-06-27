# Tasks: Debian 13 VM Development and Test Surface

**Input**: Design documents from `specs/001-debian-vm-surface/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/smoke-command-catalog.md`, `quickstart.md`

**Tests**: Required for pure logic and guardrails. Default `python -m pytest` must avoid live PostgreSQL, Redis, Neo4j, internet access, traceroute/scamper, Pi-hole, root, and systemd. VM smoke checks are implemented as explicit live checks.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently after foundational work.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish test and smoke-surface locations without changing runtime behavior.

- [X] T001 Create `tests/unit/` package structure with `tests/__init__.py` and `tests/unit/__init__.py`
- [X] T002 Add `pytest` dependency to `cyberWatch/requirements.txt`
- [X] T003 [P] Create placeholder VM smoke script file `scripts/cyberwatch-vm-smoke.sh` with executable bash entrypoint and no live checks yet
- [X] T004 [P] Create operator documentation stub `docs/debian13-vm-surface.md` with links to `specs/001-debian-vm-surface/quickstart.md`
- [X] T005 [P] Create offline test file `tests/unit/test_vm_smoke_contract.py` for smoke catalog structure expectations

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared mechanisms required before any user story can be completed.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 Define stable smoke result status vocabulary and check ID list in `scripts/cyberwatch-vm-smoke.sh`
- [X] T007 Add offline tests for smoke check IDs and required categories in `tests/unit/test_vm_smoke_contract.py`
- [X] T008 Add line-ending scanner helper in `scripts/cyberwatch-vm-smoke.sh` covering `*.sh` and `systemd/*.service`
- [X] T009 Add offline line-ending fixture tests in `tests/unit/test_line_endings.py`
- [X] T010 Add destructive operation opt-in setting name and default-deny helper in `cyberWatch/api/routes/settings.py`
- [X] T011 Add offline guardrail tests for default destructive refusal in `tests/unit/test_settings_guardrails.py`
- [X] T012 Add Redis queue constants for canonical and legacy keys in `cyberWatch/scheduler/queue.py`
- [X] T013 Add offline queue-key tests in `tests/unit/test_queue_key.py`
- [X] T014 Add enrichment import smoke test in `tests/unit/test_run_enrichment_import.py`
- [X] T015 Update `.github/copilot-instructions.md` to state default tests are `python -m pytest` and live checks are VM-only

**Checkpoint**: Offline test scaffolding, guardrail helper, queue constants, and smoke script skeleton are ready.

---

## Phase 3: User Story 1 - Prepare Disposable VM Surface (Priority: P1)

**Goal**: A maintainer or Codex operator can confirm they are in a disposable Debian 13 VM, verify Codex readiness, run install/uninstall/reinstall checks, and avoid non-cyberWatch host data.

**Independent Test**: Starting from a clean VM snapshot, run the baseline and lifecycle portions of `scripts/cyberwatch-vm-smoke.sh`; confirm snapshot, Codex, install, uninstall, and reinstall evidence are recorded without touching undeclared host resources.

### Tests for User Story 1

- [X] T016 [P] [US1] Add offline tests for Debian 13 OS-release parsing in `tests/unit/test_vm_smoke_contract.py`
- [X] T017 [P] [US1] Add offline tests for snapshot confirmation refusal in `tests/unit/test_vm_smoke_contract.py`
- [X] T018 [P] [US1] Add offline tests for cyberWatch-owned cleanup resource list in `tests/unit/test_vm_smoke_contract.py`
- [X] T019 [P] [US1] Add shell syntax validation test for `scripts/cyberwatch-vm-smoke.sh` in `tests/unit/test_vm_smoke_contract.py`

### Implementation for User Story 1

- [X] T020 [US1] Implement baseline check command group in `scripts/cyberwatch-vm-smoke.sh` for `/etc/os-release`, snapshot confirmation, Codex CLI presence, Codex auth status, and repo path
- [X] T021 [US1] Implement install check command group in `scripts/cyberwatch-vm-smoke.sh` for `install-cyberWatch.sh` execution and installer failure evidence capture
- [X] T022 [US1] Implement default uninstall/reinstall check command group in `scripts/cyberwatch-vm-smoke.sh` for `uninstall-cyberWatch.sh`, `install-cyberWatch.sh`, and cyberWatch-owned resource boundaries
- [X] T023 [US1] Harden `uninstall-cyberWatch.sh` so default cleanup lists and touches only declared cyberWatch-owned paths, services, Redis keys, and configuration files
- [X] T024 [US1] Document VM snapshot states, Codex privilege boundary, install workflow, uninstall workflow, and reinstall workflow in `docs/debian13-vm-surface.md`
- [X] T025 [US1] Update `README.md` to link Debian 13 VM validation documentation at `docs/debian13-vm-surface.md`

**Checkpoint**: User Story 1 is complete when the VM baseline plus install/uninstall/reinstall smoke flow can be run or refused safely with reviewable output.

---

## Phase 4: User Story 2 - Validate Runtime Services and Logs (Priority: P1)

**Goal**: A maintainer or Codex operator can validate systemd services, API root/health, Redis queue key state, enrichment startup, bind exposure, and journals.

**Independent Test**: After installation, run the service, API, Redis, enrichment, bind, and journal portions of `scripts/cyberwatch-vm-smoke.sh`; confirm each check emits PASS/FAIL/WARN/SKIP with actionable evidence.

### Tests for User Story 2

- [X] T026 [P] [US2] Add offline tests for canonical `cyberwatch:targets` default and legacy `cyberWatch:targets` detection in `tests/unit/test_queue_key.py`
- [X] T027 [P] [US2] Add offline tests for Redis queue migration message formatting in `tests/unit/test_queue_key.py`
- [X] T028 [P] [US2] Add offline tests that `cyberWatch.enrichment.run_enrichment` imports without NameError in `tests/unit/test_run_enrichment_import.py`
- [X] T029 [P] [US2] Add offline tests for API/UI bind exposure parsing in `tests/unit/test_vm_smoke_contract.py`
- [X] T030 [P] [US2] Add offline tests for required journal command coverage in `tests/unit/test_vm_smoke_contract.py`

### Implementation for User Story 2

- [X] T031 [US2] Change `TargetQueue` default queue key to lowercase `cyberwatch:targets` and expose legacy key detection constants in `cyberWatch/scheduler/queue.py`
- [X] T032 [US2] Update Redis queue references and migration guidance in `README.md`
- [X] T033 [US2] Update Redis queue references and migration guidance in `.github/copilot-instructions.md`
- [X] T034 [US2] Fix missing imports and undefined names in `cyberWatch/enrichment/run_enrichment.py` so import succeeds and startup errors are dependency-specific
- [X] T035 [US2] Implement Redis canonical/legacy queue inspection in `scripts/cyberwatch-vm-smoke.sh`
- [X] T036 [US2] Implement service status checks for PostgreSQL, Redis, Neo4j, API, UI, workers, enrichment, DNS collector, and remeasurement in `scripts/cyberwatch-vm-smoke.sh`
- [X] T037 [US2] Implement API root and `/health` smoke checks in `scripts/cyberwatch-vm-smoke.sh`
- [X] T038 [US2] Implement API/UI bind exposure reporting using systemd command lines and listening sockets in `scripts/cyberwatch-vm-smoke.sh`
- [X] T039 [US2] Implement enrichment import/start and dependency-failure evidence checks in `scripts/cyberwatch-vm-smoke.sh`
- [X] T040 [US2] Implement journal inspection commands for API, UI, workers, enrichment, DNS collector, and remeasurement in `scripts/cyberwatch-vm-smoke.sh`
- [X] T041 [US2] Document service, API, Redis, enrichment, bind, and journal smoke checks in `docs/debian13-vm-surface.md`

**Checkpoint**: User Story 2 is complete when runtime service smoke checks expose queue state, API/health, service status, bind exposure, enrichment startup, and journal failure evidence.

---

## Phase 5: User Story 3 - Enforce Safety and Test Separation (Priority: P2)

**Goal**: A maintainer can verify destructive settings endpoints refuse by default, pure tests stay offline, and line-ending checks block unsafe lifecycle execution.

**Independent Test**: Run `python -m pytest` without live infrastructure, then run VM-only guardrail and line-ending checks; `/settings/clear-dns` returns 403 by default and CRLF scripts/units are reported before lifecycle commands proceed.

### Tests for User Story 3

- [X] T042 [P] [US3] Add offline tests for `/settings/clear-dns` default HTTP 403 behavior in `tests/unit/test_settings_guardrails.py`
- [X] T043 [P] [US3] Add offline tests for `/settings/clear-measurements`, `/settings/clear-graph`, and `/settings/clear-all` default refusal in `tests/unit/test_settings_guardrails.py`
- [X] T044 [P] [US3] Add offline tests proving destructive opt-in is required and explicit in `tests/unit/test_settings_guardrails.py`
- [X] T045 [P] [US3] Add offline tests proving pytest collection avoids live services in `tests/unit/test_vm_smoke_contract.py`
- [X] T046 [P] [US3] Add offline tests for CRLF detection failure output in `tests/unit/test_line_endings.py`

### Implementation for User Story 3

- [X] T047 [US3] Apply default-deny guardrail to `clear_measurements`, `clear_dns`, `clear_graph`, and `clear_all` in `cyberWatch/api/routes/settings.py`
- [X] T048 [US3] Add explicit opt-in mechanism for destructive settings endpoints via environment variable or settings-table policy in `cyberWatch/api/routes/settings.py`
- [X] T049 [US3] Add structured audit logging for destructive endpoint refusal and allowed execution in `cyberWatch/api/routes/settings.py`
- [X] T050 [US3] Update settings UI copy to reflect disabled-by-default destructive actions in `cyberWatch/ui/templates/settings.html`
- [X] T051 [US3] Implement `/settings/clear-dns` HTTP 403 VM smoke check in `scripts/cyberwatch-vm-smoke.sh`
- [X] T052 [US3] Implement `python -m pytest` pure-test smoke check in `scripts/cyberwatch-vm-smoke.sh`
- [X] T053 [US3] Implement CRLF/LF blocking check for shell scripts and `systemd/*.service` in `scripts/cyberwatch-vm-smoke.sh`
- [X] T054 [US3] Document destructive endpoint opt-in, default refusal, pure test separation, and CRLF/LF protection in `docs/debian13-vm-surface.md`
- [X] T055 [US3] Update `README.md` with default destructive endpoint refusal and VM-only smoke test separation

**Checkpoint**: User Story 3 is complete when destructive endpoints refuse by default, pure tests run offline, and line-ending checks prevent unsafe lifecycle commands.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final consistency, documentation, and validation across all stories.

- [X] T056 [P] Run `python -m pytest` and record results in `specs/001-debian-vm-surface/checklists/requirements.md`
- [X] T057 [P] Run shell syntax validation for `scripts/cyberwatch-vm-smoke.sh` and record result in `specs/001-debian-vm-surface/checklists/requirements.md`
- [X] T058 [P] Review `docs/debian13-vm-surface.md` against `specs/001-debian-vm-surface/contracts/smoke-command-catalog.md`
- [X] T059 [P] Review `README.md` and `.github/copilot-instructions.md` for consistent queue key, guardrail, and test-separation wording
- [X] T060 Update `specs/001-debian-vm-surface/quickstart.md` if implementation selects different smoke script flags or output paths
- [X] T061 Run VM-only smoke checks on the dedicated Debian 13 VM and record PASS/FAIL/WARN/SKIP evidence in `specs/001-debian-vm-surface/checklists/requirements.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Phase 1 and blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Phase 2; provides MVP VM lifecycle surface.
- **User Story 2 (Phase 4)**: Depends on Phase 2; can proceed in parallel with US1 after foundational tasks, but full VM service checks need an installable VM from US1.
- **User Story 3 (Phase 5)**: Depends on Phase 2; can proceed in parallel with US1/US2 for API/test changes, but VM guardrail smoke needs an installed API.
- **Polish (Phase 6)**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1 Prepare Disposable VM Surface**: Independent MVP after foundational setup.
- **US2 Validate Runtime Services and Logs**: Independent for code/tests after foundational setup; live validation depends on an installed VM.
- **US3 Enforce Safety and Test Separation**: Independent for code/tests after foundational setup; live guardrail validation depends on the API service.

### Within Each User Story

- Tests precede implementation and should fail before code changes.
- Smoke script checks are added after their corresponding tests define expected output.
- Documentation is updated after behavior and command surfaces are defined.

---

## Parallel Opportunities

- T003, T004, and T005 can run in parallel after T001.
- T007, T009, T011, T013, and T014 can run in parallel once T006 exists.
- US1 test tasks T016-T019 can run in parallel.
- US2 test tasks T026-T030 can run in parallel.
- US3 test tasks T042-T046 can run in parallel.
- Documentation review tasks T058 and T059 can run in parallel with final test commands T056 and T057.

## Parallel Example: User Story 1

```text
Task: "T016 [P] [US1] Add offline tests for Debian 13 OS-release parsing in tests/unit/test_vm_smoke_contract.py"
Task: "T017 [P] [US1] Add offline tests for snapshot confirmation refusal in tests/unit/test_vm_smoke_contract.py"
Task: "T018 [P] [US1] Add offline tests for cyberWatch-owned cleanup resource list in tests/unit/test_vm_smoke_contract.py"
Task: "T019 [P] [US1] Add shell syntax validation test for scripts/cyberwatch-vm-smoke.sh in tests/unit/test_vm_smoke_contract.py"
```

## Parallel Example: User Story 2

```text
Task: "T026 [P] [US2] Add offline tests for canonical cyberwatch:targets default and legacy cyberWatch:targets detection in tests/unit/test_queue_key.py"
Task: "T028 [P] [US2] Add offline tests that cyberWatch.enrichment.run_enrichment imports without NameError in tests/unit/test_run_enrichment_import.py"
Task: "T029 [P] [US2] Add offline tests for API/UI bind exposure parsing in tests/unit/test_vm_smoke_contract.py"
Task: "T030 [P] [US2] Add offline tests for required journal command coverage in tests/unit/test_vm_smoke_contract.py"
```

## Parallel Example: User Story 3

```text
Task: "T042 [P] [US3] Add offline tests for /settings/clear-dns default HTTP 403 behavior in tests/unit/test_settings_guardrails.py"
Task: "T043 [P] [US3] Add offline tests for /settings/clear-measurements, /settings/clear-graph, and /settings/clear-all default refusal in tests/unit/test_settings_guardrails.py"
Task: "T045 [P] [US3] Add offline tests proving pytest collection avoids live services in tests/unit/test_vm_smoke_contract.py"
Task: "T046 [P] [US3] Add offline tests for CRLF detection failure output in tests/unit/test_line_endings.py"
```

---

## Implementation Strategy

### MVP First (US1)

1. Complete Phase 1 setup.
2. Complete Phase 2 foundational tests and helpers.
3. Complete US1 baseline/install/uninstall/reinstall smoke surface.
4. Validate US1 independently on a snapshot-backed Debian 13 VM.

### Incremental Delivery

1. US1 gives Codex a safe disposable VM lifecycle boundary.
2. US2 adds service, API, Redis, enrichment, bind, and journal validation.
3. US3 adds destructive endpoint guardrails and enforces pure/live test separation.

### Final Validation

1. Run default `python -m pytest`.
2. Run VM-only smoke checks only inside the dedicated Debian 13 VM.
3. Record evidence in `specs/001-debian-vm-surface/checklists/requirements.md`.

## Notes

- Every task uses an exact file path and follows the required checkbox/ID/label format.
- Live VM smoke tasks must not be folded into default pytest.
- Destructive endpoint implementation must test refusal paths before allowed paths.
- The canonical Redis queue key is `cyberwatch:targets`; `cyberWatch:targets` is legacy state to detect and document.
