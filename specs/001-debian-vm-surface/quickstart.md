# Quickstart: Debian 13 VM Development and Test Surface

This guide describes the implemented validation flow for the dedicated Debian
13 cyberWatch VM.

## Prerequisites

- Use only the dedicated Debian 13 cyberWatch VM.
- Confirm a restoreable VM snapshot exists before privileged lifecycle work.
- Confirm Codex CLI is installed and authenticated inside the VM before Codex
  runs privileged commands.
- Work from the repository checkout under test.

## 1. Baseline Checks

```bash
cat /etc/os-release
codex --version
git status --short
scripts/cyberwatch-vm-smoke.sh --yes-snapshot --snapshot-label "pre-install-YYYYMMDD" --run-baseline
```

Expected outcome:
- OS identifies Debian 13.
- Codex is available and authenticated for this VM.
- Repository state is reviewable before lifecycle commands run.

## 2. Line Ending Protection

```bash
scripts/cyberwatch-vm-smoke.sh --run-line-endings
```

Expected outcome:
- Shell scripts and systemd unit files are LF-safe.
- Any CRLF result blocks privileged lifecycle checks.

## 3. Install From Repository

```bash
scripts/cyberwatch-vm-smoke.sh --yes-snapshot --allow-lifecycle --run-install
```

Expected outcome:
- Installer completes or provides actionable failure output.
- cyberWatch-owned configuration is under `/etc/cyberwatch/`.
- Services are installed through systemd.

## 4. Service Status Smoke

```bash
scripts/cyberwatch-vm-smoke.sh --run-services
```

Expected outcome:
- Required services are running or documented as intentionally inactive.
- Failed services include actionable status output.

## 5. API and UI Bind Smoke

```bash
scripts/cyberwatch-vm-smoke.sh --run-bind
scripts/cyberwatch-vm-smoke.sh --run-api
```

Expected outcome:
- API root and health respond.
- API/UI bind addresses are explicit.
- All-interface binds are reported, not assumed safe.

## 6. Destructive Endpoint Guardrail

```bash
scripts/cyberwatch-vm-smoke.sh --run-guardrails
```

Expected outcome:
- HTTP status is `403` by default.
- DNS data is not cleared.

## 7. Pure Unit Tests

```bash
python -m pytest
```

Expected outcome:
- Tests pass without requiring live PostgreSQL, Redis, Neo4j, internet access,
  traceroute/scamper, Pi-hole, root, or systemd.

## 8. Enrichment Import and Startup Smoke

```bash
scripts/cyberwatch-vm-smoke.sh --run-enrichment
```

Expected outcome:
- Import succeeds.
- Enrichment service does not crash immediately due to Python errors.
- External dependency failure is clear when Neo4j or PostgreSQL is unavailable.

## 9. Redis Queue Key Smoke

```bash
scripts/cyberwatch-vm-smoke.sh --run-redis
```

Expected outcome:
- `cyberwatch:targets` is canonical.
- Any legacy `cyberWatch:targets` state is detected and documented.

## 10. Journal Diagnostics

```bash
scripts/cyberwatch-vm-smoke.sh --journal-commands
scripts/cyberwatch-vm-smoke.sh --run-journals
```

Expected outcome:
- Failure output names the service, command or module, exit status or
  exception, and relevant dependency hints.

## 11. Default Uninstall and Reinstall

```bash
scripts/cyberwatch-vm-smoke.sh --yes-snapshot --allow-lifecycle --run-uninstall-reinstall
```

Expected outcome:
- Default uninstall affects only declared cyberWatch-owned resources.
- Reinstall reaches service validation again.
- Purge or destructive database/graph cleanup requires explicit opt-in.

## 12. Record Evidence

Capture the result for each smoke check:

- Check ID and status.
- Command surface used.
- Expected and observed outcome.
- Failure evidence when status is not PASS.
- VM snapshot state and timestamp.

Proceed to task generation only after this plan, research, data model, contract,
and quickstart are reviewed.
