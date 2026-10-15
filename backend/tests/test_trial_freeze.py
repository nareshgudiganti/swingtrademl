"""The forward trial's frozen logic is enforced, not just agreed (tracker tv21, 2026-10-15).

During the trial (from 2026-10-14) no file that decides which stocks are picked, how much is bought or
when a position exits may change without the owner's yes. tests/trial_freeze.json holds a fingerprint of
each such file; this test fails on any difference, added file or removed file. To record a change the
owner approved: python scripts/approve_trial_change.py "why" <commit>.
"""

from __future__ import annotations

import json

from trial_freeze import MANIFEST, fingerprint, frozen_paths


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_no_decision_file_changed_without_the_owners_approval():
    recorded = _manifest()["files"]
    now = {p: fingerprint(p) for p in frozen_paths()}
    changed = sorted(p for p in now if p in recorded and now[p] != recorded[p])
    added = sorted(now.keys() - recorded.keys())
    removed = sorted(recorded.keys() - now.keys())
    assert not (changed or added or removed), (
        "Decision logic changed during the forward trial (frozen since 2026-10-14).\n"
        f"  changed: {changed}\n  added: {added}\n  removed: {removed}\n"
        "If the owner approved this change, record it: "
        'python scripts/approve_trial_change.py "why the owner approved it" <commit>'
    )


def test_every_approval_says_why_and_which_files():
    for entry in _manifest()["approved"]:
        assert entry["why"].strip() and entry["date"] and isinstance(entry["files"], list)


def test_the_freeze_covers_the_brain_strategies_and_risk_rules():
    paths = set(frozen_paths())
    for must in (
        "brain/constitution.py",
        "brain/modules/m08_decide/rules.py",
        "strategies/ml_swing.py",
        "services/risk.py",
        "services/limits.py",
        "services/exit_policy.py",
    ):
        assert must in paths, must
    # Research tools stay free to change: they never decide anything live.
    assert "brain/trial_journal.py" not in paths and "brain/portfolio_sim.py" not in paths
