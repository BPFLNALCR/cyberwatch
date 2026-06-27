#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${CYBERWATCH_SMOKE_API_BASE:-http://localhost:8000}"
SNAPSHOT_CONFIRMED="${CYBERWATCH_VM_SNAPSHOT_CONFIRMED:-}"
SNAPSHOT_LABEL="${CYBERWATCH_VM_SNAPSHOT_LABEL:-unrecorded}"
ALLOW_LIFECYCLE="no"

STATUSES=(PASS FAIL SKIP WARN)
CHECK_IDS=(
  vm_baseline
  line_endings
  install
  uninstall_reinstall
  service_status
  api_root
  api_health
  destructive_clear_dns
  pure_pytest
  enrichment_import
  enrichment_service
  redis_queue_key
  journals
  bind_exposure
)
JOURNAL_UNITS=(
  cyberWatch-api.service
  cyberWatch-ui.service
  'cyberWatch-worker@*'
  cyberWatch-enrichment.service
  cyberWatch-dns-collector.service
  cyberWatch-remeasure.service
)
SERVICE_UNITS=(
  postgresql.service
  redis-server.service
  neo4j.service
  cyberWatch-api.service
  cyberWatch-ui.service
  cyberWatch-enrichment.service
  cyberWatch-dns-collector.service
  cyberWatch-remeasure.service
)
OWNED_RESOURCES=(
  /etc/cyberwatch
  /var/lib/cyberwatch
  "$ROOT_DIR/.venv"
  "$ROOT_DIR/logs"
  cyberWatch-api.service
  cyberWatch-ui.service
  cyberWatch-enrichment.service
  cyberWatch-dns-collector.service
  cyberWatch-remeasure.service
  'cyberWatch-worker@.service'
  cyberwatch:targets
  cyberWatch:targets
)

usage() {
  cat <<'EOF'
Usage: scripts/cyberwatch-vm-smoke.sh [OPTIONS]

Offline helper options:
  --list-statuses
  --list-checks
  --list-owned-resources
  --journal-commands
  --pytest-command
  --classify-bind VALUE
  --assert-debian13 FILE
  --require-snapshot
  --check-line-endings [FILE...]
  --redis-migration-message CANONICAL_DEPTH LEGACY_DEPTH

VM-only smoke options:
  --run-baseline
  --run-line-endings
  --run-pure-tests
  --run-api
  --run-guardrails
  --run-redis
  --run-services
  --run-bind
  --run-enrichment
  --run-journals
  --run-install
  --run-uninstall-reinstall
  --run-all

Lifecycle gates:
  --allow-lifecycle            Allow install/uninstall/reinstall commands.
  --yes-snapshot               Confirm the current VM has a restoreable snapshot.
  --snapshot-label LABEL       Record the VM snapshot label in results.
EOF
}

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

emit_result() {
  local status="$1" check_id="$2" command_surface="$3" expected="$4" observed="$5" evidence="${6:-none}"
  printf 'check_id=%s status=%s command_surface=%q expected_outcome=%q observed_outcome=%q failure_evidence=%q vm_snapshot_state=%q timestamp=%s\n' \
    "$check_id" "$status" "$command_surface" "$expected" "$observed" "$evidence" "$SNAPSHOT_LABEL" "$(timestamp)"
}

list_statuses() {
  printf '%s\n' "${STATUSES[@]}"
}

list_checks() {
  printf '%s\n' "${CHECK_IDS[@]}"
}

list_owned_resources() {
  printf '%s\n' "${OWNED_RESOURCES[@]}"
}

journal_commands() {
  local unit
  for unit in "${JOURNAL_UNITS[@]}"; do
    printf "journalctl -u '%s' -n 80 --no-pager\n" "$unit"
  done
}

run_journalctl() {
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo journalctl "$@"
  else
    journalctl "$@"
  fi
}

pytest_command() {
  printf 'python -m pytest\n'
}

resolve_python_bin() {
  if command -v python >/dev/null 2>&1; then
    printf 'python\n'
    return 0
  fi
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$ROOT_DIR/.venv/bin/python"
    return 0
  fi
  return 1
}

