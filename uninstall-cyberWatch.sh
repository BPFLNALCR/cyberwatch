#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
SCHEMA_FILE="$ROOT_DIR/cyberWatch/db/schema.sql"
DEFAULT_DSN="${CYBERWATCH_PG_DSN:-postgresql://postgres:postgres@localhost:5432/cyberWatch}"
PURGE_PACKAGES="no"
SYSTEMD_UNITS=(cyberWatch-api.service cyberWatch-ui.service cyberWatch-enrichment.service cyberWatch-dns-collector.service)
DNS_CONFIG_DEST="/etc/cyberwatch/dns.yaml"

log() { printf "[cyberWatch] %s\n" "$*"; }
warn() { printf "[cyberWatch][warn] %s\n" "$*"; }

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
  local dsn="$DEFAULT_DSN"
  local pgpass="${PGPASSWORD:-}"
  if prompt_yes_no "Drop cyberWatch tables?" "n"; then
    read -r -p "PostgreSQL DSN [$dsn]: " input_dsn || true
    dsn=${input_dsn:-$dsn}
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
