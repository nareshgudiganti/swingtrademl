"""The deploy path must never leave the worker stopped, must not start on a full disk, and its alerts must
judge what the site actually says (the incident of 22 Nov: the disk filled, the database dump failed after
the worker was stopped, the rollback's own checkout failed, and nothing restarted the worker or told anyone).

release.sh and the uptime check are RUN here, never against anything real: the script is copied to a
temporary folder, and a PATH whose first entries are recording stubs stands in for docker, git, curl, df,
sleep and python3. Before any script runs, the test proves that each of those commands resolves to its stub
and not to the real program; if that cannot be shown the test fails without running the script. The app and
backup folders are temporary too (APP_DIR and BACKUP_ROOT, whose defaults are the server's own).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(os.environ.get("DEPLOY_TEST_ROOT") or Path(__file__).resolve().parents[2])  # override: red/green runs
RELEASE = ROOT / "infra" / "deploy" / "release.sh"
PREFLIGHT = ROOT / "infra" / "deploy" / "preflight.sh"
DEPLOY_YML = ROOT / ".github" / "workflows" / "deploy.yml"
UPTIME_YML = ROOT / ".github" / "workflows" / "uptime.yml"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

SHA = "a" * 40
PREVIOUS = "b" * 40
GB_KB = 1024 * 1024  # one GiB in the 1K blocks `df -Pk` reports

# ---------------------------------------------------------------------------------------------- stubs

MARK = "# STUB-FOR-TEST: records its calls, never touches the real program"
HEADER = f"#!/usr/bin/env bash\n{MARK}\n"
FAIL_FN = 'fail() { case ",${STUB_FAIL:-}," in *",$1,"*) return 0;; esac; return 1; }\n'
# sigat NAME: when STUB_SIGNAL_AT is NAME, send STUB_SIGNAL (default TERM) to the script that called this stub, the way
# a cancelled run or a dropped connection would. The command then carries on and returns normally.
SIG_FN = 'sigat() { [ "${STUB_SIGNAL_AT:-}" = "$1" ] && kill -s "${STUB_SIGNAL:-TERM}" "$PPID"; return 0; }\n'
# dumpseen: how many database.sql files exist right now, written to the log next to what is about to run.
SEEN_FN = (
    'dumpseen() { echo "dumpseen $(ls "$STUB_BACKUPS"/release-*/database.sql 2>/dev/null | wc -l | tr -d " ") at: $*"'
    ' >> "$STUB_LOG"; }\n'
)

DOCKER = (
    HEADER
    + FAIL_FN
    + SIG_FN
    + SEEN_FN
    + r"""echo "docker $*" >> "$STUB_LOG"
args=" $* "
case "$1" in
  inspect)
    case "$*" in
      *State.Running*) cat "$STUB_STATE/worker_running"; exit 0;;
      *) echo "sha256:stubimage"; exit 0;;
    esac;;
  tag) if fail tag; then echo "stub docker: cannot tag" >&2; exit 1; fi; exit 0;;
  commit) if fail commit; then echo "stub docker: cannot commit" >&2; exit 1; fi; exit 0;;
  info)
    if fail dockerinfo; then echo "Cannot connect to the Docker daemon" >&2; exit 1; fi
    if fail dockerinfoempty; then exit 0; fi
    echo "$STUB_DOCKER_ROOT"; exit 0;;
  start)
    if fail start; then echo "stub docker: cannot start the worker" >&2; exit 5; fi
    echo true > "$STUB_STATE/worker_running"; exit 0;;
  exec)
    case "$*" in
      *pg_dumpall*)
        if fail dump; then echo "-- stub dump, cut off"; echo "pg_dumpall: No space left on device" >&2; exit 7; fi
        sigat dump
        echo "-- stub dump"; exit 0;;
      *) sigat verify; if fail verify; then exit 6; fi; exit 0;;
    esac;;
  compose)
    case "$args" in
      *" build "*) sigat build; if fail build; then exit 3; fi; exit 0;;
      *" stop worker "*)
        dumpseen "$@"
        n=$(cat "$STUB_STATE/stops" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$STUB_STATE/stops"
        if [ "$n" -ge 2 ]; then sigat stop2; fi
        if fail stop; then exit 4; fi
        echo false > "$STUB_STATE/worker_running"; exit 0;;
      *" run --rm "*) sigat migrate; if fail migrate; then exit 8; fi; exit 0;;
      *" up -d "*)
        case "$args" in *rollback.json*) dumpseen "$@"; if fail composeup; then exit 9; fi;; esac
        case "$args" in *" worker "*) echo true > "$STUB_STATE/worker_running";; esac
        exit 0;;
    esac;;
esac
exit 0
"""
)
GIT = (
    HEADER
    + FAIL_FN
    + SEEN_FN
    + r"""echo "git $*" >> "$STUB_LOG"
case "$1" in
  rev-parse) echo "$STUB_HEAD"; exit 0;;
  checkout)
    dumpseen "$@"
    if fail checkout; then echo "error: unable to write file: No space left on device" >&2; exit 128; fi
    exit 0;;
esac
exit 0
"""
)
CURL = HEADER + FAIL_FN + 'echo "curl $*" >> "$STUB_LOG"\nif fail curl; then exit 22; fi\nexit 0\n'
SLEEP = HEADER + 'echo "sleep $*" >> "$STUB_LOG"\nexit 0\n'
PYTHON3 = HEADER + 'cat > /dev/null\nprintf "{}" > "$2"\nexit 0\n'
DF = (
    HEADER
    + r"""echo "df $*" >> "$STUB_LOG"
