"""M09 `learn._scored_rows` must return exactly what the original implementation returned.

On 2026-11-05 `_scored_rows` was rewritten for speed (page-load timeout on /brain/learning): fewer columns,
each run's large `context` read once per run, each stock's sector looked up once. The promise is "the rows
produced are exactly the same as before". This test keeps that promise checkable: `_reference_scored_rows`
below is the ORIGINAL implementation (as of commit 6f00380), copied verbatim, and every scenario compares
it with the live function — the rows themselves and what is built from them (`learning_report`,
`one_per_day`, the buy-level proposal).

Do not "fix" the reference copy to match a new behaviour. If the live function should change what it
returns, that is a decision-logic change in a frozen file: it needs the owner's approval, and this test
should then be updated deliberately, with the reason.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pytest
from sqlalchemy import func, select

from swing_trade_ml.brain.modules.m09_learn import learn
from swing_trade_ml.brain.modules.m09_learn.learn import _ROW_COLUMNS, _market_label
from swing_trade_ml.brain.modules.m09_learn.proposals import buy_level_proposal
from swing_trade_ml.brain.modules.m09_learn.report import one_per_day
from swing_trade_ml.brain.modules.m09_learn.scoring import SCORED_OUTCOMES
from swing_trade_ml.brain.reader import IST
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.ml.sector_map import get_sector_bucket

# The real function, kept before any test replaces `learn._scored_rows`, so a replacement can call it.
LIVE_SCORED_ROWS = learn._scored_rows


def _reference_scored_rows(db, since):
    """The original `_scored_rows` (commit 6f00380), verbatim apart from the name. One query that loads
    whole decision rows plus each run's `context`; the market label and sector are computed per row."""
    stmt = (
        select(BrainDecision, BrainRun.started_at, BrainRun.as_of, BrainRun.context)
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        .where(BrainDecision.outcome.in_(SCORED_OUTCOMES), BrainRun.status == "done")
    )
    records = []
    if since is not None:
        stmt = stmt.where(BrainRun.as_of >= datetime.combine(since, time(0, 0), tzinfo=IST))
    for decision, started_at, as_of, context in db.execute(stmt).all():
        decision_day = as_of.astimezone(IST).date()
        records.append(
            {
                "run_id": decision.run_id,
                "run_started": started_at,
                "decision_day": decision_day,
                "symbol": decision.symbol,
                "word": decision.word,
                "confidence": decision.confidence,
                "score_source": decision.score_source,
                "outcome": decision.outcome,
                "ret": decision.outcome_return,
                "market": _market_label(context),
                "sector": get_sector_bucket(decision.symbol),
            }
        )
    return pd.DataFrame(records, columns=list(_ROW_COLUMNS))


# ------------------------------------------------------------------------------------------ helpers


def _run(db, run_id, as_of, status="done", context="CALM"):
    ctx = {"situations": [{"scope": "market", "label": "calm"}]} if context == "CALM" else context
    db.add(
        BrainRun(
            id=run_id, kind="nightly", as_of=as_of, book="bot", status=status, context=ctx,
            started_at=as_of, modules={}, trace=[], quality={},
        )
    )
    db.flush()  # the run must exist before any decision that points at it


def _decision(db, run_id, symbol, *, word="TRADE", outcome="target", ret=0.05, conf=0.6,
              source="model", kind="idea"):
    db.add(
        BrainDecision(
            run_id=run_id, symbol=symbol, kind=kind, word=word, outcome=outcome, outcome_return=ret,
            confidence=conf, score_source=source, qty=0, horizon_days=15, reasons=[],
        )
    )


def _assert_one_decision_per_symbol_per_run(db) -> None:
    """The seeded data must look like real data: a run decides each stock once. Two decisions for the same
    stock in one run share their `run_started`, so `one_per_day` (it keeps the latest `run_started`) cannot
    tell them apart and keeps whichever the database returned last. The reference and the live query have
    no ORDER BY, so with such ties this comparison would depend on database row order, not on the code."""
    repeats = db.execute(
        select(BrainDecision.run_id, BrainDecision.symbol, func.count())
        .group_by(BrainDecision.run_id, BrainDecision.symbol)
        .having(func.count() > 1)
    ).all()
    assert not repeats, f"{len(repeats)} (run, stock) pairs have more than one decision, e.g. {repeats[:3]}"


def _normalised(df: pd.DataFrame) -> pd.DataFrame:
    keys = ["run_id", "symbol", "word", "outcome", "ret", "confidence", "score_source", "market", "sector"]
    return df.sort_values(keys, na_position="last", kind="mergesort").reset_index(drop=True)


def _as_json(obj) -> str:
    def default(o):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return o.tolist() if hasattr(o, "tolist") else str(o)

    return json.dumps(obj, default=default, sort_keys=True)