os_release_value() {
  local file="$1" key="$2"
  awk -F= -v wanted="$key" '
    $1 == wanted {
      value=$2
      gsub(/^"/, "", value)
      gsub(/"$/, "", value)
      print value
      exit
    }
  ' "$file"
}

assert_debian13() {
  local file="${1:-/etc/os-release}"
  local os_id version pretty
  if [[ ! -f "$file" ]]; then
    emit_result FAIL vm_baseline "cat $file" "Debian 13 os-release" "missing os-release file" "$file"
    return 1
  fi
  os_id="$(os_release_value "$file" ID)"
  version="$(os_release_value "$file" VERSION_ID)"
  pretty="$(os_release_value "$file" PRETTY_NAME)"
  if [[ "$os_id" == "debian" && "$version" == 13* ]]; then
    emit_result PASS vm_baseline "cat $file" "Debian 13" "${pretty:-Debian $version}"
    return 0
  fi
  emit_result FAIL vm_baseline "cat $file" "Debian 13" "ID=$os_id VERSION_ID=$version PRETTY_NAME=$pretty"
  return 1
}

require_snapshot() {
  if [[ "$SNAPSHOT_CONFIRMED" == "1" || "$SNAPSHOT_CONFIRMED" == "true" || "$SNAPSHOT_CONFIRMED" == "yes" ]]; then
    emit_result PASS vm_baseline "snapshot confirmation" "restoreable VM snapshot confirmed" "snapshot=$SNAPSHOT_LABEL"
    return 0
  fi
  emit_result FAIL vm_baseline "snapshot confirmation" "restoreable VM snapshot confirmed" "snapshot confirmation missing"
  return 1
}

classify_bind() {
  local bind_value="$1" host
  host="${bind_value%%:*}"
  case "$host" in
    0.0.0.0|"[::]"|"::"|*) ;;
  esac
  case "$bind_value" in
    0.0.0.0:*|"[::]":*|"::":*)
      printf 'all-interfaces\n'
      ;;
    127.0.0.1:*|localhost:*|"[::1]":*|"::1":*)
      printf 'localhost-only\n'
      ;;
    "")
      printf 'unknown\n'
      ;;
    *)
      printf 'explicit:%s\n' "$bind_value"
      ;;
  esac
}

collect_line_ending_files() {
  find "$ROOT_DIR" \
    -path "$ROOT_DIR/.git" -prune -o \
    -path "$ROOT_DIR/.venv" -prune -o \
    \( -name '*.sh' -o -path "$ROOT_DIR/systemd/*.service" \) \
    -type f -print
}

check_line_endings() {
  local files=("$@")
  local file violations=()
  if [[ "${#files[@]}" -eq 0 ]]; then
    mapfile -t files < <(collect_line_ending_files)
  fi
  for file in "${files[@]}"; do
    if [[ -f "$file" ]] && LC_ALL=C grep -q $'\r' "$file"; then
      violations+=("$file")
    fi
  done
  if [[ "${#violations[@]}" -gt 0 ]]; then
    emit_result FAIL line_endings "scan shell scripts and systemd units" "zero CRLF files" "CRLF files: ${violations[*]}" "${violations[*]}"
    return 1
  fi
  emit_result PASS line_endings "scan shell scripts and systemd units" "zero CRLF files" "checked ${#files[@]} files"
  return 0
}

queue_key_status_text() {
  local canonical_depth="$1" legacy_depth="$2"
  if [[ "$legacy_depth" =~ ^[0-9]+$ && "$legacy_depth" -gt 0 ]]; then
    printf 'WARN\n'
  elif [[ "$canonical_depth" =~ ^[0-9]+$ ]]; then
    printf 'PASS\n'
  else
    printf 'FAIL\n'
  fi
}

redis_migration_message() {
  local canonical_depth="$1" legacy_depth="$2"
  printf 'Canonical Redis queue is cyberwatch:targets with depth %s. Legacy key cyberWatch:targets has depth %s. If legacy depth is nonzero, migrate intentionally with: while redis-cli LLEN cyberWatch:targets | grep -vq "^0$"; do redis-cli RPOPLPUSH cyberWatch:targets cyberwatch:targets >/dev/null; done\n' \
    "$canonical_depth" "$legacy_depth"
}