last="${@: -1}"
case "$last" in
  /) label=root; kb="$STUB_ROOT_KB";;
  "$STUB_APP_DIR") label=app; kb="$STUB_APP_KB";;
  "$STUB_DOCKER_ROOT") label=docker; kb="$STUB_DOCKER_KB";;
  *) label=backup; kb="$STUB_BACKUP_KB";;
esac
if [ "${STUB_DF_BAD:-}" = "$label" ]; then
  if [ "${STUB_DF_MODE:-fail}" = garbage ]; then echo "df: this is not a table"; exit 0; fi
  echo "df: cannot read the filesystem" >&2; exit 1
fi
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "stub 99999999 1 $kb 1% $last"
"""
)
STUBS = {"docker": DOCKER, "git": GIT, "curl": CURL, "sleep": SLEEP, "python3": PYTHON3, "df": DF}


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _prove_every_command_is_a_stub(env: dict[str, str], names=tuple(STUBS)) -> None:
    """Fails the test, before any script runs, unless each command resolves to a stub file."""
    probe = (
        'for c in "$@"; do p=$(command -v "$c") || { echo "MISSING $c"; exit 9; }; '
        'head -n 3 "$p" | grep -q STUB-FOR-TEST || { echo "REAL $c -> $p"; exit 9; }; done'
    )
    done = subprocess.run(
        [BASH, "-c", probe, "probe", *names], env=env, capture_output=True, text=True, timeout=60
    )
    if done.returncode != 0:
        pytest.fail(f"refusing to run: a command is not its stub ({done.stdout.strip()})")


def _base_env(tmp: Path, bin_dir: Path, **extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": tmp.as_posix(),
        "DOCKER_HOST": "tcp://127.0.0.1:1",  # belt and braces: a real docker could not reach anything
        "STUB_LOG": (tmp / "calls.log").as_posix(),
        "STUB_STATE": (tmp / "state").as_posix(),
        **extra,
    }


def _stub_dir(tmp: Path, **overrides: str) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    for name, body in {**STUBS, **overrides}.items():
        _write(bin_dir / name, body)
    (tmp / "state").mkdir()
    (tmp / "state" / "worker_running").write_text("true\n", encoding="utf-8")
    (tmp / "calls.log").write_text("", encoding="utf-8")
    return bin_dir


# ------------------------------------------------------------------------------------- release.sh


def run_release(
    tmp: Path,
    *,
    fail: str = "",
    root_gb=50,
    backup_gb=50,
    app_gb=50,
    docker_gb=50,
    df_bad: str = "",
    df_mode: str = "fail",
    backup_root: str = "",
    head: str = "",
    **extra: str,
) -> SimpleNamespace:
    app, backups = tmp / "app", tmp / "backups"
    (app / "infra" / "deploy").mkdir(parents=True)
    (app / "infra" / "deploy" / "verify.py").write_text("print('stub')\n", encoding="utf-8")
    shutil.copyfile(PREFLIGHT, app / "infra" / "deploy" / "preflight.sh")
    backups.mkdir()
    script = tmp / "release.sh"
    shutil.copyfile(RELEASE, script)
    env = _base_env(
        tmp,
        _stub_dir(tmp),
        APP_DIR=app.as_posix(),
        BACKUP_ROOT=backup_root or backups.as_posix(),
        STUB_BACKUPS=backups.as_posix(),
        STUB_HEAD=head or SHA,
        STUB_FAIL=fail,
        STUB_ROOT_KB=str(int(root_gb * GB_KB)),
        STUB_BACKUP_KB=str(int(backup_gb * GB_KB)),
        STUB_APP_KB=str(int(app_gb * GB_KB)),
        STUB_DOCKER_KB=str(int(docker_gb * GB_KB)),
        STUB_APP_DIR=app.as_posix(),
        STUB_DOCKER_ROOT=(tmp / "docker-root").as_posix(),
        STUB_DF_BAD=df_bad,
        STUB_DF_MODE=df_mode,
        **extra,
    )
    _prove_every_command_is_a_stub(env)
    done = subprocess.run(
        [BASH, script.as_posix(), SHA, PREVIOUS],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    calls = (tmp / "calls.log").read_text(encoding="utf-8").splitlines()
    return SimpleNamespace(
        code=done.returncode,
        out=done.stdout,
        err=done.stderr,
        calls=calls,
        worker_running=(tmp / "state" / "worker_running").read_text(encoding="utf-8").strip(),
        written=sorted(p.name for p in backups.iterdir()),
        dumps=sorted(p.as_posix() for p in backups.glob("release-*/database.sql")),
    )


def _docker_calls(r) -> list[str]:
    return [c for c in r.calls if c.startswith("docker ")]


def _has(r, *needles: str) -> bool:
    return any(all(n in c for n in needles) for c in r.calls)


def test_the_harness_runs_only_stubs(tmp_path):
    """The proof itself: every command the script can reach resolves to a stub, and a real one is refused."""
    env = _base_env(tmp_path, _stub_dir(tmp_path))
    _prove_every_command_is_a_stub(env)
    with pytest.raises(pytest.fail.Exception, match="not its stub"):
        _prove_every_command_is_a_stub(env, names=("ls",))  # a real program is detected and refused


def test_a_good_deploy_keeps_its_order_and_never_rolls_back(tmp_path):
    r = run_release(tmp_path)
    assert r.code == 0, r.err
    assert "Verified deployment" in r.out
    order = [
        c.split(" -f docker-compose.prod.yml ", 1)[-1] if " compose " in c else c
        for c in _docker_calls(r)
        if " compose " in c or "pg_dumpall" in c
    ]
    assert [o.split(" -U")[0] for o in order] == [
        "build api worker frontend",
        "stop worker",
        "docker exec stml-postgres pg_dumpall",
        "run --rm -e DB_AUTO_MIGRATE=false api python -m alembic upgrade head",
        "up -d --no-build api frontend",
        "up -d --no-build worker",
    ]
    assert not _has(r, "git checkout"), "a good deploy never rolls back"
    assert r.worker_running == "true"


def test_the_migration_step_and_trading_mode_are_untouched():
    text = RELEASE.read_text(encoding="utf-8")
    assert '"${compose[@]}" run --rm -e DB_AUTO_MIGRATE=false api python -m alembic upgrade head' in text
    for forbidden in ("TRADING_MODE", "ALLOW_LIVE_TRADING", "ALLOW_MODEL_PROMOTION"):
        assert forbidden not in text
    assert "APP_DIR=${APP_DIR:-/root/app}" in text and "BACKUP_ROOT=${BACKUP_ROOT:-/root/backups}" in text


@pytest.mark.parametrize(
    ("fail", "original"),
    [
        ("dump,checkout", 7),  # the incident: the dump fails, then the rollback's checkout fails
        ("dump", 7),
        ("migrate,checkout", 8),
        ("verify,checkout", 1),
    ],
)
def test_the_rollback_brings_the_worker_back_even_when_the_checkout_fails(tmp_path, fail, original):
    r = run_release(tmp_path, fail=fail)
    assert r.code == original, (r.code, r.err)
    assert _has(r, "git checkout --detach", PREVIOUS)
    assert _has(r, "up -d --no-build api worker frontend", "rollback.json"), "the previous images are started"
    assert r.worker_running == "true", "the worker is running again"
    assert "Deployment failed" in r.err


def test_docker_start_is_the_last_resort_when_compose_up_also_fails(tmp_path):
    r = run_release(tmp_path, fail="dump,checkout,composeup")
    assert r.code == 7
    assert _has(r, "docker start stml-worker")
    assert r.worker_running == "true"


def test_a_failed_stop_still_triggers_the_rollback_with_the_original_code(tmp_path):
    r = run_release(tmp_path, fail="stop")
    assert r.code == 4
    assert _has(r, "git checkout --detach", PREVIOUS)
    assert _has(r, "up -d --no-build api worker frontend", "rollback.json")
    assert r.worker_running == "true"


def test_if_nothing_can_restart_the_worker_the_owner_is_told_in_plain_words(tmp_path):
    r = run_release(tmp_path, fail="dump,checkout,composeup,start")
    assert r.code == 7  # still the original failure's code
    assert r.worker_running == "false"
    assert "stml-worker" in r.err and "stopped" in r.err.lower()


def test_a_failed_build_stops_and_rolls_back_nothing(tmp_path):
    r = run_release(tmp_path, fail="build")
    assert r.code == 3
    assert not _has(r, "stop worker") and not _has(r, "pg_dumpall")
    _only_the_checkout_back(r)
    assert r.worker_running == "true"


# ------------------------------------------------------------------------------- the disk check


def _only_the_checkout_back(r) -> None:
    """The one thing an early failure may do: put the folder back on the commit that is running."""
    checkouts = [c for c in r.calls if c.startswith("git checkout")]
    assert checkouts == [f"git checkout --detach {PREVIOUS}"], checkouts


def _no_writes_or_actions(r) -> None:
    # Only the read-only question to Docker (where it keeps its data) may have been asked.
    asked = [c for c in r.calls if c.startswith(("docker ", "curl ", "sleep ", "python3 "))]
    assert [c for c in asked if not c.startswith("docker info")] == []
    _only_the_checkout_back(r)
    assert r.written == [], "nothing was written to the backup folder"


def test_a_nearly_full_root_disk_refuses_before_anything_is_touched(tmp_path):
    r = run_release(tmp_path, root_gb=1)
    assert r.code != 0
    assert "only 1 GB free" in r.err and "at least 5 GB" in r.err
    assert "nothing was changed" in r.err.lower()
    _no_writes_or_actions(r)


def test_a_nearly_full_backup_disk_refuses_too(tmp_path):
    r = run_release(tmp_path, backup_gb=2)
    assert r.code != 0
    assert "only 2 GB free" in r.err and "backup" in r.err.lower()
    _no_writes_or_actions(r)


def test_exactly_the_minimum_free_is_enough(tmp_path):
    r = run_release(tmp_path, root_gb=5, backup_gb=5)
    assert r.code == 0, r.err


def test_the_minimum_can_be_raised_and_a_refusal_changes_nothing(tmp_path):
    r = run_release(tmp_path, root_gb=10, backup_gb=10, MIN_FREE_GB="50")
    assert r.code != 0 and "at least 50 GB" in r.err
    _no_writes_or_actions(r)


def test_a_nearly_full_docker_storage_disk_refuses_too(tmp_path):
    """Images and containers are written to Docker's own root, which can be a different disk."""
    r = run_release(tmp_path, docker_gb=1)
    assert r.code != 0
    assert "only 1 GB free" in r.err and "docker" in r.err.lower()
    _no_writes_or_actions(r)


