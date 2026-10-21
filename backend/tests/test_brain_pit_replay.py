# backend/tests/test_brain_pit_replay.py
"""ps12: the point-in-time replay account, its risk gate and the same-rules comparison."""

from __future__ import annotations

import random
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import pit_replay as pr
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.portfolio_sim import Book, Pick, simulate
from swing_trade_ml.services.costs import apply_slippage

START = date(2026, 1, 5)
DAYS = [START + timedelta(days=i) for i in range(40)]
NO_BUCKET = lambda s: None  # noqa: E731
BUCKETS = {"BANK1": "BANK", "BANK2": "BANK", "IT1": "IT"}


def flat(price=100.0, overrides=None, days=DAYS):
    rows = []
    for i, d in enumerate(days):
        o = h = lo = cl = price
        if overrides and i in overrides:
            o, h, lo, cl = overrides[i]
        rows.append({"day": d, "open": o, "high": h, "low": lo, "close": cl})
    return pd.DataFrame(rows)


def noisy(seed: int, symbols, days=DAYS) -> dict[str, pd.DataFrame]:
    rng = random.Random(seed)
    out = {}
    for s in symbols:
        px, rows = 50 + rng.random() * 400, []
        for d in days:
            o = px * (1 + rng.gauss(0, 0.015))
            cl = o * (1 + rng.gauss(0, 0.03))
            rows.append(
                {
                    "day": d,
                    "open": o,
                    "high": max(o, cl) * (1 + abs(rng.gauss(0, 0.015))),
                    "low": min(o, cl) * (1 - abs(rng.gauss(0, 0.015))),
                    "close": cl,
                }
            )
            px = cl
        out[s] = pd.DataFrame(rows)
    return out


def record(day, picks, banner="NORMAL"):
    return pr.DayRecord(day=day, banner=banner, picks=list(picks), ideas=[])


# --- the account ------------------------------------------------------------------------------------


def test_stepping_the_account_matches_portfolio_sim_exits_and_costs():
    """Picks fed day by day through run_account give exactly simulate()'s account: same exits, costs."""
    symbols = [f"S{i}" for i in range(12)]
    bars = noisy(3, symbols)
    rng = random.Random(9)
    decision_days = DAYS[:25]
    plan = {d: [(s, rng.random()) for s in rng.sample(symbols, 4)] for d in decision_days}
    banners = {d: rng.choice(["NORMAL", "NORMAL", "DEFENSIVE", "NO_NEW_TRADES"]) for d in decision_days}

    res, _ = pr.run_account(
        bars,
        DAYS,
        decision_days,
        lambda d, a: record(d, plan[d], banners[d]),
        capital=500_000,
        buckets=NO_BUCKET,
    )
    picks = [Pick(d, s, sc) for d, ps in plan.items() for s, sc in ps]
    ref = simulate(picks, bars, DAYS, capital=500_000, modes=banners)
    assert res.summary() == ref.summary()
    assert res.curve == ref.curve
    assert res.trades > 5
    assert {t.status for t in res.closed} <= {"target", "stop", "timeout"}
    assert len(res.closed) == res.trades


def test_closed_trades_name_the_exit_rule():
    up = flat(overrides={3: (100, 109, 100, 108)})
    down = flat(overrides={3: (100, 100, 94, 95)})
    res = simulate(
        [Pick(DAYS[0], "U", 0.9), Pick(DAYS[0], "D", 0.8)], {"U": up, "D": down}, DAYS, capital=500_000
    )
    assert sorted((t.symbol, t.status) for t in res.closed) == [("D", "stop"), ("U", "target")]
    still = simulate([Pick(DAYS[0], "F", 0.9)], {"F": flat()}, DAYS, capital=500_000)
    assert [t.status for t in still.closed] == ["timeout"] and still.closed[0].exit_day == DAYS[15]


