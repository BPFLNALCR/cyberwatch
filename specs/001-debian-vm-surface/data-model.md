# Data Model: Debian 13 VM Development and Test Surface

## VM Surface

Represents the disposable environment used for privileged cyberWatch lifecycle
validation.

Fields:
- `os_release`: Must identify Debian 13.
- `snapshot_state`: One of `baseline`, `pre-install`, `post-install`,
  `pre-destructive-check`, `failed-run`, `restored`.
- `codex_status`: One of `installed-authenticated`,
  `installed-unauthenticated`, `missing`.
- `repo_path`: Absolute path to the repository checkout under test.
- `privileged_scope`: Must be limited to cyberWatch-owned resources.

Validation rules:
- Privileged lifecycle checks require `snapshot_state` of `baseline` or
  `pre-install`.
- Codex lifecycle automation requires `codex_status` of
  `installed-authenticated`.

## Snapshot Baseline

Represents a named restore point for the VM.

Fields:
- `name`: Human-readable snapshot name.
- `created_at`: Timestamp recorded by the operator or VM host.
- `purpose`: `clean-os`, `pre-install`, `post-install`, or `pre-risk-check`.
- `restore_instruction`: Where the operator finds the restore action.

Validation rules:
- A snapshot must exist before install, uninstall/reinstall, or destructive
  guardrail checks.
- A failed lifecycle run must record whether restore was performed.

## Lifecycle Workflow

Represents install, service validation, uninstall, reinstall, and restore
activity.

Fields:
- `phase`: `install`, `service-smoke`, `guardrail-smoke`, `uninstall`,
  `reinstall`, `restore`.
- `command`: The documented command or command group.
- `expected_result`: Pass condition.
- `actual_result`: Recorded pass/fail evidence.
- `affected_resources`: cyberWatch-owned resources touched by the phase.
- `requires_privilege`: Boolean.

Validation rules:
- Any privileged phase must run only inside the VM surface.
- Any cleanup phase must list affected cyberWatch-owned resources.
- Any undocumented manual step fails the workflow.

## Service Set

Represents services and dependencies expected in the VM smoke surface.

Fields:
- `name`: Service or dependency name.
- `kind`: `systemd-service`, `template-instance`, `database`,
  `queue`, `graph`, `api`, `ui`.
- `expected_state`: `active`, `enabled`, `present`, or
  `documented-inactive`.
- `status_command`: Command used to inspect state.
- `journal_command`: Command used to inspect recent failures.

Validation rules:
- API, UI, worker instances, enrichment, DNS collector, and remeasurement must
  have service status and journal inspection commands.
- PostgreSQL, Redis, and Neo4j must have dependency status checks.

## Smoke Check

Represents one live VM validation check.

Fields:
- `id`: Stable identifier.
- `category`: `snapshot`, `codex`, `install`, `service`, `api`,
  `guardrail`, `test`, `enrichment`, `redis`, `journal`, `bind`,
  `line-ending`, `uninstall`.
- `prerequisites`: Conditions that must be true before running.
- `command`: Command or documented command group.
- `expected_outcome`: Observable result.
- `failure_evidence`: Output that must be captured on failure.
- `live_dependencies`: Dependencies required by the check.

Validation rules:
- Live dependencies must be explicit.
- Smoke checks requiring root or systemd are marked VM-only.
- Failure evidence must be enough to diagnose the responsible service or
  guardrail.

## Guardrail Check

Represents validation of destructive behavior refusal.

Fields:
- `endpoint_or_command`: The API endpoint or lifecycle command under test.
- `default_expected_status`: Expected refusal, such as HTTP 403.
- `opt_in_required`: Boolean.
- `data_preservation_check`: How unchanged state is verified.
- `audit_evidence`: Log or response evidence to capture.

Validation rules:
- Destructive settings endpoints must refuse by default.
- Success without explicit opt-in fails validation.

## Queue Key Check

Represents Redis queue key validation.

Fields:
- `canonical_key`: Must be `cyberwatch:targets`.
- `legacy_key`: Must include `cyberWatch:targets` detection.
- `canonical_depth`: Observed item count.
- `legacy_depth`: Observed item count.
- `migration_guidance`: Operator-facing decision when legacy depth is nonzero.

Validation rules:
- The smoke result must report both canonical and legacy key state.
- Nonzero legacy depth requires documented migration or operator decision.

## Line Ending Check

Represents validation that Debian-executed files are LF-safe.

Fields:
- `path_glob`: Script or unit path set.
- `expected_line_ending`: `LF`.
- `violations`: Files with CRLF or malformed endings.
- `blocks_lifecycle`: Boolean.

Validation rules:
- Shell scripts and systemd units must have zero CRLF violations before
  privileged lifecycle commands proceed.
- Any violation must identify the exact file path.

## Relationships

- A `VM Surface` has many `Snapshot Baselines`.
- A `Lifecycle Workflow` runs on one `VM Surface`.
- A `Lifecycle Workflow` contains many `Smoke Checks`.
- A `Smoke Check` may inspect one or more `Service Set` members.
- A `Smoke Check` may produce a `Guardrail Check`, `Queue Key Check`, or
  `Line Ending Check` result.
