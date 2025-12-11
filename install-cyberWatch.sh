#!/usr/bin/env bash
set -euo pipefail

# Idempotent installer for cyberWatch on Debian 12+

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
REQ_FILE="$ROOT_DIR/cyberWatch/requirements.txt"
SCHEMA_FILE="$ROOT_DIR/cyberWatch/db/schema.sql"
DNS_SCHEMA_FILE="$ROOT_DIR/cyberWatch/db/dns_schema.sql"
SYSTEMD_DIR="$ROOT_DIR/systemd"
DEFAULT_DSN="${CYBERWATCH_PG_DSN:-postgresql://postgres:postgres@localhost:5432/cyberWatch}"
DNS_CONFIG_SRC="$ROOT_DIR/config/cyberwatch_dns.example.yaml"
DNS_CONFIG_DEST="/etc/cyberwatch/dns.yaml"

log() { printf "[cyberWatch] %s\n" "$*"; }
warn() { printf "[cyberWatch][warn] %s\n" "$*"; }

prompt_yes_no() {
  local prompt="$1" default_yes="$2" reply
  if [[ "${CI:-}" == "true" || "${CYBERWATCH_APPLY_SCHEMA:-}" != "" ]]; then
    # non-interactive: respect CYBERWATCH_APPLY_SCHEMA=1
    [[ "${CYBERWATCH_APPLY_SCHEMA:-}" == "1" ]] && return 0 || return 1
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

detect_env() {
  local in_container="no" in_vm="no"
  if grep -qi "docker\|lxc" /proc/1/cgroup 2>/dev/null; then in_container="yes"; fi
  if [[ -f /sys/class/dmi/id/product_name ]]; then
    if grep -qi "vmware\|kvm\|virtualbox\|hyper-v" /sys/class/dmi/id/product_name; then in_vm="yes"; fi
  fi
  log "Environment: container=${in_container}, vm=${in_vm}"
}

require_debian() {
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "${ID}" != "debian" && "${ID_LIKE}" != *"debian"* ]]; then
      warn "Non-Debian system detected (${ID:-unknown}); continuing but packages may differ."
    fi
  else
    warn "Cannot detect OS; assuming Debian-like."
  fi
}

install_packages() {
  local pkgs=(python3 python3-venv python3-pip redis-server postgresql-client libpq-dev traceroute scamper mtr-tiny curl jq)
  log "Installing system packages: ${pkgs[*]}"
  sudo apt-get update -y
  sudo apt-get install -y "${pkgs[@]}"
}

create_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating venv at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  else
    log "Reusing existing venv at $VENV_DIR"
  fi
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
  pip install --upgrade pip
  pip install -r "$REQ_FILE"
}

apply_schema() {
  local dsn="$1"
  if ! command -v psql >/dev/null 2>&1; then
    warn "psql not found; skipping schema application."
    return
  fi
  log "Applying schema to $dsn"
  PGPASSWORD="${PGPASSWORD:-}" psql "$dsn" -f "$SCHEMA_FILE"
  if [[ -f "$DNS_SCHEMA_FILE" ]]; then
    log "Applying DNS schema to $dsn"
    PGPASSWORD="${PGPASSWORD:-}" psql "$dsn" -f "$DNS_SCHEMA_FILE"
  fi
}

install_dns_config() {
  if [[ ! -f "$DNS_CONFIG_SRC" ]]; then
    warn "DNS example config missing at $DNS_CONFIG_SRC"
    return
  fi
  sudo mkdir -p "$(dirname "$DNS_CONFIG_DEST")"
  if [[ ! -f "$DNS_CONFIG_DEST" ]]; then
    log "Installing DNS config to $DNS_CONFIG_DEST"
    sudo cp "$DNS_CONFIG_SRC" "$DNS_CONFIG_DEST"
  else
    log "DNS config already present at $DNS_CONFIG_DEST"
  fi
}

install_service() {
  local unit_name="$1" template_file="$2"
  if [[ ! -f "$template_file" ]]; then
    warn "Missing service template $template_file"
    return
  fi
  local target="/etc/systemd/system/$unit_name"
  log "Installing systemd unit $unit_name"
  sudo sed "s|@ROOT_DIR@|$ROOT_DIR|g" "$template_file" | sudo tee "$target" >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable "$unit_name"
  sudo systemctl restart "$unit_name" || sudo systemctl start "$unit_name"
}

main() {
  detect_env
  require_debian
  install_packages
  create_venv

  local dsn="$DEFAULT_DSN"
  if prompt_yes_no "Apply PostgreSQL schema now?" "y"; then
    read -r -p "PostgreSQL DSN [$dsn]: " input_dsn || true
      dsn=${input_dsn:-$dsn}
    apply_schema "$dsn"
  else
    log "Skipping schema application."
  fi

  install_dns_config
  log "Install complete. Activate venv with: source $VENV_DIR/bin/activate"
  if [[ -d "$SYSTEMD_DIR" ]]; then
    install_service "cyberWatch-api.service" "$SYSTEMD_DIR/cyberWatch-api.service"
    install_service "cyberWatch-ui.service" "$SYSTEMD_DIR/cyberWatch-ui.service"
    install_service "cyberWatch-enrichment.service" "$SYSTEMD_DIR/cyberWatch-enrichment.service"
    install_service "cyberWatch-dns-collector.service" "$SYSTEMD_DIR/cyberWatch-dns-collector.service"
  fi
}

main "$@"