def test_a_nearly_full_app_disk_refuses_too(tmp_path):
    r = run_release(tmp_path, app_gb=2)
    assert r.code != 0
    assert "only 2 GB free" in r.err and "app" in r.err.lower()
    _no_writes_or_actions(r)


@pytest.mark.parametrize("fail", ["dockerinfo", "dockerinfoempty"])
def test_if_dockers_storage_folder_cannot_be_found_the_deploy_refuses(tmp_path, fail):
    r = run_release(tmp_path, fail=fail)
    assert r.code != 0
    assert "could not find where docker keeps its data" in r.err.lower()
    assert "nothing was changed" in r.err.lower()
    _no_writes_or_actions(r)


@pytest.mark.parametrize("mode", ["fail", "garbage"])
@pytest.mark.parametrize("bad", ["root", "app", "backup", "docker"])
def test_a_disk_that_cannot_be_measured_refuses_in_plain_words(tmp_path, bad, mode):
    """Unknown is not "enough": a failed or unreadable measurement of any one disk stops the deploy."""
    r = run_release(tmp_path, df_bad=bad, df_mode=mode)
    assert r.code != 0, (bad, mode)
    assert "could not measure" in r.err.lower()
    assert "nothing was changed" in r.err.lower()
    _no_writes_or_actions(r)


