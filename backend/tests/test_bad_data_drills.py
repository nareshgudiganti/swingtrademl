"""Bad-data drills (tracker qa6): every failure must make the brain more careful.

CLAUDE.md principle 5: decisions only move toward caution. Bad or stale data never
makes a decision more aggressive; a missing M07 risk gate means NO NEW TRADES; every
module has a safe fallback.

Each drill runs the SAME scenario twice — once with clean data, once with one fault
injected — and checks the faulty run is never bolder than the clean one:
  * per stock: rank(word under fault) <= rank(word with clean data)
    (AVOID < WAIT < WATCH < TRADE; EXIT < REDUCE < MONITOR < HOLD),
  * a TRADE under fault never has a bigger quantity than the clean TRADE,
  * the banner under fault is at least as cautious (NO_NEW_TRADES < DEFENSIVE < NORMAL),
  * the run itself completes (a fault is caught, never a crash), unless the fault is
    in the database/reader, where the run is recorded as failed and the brain
    strategy then says HOLD for every stock.

Faults covered: missing prices, stale prices, Kite down, a module crashing, the
risk gate missing or failing, and modules returning garbage (NaN, out of range).

Drills that found the system getting bolder are marked xfail(strict=True) with a
"BUG:" reason. They are documented, not fixed: the forward trial is frozen
(tests/test_trial_freeze.py), so logic changes need the owner's approval.

The pure drills use the in-memory reader from brain_fakes; the database drills use
the real M01 data gateway, the real M07 risk gate and the real M08 decision engine
on bars built in the test database (helpers from test_brain_m01_module). No
network, no Kite: every broker call is replaced by a stub.
"""

from __future__ import annotations

import math
from dataclasses import replace as dc_replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import delete

from brain_fakes import FakeReader, fresh_quality, make_module, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import service
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord, MarketMode, rank
from swing_trade_ml.brain.module import REGISTRY, Mode, ModuleRegistry, Step
from swing_trade_ml.brain.modules.m01_quality.module import DataGateway
from swing_trade_ml.brain.modules.m01_quality.quality import IST
from swing_trade_ml.brain.modules.m07_risk.module import RiskGate, candidates_from
from swing_trade_ml.brain.modules.m08_decide.module import DecisionEngine
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.brokers.base import BrokerMargins
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.brain_golive import BrainApproval
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml import market_context
from swing_trade_ml.services.brain_golive import approvals
from swing_trade_ml.strategies import brain as brain_strategy
from test_brain_m01_module import FRI, _add_bars, world  # noqa: F401 — `world` is a fixture
from test_brain_m18_approvals import TUE, _pending, _waiting, at, fx  # noqa: F401 — `fx` is a fixture

NAN = float("nan")

# --- comparing a faulty run with a clean one ----------------------------------------------


def _assert_not_bolder(clean, broken, where: str) -> None:
    """The faulty run decided every stock the clean run decided, and none more boldly."""
    assert broken.banner is not None, f"{where}: no banner"
    assert rank(broken.banner.mode) <= rank(clean.banner.mode), (
        f"{where}: banner bolder under fault ({clean.banner.mode} -> {broken.banner.mode})"
    )
    assert set(broken.decisions) >= set(clean.decisions), f"{where}: stocks went undecided"
    for symbol, base in clean.decisions.items():
        d = broken.decisions[symbol]
        assert type(d.word) is type(base.word), f"{where}: {symbol} changed vocabulary"
        assert rank(d.word) <= rank(base.word), (
            f"{where}: {symbol} bolder under fault ({base.word} -> {d.word}: {d.reasons[:1]})"
        )
        assert d.reasons and all(r.strip() for r in d.reasons), f"{where}: {symbol} has no reason"
        if d.word is IdeaWord.TRADE:
            assert d.qty <= base.qty, f"{where}: {symbol} bigger size under fault"
    assert _trades(broken) <= _trades(clean), f"{where}: more TRADEs under fault"


def _trades(ctx) -> set[str]:
    return {s for s, d in ctx.decisions.items() if d.word is IdeaWord.TRADE}


