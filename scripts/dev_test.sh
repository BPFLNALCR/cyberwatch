#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/mnt/c/Users/User/cyberwatch"

cd "$REPO_ROOT"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

echo "[cyberWatch] repo=$REPO_ROOT"
echo "[cyberWatch] python=$("$PYTHON" --version 2>&1)"

echo "[cyberWatch] compiling package"
"$PYTHON" -m compileall cyberWatch

echo "[cyberWatch] running pytest"
"$PYTHON" -m pytest "$@"
