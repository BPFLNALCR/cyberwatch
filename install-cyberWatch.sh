#!/usr/bin/env bash
set -euo pipefail

# Idempotent installer for cyberWatch on Debian 12+

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
REQ_FILE="$ROOT_DIR/cyberWatch/requirements.txt"
SCHEMA_FILE="$ROOT_DIR/cyberWatch/db/schema.sql"
DNS_SCHEMA_FILE="$ROOT_DIR/cyberWatch/db/dns_schema.sql"
SYSTEMD_DIR="$ROOT_DIR/systemd"
ENV_DIR="/etc/cyberwatch"
ENV_FILE_DEST="$ENV_DIR/cyberwatch.env"
DEFAULT_DSN="${CYBERWATCH_PG_DSN:-}"
DNS_CONFIG_SRC="$ROOT_DIR/config/cyberwatch_dns.example.yaml"
DNS_CONFIG_DEST="/etc/cyberwatch/dns.yaml"

log() { printf "[cyberWatch] %s\n" "$*" >&2; }
warn() { printf "[cyberWatch][warn] %s\n" "$*" >&2; }

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
  # NOTE: postgresql-client alone is not sufficient; we need the server running for localhost schema application.
  local pkgs=(python3 python3-venv python3-pip redis-server postgresql postgresql-client libpq-dev traceroute scamper mtr-tiny curl jq apt-transport-https ca-certificates gnupg)
  log "Installing system packages: ${pkgs[*]}"
  sudo apt-get update -y
  sudo apt-get install -y "${pkgs[@]}"
  
  # Add Neo4j repository and install if not already present
  if ! dpkg -l | grep -q "^ii.*neo4j"; then
    log "Adding Neo4j repository"
    curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/neo4j.gpg
    echo "deb [signed-by=/usr/share/keyrings/neo4j.gpg] https://debian.neo4j.com stable latest" | \
      sudo tee /etc/apt/sources.list.d/neo4j.list >/dev/null
    sudo apt-get update -y
    log "Installing Neo4j"
    sudo apt-get install -y neo4j
  else
    log "Neo4j already installed"
  fi
}

read_env_var() {
  local file="$1" key="$2"
  if ! sudo test -f "$file"; then
    return 1
  fi
  # shellcheck disable=SC2002
  sudo cat "$file" | awk -F= -v k="$key" '$1==k {sub(/^"|"$/, "", $2); print $2; exit}'
}

sanitize_dsn() {
  # Trim whitespace and strip surrounding single/double quotes to avoid accidental trailing quotes in DSNs.
  local dsn="$1"
  # trim leading
  dsn="${dsn#${dsn%%[![:space:]]*}}"
  # trim trailing
  dsn="${dsn%${dsn##*[![:space:]]}}"
  # remove surrounding quotes repeatedly
  while [[ "$dsn" == "\""*"\"" && "$dsn" != "" ]]; do dsn="${dsn#\"}"; dsn="${dsn%\"}"; done
  while [[ "$dsn" == "'"*"'" && "$dsn" != "" ]]; do dsn="${dsn#\'}"; dsn="${dsn%\'}"; done
  # if there is a dangling trailing quote/bracket, drop it
  if [[ "$dsn" == *"\"" && "$dsn" != "" ]]; then dsn="${dsn%\"}"; fi
  if [[ "$dsn" == *"'" && "$dsn" != "" ]]; then dsn="${dsn%\'}"; fi
  if [[ "$dsn" == *"]" && "$dsn" != "" ]]; then dsn="${dsn%]}"; fi
  printf '%s' "$dsn"
}

generate_password() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
}