def test_a_trade_is_bought_at_the_next_open_not_the_decision_close():
    bars = {"A": flat(overrides={1: (110, 111, 109, 110)})}  # the next day opens 10% higher
    seen = {}

    def decide(day, account):
        seen[day] = account.holdings()
        return record(day, [("A", 1.0)] if day == DAYS[0] else [])

    pr.run_account(bars, DAYS[:5], DAYS[:5], decide, capital=500_000, buckets=NO_BUCKET)
    assert seen[DAYS[0]] == ()  # the decision day: nothing bought yet
    (h,) = seen[DAYS[1]]
    assert h.symbol == "A" and h.opened_on == DAYS[1]
    assert h.avg_price == pytest.approx(apply_slippage(110.0, "BUY"))
    assert h.stop == pytest.approx(h.avg_price * 0.96) and h.target == pytest.approx(h.avg_price * 1.08)


def test_the_account_the_brain_sees_never_contains_later_prices():
    """The account on day D is the same whatever happens after D (no look-ahead)."""
    symbols = ["A", "B", "C", "D"]
    base = noisy(5, symbols)
    later = {s: df.copy() for s, df in base.items()}
    cut = DAYS[12]
    for df in later.values():
        after = df["day"] > cut
        df.loc[after, ["open", "high", "low", "close"]] *= 1.7  # a wild future

    def run(bars):
        seen = {}

        def decide(day, account):
            assert account.as_of == day  # stepped exactly to this close, not beyond
            seen[day] = (account.numbers(), account.holdings())
            return record(day, [(symbols[DAYS.index(day) % 4], 1.0)])

        pr.run_account(bars, DAYS[:20], DAYS[:20], decide, capital=500_000, buckets=NO_BUCKET)
        return seen

    a, b = run(base), run(later)
    assert all(a[d] == b[d] for d in DAYS[:20] if d <= cut)
    assert any(a[d] != b[d] for d in DAYS[:20] if d > cut)


def test_a_stopped_variant_resumes_without_asking_the_brain_again(tmp_path):
    bars = noisy(1, ["A", "B"])
    calls = []

    def decide(day, account):
        calls.append(day)
        if len(calls) == 6:
            raise KeyboardInterrupt  # the machine stops mid-run
        return record(day, [("A" if len(calls) % 2 else "B", 1.0)])

    cp = tmp_path / "cp.json"
    with pytest.raises(KeyboardInterrupt):
        pr.run_account(bars, DAYS[:10], DAYS[:10], decide, capital=500_000, buckets=NO_BUCKET, checkpoint=cp)
    assert len(pr._load(cp)) == 5
    resumed, _ = pr.run_account(
        bars, DAYS[:10], DAYS[:10], decide, capital=500_000, buckets=NO_BUCKET, checkpoint=cp
    )
    assert calls[6:] == DAYS[5:10]  # only the days not saved were asked
    plan = pr._load(cp)
    picks = [Pick(d, s, sc) for d, r in plan.items() for s, sc in r.picks]
    assert resumed.summary() == simulate(picks, bars, DAYS[:10], capital=500_000).summary()


# --- the limits the risk gate reads -----------------------------------------------------------------


def _account(capital=500_000, bars=None, held=(), buckets=NO_BUCKET):
    bars = bars or {s: flat() for s in ("A", "B", "C", "D", "E", "BANK1", "BANK2", "IT1")}
    book = Book(bars, capital=capital)
    book.step(DAYS[0], [])
    book.step(DAYS[1], [Pick(DAYS[0], s, 1.0, buckets(s)) for s in held])
    return pr.SimAccount(book, buckets)


def _cand(symbol, price=100.0, buckets=NO_BUCKET):
    from swing_trade_ml.brain.modules.m07_risk.allocator import Candidate

    return Candidate(symbol=symbol, price=price, strength=0.7, bucket=buckets(symbol), instrument_id=1)


def test_the_check_refuses_a_stock_already_held_and_sizes_a_new_one():
    acc = _account(held=("A",))
    no = acc.check(_cand("A"), acc.book.cash)
    assert not no.allowed and no.rule == "ALREADY_OPEN"
    yes = acc.check(_cand("B"), acc.book.cash)
    assert yes.allowed and yes.qty > 0 and yes.amount_inr >= acc.risk_account().min_position_inr


