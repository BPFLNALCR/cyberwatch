# Tasks: Stabilization Baseline

**Input**: Design documents from `specs/001-stabilization-baseline/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Tests are explicitly requested for this stabilization pass. Keep them pure/unit-level unless a task says otherwise.

**Organization**: Tasks are ordered by the requested stabilization groups A-H. Story labels map to the specification: `[US1]` enrichment startup, `[US2]` development safety checks, `[US3]` destructive-operation guardrail, `[US4]` DNS privacy posture.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other marked tasks in the same group when file paths do not overlap
- **[Story]**: User story traceability label from `spec.md`
- Every task names exact file paths and avoids broad rewrites

---

## A. Enrichment Scheduler Repair

**Goal**: Make `cyberWatch.enrichment.run_enrichment` import and start through the documented module entrypoint without immediate stale-name failures.

**Independent Test**: Import the module and verify the scheduler references current repository APIs rather than `Queue`, missing `datetime`, missing `get_enrichment_settings`, missing `AsnExpanderConfig`, or missing `expand_asns`.

- [X] T001 [US1] Replace stale `Queue(redis_url)` usage with `TargetQueue(redis_url)` and add the `TargetQueue` import in `cyberWatch/enrichment/run_enrichment.py`
- [X] T002 [US1] Import `datetime`, `get_enrichment_settings_with_defaults`, and `asn_expander` in `cyberWatch/enrichment/run_enrichment.py`
- [X] T003 [US1] Replace `AsnExpanderConfig` and `expand_asns(...)` references with `asn_expander.AsnExpanderConfig(...)` and `asn_expander.run_once(...)` in `cyberWatch/enrichment/run_enrichment.py`

**Validation after Group A**:

```powershell
python -c "import importlib; importlib.import_module('cyberWatch.enrichment.run_enrichment')"
python -c "from pathlib import Path; text=Path('cyberWatch/enrichment/run_enrichment.py').read_text(); assert 'Queue(' not in text and 'expand_asns' not in text"
```

---

## B. Pytest Scaffold And Pure-Function Tests

**Goal**: Add a pytest baseline that does not require live PostgreSQL, Redis, Neo4j, Pi-hole, traceroute, scamper, internet access, or long-running service loops.

**Independent Test**: Parser/filter tests pass in isolation; import/queue/guard/privacy tests become the regression net for later groups.

- [X] T004 Add `pytest` to `cyberWatch/requirements.txt`
- [X] T005 [P] [US2] Add import smoke tests for `cyberWatch.enrichment.run_enrichment`, `cyberWatch.workers.worker`, `cyberWatch.collector.dns_collector`, and `cyberWatch.api.routes.settings` in `tests/test_imports.py`
- [X] T006 [P] [US2] Add `_parse_traceroute_hops(...)` tests for normal hop lines, averaged RTTs, and timeout hop lines in `tests/test_worker_parsers.py`
- [X] T007 [P] [US2] Add `_parse_scamper_hops(...)` tests for normal scamper trace output in `tests/test_worker_parsers.py`
- [X] T008 [P] [US2] Add DNS filter tests for reverse DNS, Cymru enrichment lookups, `.local`, ignored qtypes, and ignored clients in `tests/test_dns_filters.py`
- [X] T009 [P] [US2] Add default and override queue key tests for `TargetQueue` in `tests/test_queue.py`
- [X] T010 [P] [US3] Add destructive settings env guard tests for unset, false-like, true-like, and blocked behavior in `tests/test_settings_guard.py`
- [X] T011 [P] [US4] Add DNS client-IP storage default and opt-in tests in `tests/test_dns_privacy.py`

**Validation after Group B**:

```powershell
python -m pytest tests/test_worker_parsers.py tests/test_dns_filters.py
python -m pytest tests/test_imports.py
```

Note: `tests/test_queue.py`, `tests/test_settings_guard.py`, and `tests/test_dns_privacy.py` may fail until Groups C, D, and E are implemented.

---

## C. Queue Key Standardization

**Goal**: Use lowercase `cyberwatch:targets` consistently as the default Redis target queue key.

**Independent Test**: `TargetQueue()` and `TargetQueue(redis_url)` default to `cyberwatch:targets`, while explicit queue-key overrides still work.

- [X] T012 [US2] Change the default `queue_key` argument from `cyberWatch:targets` to `cyberwatch:targets` in `cyberWatch/scheduler/queue.py`
- [X] T013 [P] [US2] Verify queue consumers and producers rely on `TargetQueue` defaults without adding per-caller overrides in `cyberWatch/workers/worker.py`, `cyberWatch/collector/dns_collector.py`, `cyberWatch/scheduler/remeasure.py`, `cyberWatch/api/routes/targets.py`, and `cyberWatch/api/routes/health.py`

**Validation after Group C**:

```powershell
python -m pytest tests/test_queue.py
python -c "from cyberWatch.scheduler.queue import TargetQueue; assert TargetQueue().queue_key == 'cyberwatch:targets'; assert TargetQueue(queue_key='custom').queue_key == 'custom'"
```

---

## D. Destructive Endpoint Guardrail

**Goal**: Disable destructive settings endpoints by default unless the operator explicitly enables them through environment configuration.

**Independent Test**: Guard helper rejects disabled calls before clear logic can run and allows enabled calls to proceed to existing route behavior.

- [X] T014 [US3] Add `destructive_settings_enabled()` and `require_destructive_settings_enabled()` helpers using `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS` in `cyberWatch/api/routes/settings.py`
- [X] T015 [US3] Call `require_destructive_settings_enabled()` before any database or graph work in `clear_measurements`, `clear_dns`, `clear_graph`, and `clear_all` in `cyberWatch/api/routes/settings.py`
- [X] T016 [US3] Return a clear 403-style error that mentions `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS=true` when destructive routes are disabled in `cyberWatch/api/routes/settings.py`
- [X] T017 [US3] Add `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS="false"` to the generated environment file block in `install-cyberWatch.sh`
- [X] T018 [P] [US3] Verify no route-registration changes are needed and leave `cyberWatch/api/server.py` behavior unchanged after the route-local guard is added

**Validation after Group D**:

```powershell
python -m pytest tests/test_settings_guard.py
python -c "from cyberWatch.api.routes.settings import destructive_settings_enabled; assert destructive_settings_enabled() is False"
```

---

## E. DNS Privacy Baseline

**Goal**: Avoid storing DNS client IPs for new ingestion by default, while preserving pre-storage filtering and offering explicit lab opt-in.

**Independent Test**: DNS records prepared for persistence contain no client IPs by default, preserve client IPs when enabled, and still apply ignored-client filtering before storage suppression.

- [X] T019 [US4] Add `DNSPrivacyConfig` with `store_client_ips: bool = False` and a `privacy` field on `DNSCollectorConfig` in `cyberWatch/collector/config.py`
- [X] T020 [US4] Add `CYBERWATCH_DNS_STORE_CLIENT_IPS` env override parsing helpers in `cyberWatch/collector/dns_collector.py`
- [X] T021 [US4] Apply the DNS client-IP storage helper when creating `DNSQueryRecord.client_ip` values in `cyberWatch/collector/dns_collector.py`
- [X] T022 [US4] Apply the DNS client-IP storage helper when creating `DNSTargetRecord.last_client_ip` values in `cyberWatch/collector/dns_collector.py`
- [X] T023 [P] [US4] Add a `privacy.store_client_ips: false` example and comments to `config/cyberwatch_dns.example.yaml`
- [X] T024 [P] [US4] Add SQL comments documenting `dns_queries.client_ip` and `dns_targets.last_client_ip` as nullable lab opt-in/legacy fields in `cyberWatch/db/dns_schema.sql`
- [X] T025 [US4] Add `CYBERWATCH_DNS_STORE_CLIENT_IPS="false"` to the generated environment file block in `install-cyberWatch.sh`

**Validation after Group E**:

```powershell
python -m pytest tests/test_dns_privacy.py tests/test_dns_filters.py
```

---

## F. CI Workflow

**Goal**: Add lightweight GitHub Actions CI that installs dependencies and runs pytest without live external services.

**Independent Test**: The workflow file exists, installs `cyberWatch/requirements.txt`, and runs `python -m pytest`.

- [X] T026 [US2] Add `.github/workflows/tests.yml` with pull request and push triggers, Python 3.11 setup, dependency installation from `cyberWatch/requirements.txt`, and `python -m pytest`

**Validation after Group F**:

```powershell
python -c "from pathlib import Path; p=Path('.github/workflows/tests.yml'); text=p.read_text(); assert 'python -m pytest' in text and 'cyberWatch/requirements.txt' in text"
```

---

## G. README / Developer Docs Updates

**Goal**: Document the stabilization behavior without implying new product features or completed hardening beyond this pass.

**Independent Test**: Docs show pytest commands, lowercase queue key, destructive guardrail defaults, and DNS privacy defaults/status.

- [X] T027 [US2] Add a Testing section with `python -m pip install -r cyberWatch/requirements.txt` and `python -m pytest` commands in `README.md`
- [X] T028 [US2] Verify all Redis target queue examples use lowercase `cyberwatch:targets` in `README.md`
- [X] T029 [US3] Document `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS=false` and the default-disabled destructive settings behavior in `README.md`
- [X] T030 [US4] Document `CYBERWATCH_DNS_STORE_CLIENT_IPS=false`, the new-ingestion default, and the no-historical-scrub limitation in `README.md`
- [X] T031 [US2] Replace primary manual testing guidance with `python -m pytest` and keep `test_logging.py` as optional/manual only in `.github/copilot-instructions.md`
- [X] T032 [US3] Add `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS` to the environment table or equivalent guidance in `.github/copilot-instructions.md`
- [X] T033 [US4] Add `CYBERWATCH_DNS_STORE_CLIENT_IPS` and DNS client-IP privacy notes to `.github/copilot-instructions.md`

**Validation after Group G**:

```powershell
rg -n "python -m pytest|cyberwatch:targets|CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS|CYBERWATCH_DNS_STORE_CLIENT_IPS" README.md .github/copilot-instructions.md
rg -n "cyberWatch:targets" README.md .github/copilot-instructions.md cyberWatch
```

The second command should return no default-queue references after implementation.

---

## H. Final Validation

**Goal**: Prove the stabilization baseline meets acceptance criteria and remains within scope.

- [X] T034 Run the full default test suite described in `specs/001-stabilization-baseline/quickstart.md` with `python -m pytest`
- [X] T035 Run enrichment import smoke validation from `specs/001-stabilization-baseline/quickstart.md` with `python -c "import importlib; importlib.import_module('cyberWatch.enrichment.run_enrichment')"`
- [X] T036 Run queue key smoke validation from `specs/001-stabilization-baseline/quickstart.md` with `python -c "from cyberWatch.scheduler.queue import TargetQueue; assert TargetQueue().queue_key == 'cyberwatch:targets'"`
- [X] T037 Verify CI workflow content in `.github/workflows/tests.yml` includes dependency installation and `python -m pytest`
- [X] T038 Review changed files against `specs/001-stabilization-baseline/plan.md` to confirm no Spec Kit constitution work, product feature work, architecture redesign, migrations, or live-service test requirements were introduced

**Final validation commands**:

```powershell
python -m pytest
python -c "import importlib; importlib.import_module('cyberWatch.enrichment.run_enrichment')"
python -c "from cyberWatch.scheduler.queue import TargetQueue; assert TargetQueue().queue_key == 'cyberwatch:targets'"
python -c "from pathlib import Path; text=Path('.github/workflows/tests.yml').read_text(); assert 'python -m pytest' in text"
git diff -- cyberWatch tests .github README.md install-cyberWatch.sh config cyberWatch/db/dns_schema.sql
```

---

## Dependencies & Execution Order

### Group Dependencies

- **A. Enrichment scheduler repair**: Can start immediately and gives the first MVP stabilization increment.
- **B. Pytest scaffold and pure-function tests**: Can start after or alongside A, but some tests are expected to fail until C, D, and E are implemented.
- **C. Queue key standardization**: Depends on B queue test if following test-first; otherwise can be implemented after A.
- **D. Destructive endpoint guardrail**: Depends on B settings guard test if following test-first.
- **E. DNS privacy baseline**: Depends on B DNS privacy test if following test-first.
- **F. CI workflow**: Best after B so pytest exists, but can be created before all tests pass.
- **G. README / developer docs updates**: Best after C-F decisions are implemented.
- **H. Final validation**: Depends on all selected implementation groups.

### User Story Dependencies

- **US1 Stabilize Enrichment Startup**: Group A only; no dependency on other stories.
- **US2 Establish Development Safety Checks**: Groups B, C, F, and relevant docs in G; queue key consistency supports CI/test acceptance.
- **US3 Prevent Accidental Destructive Operations**: Group D plus guardrail docs in G; independent after test scaffold exists.
- **US4 Align DNS Privacy Posture**: Group E plus privacy docs in G; independent after test scaffold exists.

### Suggested MVP Scope

The MVP is **Group A plus the relevant import smoke from Group B**:

1. T001-T003 repair `run_enrichment.py`.
2. T004-T005 establish pytest import smoke coverage.
3. Validate with the Group A commands and `python -m pytest tests/test_imports.py`.

This proves the broken enrichment entrypoint no longer fails immediately from stale local symbols.

---

## Parallel Opportunities

- T005, T006, T008, T009, T010, and T011 can be written in parallel because they touch separate test files.
- T023 and T024 can run in parallel with T020-T022 because they touch config/schema docs rather than collector logic.
- T026 can run in parallel with C, D, or E once T004 is planned because CI only shells out to pytest.
- T027-T033 can be split by file and topic, but avoid simultaneous edits to the same documentation file.

## Parallel Example: Test Scaffold

```text
Task: "T005 Add import smoke tests in tests/test_imports.py"
Task: "T006/T007 Add worker parser tests in tests/test_worker_parsers.py"
Task: "T008 Add DNS filter tests in tests/test_dns_filters.py"
Task: "T009 Add queue key tests in tests/test_queue.py"
Task: "T010 Add destructive settings guard tests in tests/test_settings_guard.py"
Task: "T011 Add DNS privacy tests in tests/test_dns_privacy.py"
```

## Implementation Strategy

1. Repair the enrichment scheduler first to remove the confirmed runtime breakage.
2. Add pytest and pure tests so subsequent stabilization changes have a regression net.
3. Implement queue, destructive guard, and DNS privacy changes as separate, independently verifiable slices.
4. Add CI only after pytest exists.
5. Update README and developer docs after behavior is settled.
6. Run final validation from `quickstart.md` and keep any live-service checks optional.

## Scope Guardrails

- Do not initialize or edit the Spec Kit constitution.
- Do not add new measurement, graph, DNS analytics, UI, or product features.
- Do not redesign the pipeline or add new infrastructure services.
- Do not add live PostgreSQL, Redis, Neo4j, Pi-hole, traceroute, scamper, or internet requirements to default tests or CI.
- Do not migrate or scrub historical DNS rows in this pass.
