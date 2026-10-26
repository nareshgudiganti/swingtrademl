"""Shadow Test: rank order, no-repeat counting, running vs finished, honest verdict, IST dates, owner-only."""

import itertools
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.services import shadow_test as st

IST = ZoneInfo("Asia/Kolkata")


_ids = itertools.count(1)


def idea(symbol, day, rank=1, outcome=None, ret=None, resolved=None):
    return st.Idea(next(_ids), symbol, day, rank, 0.9, "WATCH", outcome, ret, 5, resolved)


# ------------------------------------------------------------------- ranking --


def test_highest_score_is_rank_1_and_equal_scores_share_a_place():
    ranks = st.rank_ideas([(1, 0.95), (2, 0.90), (3, 0.90), (4, 0.80)])
    assert ranks == {1: 1, 2: 2, 3: 2, 4: 4}


def test_groups_are_fixed():
    assert [st.group_of(r) for r in (1, 5, 6, 20, 21, 300)] == [
        "Top 5", "Top 5", "Ranks 6-20", "Ranks 6-20", "Rank 21+", "Rank 21+",
    ]


# ------------------------------------------------------------ no-repeat rule --


def test_a_stock_that_stays_on_the_list_counts_once_while_running():
    ideas = [idea("KEI", date(2026, 10, d)) for d in (20, 21, 22, 23)]
    assert len(st.build_records(ideas)) == 1


def test_a_stock_can_start_again_after_its_record_finished():
    first = idea("KEI", date(2026, 10, 1), outcome="target", ret=0.08, resolved=date(2026, 10, 9))
    same_window = idea("KEI", date(2026, 10, 6))  # inside the finished window: not counted again
    after = idea("KEI", date(2026, 10, 12))
    records = st.build_records([first, same_window, after])
    assert [r.day for r in records] == [date(2026, 10, 1), date(2026, 10, 12)]


def test_different_stocks_are_independent():
    assert len(st.build_records([idea("KEI", date(2026, 10, 20)), idea("RBLBANK", date(2026, 10, 20))])) == 2


# ------------------------------------------------------- running vs finished --


def bars(*pairs):
    return [(date(2026, 10, d), c) for d, c in pairs]


def test_running_progress_counts_trading_days_and_move_since_ranked():
    series = bars((20, 100), (21, 101), (22, 103), (23, 105))
    p = st.running_progress(100, series, date(2026, 10, 20), date(2026, 10, 23))
    assert p["day"] == 3
    assert p["since_pct"] == 5.0
    assert round(p["today_pct"], 2) == round((105 / 103 - 1) * 100, 2)
    assert p["price_not_updated"] is False
    assert 0.74 < p["position"] < 0.76  # 5% on a -4..+8 bar


def test_exactly_day_15_is_still_capped_at_15():
    series = [(date(2026, 9, 1) + timedelta(days=n), 100 + n) for n in range(1, 21)]
    p = st.running_progress(100, series, date(2026, 9, 1), series[-1][0])
    assert p["day"] == 15


def test_missing_last_candle_says_price_not_updated_and_shows_no_todays_move():
    series = bars((20, 100), (21, 101))
    p = st.running_progress(100, series, date(2026, 10, 20), date(2026, 10, 23))
    assert p["price_not_updated"] is True
    assert p["today_pct"] is None
    assert p["since_pct"] == 1.0


def test_position_is_clamped_to_the_stop_and_target_ends():
    low = st.running_progress(100, bars((20, 100), (21, 80)), date(2026, 10, 20), date(2026, 10, 21))
    high = st.running_progress(100, bars((20, 100), (21, 130)), date(2026, 10, 20), date(2026, 10, 21))
    assert low["position"] == 0.0 and high["position"] == 1.0


# -------------------------------------------------------------------- verdict --


def test_under_30_days_the_page_only_says_too_early():
    finished = [idea("A", date(2026, 10, 1), 1, "target", 0.08, date(2026, 10, 5))]
    g = st.group_table(finished)
    v = st.verdict(finished, 9, g)
    assert v["state"] == "too_early" and v["headline"] == "Too early to tell"
    assert "not proven" in v["detail"]
    assert (v["days_done"], v["days_needed"]) == (9, 30)