def test_every_disk_the_release_writes_to_is_checked(tmp_path):
    r = run_release(tmp_path)
    assert r.code == 0, r.err
    measured = [c for c in r.calls if c.startswith("df ")]
    assert any(c.endswith(" /") for c in measured)
    assert any(c.endswith((tmp_path / "app").as_posix()) for c in measured)
    assert any(c.endswith((tmp_path / "backups").as_posix()) for c in measured)
    assert any(c.endswith((tmp_path / "docker-root").as_posix()) for c in measured)


# ----------------------------------------------------------------------------- the uptime check


def _uptime_script() -> str:
    workflow = yaml.safe_load(UPTIME_YML.read_text(encoding="utf-8"))
    step = next(s for s in workflow["jobs"]["check"]["steps"] if s.get("id") == "check")
    return step["run"]


PICK = 'pick() { echo "$1" | awk -F, -v n="$2" \'{ print (n <= NF) ? $n : $NF }\'; }\n'
# /ready is read ONCE per attempt: body, status and curl's own exit code all come from that one answer.
# STUB_READY_RCS / STUB_READY_CODES give the exit code and HTTP code of call 1, 2, ... (the last repeats).
# STUB_READY_PARTIAL=1 makes a failing call still deliver the body first (a transfer cut off part-way).
UPTIME_CURL = (
    HEADER
    + PICK
    + r"""echo "curl $*" >> "$STUB_LOG"
url="${@: -1}"
case "$url" in
  */health) echo "${STUB_HEALTH_CODE:-200}"; exit 0;;
  */ready)
    n=$(cat "$STUB_STATE/ready_calls" 2>/dev/null || echo 0); n=$((n + 1))
    echo "$n" > "$STUB_STATE/ready_calls"
    rc=$(pick "${STUB_READY_RCS:-0}" "$n"); code=$(pick "${STUB_READY_CODES:-200}" "$n")
    if [ "$rc" = 0 ] || [ "${STUB_READY_PARTIAL:-0}" = 1 ]; then cat "$STUB_READY_BODY"; fi
    printf '\n%s' "$code"
    exit "$rc";;
  *) echo "{}"; exit 0;;
esac
"""
)
SHIM = f'{HEADER}exec "{Path(sys.executable).as_posix()}" "$@"\n'


def run_uptime(
    tmp: Path, ready_body: str, *, codes: str = "200", rcs: str = "0", partial: bool = False
) -> SimpleNamespace:
    bin_dir = _stub_dir(tmp, curl=UPTIME_CURL, python3=SHIM)  # python3 is a shim to this interpreter
    body = tmp / "ready.json"
    body.write_text(ready_body, encoding="utf-8")
    output = tmp / "github_output"
    output.write_text("", encoding="utf-8")
    env = _base_env(
        tmp,
        bin_dir,
        BASE="https://site.invalid/api/v1",
        API_KEY="",
        GITHUB_OUTPUT=output.as_posix(),
        STUB_READY_BODY=body.as_posix(),
        STUB_READY_CODES=codes,
        STUB_READY_RCS=rcs,
        STUB_READY_PARTIAL="1" if partial else "0",
    )
    _prove_every_command_is_a_stub(env, names=("curl", "sleep", "python3"))
    done = subprocess.run(
        [BASH, "-c", _uptime_script()], cwd=tmp, env=env, capture_output=True, text=True, timeout=120
    )
    text = output.read_text(encoding="utf-8")
    calls = (tmp / "calls.log").read_text(encoding="utf-8").splitlines()
    return SimpleNamespace(
        code=done.returncode,
        out=done.stdout,
        err=done.stderr,
        text=text,
        ready_requests=[c for c in calls if c.startswith("curl ") and c.endswith("/ready")],
        sleeps=[c for c in calls if c.startswith("sleep ")],
    )