def _assert_no_new_trades(ctx, where: str) -> None:
    assert ctx.banner.mode is MarketMode.NO_NEW_TRADES, f"{where}: banner is {ctx.banner.mode}"
    assert not _trades(ctx), f"{where}: TRADE under NO NEW TRADES: {_trades(ctx)}"
    assert all(d.qty == 0 for d in ctx.decisions.values() if d.kind == "idea"), f"{where}: an idea has a size"


def _used(ctx, module_id: str) -> bool:
    return any(e.module_id == module_id and e.status == "used" for e in ctx.trace)


def _dropped(ctx, module_id: str) -> bool:
    return any(e.module_id == module_id and e.status in ("fallback", "rejected") for e in ctx.trace)


def _crashing(cls, message: str = "drill: module blew up"):
    """The same module (same manifest, same id) whose run() raises."""

    def run(self, view):
        raise RuntimeError(message)

    return type(f"Crashing{cls.__name__}", (cls,), {"run": run})


def _returning(cls, contribution_fn):
    """The same module whose run() returns `contribution_fn(view)` (garbage drills)."""

    def run(self, view):
        return contribution_fn(view)

    return type(f"Garbage{cls.__name__}", (cls,), {"run": run})


def _slow(cls):
    """The same module with a zero time budget: any run overruns it."""
    return type(f"Slow{cls.__name__}", (cls,), {"manifest": dc_replace(cls.manifest, budget_s=0.0)})


def _replace(reg_classes, module_id: str, new_cls) -> ModuleRegistry:
    """A registry with one module swapped (or removed when new_cls is None)."""
    out = ModuleRegistry()
    for cls in reg_classes:
        if cls.manifest.id == module_id:
            if new_cls is not None:
                out.register(new_cls)
        else:
            out.register(cls)
    return out


# --- part A: pure drills (in-memory reader, no database) --------------------------------

ABC_LIKED = 0.9  # above the 0.6 buy level: the clean run makes ABC a TRADE
XYZ_WEAK = 0.3  # below it: XYZ is WAIT


class DrillReader(FakeReader):
    """The fake reader plus the one extra question M07's candidate filter asks."""

    def instrument_id(self, symbol: str) -> int | None:
        return 1


def risk_gate_like_m07(max_qty: int = 10):
    """M07 stand-in for the pure drills: the REAL M07 candidate filter (liked opinion,
    a price, fresh data — `candidates_from`) and an account with room for everything.
    Unlike brain_fakes.allow_all_risk_gate it never approves a stock M07 would refuse
    before the account check, so it does not hide a bad-data fault."""

    def run(view):
        candidates, refusals = candidates_from(view)
        approved = tuple(
            c.RiskVerdict(symbol=cand.symbol, allowed=True, max_qty=max_qty, reason="Within limits")
            for cand in candidates
        )
        return c.Contribution(verdicts=(*refusals, *approved))

    return make_module(
        "M07", Step.RISK, reads=RiskGate.manifest.reads, writes=("RiskVerdict@1",), run=run, mandatory=True
    )


def _likes(probabilities: dict[str, float], module_id: str = "M90"):
    """A reasoning plug-in that scores stocks like the active model does."""

    def run(view):
        return c.Contribution(
            opinions=tuple(
                c.Opinion(
                    source="model",
                    symbol=s,
                    stance=max(-1.0, min(1.0, 2 * p - 1)) if not math.isnan(p) else 0.0,
                    confidence=0.8,
                    probability=p,
                    threshold=0.6,
                    reasons=(f"Drill model scores {s}.",),
                )
                for s, p in probabilities.items()
            )
        )

    return make_module(module_id, Step.REASON, writes=("Opinion@1",), run=run, kind="plugin")


def _pure_classes():
    return [fresh_quality(), risk_gate_like_m07(), DecisionEngine]


def _pure_run(reader=None, classes=None, modes=None, universe=("ABC", "XYZ")):
    reader = reader or DrillReader(probabilities={"ABC": ABC_LIKED, "XYZ": XYZ_WEAK})
    reg = registry(*(classes if classes is not None else _pure_classes()))
    return execute(request(universe=universe), reader, reg, modes=modes or {})


