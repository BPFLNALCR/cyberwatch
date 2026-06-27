# Research: Debian 13 VM Development and Test Surface

## Decision: Treat the Debian 13 VM as the only privileged lifecycle surface

Rationale: The constitution names the dedicated Debian 13 cyberWatch VM as the
authoritative development and deployment smoke surface. Installer, systemd,
journal, and service dependency behavior cannot be validated reliably with only
offline unit tests.

Alternatives considered:
- Run lifecycle commands on any developer host. Rejected because privileged
  install/uninstall could affect non-cyberWatch data.
- Use containers only. Rejected because systemd, package, and service behavior
  are part of the acceptance criteria.

## Decision: Require snapshot confirmation before privileged lifecycle checks

Rationale: The VM must be disposable and restoreable. Snapshot expectations make
failed installer, uninstall, or destructive smoke runs reversible without manual
host cleanup.

Alternatives considered:
- Rely on uninstall scripts alone. Rejected because uninstall is itself under
  validation and may fail.
- Use ad hoc manual cleanup. Rejected because it is not reproducible.

## Decision: Separate default unit tests from live VM smoke checks

Rationale: The spec requires `python -m pytest` to pass without live
PostgreSQL, Redis, Neo4j, internet access, traceroute/scamper, Pi-hole, root, or
systemd. Live checks remain documented VM-only smoke validations.

Alternatives considered:
- Make pytest run all live checks. Rejected because default tests would become
  slow, brittle, privileged, and environment-dependent.
- Skip live checks. Rejected because systemd and installer behavior are core
  risks for this project.

## Decision: Make `cyberwatch:targets` the canonical Redis queue key

Rationale: README and operator docs refer to `cyberwatch:targets`, while current
queue code includes a mixed-case default. The smoke surface must detect both
keys so implementation can migrate safely and avoid stranded queued work.

Alternatives considered:
- Keep the mixed-case key. Rejected because it conflicts with existing operator
  documentation and acceptance criteria.
- Delete legacy key blindly. Rejected because queued work might be lost without
  operator awareness.

## Decision: Treat destructive settings endpoints as disabled by default

Rationale: Direct API calls bypass UI confirmation. The spec requires
`/settings/clear-dns` to return HTTP 403 by default and destructive paths to
require explicit opt-in.

Alternatives considered:
- Rely only on browser confirmation dialogs. Rejected because direct API clients
  can still trigger destructive actions.
- Remove destructive endpoints entirely. Rejected because controlled lab resets
  can be useful when explicitly enabled.

## Decision: Use a versioned smoke command catalog as the contract

Rationale: The requested surface is operational, not product-facing. A contract
that names commands, prerequisites, expected outcomes, and failure evidence is
more useful than an API schema alone.

Alternatives considered:
- Put commands only in README. Rejected because the Spec Kit flow needs a
  feature-scoped contract for planning, tasks, and validation.
- Build a full test harness in the plan phase. Rejected because implementation
  belongs in tasks and code changes, not planning.

## Decision: Validate CRLF/LF before lifecycle execution

Rationale: Debian shell scripts and systemd unit files can fail in confusing
ways when CRLF line endings are introduced. The smoke surface must catch line
ending issues before privileged commands run.

Alternatives considered:
- Let lifecycle commands fail naturally. Rejected because errors are less
  actionable and may happen after partial privileged changes.
