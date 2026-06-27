#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/mnt/c/Users/User/cyberwatch"
LOG_FILE="/tmp/cyberwatch-install.log"
DEFAULT_TEST_DSN="postgresql://cyberwatch_test:cyberwatch_test@localhost:5432/cyberwatch_test"

usage() {
  cat <<'EOF'
Usage: scripts/host_install_smoke.sh --yes

Runs the repo installer from /mnt/c/Users/User/cyberwatch using the test DSN
and CYBERWATCH_APPLY_SCHEMA=1. This wrapper is intended for a user-owned Debian
WSL terminal, not Codex's restricted execution sandbox.

This command may invoke sudo through install-cyberWatch.sh and may install
system packages, apply schemas, and install systemd units. It will not proceed
without the explicit --yes flag.
EOF
}

if [[ "${1:-}" != "--yes" ]]; then
  usage
  exit 2
fi

cd "$REPO_ROOT"

rm -f "$LOG_FILE"

echo "[cyberWatch] repo=$REPO_ROOT"
echo "[cyberWatch] log=$LOG_FILE"
echo "[cyberWatch] CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS=false"

set +e
printf '\n' | env \
  CYBERWATCH_APPLY_SCHEMA=1 \
  CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS=false \
  CYBERWATCH_PG_DSN="${CYBERWATCH_PG_DSN:-$DEFAULT_TEST_DSN}" \
  bash ./install-cyberWatch.sh 2>&1 | tee "$LOG_FILE"
INSTALL_EXIT=${PIPESTATUS[1]}
set -e

echo "INSTALL_EXIT=$INSTALL_EXIT" | tee -a "$LOG_FILE"
tail -120 "$LOG_FILE"

exit "$INSTALL_EXIT"