@pytest.fixture()
def clean():
    ctx = _pure_run()
    # The baseline must actually be bold, or "never bolder" proves nothing.
    assert ctx.decisions["ABC"].word is IdeaWord.TRADE, ctx.decisions["ABC"]
    assert ctx.decisions["XYZ"].word is IdeaWord.WAIT
    assert ctx.banner.mode is MarketMode.NORMAL
    return ctx


# 1. Missing prices ----------------------------------------------------------------------


def test_drill_missing_price_for_one_stock(clean):
    reader = DrillReader(closes={"XYZ": 100.0}, probabilities={"ABC": ABC_LIKED, "XYZ": XYZ_WEAK})
    broken = _pure_run(reader)
    _assert_not_bolder(clean, broken, "ABC has no price")
    assert broken.decisions["ABC"].word is IdeaWord.WAIT
    assert "price" in broken.decisions["ABC"].reasons[0].lower()


def test_drill_missing_prices_for_the_whole_universe(clean):
    reader = DrillReader(closes={}, probabilities={"ABC": ABC_LIKED, "XYZ": XYZ_WEAK})
    broken = _pure_run(reader)
    _assert_not_bolder(clean, broken, "no prices at all")
    assert not _trades(broken)


def test_drill_no_index_history_turns_the_market_careful(clean):
    """No NIFTY bars: the market cannot be judged, so the banner is never NORMAL."""
    reader = DrillReader(
        probabilities={"ABC": ABC_LIKED, "XYZ": XYZ_WEAK}, index_closes=pd.Series(dtype=float)
    )
    broken = _pure_run(reader)
    _assert_not_bolder(clean, broken, "no NIFTY history")
    assert broken.banner.mode is not MarketMode.NORMAL


# 4. A module crashes ---------------------------------------------------------------------


@pytest.mark.parametrize("module_id", ["M01", "M07", "M08", "M90"])
def test_drill_a_crashing_module_falls_back_and_is_never_bolder(module_id):
    classes = [*_pure_classes(), _likes({"ABC": ABC_LIKED, "XYZ": XYZ_WEAK})]
    reader = DrillReader()  # scores come from the M90 plug-in, so its crash removes them
    clean_ctx = _pure_run(reader, classes)
    assert clean_ctx.decisions["ABC"].word is IdeaWord.TRADE

    target = next(cls for cls in classes if cls.manifest.id == module_id)
    broken_classes = [_crashing(cls) if cls is target else cls for cls in classes]
    broken = _pure_run(DrillReader(), broken_classes)  # the run completes: no exception

    _assert_not_bolder(clean_ctx, broken, f"{module_id} crashed")
    assert _dropped(broken, module_id) and not _used(broken, module_id)
    assert any("drill: module blew up" in e.reason for e in broken.trace if e.module_id == module_id)
    if module_id == "M07":
        _assert_no_new_trades(broken, "risk gate crashed")


@pytest.mark.parametrize("module_id", ["M01", "M08", "M90"])
def test_drill_a_module_over_its_time_budget_is_dropped(module_id):
    """A module that overruns is treated like a crash (its answer is thrown away)."""
    classes = [*_pure_classes(), _likes({"ABC": ABC_LIKED, "XYZ": XYZ_WEAK})]
    clean_ctx = _pure_run(DrillReader(), classes)
    slow = [_slow(cls) if cls.manifest.id == module_id else cls for cls in classes]
    broken = _pure_run(DrillReader(), slow)
    _assert_not_bolder(clean_ctx, broken, f"{module_id} too slow")
    assert any(e.module_id == module_id and "too slow" in e.reason for e in broken.trace)


# 5. Risk gate missing or failed ----------------------------------------------------------


def _gate_faults():
    good = risk_gate_like_m07()

    def undeclared(view):
        return c.Contribution(
            opinions=(c.Opinion(source="x", symbol="ABC", stance=1, confidence=1, reasons=("x",)),)
        )

    return {
        "not installed": None,
        "crashes": _crashing(good),
        "too slow": _slow(good),
        "writes an undeclared contract": _returning(good, undeclared),
        "returns nothing usable": _returning(good, lambda view: None),
    }


