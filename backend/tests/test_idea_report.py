"""Portfolio Reports (services/idea_report.py): pure logic, no database."""

from __future__ import annotations

from datetime import date

import pytest

from swing_trade_ml.services import idea_report as r
from swing_trade_ml.services import trial_seal

# Mon 2026-11-02 .. Fri 2026-11-06, then Mon 9 .. Fri 13 (no NSE holiday in these weeks).
DAYS = [date(2026, 11, d) for d in (2, 3, 4, 5, 6, 9, 10)]


def ob(
    symbol, day, word="WATCH", score=70, horizon=15, regime="NORMAL", outcome=None, ret=None, resolved=None
):
    return r.Obs(symbol, day, word, score, horizon, regime, outcome, ret, ret, ret, resolved)


@pytest.fixture
def unsealed(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", False)


@pytest.fixture
def sealed(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", True)
    monkeypatch.setattr(trial_seal, "SEALED_FROM", date(2026, 11, 1))


def test_same_word_on_consecutive_days_is_one_row(unsealed):
    rows = r.build_rows([ob("CYIENT", d, score=70 + i) for i, d in enumerate(DAYS[:5])], DAYS[:5])
    assert len(rows) == 1
    row = rows[0]
    assert row["entry_day"] == "2026-11-02" and row["entry_score"] == 70
    assert row["latest_score"] == 74 and row["still_this_word"] is True
    assert row["days_done"] == 4 and row["days_left"] == 11  # 15-day horizon


def test_word_change_starts_a_new_row_and_latest_word_is_shown(unsealed):
    obs = [ob("A", DAYS[0]), ob("A", DAYS[1]), ob("A", DAYS[2], word="AVOID"), ob("A", DAYS[3], word="AVOID")]
    rows = r.build_rows(obs, DAYS[:4])
    by_word = {x["word"]: x for x in rows}
    assert set(by_word) == {"WATCH", "AVOID"}
    assert by_word["WATCH"]["still_this_word"] is False and by_word["WATCH"]["latest_word"] == "AVOID"
    assert by_word["AVOID"]["still_this_word"] is True


def test_dropping_out_of_the_list_ends_the_streak(unsealed):
    obs = [ob("A", DAYS[0]), ob("A", DAYS[2])]  # missing the session in between
    assert len(r.build_rows(obs, DAYS[:3])) == 2


def test_days_done_stop_at_the_horizon_and_status_is_due_until_graded(unsealed):
    rows = r.build_rows([ob("A", DAYS[0], horizon=3)], DAYS)
    assert rows[0]["days_done"] == 3 and rows[0]["days_left"] == 0 and rows[0]["status"] == "due"


def test_graded_idea_shows_its_result_when_unsealed(unsealed):
    rows = r.build_rows([ob("A", DAYS[0], outcome="target", ret=0.08, resolved=date(2026, 11, 5))], DAYS[:4])
    row = rows[0]
    assert row["status"] == "finished" and row["outcome"] == "target" and row["return_pct"] == 8.0
    assert row["result_days"] == 3


def test_sealed_row_never_shows_a_result_or_an_early_finish(sealed):
    rows = r.build_rows([ob("A", DAYS[0], outcome="target", ret=0.08, resolved=date(2026, 11, 5))], DAYS[:4])
    row = rows[0]
    assert row["sealed"] is True and row["status"] == "tracking"  # target hit on day 3 is not revealed
    assert row["outcome"] is None and row["return_pct"] is None and row["best_pct"] is None
    assert row["result_days"] is None and row["days_left"] == 12  # calendar facts stay


def test_sealed_row_past_its_horizon_may_say_finished_but_still_no_result(sealed):
    rows = r.build_rows(
        [ob("A", DAYS[0], horizon=2, outcome="stop", ret=-0.04, resolved=date(2026, 11, 3))], DAYS
    )
    assert rows[0]["status"] == "finished" and rows[0]["outcome"] is None and rows[0]["return_pct"] is None


def test_score_bands_and_filters(unsealed):
    obs = [
        ob("A", DAYS[0], score=95),
        ob("B", DAYS[0], score=85),
        ob("C", DAYS[0], score=75, word="TRADE"),
        ob("D", DAYS[0], score=65, regime="DEFENSIVE"),
        ob("E", DAYS[0], score=40, horizon=10),
        ob("F", DAYS[0], score=None),
    ]
    rows = r.build_rows(obs, DAYS[:1])
    sym = lambda rs: sorted(x["symbol"] for x in rs)  # noqa: E731
    assert sym(r.apply_filters(rows, bands=["90+"])) == ["A"]
    assert sym(r.apply_filters(rows, bands=["80-90", "70-80"])) == ["B", "C"]
    assert sym(r.apply_filters(rows, bands=["below 60"])) == ["E"]
    assert sym(r.apply_filters(rows, words=["TRADE"])) == ["C"]
    assert sym(r.apply_filters(rows, regimes=["DEFENSIVE"])) == ["D"]
    assert sym(r.apply_filters(rows, horizons=[10])) == ["E"]
    assert r.band_of(None) is None and r.band_of(90) == "90+" and r.band_of(60) == "60-70"


def test_outcome_filter_matches_graded_unsealed_rows_and_open(unsealed):
    obs = [
        ob("W", DAYS[0], outcome="target", ret=0.08, resolved=DAYS[3]),
        ob("L", DAYS[0], outcome="stop", ret=-0.04, resolved=DAYS[2]),
        ob("O", DAYS[0]),
    ]
    rows = r.build_rows(obs, DAYS[:5])
    pick = lambda o: sorted(x["symbol"] for x in r.apply_filters(rows, outcomes=o))  # noqa: E731
    assert pick(["target"]) == ["W"] and pick(["stop"]) == ["L"] and pick(["open"]) == ["O"]


def test_outcome_filter_never_matches_sealed_rows(sealed):
    rows = r.build_rows([ob("A", DAYS[0], outcome="target", ret=0.08, resolved=DAYS[3])], DAYS[:5])
    for o in (["target"], ["open"], ["stop", "timeout"]):
        assert r.apply_filters(rows, outcomes=o) == []


def test_summary_has_counts_for_sealed_rows_and_no_results(sealed):
    rows = r.build_rows(
        [ob("A", DAYS[0], outcome="target", ret=0.08, resolved=DAYS[3]), ob("B", DAYS[0])], DAYS[:5]
    )
    s = r.summarise(rows)
    assert s["ideas"] == 2 and s["tracking"] == 2 and s["sealed_ideas"] == 2
    assert s["results"] == {"ideas": 0, "target": 0, "stop": 0, "timeout": 0, "avg_return_pct": None}


def test_summary_results_when_unsealed(unsealed):
    obs = [
        ob("W", DAYS[0], outcome="target", ret=0.08, resolved=DAYS[3]),
        ob("L", DAYS[0], outcome="stop", ret=-0.04, resolved=DAYS[2]),
    ]
    s = r.summarise(r.build_rows(obs, DAYS[:5]))
    assert s["finished"] == 2 and s["results"]["target"] == 1 and s["results"]["stop"] == 1
    assert s["results"]["avg_return_pct"] == 2.0


def test_no_sessions_gives_no_rows():
    assert r.build_rows([], []) == []


def test_only_symbols_keeps_just_the_stocks_we_hold_or_sold(unsealed):
    obs = [ob("AAA", d) for d in DAYS[:2]] + [ob("BBB", d) for d in DAYS[:2]]
    rows = r.build_rows(obs, DAYS)
    assert {x["symbol"] for x in r.apply_filters(rows)} == {"AAA", "BBB"}
    assert {x["symbol"] for x in r.apply_filters(rows, only_symbols={"AAA"})} == {"AAA"}
    assert r.apply_filters(rows, only_symbols=set()) == []  # nothing held or sold: nothing to show


def _watch_user(db_session, name, role="owner"):
    from swing_trade_ml.db.models.session import User

    u = User(username=name, hashed_password="x", is_active=True, role=role, plan="free")
    db_session.add(u)
    db_session.flush()
    return u


def _groww_rows(db_session, user):
    from datetime import UTC, datetime

    from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem, UserWatchlistSale

    now = datetime.now(UTC)
    db_session.add_all(
        [
            UserWatchlistItem(user_id=user.id, symbol="held1", buy_price=100.0),
            UserWatchlistItem(user_id=user.id, symbol="WATCHONLY"),
            UserWatchlistItem(user_id=user.id, symbol="GONE", buy_price=50.0, removed_at=now),
        ]
    )
    db_session.add(
        UserWatchlistSale(
            user_id=user.id,
            symbol="SOLD1",
            bought_on=date(2026, 11, 1),
            entry_price=10.0,
            entry_source="your_price",
            sell_price=12.0,
            sold_on=date(2026, 11, 5),
        )
    )
    db_session.flush()


def test_held_or_sold_includes_groww_held_and_sold_only_for_given_users(db_session):
    owner = _watch_user(db_session, "sudeeksha")
    other = _watch_user(db_session, "someone", role="member")
    _groww_rows(db_session, owner)
    _groww_rows(db_session, other)
    assert r.held_or_sold_symbols(db_session, "paper") == set()
    got = r.held_or_sold_symbols(db_session, "paper", [owner.id])
    assert got == {"HELD1", "SOLD1"}  # not watch-only, not removed-unsold


def test_groww_user_ids_follow_the_real_account_privacy_rule(db_session):
    from swing_trade_ml.api.deps import Principal

    owner = _watch_user(db_session, "sudeeksha")
    plain_owner = _watch_user(db_session, "otherowner")
    member = _watch_user(db_session, "mem", role="member")

    assert r.groww_user_ids(db_session, Principal(user=owner)) == [owner.id]
    assert r.groww_user_ids(db_session, Principal(user=plain_owner)) == []
    assert r.groww_user_ids(db_session, Principal(user=member)) == []
    assert r.groww_user_ids(db_session, None) == []
    assert r.groww_user_ids(db_session, Principal(user=None, via_api_key=True)) == [owner.id]