dsn_to_json() {
  local dsn="$1"
  python3 - "$dsn" <<'PY'
import json
import sys
from urllib.parse import urlparse, parse_qs, unquote

dsn = sys.argv[1]
u = urlparse(dsn)

scheme = u.scheme
if scheme not in ("postgresql", "postgres"):
    # keep best-effort parsing
    pass

qs = parse_qs(u.query)

user = u.username or (qs.get("user", [None])[0])
password = u.password or (qs.get("password", [None])[0])
host = u.hostname or ""
port = u.port or int(qs.get("port", [5432])[0])

dbname = (u.path or "").lstrip("/")
if not dbname:
    dbname = qs.get("dbname", [""])[0]

info = {
    "user": unquote(user) if user else "",
    "password": unquote(password) if password else "",
    "host": host,
    "port": port,
    "dbname": dbname,
    "is_local": (host in ("", "localhost", "127.0.0.1", "::1")),
}

print(json.dumps(info))
PY
}

ensure_postgresql_running() {
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl not found; will try pg_ctlcluster if available."
  else
    # systemctl may exist but be non-functional (e.g., containers/WSL without systemd).
    if systemctl list-unit-files >/dev/null 2>&1; then
      if systemctl list-unit-files | grep -q '^postgresql\.service'; then
        if ! sudo systemctl is-active --quiet postgresql.service; then
          log "Starting postgresql.service"
          sudo systemctl enable postgresql.service >/dev/null 2>&1 || true
          sudo systemctl start postgresql.service || true
        fi
        return 0
      else
        warn "postgresql.service not found (is PostgreSQL installed and systemd managing services?)."
      fi
    else
      warn "systemctl is not functional; will try pg_ctlcluster if available."
    fi
  fi
  if command -v pg_ctlcluster >/dev/null 2>&1; then
    log "Starting PostgreSQL clusters via pg_ctlcluster"
    sudo pg_ctlcluster --all start || true
  fi
}

wait_for_postgres() {
  local host="$1" port="$2"
  if ! command -v pg_isready >/dev/null 2>&1; then
    return 0
  fi
  local tries=20
  while (( tries > 0 )); do
    if [[ -n "$host" ]]; then
      pg_isready -h "$host" -p "$port" >/dev/null 2>&1 && return 0
    else
      pg_isready >/dev/null 2>&1 && return 0
    fi
    sleep 0.5
    tries=$((tries - 1))
  done
  return 1
}

ensure_local_db_and_user() {
  local dsn
  dsn="$(sanitize_dsn "$1")"
  local info
  info="$(dsn_to_json "$dsn")"

  local host port user password dbname is_local
  host="$(printf '%s' "$info" | jq -r '.host')"
  port="$(printf '%s' "$info" | jq -r '.port')"
  user="$(printf '%s' "$info" | jq -r '.user')"
  password="$(printf '%s' "$info" | jq -r '.password')"
  dbname="$(printf '%s' "$info" | jq -r '.dbname')"
  is_local="$(printf '%s' "$info" | jq -r '.is_local')"

  if [[ "$is_local" != "true" ]]; then
    return 0
  fi
  if [[ -z "$dbname" ]]; then
    warn "DSN does not include a database name; skipping DB/user bootstrap."
    return 0
  fi

  ensure_postgresql_running
  if ! wait_for_postgres "$host" "$port"; then
    warn "PostgreSQL did not become ready in time."
    return 1
  fi

  # If the DSN user is blank, default to a dedicated role.
  if [[ -z "$user" || "$user" == "null" ]]; then
    user="cyberwatch"
  fi
  if [[ -z "$password" || "$password" == "null" ]]; then
    password="$(generate_password)"
    # If the DSN had no password, we will update it later by writing ENV_FILE_DEST.
  fi

  log "Ensuring PostgreSQL role '$user' and database '$dbname' exist"
  if sudo -u postgres psql -v ON_ERROR_STOP=1 -tAc "SELECT 1 FROM pg_roles WHERE rolname='${user}'" 2>/dev/null | grep -q 1; then
    # If the role already exists, ensure it can authenticate with the provided password.
    # Avoid touching the built-in 'postgres' role to reduce surprise.
    if [[ -n "$password" && "$user" != "postgres" ]]; then
      sudo -u postgres psql -v ON_ERROR_STOP=1 -q -c "ALTER ROLE \"${user}\" WITH LOGIN PASSWORD '${password}'" >/dev/null
    fi
  else
    sudo -u postgres psql -v ON_ERROR_STOP=1 -q -c "CREATE ROLE \"${user}\" LOGIN PASSWORD '${password}'" >/dev/null
  fi

  sudo -u postgres psql -v ON_ERROR_STOP=1 -tAc "SELECT 1 FROM pg_database WHERE datname='${dbname}'" 2>/dev/null | grep -q 1 \
    || sudo -u postgres psql -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE \"${dbname}\" OWNER \"${user}\"" >/dev/null

  # Make sure the role owns the DB (safe to re-run).
  sudo -u postgres psql -v ON_ERROR_STOP=1 -q -c "ALTER DATABASE \"${dbname}\" OWNER TO \"${user}\"" >/dev/null

  # Export synthesized DSN for later persistence.
  printf '%s' "postgresql://${user}:${password}@${host:-localhost}:${port}/${dbname}"
}