@pytest.mark.parametrize("fault", list(_gate_faults()))
def test_drill_risk_gate_fault_means_no_new_trades(clean, fault):
    broken_cls = _gate_faults()[fault]
    broken = execute(
        request(),
        DrillReader(probabilities={"ABC": ABC_LIKED, "XYZ": XYZ_WEAK}),
        _replace(_pure_classes(), "M07", broken_cls),
        modes={},
    )
    _assert_not_bolder(clean, broken, f"risk gate {fault}")
    _assert_no_new_trades(broken, f"risk gate {fault}")
    assert broken.decisions["ABC"].downgraded_from is IdeaWord.TRADE


def test_drill_switching_the_risk_gate_off_is_refused(clean):
    """A stored mode of OFF/SHADOW for M07 is ignored: the gate still runs."""
    for mode in (Mode.OFF, Mode.SHADOW):
        ctx = _pure_run(modes={"M07": mode})
        assert _used(ctx, "M07")
        _assert_not_bolder(clean, ctx, f"M07 stored as {mode}")


def test_drill_a_non_mandatory_module_cannot_approve_trades(clean):
    """A plug-in that writes risk verdicts (pretending to be the gate) is rejected."""

    def fake_gate(view):
        return c.Contribution(verdicts=(c.RiskVerdict(symbol="ABC", allowed=True, max_qty=999),))

    impostor = make_module("M91", Step.RISK, writes=("RiskVerdict@1",), run=fake_gate, kind="plugin")
    classes = [cls for cls in _pure_classes() if cls.manifest.id != "M07"] + [impostor]
    broken = _pure_run(classes=classes)
    _assert_no_new_trades(broken, "only an impostor gate")
    assert any(e.module_id == "M91" and e.status == "rejected" for e in broken.trace)


def test_drill_no_new_trades_run_gives_the_strategy_nothing_to_buy(clean):
    """What v1's brain strategy does with a run whose risk gate failed: no BUY signal."""
    broken = execute(
        request(),
        DrillReader(probabilities={"ABC": ABC_LIKED, "XYZ": XYZ_WEAK}),
        _replace(_pure_classes(), "M07", _crashing(risk_gate_like_m07())),
        modes={},
    )
    run_row = BrainRun(id="drill", kind="nightly", live=True, status="done", book="paper")
    for symbol, d in broken.decisions.items():
        row = BrainDecision(
            id=1,
            run_id="drill",
            symbol=symbol,
            kind=d.kind,
            word=d.word.value,
            stop=d.stop,
            target=d.target,
            qty=d.qty,
            horizon_days=d.horizon_days,
            confidence=d.confidence,
            reasons=list(d.reasons),
            downgraded_from=d.downgraded_from.value if d.downgraded_from else None,
            downgrade_reason=d.downgrade_reason,
        )
        for practice in (False, True):
            sig = brain_strategy.to_signal(row, run_row, 100.0, practice=practice)
            assert sig.signal is not SignalType.BUY or sig.features.get(brain_strategy.BLOCKED_BY_RISK_KEY), (
                f"{symbol}: a BUY that could be placed came out of a NO NEW TRADES run"
            )


def test_drill_no_brain_run_today_means_hold_for_every_stock():
    """The run failed or never ran: the strategy holds, it never guesses."""
    sig = brain_strategy.to_signal(None, None, 100.0)
    assert sig.signal is SignalType.HOLD and sig.reason == brain_strategy.NO_RUN_TODAY


# 6. Garbage from a module ----------------------------------------------------------------


def _garbage_opinions(**fields):
    def fn(view):
        base = {
            "source": "model",
            "symbol": "XYZ",
            "stance": 0.9,
            "confidence": 0.9,
            "probability": 0.95,
            "threshold": 0.6,
            "reasons": ("garbage",),
        }
        base.update(fields)
        return c.Contribution(opinions=(c.Opinion(**base),))

    return fn