check_redis_queue() {
  if ! command -v redis-cli >/dev/null 2>&1; then
    emit_result SKIP redis_queue_key "redis-cli LLEN cyberwatch:targets cyberWatch:targets" "Redis queue keys inspected" "redis-cli not available"
    return 0
  fi
  local canonical legacy status message
  canonical="$(redis-cli LLEN cyberwatch:targets 2>/dev/null || printf 'unavailable')"
  legacy="$(redis-cli LLEN cyberWatch:targets 2>/dev/null || printf 'unavailable')"
  status="$(queue_key_status_text "$canonical" "$legacy")"
  message="$(redis_migration_message "$canonical" "$legacy")"
  emit_result "$status" redis_queue_key "redis-cli LLEN cyberwatch:targets cyberWatch:targets" "canonical key cyberwatch:targets; legacy key reported" "$message"
}

check_codex() {
  if ! command -v codex >/dev/null 2>&1; then
    emit_result FAIL vm_baseline "codex --version" "Codex CLI installed and authenticated" "codex command missing"
    return 1
  fi
  local version auth_output auth_status
  version="$(codex --version 2>&1 || true)"
  auth_output="$(codex auth status 2>&1 || codex login status 2>&1 || true)"
  auth_status="unknown"
  if printf '%s\n' "$auth_output" | grep -Eiq 'authenticated|logged in|success|ready'; then
    auth_status="authenticated"
  fi
  if [[ "$auth_status" == "authenticated" ]]; then
    emit_result PASS vm_baseline "codex --version; codex auth status" "Codex CLI installed and authenticated" "$version; $auth_status"
  else
    emit_result WARN vm_baseline "codex --version; codex auth status" "Codex CLI installed and authenticated" "$version; auth status not confirmed" "$auth_output"
  fi
}

run_baseline() {
  local rc=0
  assert_debian13 /etc/os-release || rc=1
  require_snapshot || rc=1
  check_codex || rc=1
  if [[ "$ROOT_DIR" == *cyberwatch* || "$ROOT_DIR" == *cyberWatch* ]]; then
    emit_result PASS vm_baseline "pwd" "repository checkout under test" "$ROOT_DIR"
  else
    emit_result WARN vm_baseline "pwd" "repository checkout under test" "$ROOT_DIR"
  fi
  return "$rc"
}

run_pure_tests() {
  local log_file rc python_bin
  if ! python_bin="$(resolve_python_bin)"; then
    emit_result FAIL pure_pytest "python -m pytest" "offline tests pass" "python command missing and repo venv unavailable"
    return 1
  fi
  log_file="$(mktemp)"
  if (cd "$ROOT_DIR" && "$python_bin" -m pytest >"$log_file" 2>&1); then
    emit_result PASS pure_pytest "python -m pytest" "offline tests pass" "$python_bin $(tail -n 5 "$log_file" | tr '\n' ' ')"
    rc=0
  else
    rc=$?
    emit_result FAIL pure_pytest "python -m pytest" "offline tests pass" "$python_bin $(tail -n 20 "$log_file" | tr '\n' ' ')" "$log_file"
  fi
  return "$rc"
}