def _ready(ready=True, database=True, scheduler=True) -> str:
    flag = {True: "true", False: "false"}
    return (
        f'{{"ready": {flag[ready]}, "database": {flag[database]}, "broker_authenticated": false, '
        f'"scheduler_running": {flag[scheduler]}, "trading_mode": "paper", "live_trading_enabled": false}}'
    )


def test_uptime_says_up_only_when_ready_database_and_scheduler_are_all_true(tmp_path):
    r = run_uptime(tmp_path, _ready())
    assert r.code == 0, r.err
    assert "state=up" in r.text


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        (_ready(scheduler=False), "scheduler"),
        (_ready(database=False), "database"),
        (_ready(ready=False), "not ready"),
        ("{}", "ready"),
        ("this is not json", "ready"),
    ],
)
def test_http_200_alone_is_not_up(tmp_path, body, fragment):
    r = run_uptime(tmp_path, body)
    assert "state=down" in r.text, r.text
    assert fragment in r.text.lower()


def test_a_ready_check_that_does_not_answer_is_still_down(tmp_path):
    r = run_uptime(tmp_path, _ready(), codes="503")
    assert "state=down" in r.text


def test_a_good_answer_is_read_with_one_request(tmp_path):
    """Status, body and curl's own exit code come from the same single request, not three."""
    r = run_uptime(tmp_path, _ready())
    assert "state=up" in r.text
    assert len(r.ready_requests) == 1, r.ready_requests


@pytest.mark.parametrize("rc", ["18", "28", "56", "6"])
def test_a_transfer_error_is_down_even_when_the_body_and_status_look_fine(tmp_path, rc):
    """A partial read (curl 18), a timeout (28), a reset (56) or no DNS (6) must never pass: here every
    attempt delivers a perfect-looking body and a 200 and still fails at the transfer."""
    r = run_uptime(tmp_path, _ready(), codes="200", rcs=rc, partial=True)
    assert "state=down" in r.text, r.text
    assert "did not complete" in r.text.lower()
    assert len(r.ready_requests) == 2  # the existing second try, then the verdict


def test_a_timeout_with_no_status_at_all_is_down(tmp_path):
    r = run_uptime(tmp_path, _ready(), codes="000", rcs="28")
    assert "state=down" in r.text


def test_a_transfer_error_followed_by_a_clean_answer_is_up_after_the_retry(tmp_path):
    r = run_uptime(tmp_path, _ready(), codes="200,200", rcs="18,0", partial=True)
    assert "state=up" in r.text, r.text
    assert len(r.ready_requests) == 2 and len(r.sleeps) >= 1


def test_a_clean_first_answer_is_accepted_without_a_second_request(tmp_path):
    r = run_uptime(tmp_path, _ready(), codes="200,200", rcs="0,18", partial=True)
    assert "state=up" in r.text and len(r.ready_requests) == 1


# ----------------------------------------------------------------------------- the deploy alert


def _deploy_jobs() -> dict:
    return yaml.safe_load(DEPLOY_YML.read_text(encoding="utf-8"))["jobs"]


def test_a_failed_deploy_job_sends_the_telegram_alert():
    jobs = _deploy_jobs()
    alert = jobs["deploy-failed"]
    assert alert["needs"] == ["deploy"] or alert["needs"] == "deploy"
    condition = alert["if"]
    assert "needs.deploy.result" in condition and "failure" in condition
    step = next(s for s in alert["steps"] if "Telegram" in s.get("name", ""))
    assert "api.telegram.org" in step["run"]
    # The alert is in plain words and tells the owner where the worker might be left.
    assert "worker" in step["run"].lower() and "FAILED" in step["run"]


def _telegram_step() -> dict:
    return next(s for s in _deploy_jobs()["deploy-failed"]["steps"] if "Telegram" in s.get("name", ""))


def test_the_alert_step_takes_its_secrets_as_environment_only():
    step = _telegram_step()
    assert set(step["env"]) >= {"TOKEN", "CHAT"}  # secrets arrive as environment, never inlined
    body = step["run"]
    assert "secrets." not in body and "set -x" not in body
    assert 'echo "$TOKEN"' not in body and 'echo "$CHAT"' not in body and "echo $TOKEN" not in body


SECRET_TOKEN = "SECRET-TOKEN-VALUE-91"
SECRET_CHAT = "SECRET-CHAT-VALUE-47"
TG_CURL = (
    HEADER
    + PICK
    + r"""echo "curl $*" >> "$STUB_LOG"
n=$(cat "$STUB_STATE/tg_calls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$STUB_STATE/tg_calls"
rc=$(pick "${STUB_TG_RCS:-0}" "$n"); code=$(pick "${STUB_TG_CODES:-200}" "$n")
printf '%s' "$code"
exit "$rc"
"""
)


def run_telegram_step(tmp: Path, *, codes="200", rcs="0", token=SECRET_TOKEN, chat=SECRET_CHAT):
    bin_dir = _stub_dir(tmp, curl=TG_CURL)
    env = _base_env(
        tmp,
        bin_dir,
        TOKEN=token,
        CHAT=chat,
        SHA="c" * 40,
        RUN="https://example.invalid/run/1",
        STUB_TG_CODES=codes,
        STUB_TG_RCS=rcs,
    )
    _prove_every_command_is_a_stub(env, names=("curl", "sleep"))
    done = subprocess.run(
        [BASH, "-c", _telegram_step()["run"]], cwd=tmp, env=env, capture_output=True, text=True, timeout=120
    )
    calls = (tmp / "calls.log").read_text(encoding="utf-8").splitlines()
    return SimpleNamespace(
        code=done.returncode,
        shown=done.stdout + done.stderr,
        sends=[c for c in calls if c.startswith("curl ")],
        sleeps=[c for c in calls if c.startswith("sleep ")],
    )