GARBAGE = {
    "opinion stance out of range": ("M90", _garbage_opinions(stance=5.0)),
    "opinion stance NaN": ("M90", _garbage_opinions(stance=NAN)),
    "opinion confidence negative": ("M90", _garbage_opinions(confidence=-1.0)),
    "opinion probability NaN": ("M90", _garbage_opinions(probability=NAN)),
    "opinion probability above 1": ("M90", _garbage_opinions(probability=7.0, stance=0.0)),
    "quality score NaN": (
        "M01",
        lambda view: c.Contribution(
            quality=tuple(c.DataQuality(symbol=s, score=NAN, fresh=True) for s in view.request.universe)
        ),
    ),
    "quality score above 1": (
        "M01",
        lambda view: c.Contribution(
            quality=tuple(c.DataQuality(symbol=s, score=9.0, fresh=True) for s in view.request.universe)
        ),
    ),
    "decision without a reason": (
        "M08",
        lambda view: c.Contribution(
            decisions=(c.Decision(symbol="ABC", kind="idea", word=IdeaWord.TRADE, reasons=()),)
        ),
    ),
    "holding word on an idea": (
        "M08",
        lambda view: c.Contribution(
            decisions=(c.Decision(symbol="ABC", kind="idea", word=HoldingWord.HOLD, reasons=("x",)),)
        ),
    ),
    "TRADE with NaN levels and a huge size": (
        "M08",
        lambda view: c.Contribution(
            decisions=(
                c.Decision(
                    symbol="ABC",
                    kind="idea",
                    word=IdeaWord.TRADE,
                    reasons=("garbage",),
                    stop=NAN,
                    target=NAN,
                    qty=10**9,
                ),
            )
        ),
    ),
}

# Known bold outcomes (documented, not fixed: trial freeze).
GARBAGE_BUGS = {
    "opinion probability above 1": (
        "BUG: a probability of 7.0 (outside 0..1) is not rejected by contracts.validate_record; it counts "
        "as liked, so a stock the clean run left at WAIT becomes a TRADE"
    ),
    "TRADE with NaN levels and a huge size": (
        "BUG: a decide module may write a TRADE with NaN stop/target and qty 10^9; nothing checks levels "
        "or size, and with an allowed verdict and fresh data the constitution lets it through"
    ),
}


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(k, marks=pytest.mark.xfail(strict=True, reason=GARBAGE_BUGS[k]))
        if k in GARBAGE_BUGS
        else k
        for k in GARBAGE
    ],
)
def test_drill_garbage_from_a_module_is_never_bolder(clean, case):
    """Clean data: ABC is an approved TRADE (qty 10), XYZ is WAIT. Garbage opinions are about
    XYZ (they must not lift it); garbage decisions are about ABC (they must not enlarge it)."""
    module_id, fn = GARBAGE[case]
    classes = _pure_classes()
    if module_id == "M90":
        classes = [*classes, _returning(_likes({}), fn)]
    else:
        target = next(cls for cls in classes if cls.manifest.id == module_id)
        classes = [_returning(cls, fn) if cls is target else cls for cls in classes]
    broken = _pure_run(classes=classes)
    _assert_not_bolder(clean, broken, case)
    for d in broken.decisions.values():
        if d.word is IdeaWord.TRADE:
            assert all(v is not None and math.isfinite(v) for v in (d.stop, d.target)), (
                f"{case}: TRADE with bad levels"
            )


@pytest.mark.xfail(
    strict=True,
    reason="BUG: with M08 dropped, the decide fallback treats a NaN model score as at/above the buy level "
    "(`p < threshold` is False for NaN) and drafts a TRADE; the constitution lowers it only to WATCH, "
    "so a stock with no usable score shows WATCH instead of WAIT (bolder than the no-score baseline)",
)
def test_drill_nan_model_score_with_decision_engine_down_is_not_bolder_than_no_score():
    classes = [cls for cls in _pure_classes() if cls.manifest.id != "M08"]
    no_score = _pure_run(DrillReader(probabilities={"ABC": ABC_LIKED}), classes)
    nan_score = _pure_run(DrillReader(probabilities={"ABC": ABC_LIKED, "XYZ": NAN}), classes)
    _assert_not_bolder(no_score, nan_score, "NaN model score, decide fallback")


def test_drill_nan_model_score_with_decision_engine_up_is_wait(clean):
    broken = _pure_run(DrillReader(probabilities={"ABC": ABC_LIKED, "XYZ": NAN}))
    _assert_not_bolder(clean, broken, "NaN model score via the reader")
    assert broken.decisions["XYZ"].word is IdeaWord.WAIT


# --- part B: database drills (real M01, M07, M08 on bars in the test database) ------------

AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)  # Fri 17:30 IST, after the day's ingest
SYMBOLS = ("DRLA", "DRLB", "DRLC", "DRLD", "DRLE", "DRLF")
TOKENS = dict(zip(SYMBOLS, range(995001, 995001 + len(SYMBOLS)), strict=True))
THU = date(2026, 9, 24)


def _db_classes(extra=()):
    return [DataGateway, RiskGate, DecisionEngine, _likes(dict.fromkeys(SYMBOLS, ABC_LIKED)), *extra]


def _db_run(db, classes=None, *, book="paper", as_of=AS_OF, modes=None, universe=SYMBOLS):
    req = c.RunRequest(run_id="drill", kind="nightly", as_of=as_of, universe=universe, book=book, live=True)
    reader = DatedReader(db, as_of=as_of, live=True)
    return execute(req, reader, registry(*(classes or _db_classes())), modes or {})


def _bars(db, last_days: dict[str, date] | None = None, n: int = 240):
    last_days = last_days or {}
    for s in SYMBOLS:
        _add_bars(db, s, TOKENS[s], last_days.get(s, FRI), n=n)
    db.commit()


def _clean_db(db):
    ctx = _db_run(db)
    assert _trades(ctx), (
        f"clean database run made no TRADE: {[(s, d.word, d.reasons[:1]) for s, d in ctx.decisions.items()]}"
    )
    return ctx


@pytest.fixture()
def db_world(world):  # noqa: F811 — the fixture imported from test_brain_m01_module
    _bars(world)
    _changed(world)
    yield world
    market_context.clear_cache()


def _set_last_bars(
    db, symbols, *, drop_after: date | None = None, close: float | None = None, day: date = FRI
):
    for s in symbols:
        inst = db.query(Instrument).filter_by(tradingsymbol=s).one()
        if drop_after is not None:
            cutoff = datetime.combine(
                drop_after + timedelta(days=1), datetime.min.time(), tzinfo=IST
            ).astimezone(UTC)
            db.execute(delete(Candle).where(Candle.instrument_id == inst.id, Candle.ts >= cutoff))
        if close is not None:
            ts = datetime.combine(day, datetime.min.time(), tzinfo=IST).astimezone(UTC)
            bar = db.query(Candle).filter_by(instrument_id=inst.id, ts=ts).one()
            bar.close = close
    _changed(db)


def _changed(db):
    """Commit a fault and drop v1's per-process market-context cache, so the faulty run
    really reads the faulty bars (a cached clean history would hide the fault)."""
    db.commit()
    market_context.clear_cache()


# 1. Missing prices (database) ---------------------------------------------------------


def test_db_drill_stock_with_no_candles_at_all(db_world):
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, ["DRLA"], drop_after=date(2000, 1, 1))  # every bar gone
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "DRLA has no candles")
    assert broken.decisions["DRLA"].word is not IdeaWord.TRADE
    assert not broken.quality["DRLA"].fresh


def test_db_drill_todays_bar_missing_for_one_stock(db_world):
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, ["DRLA"], drop_after=THU)
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "DRLA missing today's bar")
    assert broken.decisions["DRLA"].word is not IdeaWord.TRADE
    assert broken.verdicts["DRLA"].rule == "DATA"


def test_db_drill_todays_bar_missing_for_the_whole_universe(db_world):
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, [*SYMBOLS, settings.BENCHMARK_INDEX_SYMBOL], drop_after=THU)
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "nobody has today's bar")
    _assert_no_new_trades(broken, "nobody has today's bar")


def test_db_drill_nifty_missing(db_world):
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, [settings.BENCHMARK_INDEX_SYMBOL], drop_after=date(2000, 1, 1))
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "no NIFTY bars")
    _assert_no_new_trades(broken, "no NIFTY bars")


def test_db_drill_gap_in_recent_history(db_world):
    """Five trading days missing in the middle of the last 60: never bolder."""
    clean_ctx = _clean_db(db_world)
    inst = db_world.query(Instrument).filter_by(tradingsymbol="DRLA").one()
    lo = datetime(2026, 9, 7, tzinfo=IST).astimezone(UTC)
    hi = datetime(2026, 9, 14, tzinfo=IST).astimezone(UTC)
    db_world.execute(delete(Candle).where(Candle.instrument_id == inst.id, Candle.ts >= lo, Candle.ts < hi))
    _changed(db_world)
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "gap in DRLA's history")
    assert any("gap" in i for i in broken.quality["DRLA"].issues)


