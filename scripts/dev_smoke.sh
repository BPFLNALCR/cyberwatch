#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/mnt/c/Users/User/cyberwatch"

cd "$REPO_ROOT"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

API_BASE="${CYBERWATCH_API_BASE:-http://127.0.0.1:${CYBERWATCH_API_PORT:-8000}}"

echo "[cyberWatch] repo=$REPO_ROOT"
echo "[cyberWatch] python=$("$PYTHON" --version 2>&1)"

echo "[cyberWatch] compileall"
"$PYTHON" -m compileall cyberWatch

echo "[cyberWatch] pytest"
"$PYTHON" -m pytest

echo "[cyberWatch] import enrichment runner"
"$PYTHON" -c "import cyberWatch.enrichment.run_enrichment"

echo "[cyberWatch] TargetQueue default key"
QUEUE_KEY="$("$PYTHON" -c "from cyberWatch.scheduler.queue import TargetQueue; print(TargetQueue().queue_key)")"
echo "[cyberWatch] queue_key=$QUEUE_KEY"
if [[ "$QUEUE_KEY" != "cyberwatch:targets" ]]; then
  echo "[cyberWatch] expected queue key cyberwatch:targets, got $QUEUE_KEY" >&2
  exit 1
fi

echo "[cyberWatch] localhost API smoke"
API_RESULT="$(API_BASE="$API_BASE" "$PYTHON" - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

base = os.environ["API_BASE"].rstrip("/")

def request(path: str, method: str = "GET") -> tuple[int | None, str]:
    req = urllib.request.Request(f"{base}{path}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2000).decode("utf-8", "replace")
    except OSError as exc:
        return None, str(exc)

root_status, root_body = request("/")
if root_status is None:
    print(json.dumps({"running": False, "base": base, "error": root_body}))
    sys.exit(0)

health_status, health_body = request("/health")
clear_status, clear_body = request("/settings/clear-dns", method="POST")

print(json.dumps({
    "running": True,
    "base": base,
    "root_status": root_status,
    "health_status": health_status,
    "health_body": health_body[:500],
    "clear_dns_status": clear_status,
    "clear_dns_body": clear_body[:500],
}))

if health_status is None or not (200 <= health_status < 300):
    sys.exit(2)
if clear_status != 403:
    sys.exit(3)
PY
)" || API_EXIT=$?
API_EXIT="${API_EXIT:-0}"
echo "$API_RESULT"
if [[ "$API_EXIT" -eq 2 ]]; then
  echo "[cyberWatch] API is running, but /health did not return a healthy smoke response" >&2
  exit 1
fi
if [[ "$API_EXIT" -eq 3 ]]; then
  echo "[cyberWatch] API is running, but /settings/clear-dns did not return 403" >&2
  exit 1
fi

echo "[cyberWatch] Redis queue smoke"
if command -v redis-cli >/dev/null 2>&1 && redis-cli PING >/dev/null 2>&1; then
  echo "[cyberWatch] redis=running"
  echo "[cyberWatch] LLEN $QUEUE_KEY=$(redis-cli LLEN "$QUEUE_KEY")"
  echo "[cyberWatch] LLEN cyberWatch:targets=$(redis-cli LLEN "cyberWatch:targets")"
else
  echo "[cyberWatch] redis=not running or redis-cli missing; skipping queue length check"
fi

echo "[cyberWatch] smoke complete"