def _first_difference(a, b, path="report") -> str:
    """Where two reports first differ (a failure message only; the comparison itself is the JSON equality)."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key not in a or key not in b:
                return f"{path}.{key} only on one side"
            found = _first_difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return ""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return f"{path} has {len(a)} versus {len(b)} entries"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = _first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return ""
    return "" if _as_json(a) == _as_json(b) else f"{path}: {_as_json(a)[:80]} versus {_as_json(b)[:80]}"


def _assert_same_rows(db, since, live=None):
    reference = _reference_scored_rows(db, since)
    actual = (live or LIVE_SCORED_ROWS)(db, since)
    assert list(reference.columns) == list(actual.columns)
    assert len(reference) == len(actual)
    pd.testing.assert_frame_equal(_normalised(reference), _normalised(actual), check_dtype=True)
    return actual


def _ordering_ties(rows: pd.DataFrame) -> list[tuple]:
    """The (stock, IST decision day) pairs with two or more scored decisions sharing a run_started."""
    if rows.empty:
        return []
    sizes = rows.groupby(["symbol", "decision_day", "run_started"]).size()
    return [key[:2] for key in sizes[sizes > 1].index]


def _assert_no_ordering_ties(db, since) -> None:
    """No two scored decisions share (stock, IST decision day, run_started).

    `one_per_day` keeps the latest `run_started` per (stock, day). Rows that tie on all three cannot be
    ordered by it, so which one survives depends on the order the database returned them (neither query has
    an ORDER BY). Such a fixture would test the database's row order, not the code, so it is refused here,
    inside the downstream comparison, and no fixture can bypass it."""
    ties = _ordering_ties(_reference_scored_rows(db, since))
    assert not ties, f"{len(ties)} (stock, day) pairs tie on run_started, e.g. {ties[:3]}"


def _in_canonical_order(fn):
    """The same rows, sorted into one fixed order. The reports add floats, and adding the same numbers in a
    different order can differ in the last digit, so both sides are fed in the same order. The comparison
    stays exact: this removes the database's row order from the downstream result, nothing is rounded."""

    def ordered(db, since):
        return _normalised(fn(db, since))

    return ordered


def _assert_same_downstream(db, since, monkeypatch, live=None):
    """The only downstream entry. It refuses a fixture with ties first (nothing can skip that), then compares
    the reference and the live rows through the report, the one-per-day rows and the buy-level proposal."""
    _assert_no_ordering_ties(db, since)
    out = {}
    for label, fn in (("reference", _reference_scored_rows), ("live", live or LIVE_SCORED_ROWS)):
        fn = _in_canonical_order(fn)
        monkeypatch.setattr(learn, "_scored_rows", fn)
        report = learn.learning_report(db, since)
        rows = one_per_day(fn(db, since))
        model_rows = rows[rows["score_source"] == "model"]
        out[label] = (report, _normalised(rows) if len(rows) else rows, buy_level_proposal(model_rows, 0.55))
    (rep_a, rows_a, prop_a), (rep_b, rows_b, prop_b) = out["reference"], out["live"]
    assert _as_json(rep_a) == _as_json(rep_b), f"learning_report differs: {_first_difference(rep_a, rep_b)}"
    pd.testing.assert_frame_equal(rows_a, rows_b, check_dtype=True)
    assert _as_json(prop_a) == _as_json(prop_b), "buy-level proposal differs"
    return rep_b, prop_b


# ------------------------------------------------------------------------------------------ scenarios


def test_empty_database_gives_identical_empty_results(db_session, monkeypatch):
    for since in (None, date(2026, 1, 1)):
        assert len(_assert_same_rows(db_session, since)) == 0
        _assert_same_downstream(db_session, since, monkeypatch)