# 2. Stale data (database) -------------------------------------------------------------


def test_db_drill_ingestion_did_not_run_for_a_week(db_world):
    """Every bar (stocks and NIFTY) is from 18 Sep while the run is on 25 Sep."""
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, [*SYMBOLS, settings.BENCHMARK_INDEX_SYMBOL], drop_after=date(2026, 9, 18))
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "a week stale")
    _assert_no_new_trades(broken, "a week stale")
    assert "not reliable" in broken.banner.headline


def test_db_drill_only_nifty_is_stale(db_world):
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, [settings.BENCHMARK_INDEX_SYMBOL], drop_after=date(2026, 9, 22))
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "NIFTY stale")
    _assert_no_new_trades(broken, "NIFTY stale")


def test_db_drill_two_of_six_stocks_stale_stops_new_trades(db_world):
    """Two of six stale (more than a fifth): the whole market is called unreliable."""
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, ["DRLA", "DRLB"], drop_after=date(2026, 9, 21))
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "two stocks stale")
    _assert_no_new_trades(broken, "two stocks stale")


def test_db_drill_run_after_a_long_weekend_with_old_bars(db_world):
    """A Monday-evening run that still only has Friday's bars (Monday's ingest failed)."""
    clean_ctx = _clean_db(db_world)
    broken = _db_run(db_world, as_of=datetime(2026, 9, 28, 12, 0, tzinfo=UTC))
    _assert_not_bolder(clean_ctx, broken, "Monday run with Friday bars")
    _assert_no_new_trades(broken, "Monday run with Friday bars")


# 6. Garbage in the database ------------------------------------------------------------


def test_db_drill_nan_close_on_todays_bar(db_world):
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, ["DRLA"], close=NAN)
    broken = _db_run(db_world)  # must complete
    _assert_not_bolder(clean_ctx, broken, "NaN close")
    assert broken.decisions["DRLA"].word is not IdeaWord.TRADE


def test_db_drill_zero_close_on_todays_bar(db_world):
    clean_ctx = _clean_db(db_world)
    _set_last_bars(db_world, ["DRLA"], close=0.0)
    broken = _db_run(db_world)
    _assert_not_bolder(clean_ctx, broken, "zero close")
    assert broken.decisions["DRLA"].word is not IdeaWord.TRADE


# 4. Every installed module crashing, one at a time (database) ---------------------------

# Known bold outcomes (documented, not fixed: trial freeze).
MODULE_CRASH_BUGS = {
    "M10": "BUG: when the market judge (M10) fails, the state fallback judges the market from the NIFTY "
    "50/200-day trend alone and ignores breadth; a market M10 calls DEFENSIVE (0% of stocks above their "
    "50-day average) becomes NORMAL, so M07 drops its defensive limits (2 ideas, half size) and the run "
    "approves every liked stock at full size",
}
ALL_MODULE_IDS = [
    pytest.param(m, marks=pytest.mark.xfail(strict=True, reason=MODULE_CRASH_BUGS[m]))
    if m in MODULE_CRASH_BUGS
    else m
    for m in (cls.manifest.id for cls in REGISTRY.all())
]


@pytest.mark.parametrize("module_id", ALL_MODULE_IDS)
def test_db_drill_each_installed_module_crashing(db_world, module_id):
    """The full installed brain, every module ON, plus a model-like plug-in. Each module in
    turn raises inside run(view): the run completes, that module is dropped, and no
    decision is bolder than the clean run."""
    likes = _likes(dict.fromkeys(SYMBOLS, ABC_LIKED))
    full = [*REGISTRY.all(), likes]
    modes = {cls.manifest.id: Mode.ON for cls in full}
    clean_ctx = _db_run(db_world, full, modes=modes)
    target = REGISTRY.get(module_id)
    broken = _db_run(db_world, [_crashing(cls) if cls is target else cls for cls in full], modes=modes)
    _assert_not_bolder(clean_ctx, broken, f"{module_id} crashed")
    assert _dropped(broken, module_id), f"{module_id} was not marked dropped"
    if target.manifest.mandatory:
        _assert_no_new_trades(broken, f"{module_id} crashed")


