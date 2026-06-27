#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/mnt/c/Users/User/cyberwatch"

cd "$REPO_ROOT"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

export CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS="${CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS:-false}"
export CYBERWATCH_DNS_STORE_CLIENT_IPS="${CYBERWATCH_DNS_STORE_CLIENT_IPS:-false}"
export CYBERWATCH_PG_DSN="${CYBERWATCH_PG_DSN:-postgresql://cyberwatch_test:cyberwatch_test@localhost:5432/cyberwatch_test}"
export CYBERWATCH_REDIS_URL="${CYBERWATCH_REDIS_URL:-redis://localhost:6379/0}"
export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-neo4j}"

HOST="${CYBERWATCH_API_HOST:-127.0.0.1}"
PORT="${CYBERWATCH_API_PORT:-8000}"

echo "[cyberWatch] repo=$REPO_ROOT"
echo "[cyberWatch] api=http://$HOST:$PORT"
echo "[cyberWatch] destructive_settings=$CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS"

"$PYTHON" - <<'PY'
import importlib.util
import sys

if importlib.util.find_spec("uvicorn") is None:
    sys.exit("uvicorn is not installed in the selected Python environment")
PY

exec "$PYTHON" -m uvicorn cyberWatch.api.server:app --host "$HOST" --port "$PORT"