configure_neo4j() {
  local neo4j_password="$1"
  
  log "Configuring Neo4j"
  
  # Enable and start Neo4j service
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl list-unit-files >/dev/null 2>&1; then
      sudo systemctl enable neo4j.service >/dev/null 2>&1 || true
      sudo systemctl start neo4j.service || true
    fi
  fi
  
  # Wait for Neo4j to be ready
  log "Waiting for Neo4j to start..."
  local tries=30
  while (( tries > 0 )); do
    if curl -s http://localhost:7474 >/dev/null 2>&1; then
      log "Neo4j is ready"
      break
    fi
    sleep 2
    tries=$((tries - 1))
  done
  
  if (( tries == 0 )); then
    warn "Neo4j did not become ready in time. You may need to configure it manually."
    warn "Run: cypher-shell -u neo4j -p neo4j"
    warn "Then: ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO 'your_password'"
    return 1
  fi
  
  # Change default password
  log "Setting Neo4j password"
  if command -v cypher-shell >/dev/null 2>&1; then
    cypher-shell -u neo4j -p neo4j "ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO '${neo4j_password}'" 2>/dev/null || {
      log "Neo4j password already set or authentication failed (this is normal if already configured)"
    }
    
    # Apply schema constraints/indexes
    log "Creating Neo4j constraints and indexes"
    cypher-shell -u neo4j -p "${neo4j_password}" <<'CYPHER' 2>/dev/null || true
CREATE CONSTRAINT asn_unique IF NOT EXISTS FOR (a:AS) REQUIRE a.asn IS UNIQUE;
CREATE INDEX asn_org_name IF NOT EXISTS FOR (a:AS) ON (a.org_name);
CREATE INDEX asn_country IF NOT EXISTS FOR (a:AS) ON (a.country);
CYPHER
  else
    warn "cypher-shell not found. Install Neo4j or run schema commands manually."
  fi
  
  log "Neo4j configuration complete"
}

