from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "cyberwatch-vm-smoke.sh"


def test_line_ending_check_passes_lf_files(tmp_path: Path) -> None:
    script = tmp_path / "ok.sh"
    script.write_bytes(b"#!/usr/bin/env bash\nprintf 'ok\\n'\n")

    result = subprocess.run(
        [str(SMOKE_SCRIPT), "--check-line-endings", str(script)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "check_id=line_endings" in result.stdout
    assert "status=PASS" in result.stdout


def test_line_ending_check_reports_crlf_files(tmp_path: Path) -> None:
    script = tmp_path / "bad.sh"
    script.write_bytes(b"#!/usr/bin/env bash\r\nprintf 'bad\\n'\r\n")

    result = subprocess.run(
        [str(SMOKE_SCRIPT), "--check-line-endings", str(script)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "check_id=line_endings" in result.stdout
    assert "status=FAIL" in result.stdout
    assert str(script) in result.stdout