def _no_secret_shown(r) -> None:
    assert SECRET_TOKEN not in r.shown and SECRET_CHAT not in r.shown


def test_a_delivered_alert_passes_with_one_send(tmp_path):
    r = run_telegram_step(tmp_path)
    assert r.code == 0 and len(r.sends) == 1 and r.sleeps == []
    _no_secret_shown(r)


@pytest.mark.parametrize(
    ("codes", "rcs", "sends"),
    [
        ("429,200", "0", 2),  # asked to slow down
        ("500,502,200", "0", 3),  # Telegram's own trouble
        ("000,200", "28,0", 2),  # no answer at all (timeout)
    ],
)
def test_a_brief_refusal_is_retried_until_it_is_delivered(tmp_path, codes, rcs, sends):
    r = run_telegram_step(tmp_path, codes=codes, rcs=rcs)
    assert r.code == 0, r.shown
    assert len(r.sends) == sends and len(r.sleeps) == sends - 1
    _no_secret_shown(r)


@pytest.mark.parametrize(("codes", "rcs"), [("503", "0"), ("429", "0"), ("000", "28"), ("200", "18")])
def test_an_alert_that_is_never_delivered_fails_the_step(tmp_path, codes, rcs):
    """The owner must not be left believing a message went out: the step goes red."""
    r = run_telegram_step(tmp_path, codes=codes, rcs=rcs)
    assert r.code != 0
    assert "not delivered" in r.shown.lower()
    assert 2 <= len(r.sends) <= 6, "a short, bounded number of tries"
    _no_secret_shown(r)


def test_a_request_telegram_rejects_is_not_retried_and_fails(tmp_path):
    r = run_telegram_step(tmp_path, codes="400")
    assert r.code != 0 and len(r.sends) == 1 and "not delivered" in r.shown.lower()
    _no_secret_shown(r)


@pytest.mark.parametrize("which", ["token", "chat"])
def test_missing_secrets_fail_the_step_without_sending(tmp_path, which):
    r = run_telegram_step(tmp_path, **{which: ""})
    assert r.code != 0 and r.sends == []
    assert "not delivered" in r.shown.lower()
    _no_secret_shown(r)


def test_the_smoke_job_and_the_deploy_job_are_otherwise_unchanged():
    jobs = _deploy_jobs()
    assert jobs["smoke"]["needs"] == "deploy" and jobs["deploy"]["needs"] == ["window", "validate"]
    assert jobs["deploy"]["environment"] == "production"
    script = next(s for s in jobs["deploy"]["steps"])["with"]["script"]
    assert "bash infra/deploy/release.sh" in script


# ------------------------------------------------- one rollback, whichever way the release ends


def _count(r, *needles: str) -> int:
    return sum(c.startswith(("docker ", "git ")) and all(n in c for n in needles) for c in r.calls)


def _seen_dumps(r, *needles: str) -> list[str]:
    """How many database.sql files existed when each of these rollback steps was about to run."""
    return [c.split()[1] for c in r.calls if c.startswith("dumpseen") and any(n in c for n in needles)]


@pytest.mark.parametrize("at", ["dump", "migrate", "verify"])
@pytest.mark.parametrize(("sig", "code"), [("HUP", 129), ("INT", 130), ("TERM", 143)])
def test_a_signal_after_the_worker_was_stopped_runs_the_rollback_once(tmp_path, sig, code, at):
    """A cancelled run, a dropped connection or the time limit ends the script with a signal, not a failed command."""
    r = run_release(tmp_path, STUB_SIGNAL_AT=at, STUB_SIGNAL=sig)
    assert r.code == code, (r.code, r.err)
    assert _count(r, "git checkout --detach", PREVIOUS) == 1, "the rollback ran once, not twice"
    assert _count(r, "up -d --no-build api worker frontend", "rollback.json") == 1
    assert _count(r, "stop worker") == 2, "one stop by the release, one by the rollback"
    assert r.err.count("Deployment failed") == 1
    assert r.worker_running == "true"


@pytest.mark.parametrize("sig", ["HUP", "INT", "TERM"])
def test_a_signal_before_the_worker_was_stopped_changes_nothing(tmp_path, sig):
    r = run_release(tmp_path, STUB_SIGNAL_AT="build", STUB_SIGNAL=sig)
    assert r.code != 0
    assert not _has(r, "stop worker") and not _has(r, "pg_dumpall")
    assert not _has(r, "docker start") and not _has(r, "rollback.json")
    _only_the_checkout_back(r)
    assert r.worker_running == "true"


def test_a_second_signal_during_the_rollback_does_not_cut_it_short(tmp_path):
    r = run_release(tmp_path, fail="dump", STUB_SIGNAL_AT="stop2", STUB_SIGNAL="TERM")
    assert r.code == 7, (r.code, r.err)
    assert _count(r, "git checkout --detach", PREVIOUS) == 1
    assert _count(r, "up -d --no-build api worker frontend", "rollback.json") == 1
    assert r.worker_running == "true"