ensure_lifecycle_allowed() {
  local check_id="${1:-install}"
  if [[ "$ALLOW_LIFECYCLE" != "yes" ]]; then
    emit_result SKIP "$check_id" "lifecycle gate" "explicit --allow-lifecycle" "lifecycle flag not supplied"
    return 1
  fi
  require_snapshot >/dev/null || {
    emit_result SKIP "$check_id" "snapshot gate" "restoreable VM snapshot confirmed" "snapshot confirmation missing"
    return 1
  }
  if [[ "$(id -u)" -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1 || ! sudo -n true >/dev/null 2>&1; then
      emit_result SKIP "$check_id" "privilege gate" "root or passwordless sudo available for lifecycle commands" "current user cannot run privileged lifecycle commands non-interactively"
      return 1
    fi
  fi
}

run_install() {
  ensure_lifecycle_allowed install || return 0
  check_line_endings || return 1
  local log_file rc
  log_file="$(mktemp)"
  if (cd "$ROOT_DIR" && ./install-cyberWatch.sh >"$log_file" 2>&1); then
    emit_result PASS install "./install-cyberWatch.sh" "installer completes" "$(tail -n 10 "$log_file" | tr '\n' ' ')"
    rc=0
  else
    rc=$?
    emit_result FAIL install "./install-cyberWatch.sh" "installer completes" "$(tail -n 30 "$log_file" | tr '\n' ' ')" "$log_file"
  fi
  return "$rc"
}

run_uninstall_reinstall() {
  ensure_lifecycle_allowed uninstall_reinstall || return 0
  check_line_endings || return 1
  local uninstall_log install_log rc
  uninstall_log="$(mktemp)"
  install_log="$(mktemp)"
  if ! (cd "$ROOT_DIR" && CYBERWATCH_UNINSTALL_YES=1 CYBERWATCH_DROP_DB=0 CYBERWATCH_CLEAR_NEO4J=0 ./uninstall-cyberWatch.sh >"$uninstall_log" 2>&1); then
    rc=$?
    emit_result FAIL uninstall_reinstall "./uninstall-cyberWatch.sh" "default uninstall completes within cyberWatch-owned resources" "$(tail -n 30 "$uninstall_log" | tr '\n' ' ')" "$uninstall_log"
    return "$rc"
  fi
  if (cd "$ROOT_DIR" && ./install-cyberWatch.sh >"$install_log" 2>&1); then
    emit_result PASS uninstall_reinstall "./uninstall-cyberWatch.sh; ./install-cyberWatch.sh" "reinstall reaches service-validatable state" "$(tail -n 10 "$install_log" | tr '\n' ' ')"
    rc=0
  else
    rc=$?
    emit_result FAIL uninstall_reinstall "./uninstall-cyberWatch.sh; ./install-cyberWatch.sh" "reinstall reaches service-validatable state" "$(tail -n 30 "$install_log" | tr '\n' ' ')" "$install_log"
  fi
  return "$rc"
}

check_services() {
  if ! command -v systemctl >/dev/null 2>&1; then
    emit_result SKIP service_status "systemctl status" "systemd service state inspected" "systemctl not available"
    return 0
  fi
  local unit failed=() observed=()
  for unit in "${SERVICE_UNITS[@]}"; do
    if systemctl is-active --quiet "$unit"; then
      observed+=("$unit=active")
    else
      observed+=("$unit=$(systemctl is-active "$unit" 2>/dev/null || printf unknown)")
      failed+=("$unit")
    fi
  done
  if systemctl list-units 'cyberWatch-worker@*' --all --no-legend 2>/dev/null | grep -q cyberWatch-worker; then
    observed+=("cyberWatch-worker@*=present")
  else
    failed+=("cyberWatch-worker@*")
    observed+=("cyberWatch-worker@*=missing")
  fi
  if [[ "${#failed[@]}" -eq 0 ]]; then
    emit_result PASS service_status "systemctl status cyberWatch services" "services active or intentionally documented inactive" "${observed[*]}"
  else
    emit_result WARN service_status "systemctl status cyberWatch services" "services active or intentionally documented inactive" "${observed[*]}" "review journalctl for ${failed[*]}"
  fi
}

check_api() {
  local status root_body health_status health_body rc=0
  if ! command -v curl >/dev/null 2>&1; then
    emit_result SKIP api_root "curl $API_BASE/" "API root responds" "curl not available"
    emit_result SKIP api_health "curl $API_BASE/health" "API health responds" "curl not available"
    return 0
  fi
  root_body="$(mktemp)"
  status="$(curl -sS -o "$root_body" -w '%{http_code}' "$API_BASE/" 2>&1 || true)"
  if [[ "$status" =~ ^2 ]]; then
    emit_result PASS api_root "curl $API_BASE/" "2xx response" "HTTP $status $(cat "$root_body")"
  else
    emit_result FAIL api_root "curl $API_BASE/" "2xx response" "HTTP $status $(cat "$root_body" 2>/dev/null || true)"
    rc=1
  fi
  health_body="$(mktemp)"
  health_status="$(curl -sS -o "$health_body" -w '%{http_code}' "$API_BASE/health" 2>&1 || true)"
  if [[ "$health_status" =~ ^2 ]]; then
    emit_result PASS api_health "curl $API_BASE/health" "2xx response" "HTTP $health_status $(cat "$health_body")"
  else
    emit_result FAIL api_health "curl $API_BASE/health" "2xx response" "HTTP $health_status $(cat "$health_body" 2>/dev/null || true)"
    rc=1
  fi
  return "$rc"
}

check_guardrails() {
  if ! command -v curl >/dev/null 2>&1; then
    emit_result SKIP destructive_clear_dns "curl -X POST $API_BASE/settings/clear-dns" "HTTP 403 by default" "curl not available"
    return 0
  fi
  local body status
  body="$(mktemp)"
  status="$(curl -sS -o "$body" -w '%{http_code}' -X POST "$API_BASE/settings/clear-dns" 2>&1 || true)"
  if [[ "$status" == "403" ]]; then
    emit_result PASS destructive_clear_dns "curl -X POST $API_BASE/settings/clear-dns" "HTTP 403 by default" "HTTP 403 $(cat "$body")"
  else
    emit_result FAIL destructive_clear_dns "curl -X POST $API_BASE/settings/clear-dns" "HTTP 403 by default" "HTTP $status $(cat "$body" 2>/dev/null || true)"
    return 1
  fi
}

check_bind_exposure() {
  local output classification="unknown" status="PASS"
  if command -v systemctl >/dev/null 2>&1; then
    output="$(systemctl cat cyberWatch-api.service cyberWatch-ui.service 2>&1 || true)"
  else
    output="systemctl unavailable"
  fi
  if command -v ss >/dev/null 2>&1; then
    output="$output $(ss -ltnp 2>/dev/null | grep -E ':8000|:8080' || true)"
  fi
  if printf '%s\n' "$output" | grep -Eq -- '--host[= ]0\.0\.0\.0|0\.0\.0\.0:(8000|8080)|\[::\]:(8000|8080)|\*:(8000|8080)'; then
    classification="all-interfaces"
    status="WARN"
  elif printf '%s\n' "$output" | grep -Eq -- '--host 127.0.0.1|--host localhost'; then
    classification="localhost-only"
  fi
  emit_result "$status" bind_exposure "systemctl cat; ss -ltnp" "API/UI bind addresses are explicit; all-interface binds warn" "$classification $output"
}

check_enrichment() {
  local python_bin
  if ! python_bin="$(resolve_python_bin)"; then
    emit_result FAIL enrichment_import "python -c 'import cyberWatch.enrichment.run_enrichment'" "import succeeds" "python command missing and repo venv unavailable"
    return 1
  fi
  if "$python_bin" -c 'import cyberWatch.enrichment.run_enrichment' >/tmp/cyberwatch-enrichment-import.out 2>&1; then
    emit_result PASS enrichment_import "python -c 'import cyberWatch.enrichment.run_enrichment'" "import succeeds" "$python_bin import succeeded"
  else
    emit_result FAIL enrichment_import "python -c 'import cyberWatch.enrichment.run_enrichment'" "import succeeds" "$(cat /tmp/cyberwatch-enrichment-import.out)"
    return 1
  fi
  if command -v systemctl >/dev/null 2>&1; then
    local state
    state="$(systemctl is-active cyberWatch-enrichment.service 2>/dev/null || true)"
    case "$state" in
      active)
        emit_result PASS enrichment_service "systemctl status cyberWatch-enrichment.service" "service does not crash immediately" "active"
        ;;
      failed)
        local journal_output
        journal_output="$(run_journalctl -u cyberWatch-enrichment.service -n 40 --no-pager 2>&1 || true)"
        emit_result FAIL enrichment_service "systemctl status cyberWatch-enrichment.service" "service does not crash immediately" "failed" "$(printf '%s\n' "$journal_output" | tail -n 20 | tr '\n' ' ')"
        return 1
        ;;
      *)
        emit_result WARN enrichment_service "systemctl status cyberWatch-enrichment.service" "service does not crash immediately" "state=$state"
        ;;
    esac
  else
    emit_result SKIP enrichment_service "systemctl status cyberWatch-enrichment.service" "service does not crash immediately" "systemctl not available"
  fi
}