def test_the_check_refuses_when_the_slots_or_cash_run_out():
    acc = _account(capital=100_000, held=("A", "B", "C", "D"))  # the Rs 1 lakh rung: four positions
    assert acc.numbers()["free_slots"] == 0 and acc.risk_account().free_slots == 0
    assert acc.check(_cand("E"), acc.book.cash).rule == "POSITION_LIMIT"
    fresh = _account(capital=500_000)
    assert fresh.check(_cand("E"), 1_000.0).rule == "MIN_POSITION"


def test_the_check_keeps_one_stock_per_sector_on_a_small_account():
    acc = _account(capital=100_000, held=("BANK1",), buckets=BUCKETS.get)
    assert acc.risk_account().sector_rule == "one_per_sector"
    assert acc.check(_cand("BANK2", buckets=BUCKETS.get), acc.book.cash).rule == "SECTOR_CAP"
    assert acc.check(_cand("IT1", buckets=BUCKETS.get), acc.book.cash).allowed
    assert acc.risk_account().sector_exposure == {"BANK": pytest.approx(acc.book.open_[0].qty * 100.0)}


def test_the_check_stops_buying_after_a_15_percent_fall():
    crash = flat(overrides=dict.fromkeys(range(2, 40), (60, 60, 60, 60)))
    bars = {"A": crash, "B": flat()}
    book = Book(bars, capital=100_000)
    book.step(DAYS[0], [])
    book.step(DAYS[1], [Pick(DAYS[0], "A", 1.0)])
    book.step(DAYS[2], [])  # A gaps through its stop; the account falls
    acc = pr.SimAccount(book, NO_BUCKET)
    if book.drawdown() < 0.15:  # make sure the fall is past the halt whatever the sizing
        book.equity = book.peak * 0.8
    assert book.halted_now()
    v = acc.check(_cand("B"), book.cash)
    assert not v.allowed and v.rule == "DRAWDOWN"


# --- the point-in-time risk gate --------------------------------------------------------------------


def _ctx(reader, symbols=("A", "B", "C", "D"), mode=c.MarketMode.NORMAL, live=False):
    from datetime import UTC, datetime

    req = c.RunRequest(
        run_id="t", kind="nightly", as_of=datetime(2026, 1, 6, tzinfo=UTC), universe=symbols, live=live
    )
    ctx = BrainContext(request=req, reader=reader)
    ctx.market = c.MarketState(mode=mode)
    for i, s in enumerate(symbols):
        ctx.snapshots[s] = c.Snapshot(symbol=s, as_of="2026-01-05", close=100.0)
        ctx.quality[s] = c.DataQuality(symbol=s, score=1.0, fresh=True)
        ctx.opinions.append(
            c.Opinion(
                source="model",
                symbol=s,
                stance=0.5,
                confidence=0.5,
                reasons=(),
                probability=0.9 - i / 100,
                threshold=0.6,
            )
        )
    return ctx


def test_the_point_in_time_gate_approves_against_the_replay_account():
    acc = _account(capital=500_000, held=("A",))
    reader = SimpleNamespace(pit=acc, instrument_id=lambda s: 1)
    gate = pr.PointInTimeRiskGate
    out = gate().run(_ctx(reader).view_for(gate.manifest))
    by = {v.symbol: v for v in out.verdicts}
    assert not by["A"].allowed and by["A"].rule == "ALREADY_OPEN"
    assert by["B"].allowed and by["C"].allowed and by["B"].max_qty > 0
    defensive = gate().run(_ctx(reader, mode=c.MarketMode.DEFENSIVE).view_for(gate.manifest))
    assert sum(v.allowed for v in defensive.verdicts) == 2  # M07's defensive limit, unchanged
    stop = gate().run(_ctx(reader, mode=c.MarketMode.NO_NEW_TRADES).view_for(gate.manifest))
    assert not any(v.allowed for v in stop.verdicts)


def test_without_a_replay_account_the_gate_is_exactly_m07():
    from swing_trade_ml.brain.modules.m07_risk.module import RiskGate

    reader = SimpleNamespace(instrument_id=lambda s: 1)  # an ordinary replay reader
    gate = pr.PointInTimeRiskGate
    ours = gate().run(_ctx(reader).view_for(gate.manifest))
    theirs = RiskGate().run(_ctx(reader).view_for(RiskGate.manifest))
    assert ours == theirs and {v.rule for v in ours.verdicts} == {"REPLAY"}


