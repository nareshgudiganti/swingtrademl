# ruff: noqa: E501 (long test sentences)
# ruff: noqa: F811, F401 (imported fixtures)
# ruff: noqa: N812 (short L alias, as in the other ledger tests)
"""#263: every ledger row shows the lane's stored trade flags, unchanged and as an additive field only.

The flags (recorded_late, possible_corporate_action, same_candle_both_levels, gap_fill, ...) are the lane's own
words about how trustworthy one shadow trade is. The ledger shows them; it never uses them to change a status, a
count, a pass or a number, so the totals stay equal to the h05 report's.
"""

from __future__ import annotations

import pytest

from swing_trade_ml.shadow_lanes import outcome_ledger as L
from test_h05_service import SIGNAL, after, lane, make_run
from test_outcome_ledger import pick
from test_outcome_ledger_reconcile import completed, group_day

FLAGS = ["recorded_late", "possible_corporate_action", "same_candle_both_levels", "gap_fill"]


def _picks(db, run, flags):
    completed(db, run, SIGNAL, "FLAGGED", rank=1, trade_flags=flags)
    completed(db, run, SIGNAL, "PLAIN", rank=2)  # no stored flags at all (None in the table)
    completed(db, run, SIGNAL, "EMPTY", rank=3, trade_flags=[])
    pick(db, run, SIGNAL, "NOTRADE", rank=4)  # no trade yet
    group_day(db, run, SIGNAL, "large", selected_n=4)


def test_every_row_carries_the_stored_trade_flags_unchanged(db_session, lane):
    run = make_run(db_session, {})
    _picks(db_session, run, FLAGS)
    rows = {r["symbol"]: r for r in L.build(db_session)["rows"] if r["kind"] == "pick"}
    assert rows["FLAGGED"]["trade_flags"] == FLAGS  # same words, same order
    assert rows["PLAIN"]["trade_flags"] == [] and rows["EMPTY"]["trade_flags"] == []
    assert rows["NOTRADE"]["trade_flags"] == []
    assert "trade_flags" in L.ROW_FIELDS
    session_rows = [r for r in L.build(db_session)["rows"] if r["kind"] == "session"]
    assert all(r["trade_flags"] is None for r in session_rows)  # a missed session has no trade at all


@pytest.mark.parametrize("flag", FLAGS)
def test_a_flag_never_changes_a_status_a_count_a_pass_or_any_number(db_session, lane, flag):
    # The same four picks twice: run 1 without the flag, run 2 with it on the FLAGGED pick.
    _picks(db_session, make_run(db_session, {}, run_no=1), [])
    _picks(db_session, make_run(db_session, {}, run_no=2), [flag])
    plain, flagged = L.build(db_session, 1), L.build(db_session, 2)

    def shape(out):
        rows = [{k: v for k, v in r.items() if k not in ("trade_flags", "run_no")} for r in out["rows"]]
        totals = [{k: v for k, v in t.items() if k != "run_no"} for t in out["totals"]]
        return rows, totals, out["counts"]

    assert shape(flagged) == shape(plain)  # every other field, every total and every count is identical
    assert flagged["counts"] == {"completed": 3, "immature": 1, "missing": 0, "blocked": 0}
    assert [r["trade_flags"] for r in flagged["rows"] if r["symbol"] == "FLAGGED"] == [[flag]]


def test_the_gross_return_text_says_after_slippage_before_charges():
    text = " ".join(L.__doc__.split())  # the docstring wraps lines; compare the words
    assert "gross_return (stored exit fill over entry fill, after slippage and before charges;" in text
    assert "before charges), net_return" not in text  # the old, incomplete definition is gone