check_journals() {
  if ! command -v journalctl >/dev/null 2>&1; then
    emit_result SKIP journals "journalctl -u cyberWatch services" "recent journal lines are inspectable" "journalctl not available"
    return 0
  fi
  local unit output="" journal_output
  for unit in "${JOURNAL_UNITS[@]}"; do
    journal_output="$(run_journalctl -u "$unit" -n 20 --no-pager 2>&1 || true)"
    output="$output [$unit] $(printf '%s\n' "$journal_output" | tail -n 5 | tr '\n' ' ')"
  done
  if printf '%s\n' "$output" | grep -Eiq 'not seeing messages|Failed to add filter|No entries'; then
    emit_result WARN journals "journalctl -u cyberWatch services" "recent journal lines are inspectable" "$output" "journal visibility is limited for the current user"
  else
    emit_result PASS journals "journalctl -u cyberWatch services" "recent journal lines are inspectable" "$output"
  fi
}

run_all() {
  run_baseline || true
  check_line_endings || true
  run_pure_tests || true
  check_services || true
  check_api || true
  check_guardrails || true
  check_redis_queue || true
  check_bind_exposure || true
  check_enrichment || true
  check_journals || true
}

main() {
  if [[ "$#" -eq 0 ]]; then
    usage
    exit 2
  fi

  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --allow-lifecycle)
        ALLOW_LIFECYCLE="yes"
        shift
        ;;
      --yes-snapshot)
        SNAPSHOT_CONFIRMED="yes"
        shift
        ;;
      --snapshot-label)
        SNAPSHOT_LABEL="${2:?missing snapshot label}"
        shift 2
        ;;
      --list-statuses)
        list_statuses
        shift
        ;;
      --list-checks)
        list_checks
        shift
        ;;
      --list-owned-resources)
        list_owned_resources
        shift
        ;;
      --journal-commands)
        journal_commands
        shift
        ;;
      --pytest-command)
        pytest_command
        shift
        ;;
      --classify-bind)
        classify_bind "${2:?missing bind value}"
        shift 2
        ;;
      --assert-debian13)
        assert_debian13 "${2:?missing os-release file}"
        shift 2
        ;;
      --require-snapshot)
        require_snapshot
        shift
        ;;
      --check-line-endings)
        shift
        check_line_endings "$@"
        exit $?
        ;;
      --redis-migration-message)
        redis_migration_message "${2:?missing canonical depth}" "${3:?missing legacy depth}"
        shift 3
        ;;
      --run-baseline)
        run_baseline
        shift
        ;;
      --run-line-endings)
        check_line_endings
        shift
        ;;
      --run-pure-tests)
        run_pure_tests
        shift
        ;;
      --run-api)
        check_api
        shift
        ;;
      --run-guardrails)
        check_guardrails
        shift
        ;;
      --run-redis)
        check_redis_queue
        shift
        ;;
      --run-services)
        check_services
        shift
        ;;
      --run-bind)
        check_bind_exposure
        shift
        ;;
      --run-enrichment)
        check_enrichment
        shift
        ;;
      --run-journals)
        check_journals
        shift
        ;;
      --run-install)
        run_install
        shift
        ;;
      --run-uninstall-reinstall)
        run_uninstall_reinstall
        shift
        ;;
      --run-all)
        run_all
        shift
        ;;
      --help|-h)
        usage
        shift
        ;;
      *)
        printf 'Unknown option: %s\n' "$1" >&2
        usage >&2
        exit 2
        ;;
    esac
  done
}

main "$@"
