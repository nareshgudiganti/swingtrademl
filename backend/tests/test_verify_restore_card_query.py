"""#328 review: a failing card query must be visible in the restore drill, never a silent PASS (no Docker needed)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_restore.py"
spec = importlib.util.spec_from_file_location("verify_restore_under_test", SCRIPT)
vr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vr)


class FakePg:
    def __init__(self, card_query_works: bool):
        self.card_query_works = card_query_works

    def sql(self, db, statement, timeout=600):
        if "card" in statement and not self.card_query_works:
            raise RuntimeError("column metrics does not exist")
        return "[]"


def test_card_query_ok():
    rows, ok = vr.fetch_model_rows(FakePg(True), "scratch")
    assert rows == [] and ok is True


def test_card_query_failure_is_reported_not_hidden():
    rows, ok = vr.fetch_model_rows(FakePg(False), "scratch")
    assert rows == [] and ok is False


def test_card_check_line_fails_when_cards_exist_but_query_failed():
    assert vr.card_check_result(card_query_ok=False, manifest_cards=3, mismatches=0) == "FAIL"
    assert vr.card_check_result(card_query_ok=False, manifest_cards=0, mismatches=0) == "SKIPPED"
    assert vr.card_check_result(card_query_ok=True, manifest_cards=3, mismatches=0) == "PASS"
    assert vr.card_check_result(card_query_ok=True, manifest_cards=3, mismatches=1) == "FAIL"