# 3. Kite down ----------------------------------------------------------------------------


def _kite_down(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("drill: Kite is down")

    monkeypatch.setattr(kite_broker, "load_session", boom)
    monkeypatch.setattr(kite_broker, "get_margins", boom)
    monkeypatch.setattr(kite_broker, "get_ltp", boom)
    return boom


def test_db_drill_kite_down_during_a_live_book_run(db_world, monkeypatch):
    """The brain's risk gate reads the live account's cash from Kite. With Kite up (stubbed
    margins) a stock can be approved; with Kite down cash counts as 0 and nothing is."""
    monkeypatch.setattr(kite_broker, "load_session", lambda db: None)
    monkeypatch.setattr(
        kite_broker,
        "get_margins",
        lambda db: BrokerMargins(available_cash=1_000_000.0, used_margin=0.0, total=1_000_000.0),
    )
    clean_ctx = _db_run(db_world, book="live")
    _kite_down(monkeypatch)
    broken = _db_run(db_world, book="live")  # completes: no exception
    _assert_not_bolder(clean_ctx, broken, "Kite down (live book)")
    assert not _trades(broken)
    assert all(not v.allowed for v in broken.verdicts.values())


def test_db_drill_kite_down_run_through_the_service(db_world, monkeypatch):
    """The same through service.run_brain (what the scheduler calls): stored as done, no TRADE."""
    _kite_down(monkeypatch)
    ctx, run_id = service.run_brain(
        db_world, symbols=list(SYMBOLS), book="live", registry=registry(*_db_classes())
    )
    row = db_world.get(BrainRun, run_id)
    assert row.status == "done"
    assert not _trades(ctx)


def test_drill_kite_down_at_the_open_buys_nothing(fx, monkeypatch):  # noqa: F811
    """An owner-approved brain idea waits for the market open. Kite's LTP call raises:
    nothing is bought and the idea expires with a plain reason."""
    a = _waiting(fx)
    monkeypatch.setattr(approvals, "_live_price", _REAL_LIVE_PRICE)
    monkeypatch.setattr(approvals, "get_broker", lambda: SimpleNamespace(get_ltp=_raise_kite_down))
    fx.clock["now"] = at(TUE, 9, 15)
    assert approvals.execute_waiting(fx.db) == [] and fx.opened == []
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "expired" and "Could not get a live price" in row.decided_note


def test_drill_kite_down_when_approving_during_market_hours(fx, monkeypatch):  # noqa: F811
    a = _pending(fx)
    monkeypatch.setattr(approvals, "_live_price", _REAL_LIVE_PRICE)
    monkeypatch.setattr(approvals, "get_broker", lambda: SimpleNamespace(get_ltp=_raise_kite_down))
    with pytest.raises(approvals.ApprovalExpired, match="Could not get a live price"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == [] and fx.db.get(BrainApproval, a.id).status == "expired"


def _raise_kite_down(keys, db):
    raise ConnectionError("drill: Kite is down")


_REAL_LIVE_PRICE = approvals._live_price


# 3b. The database/reader itself fails -------------------------------------------------------


def test_db_drill_reader_failure_records_a_failed_run_and_the_strategy_holds(db_world, monkeypatch):
    """A fault outside any module (the reader raising) cannot be caught per module: the run
    is recorded as failed, so there is no run today and the brain strategy says HOLD."""

    def broken_last_close(self, symbol):
        raise ConnectionError("drill: database went away")

    monkeypatch.setattr(DatedReader, "last_close", broken_last_close)
    classes = [cls for cls in _db_classes() if cls.manifest.id != "M02"]
    with pytest.raises(ConnectionError):
        service.run_brain(db_world, symbols=list(SYMBOLS), registry=registry(*classes))
    rows = db_world.query(BrainRun).filter(BrainRun.status != "done").all()
    assert rows and all(r.status == "failed" for r in rows)
    sig = brain_strategy.to_signal(None, None, 100.0)
    assert sig.signal is SignalType.HOLD
