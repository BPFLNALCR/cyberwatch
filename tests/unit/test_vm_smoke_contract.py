from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "cyberwatch-vm-smoke.sh"


def run_smoke(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(SMOKE_SCRIPT), *args],
        cwd=REPO_ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_smoke_status_vocabulary_is_stable() -> None:
    result = run_smoke("--list-statuses")

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["PASS", "FAIL", "SKIP", "WARN"]


def test_smoke_check_ids_cover_required_categories() -> None:
    result = run_smoke("--list-checks")

    assert result.returncode == 0
    checks = set(result.stdout.splitlines())
    assert {
        "vm_baseline",
        "line_endings",
        "install",
        "uninstall_reinstall",
        "service_status",
        "api_root",
        "api_health",
        "destructive_clear_dns",
        "pure_pytest",
        "enrichment_import",
        "enrichment_service",
        "redis_queue_key",
        "journals",
        "bind_exposure",
    }.issubset(checks)


def test_debian_13_os_release_parsing(tmp_path: Path) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_ID="13"\n')

    result = run_smoke("--assert-debian13", str(os_release))

    assert result.returncode == 0
    assert "status=PASS" in result.stdout
    assert "Debian GNU/Linux 13" in result.stdout.replace("\\ ", " ")


def test_snapshot_confirmation_is_required() -> None:
    result = run_smoke(
        "--require-snapshot",
        env={"CYBERWATCH_VM_SNAPSHOT_CONFIRMED": "", "CYBERWATCH_VM_SNAPSHOT_LABEL": ""},
    )

    assert result.returncode != 0
    assert "check_id=vm_baseline" in result.stdout
    assert "status=FAIL" in result.stdout
    assert "snapshot" in result.stdout.lower()


def test_owned_cleanup_resources_are_cyberwatch_scoped() -> None:
    result = run_smoke("--list-owned-resources")

    assert result.returncode == 0
    resources = set(result.stdout.splitlines())
    assert "/etc/cyberwatch" in resources
    assert "/var/lib/cyberwatch" in resources
    assert "cyberwatch:targets" in resources
    assert "cyberWatch:targets" in resources
    assert "/etc/neo4j" not in resources
    assert "/var/lib/neo4j" not in resources


def test_smoke_script_shell_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SMOKE_SCRIPT)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_api_ui_bind_exposure_classification() -> None:
    all_interfaces = run_smoke("--classify-bind", "0.0.0.0:8000")
    localhost = run_smoke("--classify-bind", "127.0.0.1:8080")

    assert all_interfaces.returncode == 0
    assert all_interfaces.stdout.strip() == "all-interfaces"
    assert localhost.returncode == 0
    assert localhost.stdout.strip() == "localhost-only"


def test_required_journal_commands_are_listed() -> None:
    result = run_smoke("--journal-commands")

    assert result.returncode == 0
    output = result.stdout
    for unit in [
        "cyberWatch-api.service",
        "cyberWatch-ui.service",
        "cyberWatch-enrichment.service",
        "cyberWatch-dns-collector.service",
        "cyberWatch-remeasure.service",
        "cyberWatch-worker@*",
    ]:
        assert unit in output
    assert "journalctl" in output


def test_default_pytest_command_is_pure() -> None:
    result = run_smoke("--pytest-command")

    assert result.returncode == 0
    assert result.stdout.strip() == "python -m pytest"
    forbidden = {"systemctl", "redis-cli", "psql", "cypher-shell", "traceroute", "scamper", "sudo"}
    assert forbidden.isdisjoint(set(result.stdout.split()))
