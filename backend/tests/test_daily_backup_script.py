"""#362: infra/deploy/daily-backup.sh, run for real under bash with stand-in docker/rclone/openssl.

Found by the local restore drill (#256, 2026-11-15): on a server with no release-* folder (a new
staging server before its first deploy) the script made the local copy and then stopped with
exit 2, before the off-server copy and before writing its status record (daily-last.txt).

Every case here checks the outcome AND the status record, and that a local copy alone is never
reported as a successful off-server copy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "daily-backup.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or shutil.which("gzip") is None, reason="needs bash and gzip")

# Stand-in docker: `docker exec <c> pg_dumpall ...` prints ~2 MB of hard-to-compress text, so the
# gzip copy clears the script's 1 MB minimum. Anything else fails loudly.
DOCKER = """#!/usr/bin/env bash
[ -n "${STUB_DOCKER_FAIL:-}" ] && { echo "stub docker: database not reachable" >&2; exit 1; }
if [ "$1" = exec ] && [ "$3" = pg_dumpall ]; then head -c 1600000 /dev/urandom | base64; exit 0; fi
echo "stub docker: unexpected $*" >&2; exit 97
"""
# Stand-in rclone: one remote "gdrive:"; copies into $STUB_REMOTE_DIR; `copy` fails when
# STUB_RCLONE_FAIL=copy. Every call is logged so the test can see what ran.
RCLONE = """#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
case "$1" in
  listremotes) echo "gdrive:" ;;
  copy) [ "${STUB_RCLONE_FAIL:-}" = copy ] && { echo "stub rclone: upload failed" >&2; exit 5; }
        cp "$2" "$STUB_REMOTE_DIR/" ;;
  check) [ -e "$STUB_REMOTE_DIR/$(basename "$(ls "$2"/*.enc)")" ] ;;
  delete) exit 0 ;;
  *) echo "stub rclone: unexpected $*" >&2; exit 97 ;;
esac
"""
# Stand-in openssl: "encrypts" by copying (-in X -out Y), so the test needs no real openssl.
OPENSSL = """#!/usr/bin/env bash
while [ $# -gt 0 ]; do case "$1" in -in) in=$2; shift;; -out) out=$2; shift;; esac; shift; done
cp "$in" "$out"
"""


def _bin(tmp: Path, *, offsite: bool) -> Path:
    b = tmp / "bin"
    b.mkdir()
    stubs = {"docker": DOCKER, "openssl": OPENSSL}
    if offsite:
        stubs["rclone"] = RCLONE
    for name, body in stubs.items():
        p = b / name
        p.write_text(body, encoding="utf-8", newline="\n")
        p.chmod(0o755)
    return b


def run_backup(
    tmp: Path,
    *,
    release_folder: bool,
    offsite: bool = False,
    fail: str = "",
    docker_fail: bool = False,
    record_is_dir: bool = False,
    before_bin: Path | None = None,
    root_mode: int | None = None,
):
    root = tmp / "backups"
    root.mkdir()
    if release_folder:
        (root / "release-20261101_1200").mkdir()
    if record_is_dir:
        # The status file cannot be written: its path is taken by a folder.
        (root / "daily-last.txt").mkdir()
    remote = tmp / "remote"
    remote.mkdir()
    passphrase = tmp / "passphrase"
    if offsite:
        passphrase.write_text("drill-passphrase\n", encoding="utf-8")
    bin_dir = _bin(tmp, offsite=offsite)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "BACKUP_ROOT": str(root),
        "PASSPHRASE_FILE": str(passphrase),
        "MODELS_OFFSITE_FLAG": str(tmp / "no-models-flag"),
        "STUB_REMOTE_DIR": str(remote),
        "STUB_LOG": str(tmp / "rclone.log"),
        "STUB_RCLONE_FAIL": fail,
        "STUB_DOCKER_FAIL": "1" if docker_fail else "",
    }
    if not offsite:
        # Hide any real rclone on this machine: the "not set up" path must be what runs.
        env["PATH"] = os.pathsep.join(
            [str(bin_dir)]
            + [
                p
                for p in os.environ["PATH"].split(os.pathsep)
                if not (Path(p) / "rclone").exists() and not (Path(p) / "rclone.exe").exists()
            ]
        )
    if before_bin is not None:
        env["PATH"] = f"{before_bin}{os.pathsep}{env['PATH']}"
    if root_mode is not None:
        root.chmod(root_mode)
    try:
        done = subprocess.run([BASH, str(SCRIPT)], capture_output=True, text=True, env=env, timeout=180)
    finally:
        root.chmod(0o755)
    record = root / "daily-last.txt"
    return done, (record.read_text(encoding="utf-8").strip() if record.is_file() else None), remote


def _failing_tail(tmp: Path) -> Path:
    """A `tail` that exits 3: makes the trim step stop the script unexpectedly."""
    b = tmp / "badbin"
    b.mkdir()
    (b / "tail").write_text("#!/usr/bin/env bash\nexit 3\n", encoding="utf-8", newline="\n")
    (b / "tail").chmod(0o755)
    return b


def test_a_server_with_no_release_folder_completes_and_writes_its_status(tmp_path):
    done, record, _ = run_backup(tmp_path, release_folder=False)

    assert done.returncode == 0, done.stdout + done.stderr
    assert record is not None, "the status record must be written"
    assert record.startswith("ok ") and "offsite=not set up" in record
    assert "DAILY BACKUP OK (off-server: not set up)" in done.stdout


def test_a_server_that_already_has_a_release_folder_completes_and_writes_its_status(tmp_path):
    done, record, _ = run_backup(tmp_path, release_folder=True)

    assert done.returncode == 0, done.stdout + done.stderr
    assert record is not None and record.startswith("ok ") and "offsite=not set up" in record


@pytest.mark.parametrize("release_folder", [False, True])
def test_with_off_server_set_up_the_encrypted_copy_is_uploaded(tmp_path, release_folder):
    done, record, remote = run_backup(tmp_path, release_folder=release_folder, offsite=True)

    assert done.returncode == 0, done.stdout + done.stderr
    assert record is not None and record.startswith("ok ") and "offsite=ok" in record
    assert [p.suffix for p in remote.iterdir()] == [".enc"], "only the encrypted copy leaves the server"
    assert "DAILY BACKUP OK (off-server: ok)" in done.stdout


@pytest.mark.parametrize("release_folder", [False, True])
def test_a_failed_upload_is_reported_as_a_failure_not_as_ok(tmp_path, release_folder):
    done, record, remote = run_backup(tmp_path, release_folder=release_folder, offsite=True, fail="copy")

    assert done.returncode == 1
    assert record is not None and record.startswith("failed ") and "offsite=failed" in record
    assert "OFF-SERVER COPY FAILED" in done.stderr
    assert "DAILY BACKUP OK" not in done.stdout
    assert list(remote.iterdir()) == []


def test_a_local_copy_alone_never_reads_as_an_off_server_success(tmp_path):
    done, record, _ = run_backup(tmp_path, release_folder=False)

    assert "offsite=ok" not in (record or "")
    assert "off-server: ok" not in done.stdout


def test_an_unexpected_stop_still_writes_a_failed_status_record(tmp_path):
    """Any exit before the normal end (here: the trim step's `tail` replaced by one that fails)
    leaves a 'failed' record rather than none at all, and keeps the failing exit code."""
    done, record, _ = run_backup(tmp_path, release_folder=False, before_bin=_failing_tail(tmp_path))

    assert done.returncode == 3, done.stdout + done.stderr
    assert record is not None and record.startswith("failed "), record


# --- No release-* folder is normal; a real listing error is not ------------------------------------


def test_no_release_folder_is_treated_as_normal_with_no_error_printed(tmp_path):
    done, record, _ = run_backup(tmp_path, release_folder=False)

    assert done.returncode == 0, done.stdout + done.stderr
    assert record is not None and record.startswith("ok ")
    assert "could not list" not in done.stderr
    assert "No such file" not in done.stderr


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions and a non-root user (Linux CI)",
)
@pytest.mark.parametrize("release_folder", [False, True])
def test_a_real_listing_error_fails_the_run_visibly(tmp_path, release_folder):
    """The backup folder can be written but not listed (mode 333): trimming old copies cannot see
    what is there. That is a real error, not "no release folder", so the run must fail loudly."""
    done, record, _ = run_backup(tmp_path, release_folder=release_folder, root_mode=0o333)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "could not list" in done.stderr
    assert "DAILY BACKUP OK" not in done.stdout
    assert record is not None and record.startswith("failed "), record
    assert "cleanup=failed" in record


# --- Writing the status record is best effort; it never hides the real result -------------------


def test_status_file_unwritable_on_a_failed_backup_is_reported_and_keeps_exit_1(tmp_path):
    done, record, _ = run_backup(tmp_path, release_folder=False, docker_fail=True, record_is_dir=True)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "DAILY BACKUP FAILED" in done.stderr
    assert "could not write the status record" in done.stderr
    assert record is None


def test_status_file_unwritable_on_an_unexpected_stop_keeps_the_original_exit_code(tmp_path):
    done, record, _ = run_backup(
        tmp_path, release_folder=False, record_is_dir=True, before_bin=_failing_tail(tmp_path)
    )

    assert done.returncode == 3, done.stdout + done.stderr
    assert "could not write the status record" in done.stderr
    assert record is None


def test_status_file_unwritable_on_a_good_backup_is_reported_and_backup_stays_ok(tmp_path):
    done, _, _ = run_backup(tmp_path, release_folder=False, record_is_dir=True)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "could not write the status record" in done.stderr
    assert "DAILY BACKUP OK (off-server: not set up)" in done.stdout