def test_a_live_run_always_goes_to_m07s_own_code(monkeypatch):
    from swing_trade_ml.brain.modules.m07_risk.module import RiskGate

    calls = []
    monkeypatch.setattr(RiskGate, "run", lambda self, view: calls.append(view) or c.Contribution())
    acc = _account()
    gate = pr.PointInTimeRiskGate
    gate().run(_ctx(SimpleNamespace(pit=acc, instrument_id=lambda s: 1), live=True).view_for(gate.manifest))
    assert len(calls) == 1


def test_the_live_registry_and_reader_are_untouched():
    import swing_trade_ml.brain.modules  # noqa: F401
    from swing_trade_ml.brain.module import REGISTRY
    from swing_trade_ml.brain.modules.m07_risk.module import RiskGate
    from swing_trade_ml.brain.reader import DatedReader

    before = list(REGISTRY.all())
    reg = pr.pit_registry()
    assert REGISTRY.get("M07") is RiskGate and REGISTRY.all() == before
    assert reg.get("M07") is pr.PointInTimeRiskGate
    assert [c.manifest.id for c in reg.all()] == [c.manifest.id for c in before]
    assert pr.PointInTimeRiskGate.manifest is RiskGate.manifest
    # the replay reader overrides only these; the live DatedReader keeps its own code
    for name in ("holdings", "portfolio_numbers", "system_state", "model_probability"):
        assert getattr(pr.PointInTimeReader, name) is not getattr(DatedReader, name)
        assert getattr(DatedReader, name).__qualname__.startswith("DatedReader.")


# --- baselines --------------------------------------------------------------------------------------


def test_random_accounts_are_fixed_by_their_seed():
    symbols = [f"S{i}" for i in range(10)]
    bars = noisy(7, symbols)
    pool = dict.fromkeys(DAYS[:20], symbols)
    per_day = dict.fromkeys(DAYS[:20], 2)
    modes = dict.fromkeys(DAYS[:20], "NORMAL")

    def summaries(seed):
        return [
            r.summary()
            for r in pr.random_accounts(pool, per_day, bars, DAYS, modes, NO_BUCKET, draws=5, seed=seed)
        ]

    assert summaries(12) == summaries(12)
    assert summaries(12) != summaries(13)


def test_model_only_takes_every_stock_at_the_buy_level():
    scores = {"A": {DAYS[0]: 0.7, DAYS[1]: 0.5}, "B": {DAYS[0]: 0.6}, "C": {DAYS[0]: 0.59}}
    picks = pr.model_only_picks(scores, DAYS[:2], 0.6, NO_BUCKET)
    assert sorted((p.day, p.symbol) for p in picks) == [(DAYS[0], "A"), (DAYS[0], "B")]


def test_account_days_cover_the_decisions_then_let_the_last_buys_finish():
    days = pr.account_days(set(DAYS), DAYS[2:5], settle=3)
    assert days == DAYS[2:8]
    with pytest.raises(ValueError):
        pr.account_days(set(DAYS[3:]), DAYS[2:5])


def test_nifty_and_cash_rows():
    idx = flat(overrides=dict.fromkeys(range(5, 40), (110, 110, 110, 110)))
    r = pr.nifty_row(idx, DAYS[:10], capital=100_000)
    assert 0.09 < r["return"] < 0.1  # bought at the second day's open (100), sold at 110, after costs
    assert pr.CASH_ROW["return"] == 0.0