@pytest.mark.parametrize("fail", ["dump", "migrate", "verify", "stop"])
def test_a_failed_command_runs_the_rollback_once_not_twice(tmp_path, fail):
    """The failed command raises the error trap and then the exit trap: only the first may roll back."""
    r = run_release(tmp_path, fail=fail)
    assert r.code != 0
    assert _count(r, "git checkout --detach", PREVIOUS) == 1
    assert _count(r, "up -d --no-build api worker frontend", "rollback.json") == 1
    assert r.err.count("Deployment failed") == 1
    assert r.worker_running == "true"


def test_a_good_deploy_runs_no_rollback_when_the_script_ends(tmp_path):
    r = run_release(tmp_path)
    assert r.code == 0 and "Deployment failed" not in r.err
    assert not _has(r, "git checkout") and _count(r, "stop worker") == 1


# ------------------------------------------------------------------------- the partial dump


def test_a_failed_dump_removes_its_partial_file_before_the_rollback_starts_anything(tmp_path):
    """22 Nov: the half-written dump was what filled the disk. Nothing may be restarted on top of it."""
    r = run_release(tmp_path, fail="dump")
    assert r.code == 7
    assert r.dumps == [], "the cut-off dump is gone"
    seen = _seen_dumps(r, "stop worker", "checkout", "rollback.json")
    assert seen and set(seen) == {"0"}, f"a partial dump was still on disk during the rollback: {seen}"
    assert r.worker_running == "true"


@pytest.mark.parametrize("sig", ["HUP", "INT", "TERM"])
def test_an_interrupted_dump_removes_its_partial_file_first_too(tmp_path, sig):
    r = run_release(tmp_path, STUB_SIGNAL_AT="dump", STUB_SIGNAL=sig)
    assert r.dumps == []
    assert set(_seen_dumps(r, "git checkout", "rollback.json")) == {"0"}


def test_a_finished_dump_is_kept_when_a_later_step_fails(tmp_path):
    """The dump taken before the migration is the owner's way back: only an unfinished one is removed."""
    r = run_release(tmp_path, fail="migrate")
    assert r.code == 8
    assert len(r.dumps) == 1
    assert set(_seen_dumps(r, "git checkout", "rollback.json")) == {"1"}


def test_a_failed_dump_with_a_failing_checkout_still_restarts_the_worker(tmp_path):
    r = run_release(tmp_path, fail="dump,checkout,composeup")
    assert r.code == 7 and r.dumps == [] and r.worker_running == "true" and _has(r, "docker start stml-worker")


# ---------------------------------------------------- the deploy job: checks before the checkout

GIT_DEPLOY = (
    HEADER
    + FAIL_FN
    + SEEN_FN
    + r"""echo "git $*" >> "$STUB_LOG"
head_file="$STUB_STATE/head"
case "$1" in
  rev-parse) cat "$head_file" 2>/dev/null || echo "$STUB_PREVIOUS"; exit 0;;
  show) cat "$STUB_PREFLIGHT"; exit 0;;
  checkout) dumpseen "$@"; echo "$3" > "$head_file"; exit 0;;
esac
exit 0
"""
)


def _deploy_script() -> str:
    return next(iter(_deploy_jobs()["deploy"]["steps"]))["with"]["script"]


def run_deploy_script(tmp: Path, *, root_gb=50, fail: str = "", **extra: str) -> SimpleNamespace:
    """The deploy job's own ssh script, with the server folder swapped for a temporary one and every command stubbed."""
    app, backups = tmp / "app", tmp / "backups"
    first = not (tmp / "bin").exists()
    if first:
        (app / "infra" / "deploy").mkdir(parents=True)
        backups.mkdir()
        for name in ("release.sh", "preflight.sh"):
            shutil.copyfile(ROOT / "infra" / "deploy" / name, app / "infra" / "deploy" / name)
        (app / "infra" / "deploy" / "verify.py").write_text("print('stub')\n", encoding="utf-8")
        _stub_dir(tmp, git=GIT_DEPLOY)
    (tmp / "calls.log").write_text("", encoding="utf-8")
    env = _base_env(
        tmp,
        tmp / "bin",
        APP_DIR=app.as_posix(),
        BACKUP_ROOT=backups.as_posix(),
        STUB_BACKUPS=backups.as_posix(),
        STUB_PREVIOUS=PREVIOUS,
        STUB_PREFLIGHT=PREFLIGHT.as_posix(),
        STUB_FAIL=fail,
        RELEASE_SHA=SHA,
        STUB_ROOT_KB=str(int(root_gb * GB_KB)),
        STUB_BACKUP_KB=str(50 * GB_KB),
        STUB_APP_KB=str(50 * GB_KB),
        STUB_DOCKER_KB=str(50 * GB_KB),
        STUB_APP_DIR=app.as_posix(),
        STUB_DOCKER_ROOT=(tmp / "docker-root").as_posix(),
        **extra,
    )
    _prove_every_command_is_a_stub(env, names=("docker", "git", "curl", "df", "sleep", "python3"))
    script = _deploy_script().replace("/root/app", app.as_posix())
    done = subprocess.run([BASH, "-c", script], cwd=tmp, env=env, capture_output=True, text=True, timeout=180)
    calls = (tmp / "calls.log").read_text(encoding="utf-8").splitlines()
    head = tmp / "state" / "head"
    return SimpleNamespace(
        code=done.returncode,
        err=done.stderr,
        out=done.stdout,
        calls=calls,
        head=head.read_text(encoding="utf-8").strip() if head.exists() else None,
        previous_recorded=[p.read_text(encoding="utf-8").strip() for p in backups.glob("release-*/previous-sha")],
    )


