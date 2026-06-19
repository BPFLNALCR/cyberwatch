# Research: Stabilization Baseline

## Decision: Fix enrichment scheduler against current repository APIs

**Rationale**: `run_enrichment.py` is the systemd module entrypoint and currently references stale or missing symbols. The narrow fix is to import and use the APIs that already exist: `TargetQueue`, `get_enrichment_settings`, `datetime`, and `asn_expander.run_once(...)`.

**Alternatives considered**:

- Add compatibility aliases such as `Queue` or `expand_asns`: rejected because it preserves stale names and hides the real API contract.
- Rewrite the scheduler loop: rejected because the spec requires preserving existing loop behavior.

## Decision: Use lowercase `cyberwatch:targets` as the canonical Redis key

**Rationale**: Operator docs, installer output, and Copilot guidance already use lowercase. Changing the `TargetQueue` default aligns producers and consumers without touching every caller.

**Alternatives considered**:

- Keep mixed-case `cyberWatch:targets`: rejected because it contradicts more repository-facing documentation.
- Support two default queues: rejected because it risks split-brain producer/consumer behavior and expands scope.

## Decision: Add pytest to runtime requirements for this stabilization pass

**Rationale**: The repository currently has one requirements file and no test dependency scaffold. Adding `pytest` there is the lowest-friction way to make local and CI validation work consistently.

**Alternatives considered**:

- Add a separate dev requirements file: reasonable later, but extra dependency-management surface for a first scaffold.
- Keep manual scripts only: rejected because CI and regression coverage require normal test discovery.

## Decision: Unit/smoke tests only, with no live external services

**Rationale**: The stabilization concerns can be covered through imports, parser functions, filter logic, env guard helpers, queue defaults, and small fakes. Live services would make CI brittle and violate the spec.

**Alternatives considered**:

- Use Docker services in CI: rejected as heavier than required for a stabilization baseline.
- Run `python -m cyberWatch.enrichment.run_enrichment` in CI: rejected because it is a long-running service loop and depends on live infrastructure.

## Decision: Destructive settings endpoints disabled by default through `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS`

**Rationale**: A server-side env guard protects direct API calls and scripts, while keeping intentional operator access available after explicit opt-in.

**Alternatives considered**:

- UI confirmation only: rejected because direct HTTP callers bypass it.
- Full authentication/authorization: correct for future hardening but too broad for this stabilization pass.
- Per-request typed confirmation phrase: useful, but the user specifically requested an environment-controlled guard and safe default.

## Decision: DNS client-IP storage disabled by default with env/config opt-in

**Rationale**: This addresses the privacy mismatch for new ingestion without schema churn, historical data migration, hashing, or analytics redesign. Existing `ignore_clients` behavior can still use source client IPs before persistence.

**Alternatives considered**:

- Documentation-only privacy note: acceptable fallback, but a minimal implementation is feasible.
- Drop client IP columns: rejected because it is a migration and may break existing UI/API queries.
- Hash client IPs: rejected as overbuilt for this pass and still potentially identifying on small LANs.

## Decision: Leave `systemd/cyberWatch-enrichment.service` unchanged

**Rationale**: The service already points at the intended module entrypoint. The problem is inside the module, not the service file.

**Alternatives considered**:

- Change systemd to call a new script: rejected because it creates an unnecessary alternate entrypoint.