def test_the_report_names_every_variant_and_says_it_is_not_proof():
    row = {
        "final_equity": 1.0,
        "return": 0.01,
        "max_drawdown": 0.02,
        "trades": 3,
        "still_open": 0,
        "hit_rate_target_first": 0.33,
        "avg_net_per_trade": 0.002,
        "exits": {},
        "halted_days": 0,
        "days_no_new_trades": 1,
        "days_defensive": 2,
        "skipped": {},
    }
    spread = {"median": 0.0, "p5": -0.01, "p95": 0.01}
    rnd = {
        "draws": 3,
        "days_no_new_trades": 1,
        "days_defensive": 2,
        **dict.fromkeys(
            (
                "final_equity",
                "return",
                "max_drawdown",
                "trades",
                "hit_rate_target_first",
                "avg_net_per_trade",
            ),
            spread,
        ),
    }
    result = {
        "protocol": pr.PROTOCOL_ID,
        "decision_days": ["2026-07-13", "2026-08-14"],
        "account_days": ["2026-07-13", "2026-09-04", 40],
        "asof_model": "m",
        "capital": pr.CAPITAL,
        "buy_level": 0.6,
        "slippage_bps": 5.0,
        "accounts": {
            "brain": row,
            "rules_only": row,
            "model_only": row,
            "random": rnd,
            "nifty": {"final_equity": 1, "return": 0.0, "max_drawdown": 0.0, "trades": 1},
            "cash": pr.CASH_ROW,
        },
    }
    text = pr.plain_report(result)
    for name in pr.NAMES.values():
        assert name in text
    assert "not proof" in text


# --- module on/off on the point-in-time replay -------------------------------------------------------


def test_module_ablation_can_run_on_the_point_in_time_replay(tmp_path, monkeypatch):
    import swing_trade_ml.brain.modules  # noqa: F401
    from swing_trade_ml.brain import module_ablation as ma
    from swing_trade_ml.brain import replay_score, service

    monkeypatch.setattr(service, "load_modes", lambda db: {})
    monkeypatch.setattr(replay_score, "load_bars", lambda db, symbols, upto: {})
    test, skip = ma.plan(ma.REGISTRY, {}, pit=True)
    assert {"M14", "M15", "M07"} <= set(test)  # judgeable once the replay has an account
    assert "M09" in skip and "M14" not in skip and "M15" not in skip
    _, plain_skip = ma.plan(ma.REGISTRY, {})
    assert {"M14", "M15"} <= set(plain_skip)  # an ordinary replay still cannot judge them

    bars = {"A": flat(), "B": flat()}
    calls = []

    def decide(registry, day, account):
        calls.append(day)
        has_gate = registry.get("M07") is not None
        word = "TRADE" if has_gate else "WATCH"
        return pr.DayRecord(
            day, "NORMAL", [("A", 1.0)] if has_gate else [], [("A", word, None), ("B", "WAIT", None)]
        )

    kw = {
        "days": DAYS[:3],
        "asof_model": None,
        "checkpoint": tmp_path / "checkpoint.json",
        "upto": DAYS[20],
        "only": ["M07"],
        "pit": True,
        "pit_setup": (DAYS[:3], bars, DAYS[:20]),
        "pit_decide": decide,
    }
    first = ma.run(None, **kw)
    assert len(calls) == 6  # base + without M07, three days each
    again = ma.run(None, **kw)
    assert len(calls) == 6 and first == again
    assert first["protocol"] == ma.PIT_PROTOCOL_ID
    assert first["base"]["account"]["trades"] == 1 and first["without"]["M07"]["account"]["trades"] == 0
    assert first["without"]["M07"]["reading"].startswith("safe")
    assert "replay account of each variant" in ma.plain_report(first)


# --- the real brain on one replayed day (test database) ---------------------------------------------


def _golden(db_session):
    from test_brain_golden_day import GOLDEN_DAY, STOCKS, _build_market

    _build_market(db_session)
    return GOLDEN_DAY, [s[0] for s in STOCKS]


