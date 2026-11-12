"""tv27: the trial journal counts real NSE trading days only (synthetic days, no database)."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import swing_trade_ml.services.risk  # noqa: F401  (import order: avoids a known trial_journal circular import)
from swing_trade_ml.brain.trial_journal import split_session_days

_spec = importlib.util.spec_from_file_location(
    "audit_session_days", Path(__file__).resolve().parents[1] / "scripts" / "audit_session_days.py"
)
audit_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit_mod)

# Run days seen on prod: 20 Oct (Dussehra) and 10 Nov (Diwali Balipratipada) have no candle.
DAYS = [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 11, 9), date(2026, 11, 10)]


def test_audit_reports_each_mismatch_with_date_and_reason():
    assert audit_mod.audit(DAYS) == [(date(2026, 10, 20), "NSE holiday"), (date(2026, 11, 10), "NSE holiday")]


def test_audit_reports_weekend_special_session():
    assert audit_mod.audit([date(2026, 11, 8)]) == [(date(2026, 11, 8), "weekend")]  # Muhurat Sunday


def test_journal_counts_exactly_what_the_audit_calls_real():
    counted, excluded = split_session_days(DAYS)
    assert [d for d, _ in audit_mod.audit(DAYS)] == excluded
    assert 20 not in {d.day for d in counted if d.month == 10}


def test_audit_exit_code(capsys):
    assert audit_mod.main(["2026-10-19"]) == 0
    assert audit_mod.main(["2026-10-20"]) == 1
    assert "2026-10-20" in capsys.readouterr().out
