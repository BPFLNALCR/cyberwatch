#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
SCHEMA_FILE="$ROOT_DIR/cyberWatch/db/schema.sql"
ENV_FILE="/etc/cyberwatch/cyberwatch.env"
DEFAULT_DSN="${CYBERWATCH_PG_DSN:-}"
PURGE_PACKAGES="no"
SYSTEMD_UNITS=(cyberWatch-api.service cyberWatch-ui.service cyberWatch-enrichment.service cyberWatch-dns-collector.service cyberWatch-remeasure.service)
SYSTEMD_TEMPLATE_UNITS=(cyberWatch-worker@.service)
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
    log "Dropping all cyberWatch tables on $dsn"
    if ! PGPASSWORD="$pgpass" psql "$dsn" -c "DROP TABLE IF EXISTS dns_queries, dns_targets, hops, measurements, targets, asns, settings CASCADE;"; then
      warn "Failed to drop tables. Check credentials/DSN and try again."
    fi
    
    # Optionally drop the entire database and user
    if prompt_yes_no "Drop entire cyberWatch database and user?" "n"; then
      log "Dropping cyberWatch database and user"
      PGPASSWORD="$pgpass" psql "$dsn" -c "DROP DATABASE IF EXISTS cyberwatch;" 2>/dev/null || true
      PGPASSWORD="$pgpass" psql "$dsn" -c "DROP USER IF EXISTS cyberwatch;" 2>/dev/null || true
    fi
  fi
}

remove_redis_data() {
  if ! command -v redis-cli >/dev/null 2>&1; then
    log "redis-cli not found; skipping Redis cleanup."
    return
  fi
  
  if prompt_yes_no "Clear cyberWatch Redis queues and data?" "y"; then
    log "Clearing cyberWatch Redis data"
    redis-cli DEL cyberwatch:targets 2>/dev/null || true
    redis-cli KEYS "cyberwatch:*" | xargs -r redis-cli DEL 2>/dev/null || true
    log "Redis data cleared"
  fi
}

remove_neo4j() {
  if ! command -v systemctl >/dev/null 2>&1; then
    log "systemctl not found; skipping Neo4j removal."
    return
  fi
  
  if ! systemctl list-unit-files | grep -q "neo4j.service"; then
    log "Neo4j service not found; skipping Neo4j removal."
    return
  fi
  
  if prompt_yes_no "Remove Neo4j and clean all data?" "y"; then
    log "Stopping and disabling Neo4j service"
    sudo systemctl stop neo4j.service || true
    sudo systemctl disable neo4j.service || true
    
    log "Removing all Neo4j data and configuration"
    # Remove all Neo4j data including auth files
    sudo rm -rf /var/lib/neo4j/data/* || true
    sudo rm -rf /var/lib/neo4j/data/dbms/auth* || true
    sudo rm -rf /var/lib/neo4j/data/databases/* || true
    sudo rm -rf /var/lib/neo4j/data/transactions/* || true
    sudo rm -rf /var/lib/neo4j/logs/* || true
    
    # Remove Neo4j configuration
    sudo rm -rf /etc/neo4j/* || true
    
    if [[ "$PURGE_PACKAGES" == "yes" ]]; then
      log "Purging Neo4j package"
      sudo apt-get purge -y neo4j || true
      sudo rm -f /etc/apt/sources.list.d/neo4j.list || true
      sudo rm -f /usr/share/keyrings/neo4j.gpg || true
    else
      log "To fully remove Neo4j package, run with --purge flag"
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
  # Stop and disable regular services
  for unit in "${SYSTEMD_UNITS[@]}"; do
    if systemctl list-unit-files | grep -q "$unit"; then
      log "Stopping and disabling $unit"
      sudo systemctl stop "$unit" || true
      sudo systemctl disable "$unit" || true
      sudo rm -f "/etc/systemd/system/$unit"
    fi
  done
  
  # Stop and disable template-based services (workers)
  for unit in "${SYSTEMD_TEMPLATE_UNITS[@]}"; do
    if systemctl list-unit-files | grep -q "$unit"; then
      log "Stopping and disabling all $unit instances"
      # Stop all running instances
      sudo systemctl stop "${unit%@*}@*.service" 2>/dev/null || true
      # Disable all enabled instances
      for instance in /etc/systemd/system/multi-user.target.wants/${unit%@*}@*.service; do
        if [[ -f "$instance" ]]; then
          instance_name=$(basename "$instance")
          log "Disabling $instance_name"
          sudo systemctl disable "$instance_name" || true
        fi
      done
      # Remove template file
      sudo rm -f "/etc/systemd/system/$unit"
    fi
  done
  
  sudo systemctl daemon-reload || true
  log "All cyberWatch services removed"
}

remove_dns_config() {
  if [[ -f "$DNS_CONFIG_DEST" ]] && prompt_yes_no "Remove DNS config at $DNS_CONFIG_DEST?" "n"; then
    log "Removing $DNS_CONFIG_DEST"
    sudo rm -f "$DNS_CONFIG_DEST"
  fi
}

remove_config_files() {
  if prompt_yes_no "Remove all cyberWatch config files in /etc/cyberwatch/?" "y"; then
    log "Removing /etc/cyberwatch directory"
    sudo rm -rf /etc/cyberwatch || true
  fi
}

remove_logs() {
  if [[ -d "$ROOT_DIR/logs" ]] && prompt_yes_no "Remove log files in $ROOT_DIR/logs/?" "y"; then
    log "Removing logs directory"
    rm -rf "$ROOT_DIR/logs" || true
  fi
}

main() {
  log "Starting cyberWatch uninstallation..."
  log ""
  
  # Stop and remove all services first
  remove_services
  
  # Clean up data stores
  remove_redis_data
  maybe_drop_tables
  remove_neo4j
  
  # Remove application files
  remove_venv
  remove_logs
  clean_var_lib
  
  # Remove configuration
  remove_config_files  # This includes DNS config
  
  # Optionally purge packages
  purge_packages
  
  log ""
  log "=== Uninstall complete ==="
  log ""
  log "Remaining manual cleanup (if needed):"
  log "  - Review and remove: $ROOT_DIR (source code)"
  log "  - Check PostgreSQL: psql -c '\\l' (for cyberwatch database)"
  log "  - Check Redis: redis-cli KEYS 'cyberwatch:*'"
  log "  - Check Neo4j: sudo systemctl status neo4j"
  log ""
}

main "$@"