write_env_file() {
  local dsn neo4j_password
  dsn="$(sanitize_dsn "$1")"
  neo4j_password="${2:-$(generate_password)}"
  sudo mkdir -p "$ENV_DIR"

  if sudo test -f "$ENV_FILE_DEST"; then
    local existing
    existing="$(sanitize_dsn "$(read_env_var "$ENV_FILE_DEST" "CYBERWATCH_PG_DSN" || true)")"
    if [[ -n "$existing" && "$existing" == "$dsn" ]]; then
      # DSN matches, check if we should update Neo4j password
      local existing_neo4j_pass
      existing_neo4j_pass="$(read_env_var "$ENV_FILE_DEST" "NEO4J_PASSWORD" || true)"
      if [[ "$existing_neo4j_pass" == "neo4j" ]]; then
        log "Updating Neo4j password in $ENV_FILE_DEST"
      else
        # Return existing Neo4j password
        printf '%s' "${existing_neo4j_pass:-$neo4j_password}"
        return 0
      fi
    fi
    if prompt_yes_no "Update $ENV_FILE_DEST with the selected DSN?" "y"; then
      log "Updating $ENV_FILE_DEST"
    else
      log "Keeping existing $ENV_FILE_DEST"
      local existing_neo4j_pass
      existing_neo4j_pass="$(read_env_var "$ENV_FILE_DEST" "NEO4J_PASSWORD" || true)"
      printf '%s' "${existing_neo4j_pass:-$neo4j_password}"
      return 0
    fi
  else
    log "Creating $ENV_FILE_DEST"
  fi

  sudo tee "$ENV_FILE_DEST" >/dev/null <<EOF
CYBERWATCH_PG_DSN="$dsn"
CYBERWATCH_REDIS_URL="redis://localhost:6379/0"
NEO4J_URI="bolt://localhost:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="$neo4j_password"
EOF
  sudo chmod 0640 "$ENV_FILE_DEST" || true
  printf '%s' "$neo4j_password"
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
  # Remove deprecated aioredis if present (replaced by redis package with async support)
  pip uninstall aioredis -y 2>/dev/null || true
  pip install -r "$REQ_FILE"
}

apply_schema() {
  local dsn
  dsn="$(sanitize_dsn "$1")"
  if ! command -v psql >/dev/null 2>&1; then
    warn "psql not found; skipping schema application."
    return
  fi
  ensure_postgresql_running
  local info
  info="$(dsn_to_json "$dsn")"
  if ! wait_for_postgres "$(printf '%s' "$info" | jq -r '.host')" "$(printf '%s' "$info" | jq -r '.port')"; then
    warn "PostgreSQL is not reachable; cannot apply schema."
    warn "If using localhost, ensure 'postgresql' is installed and the service is running."
    return 1
  fi
  log "Applying schema to $dsn"
  psql -v ON_ERROR_STOP=1 "$dsn" -f "$SCHEMA_FILE"
  if [[ -f "$DNS_SCHEMA_FILE" ]]; then
    log "Applying DNS schema to $dsn"
    psql -v ON_ERROR_STOP=1 "$dsn" -f "$DNS_SCHEMA_FILE"
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

  # Prefer persisted DSN (used by systemd units) if present.
  if [[ -z "$DEFAULT_DSN" ]]; then
    DEFAULT_DSN="$(sanitize_dsn "$(read_env_var "$ENV_FILE_DEST" "CYBERWATCH_PG_DSN" || true)")"
  else
    DEFAULT_DSN="$(sanitize_dsn "$DEFAULT_DSN")"
  fi
  if [[ -z "$DEFAULT_DSN" ]]; then
    # Secure-ish default: create a dedicated local role and generate a password.
    local pw
    pw="$(generate_password)"
    DEFAULT_DSN="postgresql://cyberwatch:${pw}@localhost:5432/cyberWatch"
  fi

  local dsn="$DEFAULT_DSN"
  if prompt_yes_no "Apply PostgreSQL schema now?" "y"; then
    read -r -p "PostgreSQL DSN [$dsn]: " input_dsn || true
      dsn=${input_dsn:-$dsn}
      dsn="$(sanitize_dsn "$dsn")"
    # If this is a local DSN, ensure the role/DB exist and keep credentials consistent.
    local synthesized
    synthesized="$(ensure_local_db_and_user "$dsn" || true)"
    if [[ -n "$synthesized" ]]; then
      dsn="$synthesized"
    fi
    apply_schema "$dsn"
    
    # Persist the final DSN and generate Neo4j password
    local neo4j_password
    neo4j_password=$(write_env_file "$dsn")
    
    # Configure Neo4j with generated password
    if prompt_yes_no "Configure Neo4j now?" "y"; then
      configure_neo4j "$neo4j_password"
    else
      log "Skipping Neo4j configuration. You can configure it manually later."
      log "Default password is stored in $ENV_FILE_DEST"
    fi
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
