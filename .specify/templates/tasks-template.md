---

description: "Task list template for feature implementation"
---

# Tasks: [FEATURE NAME]

**Input**: Design documents from `/specs/[###-feature-name]/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are REQUIRED for pure logic, regressions, parsers, filters,
settings defaults, redaction, safety guards, graph construction, and API
serialization. Default tests MUST NOT require live PostgreSQL, Redis, Neo4j,
internet access, traceroute/scamper, Pi-hole, root privileges, or systemd. Live
integration checks belong in documented Debian 13 VM smoke scripts.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **API**: `cyberWatch/api/`
- **DNS collector**: `cyberWatch/collector/`
- **Measurement workers**: `cyberWatch/workers/`
- **Enrichment and graph projection**: `cyberWatch/enrichment/`
- **Queue and scheduling**: `cyberWatch/scheduler/`
- **Database schemas/access**: `cyberWatch/db/`
- **UI**: `cyberWatch/ui/`
- **Operator config**: `config/`, `/etc/cyberwatch/` examples, and settings table code
- **Debian/systemd lifecycle**: `install-cyberWatch.sh`, `systemd/`, smoke scripts/docs
- **Default tests**: `tests/` or focused root test files that run offline

<!--
  ============================================================================
  IMPORTANT: The tasks below are SAMPLE TASKS for illustration purposes only.

  The /speckit-tasks command MUST replace these with actual tasks based on:
  - User stories from spec.md (with their priorities P1, P2, P3...)
  - Feature requirements from plan.md
  - Entities from data-model.md
  - Endpoints from contracts/

  Tasks MUST be organized by user story so each story can be:
  - Implemented independently
  - Tested independently
  - Delivered as an MVP increment

  DO NOT keep these sample tasks in the generated tasks.md file.
  ============================================================================
-->

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Create project structure per implementation plan
- [ ] T002 Initialize [language] project with [framework] dependencies
- [ ] T003 [P] Configure linting and formatting tools

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

Examples of foundational tasks (adjust based on your project):

- [ ] T004 Identify affected pipeline stages and preserve explicit data flow
- [ ] T005 [P] Add or update offline unit tests for pure logic before implementation
- [ ] T006 [P] Update structured logging fields for new operations or failures
- [ ] T007 Add safety gates for any delete/reset/restart/schema/credential path
- [ ] T008 Keep runtime policy in config, environment variables, or `settings`
- [ ] T009 Update Debian/systemd/installer surfaces if runtime behavior changes
- [ ] T010 Document DNS privacy handling if DNS-derived data is touched

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - [Title] (Priority: P1) 🎯 MVP

**Goal**: [Brief description of what this story delivers]

**Independent Test**: [How to verify this story works on its own]

### Tests for User Story 1 (REQUIRED for pure logic and regressions) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T011 [P] [US1] Offline unit test for [parser/filter/settings/safety behavior] in tests/unit/test_[name].py
- [ ] T012 [P] [US1] API/model contract test for [endpoint/serialization] in tests/contract/test_[name].py

### Implementation for User Story 1

- [ ] T013 [P] [US1] Create or update model in cyberWatch/[component]/[file].py
- [ ] T014 [P] [US1] Create or update pipeline mechanism in cyberWatch/[component]/[file].py
- [ ] T015 [US1] Implement API/UI/worker/collector/enrichment behavior in cyberWatch/[component]/[file].py
- [ ] T016 [US1] Add validation, refusal paths, and explicit error handling
- [ ] T017 [US1] Add structured logging with action, outcome, IDs, counts, and durations
- [ ] T018 [US1] Update config/env/settings handling for runtime policy

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - [Title] (Priority: P2)

**Goal**: [Brief description of what this story delivers]

**Independent Test**: [How to verify this story works on its own]

### Tests for User Story 2 (REQUIRED for pure logic and regressions) ⚠️

- [ ] T019 [P] [US2] Offline unit test for [parser/filter/settings/safety behavior] in tests/unit/test_[name].py
- [ ] T020 [P] [US2] API/model contract test for [endpoint/serialization] in tests/contract/test_[name].py

### Implementation for User Story 2

- [ ] T021 [P] [US2] Create or update model in cyberWatch/[component]/[file].py
- [ ] T022 [US2] Implement mechanism in cyberWatch/[component]/[file].py
- [ ] T023 [US2] Integrate with existing pipeline stage boundaries
- [ ] T024 [US2] Add structured logs and explicit failure paths

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - [Title] (Priority: P3)

**Goal**: [Brief description of what this story delivers]

**Independent Test**: [How to verify this story works on its own]

### Tests for User Story 3 (REQUIRED for pure logic and regressions) ⚠️

- [ ] T025 [P] [US3] Offline unit test for [parser/filter/settings/safety behavior] in tests/unit/test_[name].py
- [ ] T026 [P] [US3] API/model contract test for [endpoint/serialization] in tests/contract/test_[name].py

### Implementation for User Story 3

- [ ] T027 [P] [US3] Create or update model in cyberWatch/[component]/[file].py
- [ ] T028 [US3] Implement mechanism in cyberWatch/[component]/[file].py
- [ ] T029 [US3] Integrate with existing pipeline stage boundaries

**Checkpoint**: All user stories should now be independently functional

---

[Add more user story phases as needed, following the same pattern]

---

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] TXXX [P] Documentation updates in docs/
- [ ] TXXX Code cleanup and refactoring
- [ ] TXXX Performance optimization across all stories
- [ ] TXXX [P] Additional offline unit tests in tests/unit/
- [ ] TXXX Security hardening
- [ ] TXXX Validate Debian 13 VM smoke script or quickstart when runtime lifecycle changed
- [ ] TXXX Update `install-cyberWatch.sh`, `systemd/`, `.github/copilot-instructions.md`, README, or operator docs as needed

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed)
  - Or sequentially in priority order (P1 → P2 → P3)
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - May integrate with US1 but should be independently testable
- **User Story 3 (P3)**: Can start after Foundational (Phase 2) - May integrate with US1/US2 but should be independently testable

### Within Each User Story

- Required tests MUST be written and FAIL before implementation
- Models before services
- Services before endpoints
- Core implementation before integration
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel
- All Foundational tasks marked [P] can run in parallel (within Phase 2)
- Once Foundational phase completes, all user stories can start in parallel (if team capacity allows)
- All tests for a user story marked [P] can run in parallel
- Models within a story marked [P] can run in parallel
- Different user stories can be worked on in parallel by different team members

---

## Parallel Example: User Story 1

```bash
# Launch all offline tests for User Story 1 together:
Task: "Offline unit test for [parser/filter/settings/safety behavior] in tests/unit/test_[name].py"
Task: "API/model contract test for [endpoint/serialization] in tests/contract/test_[name].py"

# Launch independent cyberWatch component edits for User Story 1 together:
Task: "Create or update [model/parser/filter] in cyberWatch/[component]/[file].py"
Task: "Create or update [API/UI/worker] behavior in cyberWatch/[component]/[file].py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test User Story 1 independently
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 → Test independently → Deploy/Demo
4. Add User Story 3 → Test independently → Deploy/Demo
5. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1
   - Developer B: User Story 2
   - Developer C: User Story 3
3. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story MUST be independently completable and testable
- Verify required tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
- Keep live PostgreSQL, Redis, Neo4j, traceroute/scamper, Pi-hole, root, and systemd checks in explicit VM smoke tasks
