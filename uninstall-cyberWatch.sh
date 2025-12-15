#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
SCHEMA_FILE="$ROOT_DIR/cyberWatch/db/schema.sql"
ENV_FILE="/etc/cyberwatch/cyberwatch.env"
DEFAULT_DSN="${CYBERWATCH_PG_DSN:-}"
PURGE_PACKAGES="no"
SYSTEMD_UNITS=(cyberWatch-api.service cyberWatch-ui.service cyberWatch-enrichment.service cyberWatch-dns-collector.service)
DNS_CONFIG_DEST="/etc/cyberwatch/dns.yaml"

log() { printf "[cyberWatch] %s\n" "$*"; }
warn() { printf "[cyberWatch][warn] %s\n" "$*"; }

read_env_var() {
  local file="$1" key="$2"
  if sudo test -f "$file"; then
    # shellcheck disable=SC2002
    sudo cat "$file" | awk -F= -v k="$key" '$1==k {sub(/^"|"$/, "", $2); print $2; exit}'
  fi
}

sanitize_dsn() {
  local dsn="$1"
  dsn="${dsn#${dsn%%[![:space:]]*}}"   # trim leading space
  dsn="${dsn%${dsn##*[![:space:]]}}"   # trim trailing space
  dsn="${dsn%]}"                       # strip accidental trailing bracket
  dsn="${dsn%\"}"; dsn="${dsn#\"}"    # strip surrounding quotes
  dsn="${dsn%\'}"; dsn="${dsn#\'}"  # strip surrounding single quotes
  printf '%s' "$dsn"
}

dsn_password() {
  local dsn
  dsn="$(sanitize_dsn "$1")"
  python3 - "$dsn" <<'PY'
import sys
from urllib.parse import urlparse

dsn = sys.argv[1]
u = urlparse(dsn)
print(u.password or "")
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge)
      PURGE_PACKAGES="yes"
      shift
      ;;
    *)
      warn "Unknown argument: $1"
      shift
      ;;
  esac
done

prompt_yes_no() {
  local prompt="$1" default_yes="$2" reply
  if [[ "${CI:-}" == "true" || "${CYBERWATCH_DROP_DB:-}" != "" ]]; then
    [[ "${CYBERWATCH_DROP_DB:-}" == "1" ]] && return 0 || return 1
  fi
  if [[ "$default_yes" == "y" ]]; then
    prompt+=" [Y/n]: "
  else
    prompt+=" [y/N]: "
  fi
  read -r -p "$prompt" reply || true
  reply=${reply:-$default_yes}
  [[ "$reply" =~ ^[Yy]$ ]]
}

remove_venv() {
  if [[ -d "$VENV_DIR" ]]; then
    log "Removing venv at $VENV_DIR"
    rm -rf "$VENV_DIR"
  else
    log "No venv to remove."
  fi
}

maybe_drop_tables() {
  if ! command -v psql >/dev/null 2>&1; then
    warn "psql not found; skipping DB drop."
    return
  fi
  local dsn
  dsn=$(sanitize_dsn "${DEFAULT_DSN:-}")
  if [[ -z "$dsn" ]]; then
    dsn=$(sanitize_dsn "$(read_env_var "$ENV_FILE" "CYBERWATCH_PG_DSN" || true)")
  fi
  if [[ -z "$dsn" ]]; then
    dsn="postgresql://postgres:postgres@localhost:5432/cyberWatch"
  fi
  local pgpass="${PGPASSWORD:-}"
  if prompt_yes_no "Drop cyberWatch tables?" "n"; then
    read -r -p "PostgreSQL DSN [$dsn]: " input_dsn || true
    dsn=$(sanitize_dsn "${input_dsn:-$dsn}")
    if [[ -z "$pgpass" ]]; then
      pgpass=$(dsn_password "$dsn")
    fi
    if [[ -z "$pgpass" ]]; then
      read -r -s -p "PostgreSQL password (optional, Enter to skip): " pgpass || true
      echo
    fi
    log "Dropping tables on $dsn"
    if ! PGPASSWORD="$pgpass" psql "$dsn" -c "DROP TABLE IF EXISTS dns_queries, dns_targets, hops, measurements, targets CASCADE;"; then
      warn "Failed to drop tables. Check credentials/DSN and try again."
    fi
  fi
}

purge_packages() {
  if [[ "$PURGE_PACKAGES" != "yes" ]]; then
    return
  fi
  local pkgs=(redis-server postgresql-client traceroute scamper)
  log "Purging packages: ${pkgs[*]}"
  sudo apt-get remove -y "${pkgs[@]}"
}

clean_var_lib() {
  if [[ -d /var/lib/cyberWatch ]]; then
    log "Cleaning /var/lib/cyberWatch"
    sudo rm -rf /var/lib/cyberWatch
  fi
}

remove_services() {
  for unit in "${SYSTEMD_UNITS[@]}"; do
    if systemctl list-unit-files | grep -q "$unit"; then
      log "Disabling $unit"
      sudo systemctl stop "$unit" || true
      sudo systemctl disable "$unit" || true
      sudo rm -f "/etc/systemd/system/$unit"
    fi
  done
  sudo systemctl daemon-reload || true
}

remove_dns_config() {
  if [[ -f "$DNS_CONFIG_DEST" ]] && prompt_yes_no "Remove DNS config at $DNS_CONFIG_DEST?" "n"; then
    log "Removing $DNS_CONFIG_DEST"
    sudo rm -f "$DNS_CONFIG_DEST"
  fi
}

main() {
  remove_services
  remove_venv
  maybe_drop_tables
  clean_var_lib
  remove_dns_config
  purge_packages
  log "Uninstall complete."
}

main "$@"
