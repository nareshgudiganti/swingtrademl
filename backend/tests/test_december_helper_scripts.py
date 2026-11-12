"""Static and light behaviour checks for scripts/december/*.ps1 (the December helper scripts).

These scripts are convenience wrappers only. The tests make sure they stay safe: they exist, they parse, live steps
have no helper, writing steps are gated behind an explicit switch, nothing pushes or tags, and the API key is never
printed. No database and no network are used.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DIR = REPO / "scripts" / "december"
SCRIPTS = [
    "01-preflight.ps1",
    "02-phase-b-dry-run.ps1",
    "03-phase-b-manifest.ps1",
    "04-phase-b-finish.ps1",
    "05-lab-check.ps1",
    "06-sx5-dry-run.ps1",
    "07-h05-daily-check.ps1",
    "08-weekly-scoreboard.ps1",
]
ALL = SCRIPTS + ["_common.ps1"]
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")


def _text(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


def _code_lines(name: str) -> list[str]:
    """Lines that are not pure comments."""
    return [ln for ln in _text(name).splitlines() if not ln.strip().startswith("#")]


@pytest.mark.parametrize("name", ALL)
def test_script_exists(name):
    assert (DIR / name).is_file()


@pytest.mark.parametrize("name", ALL)
def test_nothing_pushes_tags_or_commits(name):
    body = "\n".join(_code_lines(name)).lower()
    # "git merge-base --is-ancestor" is a read-only question, so only a real "git merge" is forbidden.
    for forbidden in (r"git push", r"git tag", r"git commit", r"git add", r"git reset", r"git checkout", r"git merge(?!-base)", r"git rebase"):
        assert not re.search(forbidden, body), f"{name} contains '{forbidden}'"
    assert "--tags" not in body
    assert "remove-item" not in body, f"{name} deletes files"


@pytest.mark.parametrize("name", ALL)
def test_no_secret_reading_or_printing_of_env(name):
    body = "\n".join(_code_lines(name))
    assert not re.search(r"(?i)\bcat\b[^\n]*\.env", body)
    assert not re.search(r"(?i)type\s+[^\n]*\.env", body)
    for ln in body.splitlines():
        if re.search(r"(?i)\b(say|write-host|write-output|write-verbose|out-file|add-content|set-content)\b", ln):
            assert "$key" not in ln.lower(), f"{name}: the API key is printed or written: {ln.strip()}"
            assert "x-api-key" not in ln.lower()


@pytest.mark.parametrize("name", SCRIPTS)
def test_no_non_local_database_or_write_http(name):
    body = "\n".join(_code_lines(name))
    assert not re.search(r"(?i)-Method\s+(Post|Put|Delete|Patch)", body)


def test_apply_is_always_gated_by_a_switch():
    for name in SCRIPTS:
        body = _text(name)
        lines = [ln for ln in _code_lines(name) if "--apply" in ln]
        if not lines:
            continue
        assert re.search(r"\[switch\]\s*\$Apply", body), f"{name} uses --apply without a -Apply switch"
        for ln in lines:
            assert "$Apply" in ln, f"{name}: --apply is not gated on the same line: {ln.strip()}"


def test_dry_run_is_the_default_for_writing_helpers():
    for name in ("03-phase-b-manifest.ps1", "04-phase-b-finish.ps1"):
        body = _text(name)
        assert "DRY RUN" in body
        assert re.search(r"\[switch\]\s*\$Apply", body)


def test_no_helper_for_live_steps():
    # sx5 --run, lab start without --check-only, real Phase B run: typed commands only.
    for name in SCRIPTS:
        executable = [ln for ln in _code_lines(name) if not re.match(r"\s*Say\b", ln)]
        joined = "\n".join(executable)
        assert "'--run'" not in joined and '"--run"' not in joined and " --run" not in joined, name
        if "selection_lab_start" in joined:
            assert "--check-only" in joined, f"{name} could start the lab"
        # the real Phase B run goes through cli main with sys.argv; no executable line may do that
        assert "brain','phase-b'" not in joined.replace(" ", ""), f"{name} could start a real Phase B run"
    assert not (DIR / "09-lab-start.ps1").exists()


def test_every_script_prints_what_it_will_do_first():
    for name in SCRIPTS:
        first_say = next((ln for ln in _code_lines(name) if re.match(r"\s*(if \(.*\) \{ )?Say\b", ln.strip()) or "Say " in ln), None)
        assert first_say is not None, name


def test_helpers_use_the_local_database_only():
    common = _text("_common.ps1")
    assert "@(localhost|127" in common  # the guard against a non-local DSN
    assert "SECTOR_FEATURES_DSN" in common  # removed from the child environment
    for var in ("API_KEY", "JWT_SECRET_KEY", "TRADING_MODE"):
        assert var in common


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
@pytest.mark.parametrize("name", ALL)
def test_script_parses(name):
    cmd = (
        "$e=$null; $t=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{(DIR / name)}', [ref]$t, [ref]$e); if ($e) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}"
    )
    done = subprocess.run([POWERSHELL, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def _run_ps(script: str, *args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["STML_PYTHON"] = sys.executable
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(DIR / script), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_h05_check_reads_a_mock_report_and_prints_no_key(tmp_path):
    report = {
        "protocol_code": "h05-test",
        "protocol_accepted": True,
        "runs": [
            {
                "run_no": 1,
                "status": "active",
                "start_day": "2026-11-02",
                "end_day": "2027-01-28",
                "days_recorded": 4,
                "sessions_in_window": 5,
                "missed_sessions": ["2026-11-04"],
                "events": [],
            }
        ],
        "verdict": {
            "large": {"combined": {"selection": {"verdict": "INCONCLUSIVE"}, "economic": {"verdict": "INCONCLUSIVE"}}},
            "mid": {"combined": {"selection": {"verdict": "INCONCLUSIVE"}, "economic": {"verdict": "INCONCLUSIVE"}}},
            "small": {"combined": {"selection": {"verdict": "INCONCLUSIVE"}, "economic": {"verdict": "INCONCLUSIVE"}}},
        },
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    done = _run_ps("07-h05-daily-check.ps1", "-MockJson", str(path))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "sessions recorded: 4 of 5" in done.stdout
    assert "missed sessions: 1" in done.stdout
    assert "ATTENTION" in done.stdout  # a missed session is flagged, never silently accepted
    assert "Verdict large: selection INCONCLUSIVE" in done.stdout


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_phase_b_dry_run_helper_prints_plan_and_writes_nothing():
    before = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO, capture_output=True, text=True).stdout
    done = _run_ps("02-phase-b-dry-run.ps1", "-Candidate", "B1")
    after = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO, capture_output=True, text=True).stdout
    assert done.returncode == 0, done.stdout + done.stderr
    assert "DRY RUN: Phase B candidate B1" in done.stdout
    assert "NOT done by this helper" in done.stdout
    assert before == after, "the dry run changed the working tree"
