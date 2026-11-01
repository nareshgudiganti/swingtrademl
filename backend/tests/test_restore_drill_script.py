"""The restore drill unpacks a compressed nightly backup into a temp file and reads it several times.
An early call to cleanup() once deleted that file before the restore (drill failed 2026-11-01)."""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "restore-drill.sh"


def test_the_unpacked_backup_is_not_deleted_before_it_is_read():
    text = SCRIPT.read_text(encoding="utf-8")
    after_trap = text.split("trap cleanup EXIT", 1)[1]
    # cleanup only runs from the EXIT trap; a bare call would also remove the unpacked dump
    assert not re.search(r"^cleanup\s*$", after_trap, flags=re.MULTILINE)
    assert 'docker rm -f "$DRILL"' in after_trap.split("docker run", 1)[0]
    # and the dump is still read after that point
    assert '"$dump"' in after_trap.split("docker run", 1)[1]