def test_the_workflow_script_checks_the_disk_before_it_checks_anything_out():
    script = _deploy_script()
    assert script.index("git rev-parse HEAD") < script.index("preflight.sh") < script.index("git checkout --detach")
    assert script.index("git fetch") < script.index("preflight.sh")


def test_a_refused_deploy_leaves_the_checkout_on_the_running_commit(tmp_path):
    r = run_deploy_script(tmp_path, root_gb=1)
    assert r.code != 0
    assert "only 1 GB free" in r.err and "nothing was changed" in r.err.lower()
    assert not any(c.startswith("git checkout") for c in r.calls), "nothing was checked out"
    assert r.head is None, "the folder is still on the commit that is running"
    assert not any(c.startswith("docker compose") or " compose " in c for c in r.calls)
    assert r.previous_recorded == []


def test_the_next_deploy_after_a_refusal_records_the_commit_that_is_really_running(tmp_path):
    refused = run_deploy_script(tmp_path, root_gb=1)
    assert refused.code != 0
    r = run_deploy_script(tmp_path, root_gb=50)
    assert r.code == 0, r.err
    assert r.previous_recorded == [PREVIOUS], "the commit that was running, not the refused release"
    first_checkout = next(i for i, c in enumerate(r.calls) if c.startswith("git checkout"))
    assert next(i for i, c in enumerate(r.calls) if c.startswith("git show")) < first_checkout
    assert next(i for i, c in enumerate(r.calls) if c.startswith("df ")) < first_checkout


def test_a_good_deploy_through_the_workflow_script_checks_out_then_releases(tmp_path):
    r = run_deploy_script(tmp_path)
    assert r.code == 0, r.err
    assert r.head == SHA and "Verified deployment" in r.out
    assert r.previous_recorded == [PREVIOUS]


def test_the_alert_also_fires_when_the_deploy_job_is_cancelled():
    """A cancelled run stops the release script with a signal; the owner must hear that the worker may be down."""
    alert = _deploy_jobs()["deploy-failed"]
    condition = alert["if"]
    assert "always()" in condition
    assert "needs.deploy.result == 'failure'" in condition and "needs.deploy.result == 'cancelled'" in condition
    # A deploy that never started (market-hours guard, red tests, another branch) stays silent.
    assert "skipped" not in condition and "success" not in condition
    assert "CANCELLED" in _telegram_step()["run"] and "FAILED" in _telegram_step()["run"]
    assert alert["needs"] == ["deploy"] or alert["needs"] == "deploy"


# --------------------------------------------- a failure before the worker stops puts the folder back


EARLY = [
    ("build", 3),
    ("tag,commit", 1),  # no rollback image can be made: docker tag fails and so does the docker commit fallback
]


@pytest.mark.parametrize(("fail", "code"), EARLY)
def test_an_early_failure_puts_the_folder_back_and_never_touches_the_worker(tmp_path, fail, code):
    r = run_release(tmp_path, fail=fail)
    assert r.code == code, (r.code, r.err)
    _only_the_checkout_back(r)
    assert not _has(r, "stop worker") and not _has(r, "pg_dumpall") and not _has(r, "rollback.json")
    assert not _has(r, "docker start") and not _has(r, " up -d ")
    assert r.worker_running == "true"
    assert "before the worker was stopped" in r.err


def test_a_failed_backup_folder_puts_the_folder_back_too(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so a folder cannot be made under it\n", encoding="utf-8")
    r = run_release(tmp_path, backup_root=(blocker / "backups").as_posix())
    assert r.code != 0
    _only_the_checkout_back(r)
    assert not _has(r, "docker compose") and r.worker_running == "true"


def test_the_second_disk_check_refusing_puts_the_folder_back(tmp_path):
    r = run_release(tmp_path, root_gb=1)
    assert r.code != 0 and "only 1 GB free" in r.err
    _only_the_checkout_back(r)
    assert not _has(r, "stop worker") and r.worker_running == "true"


def test_a_folder_that_is_not_on_the_release_commit_is_left_alone(tmp_path):
    """If the checkout is not the release commit, something else is wrong: nothing is moved."""
    r = run_release(tmp_path, head="c" * 40)
    assert r.code != 0
    assert not any(c.startswith("git checkout") for c in r.calls)
    assert not _has(r, "docker compose")


def test_a_failed_release_through_the_workflow_script_leaves_the_right_commit_for_the_next_deploy(tmp_path):
    failed = run_deploy_script(tmp_path, fail="build")
    assert failed.code != 0
    assert failed.head == PREVIOUS, "the folder is back on the commit that is running"
    nxt = run_deploy_script(tmp_path)
    assert nxt.code == 0, nxt.err
    assert set(nxt.previous_recorded) == {PREVIOUS}, "no release records the failed commit as the previous one"
    assert nxt.head == SHA


def test_an_early_failure_that_cannot_check_out_says_so_and_still_exits_with_the_original_code(tmp_path):
    r = run_release(tmp_path, fail="build,checkout")
    assert r.code == 3
    assert "could not check out" in r.err
    assert r.worker_running == "true"