def _seed_edge_cases(db, ties=True):
    """Every edge: null context, excluded statuses and outcomes, the IST-midnight boundary, null confidence,
    score source, return and sector, a holding. With `ties` the same stock is also decided twice in one run
    and in two runs at the same instant (raw-row parity keeps those). Without them (the downstream
    comparison, which refuses ties) each of those edges is kept on a different stock, so no tie exists but
    the stop and the same-instant-runs paths are still covered."""
    base = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    _run(db, "r-ctx-market", base)
    _run(db, "r-ctx-none", base + timedelta(days=1), context=None)
    _run(db, "r-ctx-nomarket", base + timedelta(days=2),
         context={"situations": [{"scope": "sector", "label": "x"}]})
    _run(db, "r-ctx-empty", base + timedelta(days=3), context={})
    _run(db, "r-queued", base + timedelta(days=4), status="queued")  # excluded: not done
    _run(db, "r-superseded", base + timedelta(days=5), status="superseded")  # excluded
    # IST-midnight boundary: 18:29 UTC is 23:59 IST (the day before); 18:30 UTC is 00:00 IST (next day).
    _run(db, "r-edge-before", datetime(2026, 10, 10, 18, 29, tzinfo=UTC))
    _run(db, "r-edge-after", datetime(2026, 10, 10, 18, 30, tzinfo=UTC))
    _run(db, "r-twin-a", base + timedelta(days=6))
    _run(db, "r-twin-b", base + timedelta(days=6))  # same instant, different run

    for run_id in ("r-ctx-market", "r-ctx-none", "r-ctx-nomarket", "r-ctx-empty",
                   "r-edge-before", "r-edge-after"):
        _decision(db, run_id, "RELIANCE")
        if ties:
            _decision(db, run_id, "RELIANCE", ret=-0.03, outcome="stop")  # repeated symbol, same run
        else:
            _decision(db, run_id, "SUNPHARMA", ret=-0.03, outcome="stop")  # the stop path, no repeated stock
        _decision(db, run_id, "TCS", conf=None)  # null confidence
        _decision(db, run_id, "INFY", source=None)  # null score source
        _decision(db, run_id, "ZZUNKNOWNSYM", ret=None, outcome="timeout")  # unknown sector, null return
        _decision(db, run_id, "HDFCBANK", word="WATCH", outcome="timeout", ret=0.0)
        _decision(db, run_id, "ICICIBANK", outcome=None, ret=None)  # unscored: excluded
        _decision(db, run_id, "SBIN", outcome="open")  # not a scored outcome: excluded
        _decision(db, run_id, "ITC", outcome="noscore", ret=None)  # excluded
        _decision(db, run_id, "LT", kind="holding")  # a holding with a scored outcome
    for run_id in ("r-queued", "r-superseded"):
        _decision(db, run_id, "RELIANCE")  # must never appear
    if ties:
        for run_id in ("r-twin-a", "r-twin-b"):
            _decision(db, run_id, "TCS")
            _decision(db, run_id, "TCS")
    else:  # two runs at the same instant, each deciding a different stock
        _decision(db, "r-twin-a", "TCS")
        _decision(db, "r-twin-b", "INFY")
    db.flush()


SINCES = (None, date(2026, 10, 1), date(2026, 10, 3), date(2026, 10, 11), date(2026, 12, 1))


def _reversed_live(db, since):
    """The live query answering with the same rows in the opposite order (what a different plan could do)."""
    return LIVE_SCORED_ROWS(db, since).iloc[::-1].reset_index(drop=True)


def _assert_edge_rows(rows):
    assert not {"r-queued", "r-superseded"} & set(rows["run_id"])
    assert rows["market"].isna().any() and (rows["market"] == "calm").any()
    assert rows["sector"].isna().any() and rows["sector"].notna().any()  # unknown symbol has no sector


def test_raw_rows_are_identical_with_repeats_twins_nulls_exclusions_and_boundaries(db_session):
    """Raw-row parity keeps every edge, including the two kinds of tie (a stock twice in one run, and two
    runs at the same instant): the rows are sorted before they are compared, so ties cannot matter here."""
    _seed_edge_cases(db_session, ties=True)
    for since in SINCES:
        _assert_same_rows(db_session, since)
    rows = _assert_same_rows(db_session, None)
    _assert_edge_rows(rows)
    repeats = (rows["symbol"] == "RELIANCE").groupby(rows["run_id"]).sum()
    assert repeats.max() == 2  # the repeat is really there
    assert rows[rows["run_id"].isin(["r-twin-a", "r-twin-b"])].groupby("run_id").size().eq(2).all()


def test_downstream_results_are_identical_on_every_edge_that_does_not_need_a_tie(db_session, monkeypatch):
    _seed_edge_cases(db_session, ties=False)
    for since in SINCES:
        _assert_same_rows(db_session, since)
        _assert_same_downstream(db_session, since, monkeypatch)
        _assert_same_downstream(db_session, since, monkeypatch, live=_reversed_live)
    rows = _assert_same_rows(db_session, None)
    _assert_edge_rows(rows)
    assert (rows["outcome"] == "stop").any()  # the stop path is still covered without a repeated stock


def test_the_downstream_guard_refuses_a_fixture_with_ties(db_session, monkeypatch):
    _seed_edge_cases(db_session, ties=True)
    with pytest.raises(AssertionError, match="tie"):
        _assert_no_ordering_ties(db_session, None)
    with pytest.raises(AssertionError, match="tie"):
        _assert_same_downstream(db_session, None, monkeypatch)  # no fixture reaches the comparison with ties