def test_group_table_counts_finished_only():
    finished = [
        idea("A", date(2026, 10, 1), 2, "target", 0.08, date(2026, 10, 5)),
        idea("B", date(2026, 10, 1), 3, "stop", -0.04, date(2026, 10, 3)),
        idea("C", date(2026, 10, 1), 30, "timeout", -0.01, date(2026, 10, 22)),
    ]
    top, mid, rest = st.group_table(finished)
    assert (top["finished"], top["target"], top["stop"], top["average_pct"]) == (2, 1, 1, 2.0)
    assert mid["finished"] == 0 and mid["average_pct"] is None
    assert (rest["finished"], rest["average_pct"]) == (1, -1.0)


def test_after_30_days_the_verdict_describes_but_never_promises():
    finished = [
        idea(f"S{n}", date(2026, 9, 1), 1 if n % 2 else 30, "timeout", 0.01, date(2026, 9, 20))
        for n in range(6)
    ]
    v = st.verdict(finished, 31, st.group_table(finished))
    assert v["state"] == "reviewable"
    assert "chance" in v["detail"]
    for word in ("buy", "sell", "guarantee", "profit"):
        assert word not in v["detail"].lower()


# ------------------------------------------------------------------- database --


def _inst(db, symbol, token):
    inst = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(inst)
    db.flush()
    return inst


def _bar(db, inst, day, close):
    db.add(
        Candle(
            instrument_id=inst.id, interval="day",
            ts=datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC),
            open=close, high=close, low=close, close=close, volume=1,
        )
    )


def _run(db, run_id, day, status="done"):
    db.add(
        BrainRun(
            id=run_id, kind="nightly", book="paper", live=True, status=status,
            as_of=datetime.combine(day, time(15, 50), tzinfo=IST).astimezone(UTC),
        )
    )
    db.flush()


def _dec(db, run_id, symbol, score, outcome=None, ret=None, resolved=None):
    db.add(
        BrainDecision(
            run_id=run_id, symbol=symbol, kind="idea", word="WATCH", confidence=score,
            outcome=outcome, outcome_return=ret, outcome_days=4 if outcome else None, resolved_on=resolved,
        )
    )


def test_view_from_the_database_ranks_follows_and_leaves_out_superseded_runs(db_session, monkeypatch):
    monkeypatch.setattr(st, "last_closed_trading_day", lambda now: date(2026, 10, 23))
    kei, rbl = _inst(db_session, "KEI", 920001), _inst(db_session, "RBLBANK", 920002)
    for inst, closes in ((kei, (100, 102, 104)), (rbl, (100, 99, 97))):
        for day, c in zip((21, 22, 23), closes, strict=True):
            _bar(db_session, inst, date(2026, 10, day), c)
    _run(db_session, "r1", date(2026, 10, 21))
    _run(db_session, "r1old", date(2026, 10, 21), status="superseded")
    _dec(db_session, "r1", "KEI", 0.95)
    _dec(db_session, "r1", "RBLBANK", 0.90)
    _dec(db_session, "r1old", "KEI", 0.99)  # superseded: never counted
    _run(db_session, "r0", date(2026, 10, 1))
    _dec(db_session, "r0", "OLDONE", 0.97, "target", 0.08, date(2026, 10, 6))
    db_session.flush()

    v = st.build_view(db_session, datetime(2026, 10, 24, 6, 0, tzinfo=UTC))
    assert v["totals"] == {"running": 2, "finished": 1, "target": 1, "stop": 0}
    by = {r["symbol"]: r for r in v["running"]}
    assert by["KEI"]["rank"] == 1 and by["RBLBANK"]["rank"] == 2
    assert by["KEI"]["day"] == 2 and by["KEI"]["since_pct"] == 4.0
    assert by["RBLBANK"]["since_pct"] == -3.0
    assert by["KEI"]["paper_bought"] is False
    assert v["verdict"]["state"] == "too_early"
    assert v["groups"][0]["finished"] == 1
    assert "not part of the sealed" in v["label"]


def test_route_is_owner_only_and_read_only(client, db_session, monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)
    from swing_trade_ml.core.security import create_access_token
    from swing_trade_ml.db.models.session import User

    def token(name, role):
        u = User(username=name, hashed_password="x", is_active=True, role=role, plan="pro")
        db_session.add(u)
        db_session.flush()
        return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id, 'tv': 0})}"}

    assert client.get("/api/v1/brain/shadow-test", headers=token("shmember", "member")).status_code == 403
    r = client.get("/api/v1/brain/shadow-test", headers=token("showner", "owner"))
    assert r.status_code == 200
    assert set(r.json()) >= {"verdict", "totals", "groups", "running", "finished", "label"}