def test_with_no_holdings_the_replay_runs_the_same_steps_as_the_runner(db_session):
    import swing_trade_ml.brain.modules  # noqa: F401
    from swing_trade_ml.brain import service
    from swing_trade_ml.brain.module import REGISTRY
    from swing_trade_ml.brain.reader import DatedReader
    from swing_trade_ml.brain.replay_week import as_of_end_of_ist_day
    from swing_trade_ml.brain.runner import execute

    day, symbols = _golden(db_session)
    as_of = as_of_end_of_ist_day(day)
    req = c.RunRequest(run_id="x", kind="nightly", as_of=as_of, universe=tuple(symbols), live=False)
    modes = service.load_modes(db_session)
    theirs = execute(req, DatedReader(db_session, as_of=as_of, live=False), REGISTRY, modes)
    ours = pr.execute_with_holdings(req, DatedReader(db_session, as_of=as_of, live=False), REGISTRY, modes)
    assert {s: d.word for s, d in ours.decisions.items()} == {s: d.word for s, d in theirs.decisions.items()}
    assert ours.banner.mode == theirs.banner.mode
    assert [(e.module_id, e.status) for e in ours.trace] == [(e.module_id, e.status) for e in theirs.trace]


def test_a_rules_only_day_is_approved_on_the_replay_account_but_never_on_a_plain_replay(
    db_session, monkeypatch
):
    import swing_trade_ml.brain.modules  # noqa: F401
    from swing_trade_ml.brain import service
    from swing_trade_ml.brain.module import REGISTRY
    from swing_trade_ml.brain.replay_week import as_of_end_of_ist_day

    day, symbols = _golden(db_session)
    monkeypatch.setattr(pr.PointInTimeReader, "universe", lambda self: tuple(symbols))
    from swing_trade_ml.brain.replay_score import load_bars

    bars = load_bars(db_session, symbols, day)
    book = Book(bars, capital=pr.CAPITAL)
    book.step(day, [])
    account = pr.SimAccount(book, NO_BUCKET)
    modes = service.load_modes(db_session)
    rec = pr.run_brain_day(
        db_session,
        day,
        account,
        registry=pr.pit_registry(),
        modes=modes,
        asof_model=object(),
        flat_score=0.6,
        release=False,  # keep the test's transaction (and its market) alive
    )
    words = {s: w for s, w, _ in rec.ideas}
    assert set(words) == set(symbols)
    assert rec.seen["as_of"] == day.isoformat() and rec.seen["held"] == []

    # the same day and inputs with the ordinary risk gate: every liked idea refused ("REPLAY")
    as_of = as_of_end_of_ist_day(day)
    reader = pr.PointInTimeReader(db_session, as_of, account, asof_model=object(), flat_score=0.6)
    req = c.RunRequest(run_id="y", kind="nightly", as_of=as_of, universe=tuple(symbols), live=False)
    plain = pr.execute_with_holdings(req, reader, REGISTRY, modes)
    assert all(v.rule == "REPLAY" for v in plain.verdicts.values() if not v.allowed)
    assert not any(v.allowed for v in plain.verdicts.values())
    pit = pr.execute_with_holdings(req, reader, pr.pit_registry(), modes)
    approved = {s for s, v in pit.verdicts.items() if v.allowed}
    assert approved, "the replay account has room, so the point-in-time gate approves a liked idea"
    assert rec.picks and {s for s, _ in rec.picks} <= approved  # an approved idea became a TRADE


def test_the_live_reader_still_reads_the_real_account(db_session):
    from datetime import UTC, datetime

    from swing_trade_ml.brain.reader import DatedReader
    from swing_trade_ml.core.enums import PositionStatus
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Position

    inst = Instrument(instrument_token=994001, tradingsymbol="LIVEPOS", exchange="NSE", is_active=True)
    db_session.add(inst)
    db_session.flush()
    db_session.add(
        Position(
            instrument_id=inst.id,
            mode="paper",
            status=PositionStatus.OPEN,
            quantity=7,
            entry_price=50,
            entry_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    db_session.flush()
    now = datetime.now(UTC)
    live = DatedReader(db_session, as_of=now, live=True)
    assert [h.symbol for h in live.holdings("paper")] == ["LIVEPOS"]
    assert DatedReader(db_session, as_of=now, live=False).holdings("paper") == ()
    sim = pr.PointInTimeReader(db_session, now, _account(held=("A",)))
    assert [h.symbol for h in sim.holdings("paper")] == ["A"]
    assert sim.portfolio_numbers("paper")["value"] > 0
    assert DatedReader(db_session, as_of=now, live=False).portfolio_numbers("paper") is None