def test_a_tie_is_found_in_memory_and_decides_which_row_one_per_day_keeps():
    """The reason for the guard, on a small fixed in-memory frame (no database, so no row order to depend on):
    two decisions for one stock in one run tie on run_started, one_per_day keeps the last one it is given, so
    the answer follows the input order."""
    tied = pd.DataFrame(
        [
            {"symbol": "TCS", "decision_day": date(2026, 10, 1), "run_started": 1, "word": "TRADE"},
            {"symbol": "TCS", "decision_day": date(2026, 10, 1), "run_started": 1, "word": "WAIT"},
        ]
    )
    assert _ordering_ties(tied) == [("TCS", date(2026, 10, 1))]
    forward = one_per_day(tied)["word"].tolist()
    backward = one_per_day(tied.iloc[::-1])["word"].tolist()
    assert forward != backward  # same rows, different answer: the order decided it
    free = tied.assign(run_started=[1, 2])
    assert _ordering_ties(free) == []
    assert one_per_day(free)["word"].tolist() == one_per_day(free.iloc[::-1])["word"].tolist() == ["WAIT"]


def test_a_large_realistic_set_is_identical(db_session, monkeypatch):
    rng = random.Random(20261113)
    symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "LT", "AXISBANK",
               "WIPRO", "MARUTI", "SUNPHARMA", "ZZUNKNOWNSYM"]
    start = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    for day in range(70):
        run_id = f"big-{day:03d}"
        _run(db_session, run_id, start + timedelta(days=day), context=None if day % 7 == 0 else "CALM")
        # sample, not choice: a run decides each stock once (see _assert_one_decision_per_symbol_per_run)
        for symbol in rng.sample(symbols, rng.randint(2, 6)):
            outcome = rng.choices(["target", "stop", "timeout"], weights=[4, 3, 3])[0]
            ret = {"target": 0.08, "stop": -0.04, "timeout": rng.uniform(-0.03, 0.05)}[outcome]
            _decision(
                db_session, run_id, symbol,
                word=rng.choice(["TRADE", "WATCH", "WAIT"]), outcome=outcome,
                ret=None if rng.random() < 0.05 else ret,
                conf=rng.choice([None, round(rng.uniform(0.4, 0.95), 3)]),
                source=rng.choice(["model", "model", "calibrated", None]),
            )
    db_session.flush()
    _assert_one_decision_per_symbol_per_run(db_session)
    assert len(_assert_same_rows(db_session, None)) > 150
    for since in (None, date(2026, 9, 1)):
        _assert_same_rows(db_session, since)
        report, _ = _assert_same_downstream(db_session, since, monkeypatch)
    assert report["n_scored"] > 30 and report["by_band"] and report["by_word"] and report["by_week"]


def test_a_real_buy_level_proposal_is_identical(db_session, monkeypatch):
    """High-confidence ideas clearly do better, so a proposal IS produced and the comparison has teeth."""
    rng = random.Random(7)
    symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ITC", "LT"]
    start = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    for day in range(90):
        run_id = f"sig-{day:03d}"
        _run(db_session, run_id, start + timedelta(days=day))
        for symbol in rng.sample(symbols, rng.randint(1, 3)):  # each stock once per run
            conf = round(rng.uniform(0.5, 0.95), 3)
            win = rng.random() < (0.25 if conf < 0.7 else 0.8)
            outcome, ret = ("target", 0.08) if win else ("stop", -0.04)
            _decision(db_session, run_id, symbol, outcome=outcome, ret=ret, conf=conf)
    db_session.flush()
    _assert_one_decision_per_symbol_per_run(db_session)
    _assert_same_rows(db_session, None)
    report, proposal = _assert_same_downstream(db_session, None, monkeypatch)
    assert proposal is not None, "this scenario must yield a proposal, or the comparison proves nothing"
    assert report["by_band"]


# ------------------------------------------------------------------- the comparison must be able to fail


def _wrong_versions():
    real = LIVE_SCORED_ROWS

    def drop_market(db, since):
        df = real(db, since)
        df["market"] = None
        return df

    def wrong_sector(db, since):
        df = real(db, since)
        df["sector"] = "X"
        return df

    def lose_a_row(db, since):
        return real(db, since).iloc[1:].reset_index(drop=True)

    def nulls_become_zero(db, since):
        df = real(db, since)
        df["ret"] = df["ret"].fillna(0.0)
        return df

    return {
        "market label dropped": drop_market,
        "wrong sector": wrong_sector,
        "a row lost": lose_a_row,
        "null return turned into 0": nulls_become_zero,
    }


@pytest.mark.parametrize("mistake", list(_wrong_versions()))
def test_the_comparison_catches_a_subtly_wrong_version(mistake, db_session):
    _seed_edge_cases(db_session)
    with pytest.raises(AssertionError):
        _assert_same_rows(db_session, None, live=_wrong_versions()[mistake])
