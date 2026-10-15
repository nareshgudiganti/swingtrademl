# Real Buy/Sell from My Holdings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner place small REAL buy and sell orders to Zerodha by hand from the My Holdings screen, while the bot stays on paper.

**Architecture:** A new latch `ALLOW_REAL_HOLDINGS_ORDERS` (off by default) opens `KiteBroker.place_order` only for requests tagged with a reserved prefix that only the My Holdings flow sets. `services/real_orders.py` holds every check (latch, market clock, ₹ limits, owned quantity, one waiting order per stock); `services/execution.py` stays the only writer of Order/Position/Trade and gains two small placement functions plus a second reconcile pass for live My Holdings orders. Two owner-only routes and a status/quote route feed new buttons on My Holdings.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, pytest (Docker Postgres test DB), kiteconnect; React + TypeScript + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-10-14-real-holdings-orders-design.md`

## Global Constraints

- Branch `feature/real-holdings-orders`, worktree `D:\machine learning\swing-trade-bot\.claude\worktrees\real-holdings`. **Never push to `main`, never merge, never deploy.** Owner reviews first.
- `ALLOW_REAL_HOLDINGS_ORDERS` defaults to `false` everywhere (code default and `.env.example`). Never set it `true` in any file.
- Never change `TRADING_MODE` / `ALLOW_LIVE_TRADING` defaults; never set `TRADING_MODE=live`.
- Limits: `REAL_HOLDINGS_MAX_ORDER_INR = 10000`, `REAL_HOLDINGS_MAX_DAY_INR = 25000`; money limits apply to **buys only**.
- Orders: MARKET, product CNC, `KITE_MARKET_PROTECTION` (already applied by `KiteBroker.place_order`).
- Stop/target on an app buy: −4% / +8% of the real fill price.
- Tag prefix `stmlh-` (`REAL_HOLDINGS_TAG_PREFIX`); Kite tags are ≤ 20 chars.
- Scope: manual BUY, manual SELL, holdings sync, order safety, reporting. No automated trading, no brain changes, no new infrastructure, no app redesign.
- No real Zerodha calls in tests — `kite_broker` methods are monkeypatched.
- `ruff format` only files you touched. No prettier on existing frontend files; check with `npx tsc --noEmit -p .`.
- User-facing text: plain English, one sentence per refusal.
- Run backend tests from `backend/` of the worktree:
  `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m pytest <tests> -q`
  (the shared venv; `PYTHONPATH=src` makes it import the worktree's code). Docker Postgres must be up — DB tests hang silently otherwise. Check first:
  `"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -c "import psycopg; psycopg.connect('postgresql://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml_test', connect_timeout=5)"`
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A bot/brain/tester order while the new latch is on** must still go to paper and never reach Kite — pinned in Task 1 (gate test) and Task 2 (reconcile leaves paper orders alone).
2. **Double tap / two tabs** placing the same buy twice — pinned in Task 3 (`test_a_second_order_while_one_is_waiting_is_refused`).
3. **Zerodha logged out (token expired mid-day)** must refuse with a clear sentence, not a 500 — pinned in Task 3 (`test_no_zerodha_session_is_refused_plainly`).
4. **Daily cap counting pending orders** (market orders have no fill price yet) — pinned in Task 3 (`test_pending_buys_count_toward_the_daily_cap`), using the reference price stored on the order.
5. **Holdings sync closing a holding at a guessed price while an app sell is still waiting** — pinned in Task 3 (`test_sync_leaves_a_holding_with_a_waiting_order_alone`).

---

### Task 1: Latch, limits and the narrow Kite gate

**Files:**
- Modify: `backend/src/swing_trade_ml/core/config.py` (after `ALLOW_LIVE_TRADING: bool = False`, line ~85)
- Modify: `backend/src/swing_trade_ml/brokers/base.py` (module-level constant)
- Modify: `backend/src/swing_trade_ml/brokers/kite.py:385-395` (gate in `place_order`)
- Modify: `.env.example` (after `ALLOW_LIVE_TRADING=false`, line ~111)
- Test: `backend/tests/test_real_holdings_gate.py`

**Interfaces:**
- Produces: `settings.ALLOW_REAL_HOLDINGS_ORDERS: bool`, `settings.REAL_HOLDINGS_MAX_ORDER_INR: float`, `settings.REAL_HOLDINGS_MAX_DAY_INR: float`; `swing_trade_ml.brokers.base.REAL_HOLDINGS_TAG_PREFIX = "stmlh-"`; `KiteBroker.place_order` accepts a request whose `tag` starts with that prefix when the latch is on.

- [ ] **Step 1: Write the failing test**

```python
"""Real orders from My Holdings open a narrow door, not the whole system.

The bot stays on paper for its trial. The owner's own hand-placed My Holdings
orders may reach Zerodha only when ALLOW_REAL_HOLDINGS_ORDERS is on AND the
request carries the reserved tag only services/real_orders.py sets. Anything
else still needs both full live latches, exactly as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swing_trade_ml.brokers import get_broker, paper_broker
from swing_trade_ml.brokers.base import REAL_HOLDINGS_TAG_PREFIX, OrderRequest
from swing_trade_ml.brokers.kite import KiteBroker
from swing_trade_ml.core import config
from swing_trade_ml.core.enums import OrderStatus, OrderType, ProductType, TransactionType


class _RecordingKite:
    VARIETY_REGULAR = "regular"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return 990001


@pytest.fixture
def broker(monkeypatch):
    monkeypatch.setattr(config.settings, "TRADING_MODE", "paper", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", False, raising=False)
    b = KiteBroker()
    b._token_loaded = True
    b._kite = _RecordingKite()
    return b


def _request(tag: str | None) -> OrderRequest:
    return OrderRequest(
        tradingsymbol="ITC",
        exchange="NSE",
        transaction_type=TransactionType.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        tag=tag,
    )


def test_the_latch_is_off_by_default():
    assert config.Settings.model_fields["ALLOW_REAL_HOLDINGS_ORDERS"].default is False
    assert config.Settings.model_fields["REAL_HOLDINGS_MAX_ORDER_INR"].default == 10000
    assert config.Settings.model_fields["REAL_HOLDINGS_MAX_DAY_INR"].default == 25000


def test_latch_off_refuses_even_a_my_holdings_order(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", False, raising=False)
    with pytest.raises(RuntimeError, match="Refusing to place a live order"):
        broker.place_order(_request(f"{REAL_HOLDINGS_TAG_PREFIX}b-1"), db=None)
    assert broker._kite.calls == []


def test_latch_on_lets_only_a_my_holdings_order_through(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)

    result = broker.place_order(_request(f"{REAL_HOLDINGS_TAG_PREFIX}b-1"), db=None)
    assert result.status == OrderStatus.PENDING
    assert len(broker._kite.calls) == 1

    for tag in (None, "manual", "stml-exit-7", "brain-approval"):
        with pytest.raises(RuntimeError, match="Refusing to place a live order"):
            broker.place_order(_request(tag), db=None)
    assert len(broker._kite.calls) == 1, "a bot/manual/brain order must never reach Zerodha"


def test_latch_on_still_hands_the_bot_the_paper_broker(monkeypatch):
    monkeypatch.setattr(config.settings, "TRADING_MODE", "paper", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", False, raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)
    assert get_broker() is paper_broker


def test_only_the_my_holdings_flow_uses_the_reserved_tag():
    """The gate trusts the tag, so only real_orders' placement code may build one."""
    src = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml"
    allowed = {"brokers/base.py", "brokers/kite.py", "services/execution.py"}
    users = {
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if "REAL_HOLDINGS_TAG_PREFIX" in p.read_text(encoding="utf-8") or "stmlh-" in p.read_text(encoding="utf-8")
    }
    assert users <= allowed, f"unexpected users of the real-order tag: {users - allowed}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m pytest tests/test_real_holdings_gate.py -q`
Expected: FAIL — `ImportError: cannot import name 'REAL_HOLDINGS_TAG_PREFIX'`.

- [ ] **Step 3: Implement**

`core/config.py`, directly after `ALLOW_LIVE_TRADING: bool = False`:

```python
    # Real orders the OWNER places by hand from My Holdings, while the bot
    # itself stays on paper. A third, separate latch: it never opens the bot's
    # path (get_broker() still reads only the two above), and KiteBroker only
    # honours it for requests carrying the reserved My Holdings order tag
    # (brokers/base.py). Off unless the owner turns it on in prod.
    ALLOW_REAL_HOLDINGS_ORDERS: bool = False
    # Hard money limits on those buys (sells are never blocked by money).
    REAL_HOLDINGS_MAX_ORDER_INR: float = 10_000.0
    REAL_HOLDINGS_MAX_DAY_INR: float = 25_000.0
```

`brokers/base.py`, module level near the top (after imports):

```python
#: Reserved Kite order tag for the owner's hand-placed My Holdings orders.
#: KiteBroker lets a request with this prefix through when
#: ALLOW_REAL_HOLDINGS_ORDERS is on, so nothing else may build one
#: (test_real_holdings_gate.py checks who uses it). Kite tags are <= 20 chars.
REAL_HOLDINGS_TAG_PREFIX = "stmlh-"
```

`brokers/kite.py`: add `REAL_HOLDINGS_TAG_PREFIX` to the `from swing_trade_ml.brokers.base import (...)` list, then replace the gate at the top of `place_order`:

```python
    def place_order(self, request: OrderRequest, db: Session) -> OrderResult:
        # Belt and braces: the factory should never hand out a live broker while
        # the latches are closed, but an order that reaches the exchange cannot
        # be un-sent, so the check is repeated at the point of no return.
        # The one narrow exception: the owner's own My Holdings order, tagged
        # by services/execution.py and only allowed while its latch is on.
        my_holdings = settings.ALLOW_REAL_HOLDINGS_ORDERS and (request.tag or "").startswith(
            REAL_HOLDINGS_TAG_PREFIX
        )
        if not (settings.is_live_trading or my_holdings):
            raise RuntimeError(
                "Refusing to place a live order: requires TRADING_MODE=live AND "
                "ALLOW_LIVE_TRADING=true"
            )
        self._require_auth()
```

(keep everything after `self._require_auth()` unchanged). Update the module docstring's second paragraph to: "Order *placement* is gated behind `settings.is_live_trading`, or — for the owner's My Holdings orders only — `ALLOW_REAL_HOLDINGS_ORDERS` plus the reserved tag."

`.env.example`, after `ALLOW_LIVE_TRADING=false`:

```
# Owner's hand-placed REAL orders from My Holdings while the bot stays on paper.
# Leave false until the owner has reviewed the safety tests.
ALLOW_REAL_HOLDINGS_ORDERS=false
REAL_HOLDINGS_MAX_ORDER_INR=10000
REAL_HOLDINGS_MAX_DAY_INR=25000
```

- [ ] **Step 4: Run tests to verify they pass**

Run: same command, plus `tests/test_kite_order_reauth.py`.
Expected: all PASS. (The tag-users test passes now because only base.py/kite.py mention it.)

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/core/config.py backend/src/swing_trade_ml/brokers/base.py backend/src/swing_trade_ml/brokers/kite.py .env.example backend/tests/test_real_holdings_gate.py
git commit -m "Real holdings orders: separate off-by-default latch and a tag-only Kite gate; bot stays on paper"
```

---

### Task 2: Placement and reconciliation in execution.py

**Files:**
- Modify: `backend/src/swing_trade_ml/services/execution.py` (imports; new functions after `manual_close_position`; `reconcile_pending_orders` ~1334; `_finish_reconciled_order` ~1391-1460)
- Test: `backend/tests/test_real_holdings_execution.py`

**Interfaces:**
- Consumes: `REAL_HOLDINGS_TAG_PREFIX` (Task 1); `kite_broker` singleton from `swing_trade_ml.brokers.kite`.
- Produces:
  - `place_real_holding_buy(db: Session, strategy: Strategy, instrument: Instrument, quantity: int, reference_price: float) -> Order`
  - `place_real_holding_sell(db: Session, position: Position, quantity: int) -> Order`
  - `REAL_HOLDING_STOP_PCT = 0.04`, `REAL_HOLDING_TARGET_PCT = 0.08`
  - `reconcile_pending_orders` also finishes live orders of the `real_trading` strategy via `kite_broker` while the bot is on paper.
  - Orders are written with `mode="live"`, `price=reference_price` (reference only, never sent to Kite), `exit_reason=MANUAL` on sells.

- [ ] **Step 1: Write the failing test**

```python
"""Placing and finishing the owner's real My Holdings orders.

Kite is never called for real: the kite_broker singleton's methods are
replaced by a fake that records what it was asked to do.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers import OrderResult
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.enums import ExitReason, OrderStatus, PositionStatus, TransactionType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.services import execution


class FakeKite:
    def __init__(self) -> None:
        self.placed: list = []
        self.status: dict[str, OrderResult] = {}
        self.next_id = 500

    def place_order(self, request, db):
        self.placed.append(request)
        self.next_id += 1
        return OrderResult(broker_order_id=str(self.next_id), status=OrderStatus.PENDING)

    def get_order_status(self, broker_order_id, db):
        return self.status.get(broker_order_id)

    def load_session(self, db):
        return True


@pytest.fixture
def kite(monkeypatch):
    fake = FakeKite()
    for name in ("place_order", "get_order_status", "load_session"):
        monkeypatch.setattr(kite_broker, name, getattr(fake, name))
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **k: True)
    return fake


def _setup(db, symbol="ZZRHBUY", token=881_001):
    strategy = Strategy(
        name="real_trading", strategy_type="ml_swing", mode="live",
        execution_mode="advisory", is_active=True, params={}, symbols=[],
    )
    instrument = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE")
    db.add_all([strategy, instrument])
    db.flush()
    return strategy, instrument


def _complete(kite, order, price, qty):
    kite.status[order.broker_order_id] = OrderResult(
        broker_order_id=order.broker_order_id, status=OrderStatus.COMPLETE,
        filled_quantity=qty, average_price=price,
    )


def test_buy_is_sent_tagged_as_live_market_cnc(db_session, kite):
    strategy, instrument = _setup(db_session)
    order = execution.place_real_holding_buy(db_session, strategy, instrument, 3, 1000.0)

    assert order.mode == "live" and order.transaction_type == TransactionType.BUY
    assert order.status == OrderStatus.PENDING and order.broker_order_id == "501"
    assert order.price == 1000.0
    [req] = kite.placed
    assert req.tag == f"stmlh-b-{order.id}" and len(req.tag) <= 20
    assert req.price is None and req.quantity == 3


def test_a_filled_buy_becomes_a_holding_with_minus_4_plus_8(db_session, kite):
    strategy, instrument = _setup(db_session)
    order = execution.place_real_holding_buy(db_session, strategy, instrument, 3, 1000.0)
    _complete(kite, order, 990.0, 3)

    execution.reconcile_pending_orders(db_session)

    position = db_session.execute(
        select(Position).where(Position.strategy_id == strategy.id)
    ).scalar_one()
    assert position.status == PositionStatus.OPEN and position.mode == "live"
    assert position.quantity == 3 and position.entry_price == 990.0
    assert position.stop_loss == round(990.0 * 0.96, 2)
    assert position.take_profit == round(990.0 * 1.08, 2)
    assert "ZZRHBUY" in (strategy.symbols or []), "the model must read an app-bought stock daily"


def test_a_rejected_buy_creates_nothing(db_session, kite):
    strategy, instrument = _setup(db_session)
    order = execution.place_real_holding_buy(db_session, strategy, instrument, 3, 1000.0)
    kite.status[order.broker_order_id] = OrderResult(
        broker_order_id=order.broker_order_id, status=OrderStatus.REJECTED, message="Insufficient funds"
    )

    execution.reconcile_pending_orders(db_session)

    assert db_session.get(Order, order.id).status == OrderStatus.REJECTED
    assert db_session.execute(select(Position).where(Position.strategy_id == strategy.id)).first() is None


def _holding(db, strategy, instrument, qty=10):
    p = Position(
        strategy_id=strategy.id, instrument_id=instrument.id, mode="live", quantity=qty,
        initial_quantity=qty, entry_price=100.0, current_price=110.0, total_charges=0.0,
        entry_at=datetime(2026, 10, 1, tzinfo=UTC), status=PositionStatus.OPEN,
    )
    db.add(p)
    db.flush()
    return p


def test_a_full_sell_closes_the_holding_at_the_real_fill(db_session, kite):
    strategy, instrument = _setup(db_session, "ZZRHSELL", 881_002)
    position = _holding(db_session, strategy, instrument)

    order = execution.place_real_holding_sell(db_session, position, 10)
    assert kite.placed[0].tag == f"stmlh-s-{order.id}"
    assert order.exit_reason == ExitReason.MANUAL and order.position_id == position.id
    _complete(kite, order, 112.0, 10)

    execution.reconcile_pending_orders(db_session)

    db_session.refresh(position)
    assert position.status == PositionStatus.CLOSED and position.exit_price == 112.0
    trade = db_session.execute(select(Trade).where(Trade.position_id == position.id)).scalar_one()
    assert trade.quantity == 10 and trade.exit_reason == ExitReason.MANUAL


def test_a_partial_sell_keeps_the_rest(db_session, kite):
    strategy, instrument = _setup(db_session, "ZZRHHALF", 881_003)
    position = _holding(db_session, strategy, instrument)

    order = execution.place_real_holding_sell(db_session, position, 4)
    _complete(kite, order, 112.0, 4)
    execution.reconcile_pending_orders(db_session)

    db_session.refresh(position)
    assert position.status == PositionStatus.OPEN and position.quantity == 6


def test_paper_bot_orders_are_not_sent_to_kite_by_the_second_pass(db_session, kite, monkeypatch):
    """The extra pass looks only at real_trading's live orders."""
    strategy, instrument = _setup(db_session, "ZZRHBOT", 881_004)
    bot = Strategy(name="zz_bot", strategy_type="ml_swing", mode="paper", execution_mode="auto", is_active=True)
    db_session.add(bot)
    db_session.flush()
    db_session.add(Order(
        strategy_id=bot.id, instrument_id=instrument.id, mode="live", transaction_type="BUY",
        quantity=1, status=OrderStatus.PENDING, broker_order_id="777",
        placed_at=datetime.now(UTC),
    ))
    db_session.flush()
    asked: list[str] = []
    monkeypatch.setattr(kite_broker, "get_order_status", lambda oid, db: asked.append(oid))

    execution.reconcile_pending_orders(db_session)

    assert "777" not in asked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... -m pytest tests/test_real_holdings_execution.py -q`
Expected: FAIL — `AttributeError: module 'swing_trade_ml.services.execution' has no attribute 'place_real_holding_buy'`.

- [ ] **Step 3: Implement**

Imports in `execution.py`: add `REAL_HOLDINGS_TAG_PREFIX` via `from swing_trade_ml.brokers.base import REAL_HOLDINGS_TAG_PREFIX`; add `TradingMode` to the `core.enums` import; change `from swing_trade_ml.services.portfolio import portfolio_value_and_cash, record_price` to also import `REAL_TRADING_STRATEGY_NAME`.

Add after `manual_close_position`:

```python
# ------------------------------------------------- real My Holdings orders --

#: The settled per-trade rules (CLAUDE.md "Risk rules"): -4% stop, +8% target,
#: measured from the real fill of an app-placed My Holdings buy.
REAL_HOLDING_STOP_PCT = 0.04
REAL_HOLDING_TARGET_PCT = 0.08


def _place_real_holding_order(
    db: Session,
    *,
    strategy_id: int,
    instrument: Instrument,
    side: TransactionType,
    quantity: int,
    reference_price: float | None,
    position_id: int | None = None,
    exit_reason: ExitReason | None = None,
) -> Order:
    """Send one owner-placed My Holdings order to Zerodha.

    Always the Kite broker, never get_broker(): the bot is on paper, these are
    the owner's real shares. KiteBroker only lets it through while
    ALLOW_REAL_HOLDINGS_ORDERS is on, because of the reserved tag. Every check
    (limits, market clock, owned quantity) is done before this, in
    services/real_orders.py.

    `price` stores the price seen when the order was placed. It is a reference
    for the daily limit and the screen only — a MARKET order is sent without
    a price. Like every live order, the Position/Trade is finished later by
    reconcile_pending_orders once Zerodha reports the fill.
    """
    from swing_trade_ml.brokers.kite import kite_broker

    order = Order(
        strategy_id=strategy_id,
        position_id=position_id,
        instrument_id=instrument.id,
        mode=TradingMode.LIVE,
        transaction_type=side,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        quantity=quantity,
        price=reference_price,
        status=OrderStatus.PENDING,
        exit_reason=exit_reason,
        placed_at=datetime.now(UTC),
    )
    db.add(order)
    db.commit()

    letter = "b" if side == TransactionType.BUY else "s"
    result = kite_broker.place_order(
        OrderRequest(
            tradingsymbol=instrument.tradingsymbol,
            exchange=instrument.exchange,
            transaction_type=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            product=ProductType.CNC,
            tag=f"{REAL_HOLDINGS_TAG_PREFIX}{letter}-{order.id}",
        ),
        db,
    )
    order.broker_order_id = result.broker_order_id
    order.status = result.status
    order.status_message = result.message
    db.commit()

    word = "BUY" if side == TransactionType.BUY else "SELL"
    if result.status == OrderStatus.REJECTED:
        notifier.send_sync(
            f"⚠️ <b>Real {word} refused by Zerodha · {instrument.tradingsymbol}</b>\n"
            f"{result.message or 'No reason given.'}",
            "error",
        )
    else:
        about = f" (about ₹{reference_price * quantity:,.0f})" if reference_price else ""
        notifier.send_sync(
            f"💰 <b>Real {word} sent · {instrument.tradingsymbol}</b>\n"
            f"{quantity:,} shares at market price{about}. Waiting for Zerodha to confirm.",
            "fill",
        )
    log.info(
        "execution.real_holding.sent",
        symbol=instrument.tradingsymbol, side=word, qty=quantity, status=str(result.status),
    )
    return order


def place_real_holding_buy(
    db: Session, strategy: Strategy, instrument: Instrument, quantity: int, reference_price: float
) -> Order:
    return _place_real_holding_order(
        db, strategy_id=strategy.id, instrument=instrument, side=TransactionType.BUY,
        quantity=quantity, reference_price=reference_price,
    )


def place_real_holding_sell(db: Session, position: Position, quantity: int) -> Order:
    instrument = db.get(Instrument, position.instrument_id)
    if instrument is None:
        raise ValueError(f"Instrument {position.instrument_id} not found for position {position.id}")
    return _place_real_holding_order(
        db, strategy_id=position.strategy_id, instrument=instrument, side=TransactionType.SELL,
        quantity=quantity, reference_price=position.current_price, position_id=position.id,
        exit_reason=ExitReason.MANUAL,
    )
```

Replace `reconcile_pending_orders` with a version that splits the loop out and adds the second pass (keep the existing docstring and append the paragraph shown):

```python
def reconcile_pending_orders(db: Session) -> dict[str, int]:
    """...existing docstring...

    The owner's real My Holdings orders are live while the bot is on paper,
    so the pass over the bot's own mode never sees them. A second pass checks
    those with the Kite broker directly.
    """
    broker = get_broker()
    counts = {"checked": 0, "filled": 0, "failed": 0, "unchanged": 0}
    _reconcile_orders(db, broker, _waiting_orders(db, broker.mode), counts)

    if broker.mode != TradingMode.LIVE:
        real = _waiting_real_holding_orders(db)
        if real:
            from swing_trade_ml.brokers.kite import kite_broker

            if kite_broker.load_session(db):
                _reconcile_orders(db, kite_broker, real, counts)
            else:
                log.warning("execution.reconcile.real_holdings_no_session", waiting=len(real))

    db.commit()
    log.info("execution.reconcile.done", **counts)
    return counts


_WAITING = (OrderStatus.PENDING, OrderStatus.OPEN)


def _waiting_orders(db: Session, mode: str) -> list[Order]:
    return list(
        db.execute(
            select(Order).where(
                Order.mode == mode,
                Order.status.in_(_WAITING),
                Order.broker_order_id.isnot(None),
                Order.broker_order_id != "",
            )
        )
        .scalars()
        .all()
    )


def _waiting_real_holding_orders(db: Session) -> list[Order]:
    return list(
        db.execute(
            select(Order)
            .join(Strategy, Strategy.id == Order.strategy_id)
            .where(
                Strategy.name == REAL_TRADING_STRATEGY_NAME,
                Order.mode == TradingMode.LIVE,
                Order.status.in_(_WAITING),
                Order.broker_order_id.isnot(None),
                Order.broker_order_id != "",
            )
        )
        .scalars()
        .all()
    )


def _reconcile_orders(db: Session, broker, orders: list[Order], counts: dict[str, int]) -> None:
    for order in orders:
        counts["checked"] += 1
        result = broker.get_order_status(order.broker_order_id, db)
        if result is None or result.status == order.status:
            counts["unchanged"] += 1
            continue

        order.status = result.status
        order.filled_quantity = result.filled_quantity
        order.average_price = result.average_price
        order.status_message = result.message

        if result.status == OrderStatus.COMPLETE:
            order.filled_at = order.filled_at or datetime.now(UTC)
            _finish_reconciled_order(db, order, result)
            counts["filled"] += 1
        elif result.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
            _fail_reconciled_order(db, order, result)
            counts["failed"] += 1
```

In `_finish_reconciled_order`:
- Change `if settings.is_live_trading:` (the charges-estimated log) to `if order.mode == TradingMode.LIVE:`.
- In the BUY branch, replace the `_finalize_open_position(...)` call's stop/target arguments with locals computed first:

```python
        stop_loss = signal.stop_loss if signal else None
        take_profit = signal.take_profit if signal else None
        is_my_holdings = signal is None and strategy.name == REAL_TRADING_STRATEGY_NAME
        if is_my_holdings:
            stop_loss = round(fill_price * (1 - REAL_HOLDING_STOP_PCT), 2)
            take_profit = round(fill_price * (1 + REAL_HOLDING_TARGET_PCT), 2)

        position = _finalize_open_position(
            db, strategy, instrument, order.mode, filled_qty, fill_price, brokerage, taxes,
            stop_loss,
            take_profit,
            order.filled_at or datetime.now(UTC),
            signal.confidence if signal else None,
        )
        order.position_id = position.id
        if is_my_holdings and instrument.tradingsymbol not in (strategy.symbols or []):
            # Same as Import from Kite: the strategy's universe is what the
            # model reads daily, and a hand-bought stock is rarely watchlisted.
            strategy.symbols = sorted({*(strategy.symbols or []), instrument.tradingsymbol})
```

(the rest of the BUY branch — `signal.was_executed`, log, notifier — unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `... -m pytest tests/test_real_holdings_execution.py tests/test_paper_trade_lifecycle.py tests/test_partial_profit_booking.py tests/test_real_holdings_gate.py -q`
Also run whatever existing reconcile tests exist: `grep -l reconcile_pending_orders tests/*.py` and include them.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/services/execution.py backend/tests/test_real_holdings_execution.py
git commit -m "Real holdings orders: place tagged live buy/sell via Kite and finish them in reconciliation, -4%/+8% on fill"
```

---

### Task 3: Safety checks (`services/real_orders.py`) and holdings-sync guard

**Files:**
- Create: `backend/src/swing_trade_ml/services/real_orders.py`
- Modify: `backend/src/swing_trade_ml/services/holdings_sync.py` (`close_positions_no_longer_held`)
- Test: `backend/tests/test_real_holdings_orders.py`

**Interfaces:**
- Consumes: `execution.place_real_holding_buy/sell` (Task 2), settings (Task 1), `kite_broker.load_session/get_ltp`, `market_session.is_open/session/when`.
- Produces:
  - `class RealOrderRefused(Exception)` — message is the plain sentence shown to the owner.
  - `quote(db, instrument) -> float`
  - `buy(db, strategy, instrument, quantity) -> Order`
  - `sell(db, position, quantity: int | None) -> Order`
  - `spent_today(db, strategy_id: int, now: datetime | None = None) -> float`
  - `status(db, strategy: Strategy | None) -> dict` with keys `enabled, max_order_inr, max_day_inr, spent_today_inr, market_open, market_text, waiting` (`waiting` = list of `{symbol, side, quantity, placed_at}`).

- [ ] **Step 1: Write the failing test**

```python
"""Every check in front of a real My Holdings order. Nothing reaches Zerodha
when one fails; the owner sees one plain sentence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.brokers import OrderResult
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core import config, market_session
from swing_trade_ml.core.enums import OrderStatus, PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services import execution, holdings_sync, real_orders
from swing_trade_ml.services.real_orders import RealOrderRefused


@pytest.fixture
def ready(monkeypatch):
    """Latch on, market open, Zerodha logged in, price 1000, orders recorded."""
    sent: list = []
    state = {"price": 1000.0, "session": True}
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)
    monkeypatch.setattr(market_session, "is_open", lambda *a, **k: True)
    monkeypatch.setattr(kite_broker, "load_session", lambda db: state["session"])
    monkeypatch.setattr(kite_broker, "_token_loaded", True, raising=False)
    monkeypatch.setattr(kite_broker, "get_ltp", lambda symbols, db: {s: state["price"] for s in symbols})

    def place(request, db):
        sent.append(request)
        return OrderResult(broker_order_id=str(600 + len(sent)), status=OrderStatus.PENDING)

    monkeypatch.setattr(kite_broker, "place_order", place)
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **k: True)
    return sent, state


def _setup(db, symbol="ZZRO", token=882_001):
    strategy = Strategy(name="real_trading", strategy_type="ml_swing", mode="live",
                        execution_mode="advisory", is_active=True, params={}, symbols=[])
    instrument = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE")
    db.add_all([strategy, instrument])
    db.flush()
    return strategy, instrument


def _holding(db, strategy, instrument, qty=10):
    p = Position(strategy_id=strategy.id, instrument_id=instrument.id, mode="live", quantity=qty,
                 initial_quantity=qty, entry_price=100.0, current_price=110.0, total_charges=0.0,
                 entry_at=datetime(2026, 10, 1, tzinfo=UTC), status=PositionStatus.OPEN)
    db.add(p)
    db.flush()
    return p


def test_a_small_buy_inside_the_limits_is_sent(db_session, ready):
    sent, _ = ready
    strategy, instrument = _setup(db_session)
    order = real_orders.buy(db_session, strategy, instrument, 9)
    assert order.status == OrderStatus.PENDING and len(sent) == 1


def test_switch_off_refuses_and_sends_nothing(db_session, ready, monkeypatch):
    sent, _ = ready
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", False, raising=False)
    strategy, instrument = _setup(db_session)
    with pytest.raises(RealOrderRefused, match="switched off"):
        real_orders.buy(db_session, strategy, instrument, 1)
    position = _holding(db_session, strategy, instrument)
    with pytest.raises(RealOrderRefused, match="switched off"):
        real_orders.sell(db_session, position, None)
    assert sent == []


def test_market_closed_is_refused(db_session, ready, monkeypatch):
    sent, _ = ready
    monkeypatch.setattr(market_session, "is_open", lambda *a, **k: False)
    strategy, instrument = _setup(db_session)
    with pytest.raises(RealOrderRefused, match="market is closed"):
        real_orders.buy(db_session, strategy, instrument, 1)
    assert sent == []


def test_over_10k_in_one_order_is_refused(db_session, ready):
    sent, state = ready
    state["price"] = 1000.01
    strategy, instrument = _setup(db_session)
    with pytest.raises(RealOrderRefused, match="per order"):
        real_orders.buy(db_session, strategy, instrument, 10)
    assert sent == []


def test_the_third_10k_buy_of_the_day_is_refused(db_session, ready):
    sent, _ = ready
    strategy, instrument = _setup(db_session)
    other = Instrument(instrument_token=882_002, tradingsymbol="ZZRO2", exchange="NSE")
    third = Instrument(instrument_token=882_003, tradingsymbol="ZZRO3", exchange="NSE")
    db_session.add_all([other, third])
    db_session.flush()
    real_orders.buy(db_session, strategy, instrument, 10)  # ₹10,000
    real_orders.buy(db_session, strategy, other, 10)       # ₹20,000
    with pytest.raises(RealOrderRefused, match="daily limit"):
        real_orders.buy(db_session, strategy, third, 10)   # would be ₹30,000
    assert len(sent) == 2


def test_pending_buys_count_toward_the_daily_cap(db_session, ready):
    """A market order has no fill price yet; its reference price still counts."""
    strategy, instrument = _setup(db_session)
    real_orders.buy(db_session, strategy, instrument, 10)
    assert real_orders.spent_today(db_session, strategy.id) == 10_000


def test_rejected_buys_do_not_use_up_the_day(db_session, ready):
    strategy, instrument = _setup(db_session)
    order = real_orders.buy(db_session, strategy, instrument, 10)
    order.status = OrderStatus.REJECTED
    db_session.flush()
    assert real_orders.spent_today(db_session, strategy.id) == 0


def test_a_sell_is_never_blocked_by_the_money_limit(db_session, ready):
    sent, state = ready
    state["price"] = 50_000.0
    strategy, instrument = _setup(db_session)
    position = _holding(db_session, strategy, instrument, qty=10)
    real_orders.sell(db_session, position, None)
    assert sent[-1].quantity == 10


def test_selling_more_than_held_is_refused(db_session, ready):
    strategy, instrument = _setup(db_session)
    position = _holding(db_session, strategy, instrument, qty=5)
    with pytest.raises(RealOrderRefused, match="between 1 and 5"):
        real_orders.sell(db_session, position, 6)


def test_only_my_holdings_positions_can_be_sold(db_session, ready):
    _, instrument = _setup(db_session)
    bot = Strategy(name="zz_bot2", strategy_type="ml_swing", mode="paper", execution_mode="auto", is_active=True)
    db_session.add(bot)
    db_session.flush()
    position = _holding(db_session, bot, instrument)
    with pytest.raises(RealOrderRefused, match="My Holdings"):
        real_orders.sell(db_session, position, None)


def test_a_second_order_while_one_is_waiting_is_refused(db_session, ready):
    sent, _ = ready
    strategy, instrument = _setup(db_session)
    real_orders.buy(db_session, strategy, instrument, 1)
    with pytest.raises(RealOrderRefused, match="still waiting"):
        real_orders.buy(db_session, strategy, instrument, 1)
    assert len(sent) == 1


def test_no_zerodha_session_is_refused_plainly(db_session, ready):
    sent, state = ready
    state["session"] = False
    strategy, instrument = _setup(db_session)
    with pytest.raises(RealOrderRefused, match="Log in to Zerodha"):
        real_orders.buy(db_session, strategy, instrument, 1)
    assert sent == []


def test_status_reports_switch_limits_spend_and_waiting(db_session, ready):
    strategy, instrument = _setup(db_session)
    real_orders.buy(db_session, strategy, instrument, 2)
    s = real_orders.status(db_session, strategy)
    assert s["enabled"] is True and s["max_order_inr"] == 10_000 and s["max_day_inr"] == 25_000
    assert s["spent_today_inr"] == 2_000
    assert s["waiting"][0]["symbol"] == "ZZRO" and s["waiting"][0]["side"] == "BUY"


def test_sync_leaves_a_holding_with_a_waiting_order_alone(db_session, ready):
    """Zerodha already dropped the sold shares, but the app has not recorded
    the real fill yet. The sync must not close it at a guessed price."""
    strategy, instrument = _setup(db_session)
    position = _holding(db_session, strategy, instrument)
    real_orders.sell(db_session, position, None)

    closed = holdings_sync.close_positions_no_longer_held(db_session, strategy, held_symbols=set())

    assert closed == []
    db_session.refresh(position)
    assert position.status == PositionStatus.OPEN


def test_sync_still_closes_a_holding_sold_outside_the_app(db_session, ready):
    strategy, instrument = _setup(db_session)
    position = _holding(db_session, strategy, instrument)
    closed = holdings_sync.close_positions_no_longer_held(db_session, strategy, held_symbols=set())
    assert [c["symbol"] for c in closed] == ["ZZRO"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... -m pytest tests/test_real_holdings_orders.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'swing_trade_ml.services.real_orders'`.

- [ ] **Step 3: Implement**

Create `services/real_orders.py`:

```python
"""Real orders the owner places by hand from My Holdings.

The bot stays on paper for its trial; the owner's own Zerodha shares are real.
This module is every check in front of a real order — the latch, the market
clock, the money limits, what is actually owned, one waiting order per stock —
so a refusal is always a plain sentence and nothing reaches Zerodha.
Placement and bookkeeping stay in services/execution.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import KiteException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core import market_session
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import OrderStatus, PositionStatus, TradingMode, TransactionType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy
from swing_trade_ml.services import execution
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME

IST = ZoneInfo("Asia/Kolkata")
_WAITING = (OrderStatus.PENDING, OrderStatus.OPEN)
_NOT_SPENT = (OrderStatus.REJECTED, OrderStatus.CANCELLED)


class RealOrderRefused(Exception):
    """Why a real order was not sent, in one plain sentence. Nothing reached Zerodha."""


def _require_switch_and_market() -> None:
    if not settings.ALLOW_REAL_HOLDINGS_ORDERS:
        raise RealOrderRefused("Real orders are switched off.")
    if not market_session.is_open():
        opens = market_session.when(market_session.session().next_open)
        raise RealOrderRefused(f"The market is closed right now. It opens {opens}.")


def _kite_ready(db: Session):
    from swing_trade_ml.brokers.kite import kite_broker

    if not kite_broker.load_session(db):
        raise RealOrderRefused("Zerodha is not logged in today. Log in to Zerodha first.")
    return kite_broker


def _waiting(db: Session, strategy_id: int, instrument_id: int) -> bool:
    return (
        db.execute(
            select(Order.id).where(
                Order.strategy_id == strategy_id,
                Order.instrument_id == instrument_id,
                Order.status.in_(_WAITING),
            )
        ).first()
        is not None
    )


def quote(db: Session, instrument: Instrument) -> float:
    kite = _kite_ready(db)
    key = f"{instrument.exchange}:{instrument.tradingsymbol}"
    try:
        price = kite.get_ltp([key], db).get(key)
    except KiteException:
        price = None
    if not price:
        raise RealOrderRefused("Could not get a live price from Zerodha, so nothing was sent.")
    return float(price)


def spent_today(db: Session, strategy_id: int, now: datetime | None = None) -> float:
    """Rupees of real buys placed today (IST), waiting or filled.

    A waiting market order has no fill price yet, so its reference price
    counts; a refused or cancelled one does not."""
    local = (now or datetime.now(UTC)).astimezone(IST)
    start = datetime.combine(local.date(), time(0, 0), tzinfo=IST).astimezone(UTC)
    total = db.execute(
        select(
            func.coalesce(
                func.sum(Order.quantity * func.coalesce(Order.average_price, Order.price)), 0.0
            )
        ).where(
            Order.strategy_id == strategy_id,
            Order.mode == TradingMode.LIVE,
            Order.transaction_type == TransactionType.BUY,
            Order.placed_at >= start,
            Order.status.notin_(_NOT_SPENT),
        )
    ).scalar_one()
    return float(total)


def buy(db: Session, strategy: Strategy, instrument: Instrument, quantity: int) -> Order:
    if quantity < 1:
        raise RealOrderRefused("Choose at least 1 share.")
    _require_switch_and_market()
    if _waiting(db, strategy.id, instrument.id):
        raise RealOrderRefused(
            f"An order for {instrument.tradingsymbol} is still waiting at Zerodha. Wait for it to finish."
        )
    price = quote(db, instrument)
    cost = price * quantity
    per_order = settings.REAL_HOLDINGS_MAX_ORDER_INR
    if cost > per_order:
        raise RealOrderRefused(
            f"This buy is about ₹{cost:,.0f}. The limit is ₹{per_order:,.0f} per order."
        )
    spent, per_day = spent_today(db, strategy.id), settings.REAL_HOLDINGS_MAX_DAY_INR
    if spent + cost > per_day:
        raise RealOrderRefused(
            f"You have already bought ₹{spent:,.0f} today. This buy (about ₹{cost:,.0f}) "
            f"would go over the ₹{per_day:,.0f} daily limit."
        )
    return execution.place_real_holding_buy(db, strategy, instrument, quantity, price)


def sell(db: Session, position: Position, quantity: int | None) -> Order:
    if position.strategy is None or position.strategy.name != REAL_TRADING_STRATEGY_NAME:
        raise RealOrderRefused("Only shares in My Holdings can be sold here.")
    if position.status != PositionStatus.OPEN:
        raise RealOrderRefused("This holding is already closed.")
    qty = position.quantity if quantity is None else int(quantity)
    if not 1 <= qty <= position.quantity:
        raise RealOrderRefused(
            f"You hold {position.quantity} shares. Choose between 1 and {position.quantity}."
        )
    _require_switch_and_market()
    if _waiting(db, position.strategy_id, position.instrument_id):
        raise RealOrderRefused("An order for this stock is still waiting at Zerodha. Wait for it to finish.")
    _kite_ready(db)
    return execution.place_real_holding_sell(db, position, qty)


def status(db: Session, strategy: Strategy | None) -> dict[str, Any]:
    session = market_session.session()
    waiting: list[dict[str, Any]] = []
    spent = 0.0
    if strategy is not None:
        spent = spent_today(db, strategy.id)
        rows = db.execute(
            select(Order, Instrument.tradingsymbol)
            .join(Instrument, Instrument.id == Order.instrument_id)
            .where(Order.strategy_id == strategy.id, Order.status.in_(_WAITING))
            .order_by(Order.placed_at)
        ).all()
        waiting = [
            {
                "symbol": symbol,
                "side": str(order.transaction_type),
                "quantity": order.quantity,
                "placed_at": order.placed_at.isoformat() if order.placed_at else None,
            }
            for order, symbol in rows
        ]
    return {
        "enabled": bool(settings.ALLOW_REAL_HOLDINGS_ORDERS),
        "max_order_inr": settings.REAL_HOLDINGS_MAX_ORDER_INR,
        "max_day_inr": settings.REAL_HOLDINGS_MAX_DAY_INR,
        "spent_today_inr": spent,
        "market_open": market_session.is_open(),
        "market_text": session.plain,
        "waiting": waiting,
    }
```

Note: `Position.strategy` must be a loaded relationship (it is used the same way in `portfolio.py`'s `_position_cap_tier`). If the test's freshly-flushed `Position` has `strategy` as `None`, call `db_session.refresh(p)` in `_holding` after flush.

`services/holdings_sync.py`: add `OrderStatus` to the enums import and `Order` to the models import, then in `close_positions_no_longer_held` before the loop:

```python
    # A holding with a real order still waiting at Zerodha is left alone: an
    # app sell drops the shares from Zerodha before reconciliation records the
    # real fill, and closing it here would book a guessed price instead.
    # Reconciliation closes it with the real one, in the same step that marks
    # the order finished, so there is no gap for this to fall into.
    waiting = set(
        db.execute(
            select(Order.instrument_id).where(
                Order.strategy_id == strategy.id,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
            )
        ).scalars()
    )
```

and inside the loop, right after the `instrument is None or ... in held_symbols` check:

```python
        if position.instrument_id in waiting:
            log.info("holdings_sync.skipped_order_waiting", symbol=instrument.tradingsymbol)
            continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `... -m pytest tests/test_real_holdings_orders.py tests/test_sold_holdings_stop_warning.py tests/test_holdings_t1_quantity.py tests/test_real_holdings_execution.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/services/real_orders.py backend/src/swing_trade_ml/services/holdings_sync.py backend/tests/test_real_holdings_orders.py
git commit -m "Real holdings orders: all safety checks in one place; holdings sync leaves a holding with a waiting order alone"
```

---

### Task 4: Owner-only API routes

**Files:**
- Modify: `backend/src/swing_trade_ml/schemas/__init__.py` (after `TesterPaperBuyRequest`, ~line 420)
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py` (imports; new routes after `close_manual_position`, ~line 687)
- Test: `backend/tests/test_real_holdings_api.py`

**Interfaces:**
- Consumes: `real_orders.buy/sell/quote/status/RealOrderRefused` (Task 3), `_get_or_create_real_trading_strategy` (existing in portfolio.py), `require_owner` (api/deps.py).
- Produces:
  - `GET /api/v1/portfolio/real/orders-status` → `status()` dict
  - `GET /api/v1/portfolio/real/quote?symbol=X&exchange=NSE` → `{symbol, exchange, price}`
  - `POST /api/v1/portfolio/real/buy` body `{symbol, quantity, exchange?}` → 201 `{order_id, symbol, side, quantity, status, message}`
  - `POST /api/v1/portfolio/real/positions/{id}/sell` body `{quantity?}` → 201 same shape
  - Refusal → 409 `{"detail": "<sentence>"}`; unknown stock/position → 404.

- [ ] **Step 1: Write the failing test**

```python
"""The real-order routes: owner only, refusals as plain 409s."""

from __future__ import annotations

import pytest

from swing_trade_ml.brokers import OrderResult
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core import config, market_session
from swing_trade_ml.core.enums import OrderStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services import execution

HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture
def ready(monkeypatch, db_session):
    sent: list = []
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)
    monkeypatch.setattr(market_session, "is_open", lambda *a, **k: True)
    monkeypatch.setattr(kite_broker, "load_session", lambda db: True)
    monkeypatch.setattr(kite_broker, "get_ltp", lambda symbols, db: {s: 500.0 for s in symbols})

    def place(request, db):
        sent.append(request)
        return OrderResult(broker_order_id="701", status=OrderStatus.PENDING)

    monkeypatch.setattr(kite_broker, "place_order", place)
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **k: True)
    db_session.add(Instrument(instrument_token=883_001, tradingsymbol="ZZAPI", exchange="NSE"))
    db_session.commit()
    return sent


def test_buy_route_sends_a_small_order(client, ready):
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "zzapi", "quantity": 4}, headers=HEADERS)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "PENDING" and r.json()["symbol"] == "ZZAPI"
    assert len(ready) == 1


def test_a_refusal_is_a_409_with_the_reason(client, ready):
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "ZZAPI", "quantity": 100}, headers=HEADERS)
    assert r.status_code == 409 and "per order" in r.json()["detail"]
    assert ready == []


def test_switch_off_is_refused(client, ready, monkeypatch):
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", False, raising=False)
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "ZZAPI", "quantity": 1}, headers=HEADERS)
    assert r.status_code == 409 and "switched off" in r.json()["detail"]


def test_unknown_stock_is_404(client, ready):
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "NOPE", "quantity": 1}, headers=HEADERS)
    assert r.status_code == 404


def test_status_and_quote(client, ready):
    s = client.get("/api/v1/portfolio/real/orders-status", headers=HEADERS)
    assert s.status_code == 200 and s.json()["enabled"] is True
    q = client.get("/api/v1/portfolio/real/quote?symbol=ZZAPI", headers=HEADERS)
    assert q.status_code == 200 and q.json()["price"] == 500.0


def test_no_credentials_is_refused(client, ready):
    assert client.post("/api/v1/portfolio/real/buy", json={"symbol": "ZZAPI", "quantity": 1}).status_code in (401, 403)
    assert ready == []
```

The non-owner case for every write is already covered by `tests/test_permissions_review.py`, which walks every route; run it in Step 4.

- [ ] **Step 2: Run test to verify it fails**

Run: `... -m pytest tests/test_real_holdings_api.py -q`
Expected: FAIL — 404/405 on `/portfolio/real/buy`.

- [ ] **Step 3: Implement**

`schemas/__init__.py`, after `TesterPaperBuyRequest`:

```python
class RealBuyRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0)
    exchange: str = "NSE"


class RealSellRequest(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
```

`portfolio.py` imports: add `Depends` to the fastapi import; `from swing_trade_ml.api.deps import DbSession, PlanAccessDep, require_owner`; add `RealBuyRequest, RealSellRequest` to the schemas import; `from swing_trade_ml.services import real_orders`; add `Order` to the `db.models.trading` import.

Routes, after `close_manual_position`:

```python
# ---------------------------------------- real orders from My Holdings --
# The owner's own hand-placed Zerodha orders while the bot stays on paper.
# Every check lives in services/real_orders.py; these only translate.

_OWNER = [Depends(require_owner)]


def _real_order_out(order: Order, instrument: Instrument) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "symbol": instrument.tradingsymbol,
        "side": str(order.transaction_type),
        "quantity": order.quantity,
        "status": str(order.status),
        "message": order.status_message,
    }


def _instrument_or_404(db: DbSession, symbol: str, exchange: str) -> Instrument:
    instrument = db.execute(
        select(Instrument).where(
            Instrument.tradingsymbol == symbol.strip().upper(), Instrument.exchange == exchange
        )
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown stock {symbol.strip().upper()}.")
    return instrument


@router.get("/real/orders-status", dependencies=_OWNER)
def real_orders_status(db: DbSession) -> dict[str, Any]:
    strategy = db.execute(
        select(Strategy).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
    ).scalar_one_or_none()
    return real_orders.status(db, strategy)


@router.get("/real/quote", dependencies=_OWNER)
def real_quote(db: DbSession, symbol: str, exchange: str = "NSE") -> dict[str, Any]:
    instrument = _instrument_or_404(db, symbol, exchange)
    try:
        price = real_orders.quote(db, instrument)
    except real_orders.RealOrderRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"symbol": instrument.tradingsymbol, "exchange": instrument.exchange, "price": price}


@router.post("/real/buy", status_code=status.HTTP_201_CREATED, dependencies=_OWNER)
def real_buy(payload: RealBuyRequest, db: DbSession) -> dict[str, Any]:
    instrument = _instrument_or_404(db, payload.symbol, payload.exchange)
    strategy = _get_or_create_real_trading_strategy(db)
    try:
        order = real_orders.buy(db, strategy, instrument, payload.quantity)
    except real_orders.RealOrderRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _real_order_out(order, instrument)


@router.post("/real/positions/{position_id}/sell", status_code=status.HTTP_201_CREATED, dependencies=_OWNER)
def real_sell(position_id: int, payload: RealSellRequest, db: DbSession) -> dict[str, Any]:
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holding not found.")
    try:
        order = real_orders.sell(db, position, payload.quantity)
    except real_orders.RealOrderRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _real_order_out(order, db.get(Instrument, position.instrument_id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `... -m pytest tests/test_real_holdings_api.py tests/test_permissions_review.py tests/test_system_endpoint_auth.py -q`
Expected: all PASS. If `test_permissions_review.py` has an explicit allow-list of routes that a non-owner may read, these GETs are owner-only and must NOT be added to it.

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/schemas/__init__.py backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py backend/tests/test_real_holdings_api.py
git commit -m "Real holdings orders: owner-only buy, sell, quote and status routes"
```

---

### Task 5: My Holdings screen — Buy real / Sell real / status line

**Files:**
- Modify: `frontend/src/api/types.ts` (add two interfaces)
- Modify: `frontend/src/api/client.ts` (after `manualClosePosition`, ~line 321)
- Modify: `frontend/src/trademind/pages/MyHoldings.tsx` (`HoldingsTab`, plus two dialog components above it)

**Interfaces:**
- Consumes: the four routes from Task 4.
- Produces: UI only.

- [ ] **Step 1: Setup — frontend dependencies in the worktree**

The worktree has no `node_modules`. Create a junction to the main checkout's (same as the brain worktree):

```bash
cmd //c mklink /J "D:\machine learning\swing-trade-bot\.claude\worktrees\real-holdings\frontend\node_modules" "D:\machine learning\swing-trade-bot\frontend\node_modules"
```

- [ ] **Step 2: Types and client**

`api/types.ts`:

```ts
export interface RealOrdersStatus {
  enabled: boolean
  max_order_inr: number
  max_day_inr: number
  spent_today_inr: number
  market_open: boolean
  market_text: string
  waiting: { symbol: string; side: 'BUY' | 'SELL'; quantity: number; placed_at: string | null }[]
}

export interface RealOrder {
  order_id: number
  symbol: string
  side: 'BUY' | 'SELL'
  quantity: number
  status: string
  message: string | null
}
```

`api/client.ts`, after `manualClosePosition` (add `RealOrder, RealOrdersStatus` to the types import):

```ts
  // REAL orders to Zerodha for My Holdings — owner only, refused by the
  // server unless the real-orders switch is on and the limits allow it.
  realOrdersStatus: () => get<RealOrdersStatus>('/portfolio/real/orders-status'),
  realQuote: (symbol: string) =>
    get<{ symbol: string; exchange: string; price: number }>(
      `/portfolio/real/quote?symbol=${encodeURIComponent(symbol)}`,
    ),
  realBuy: (symbol: string, quantity: number) =>
    post<RealOrder>('/portfolio/real/buy', { symbol, quantity }),
  realSell: (id: number, quantity?: number) =>
    post<RealOrder>(`/portfolio/real/positions/${id}/sell`, quantity ? { quantity } : {}),
```

- [ ] **Step 3: Dialogs** — add above `function HoldingsTab()` in `MyHoldings.tsx` (add `RealOrdersStatus` to the types import):

```tsx
function BuyRealDialog({
  limits,
  onSubmit,
  onClose,
}: {
  limits: RealOrdersStatus
  onSubmit: (symbol: string, quantity: number) => Promise<unknown>
  onClose: () => void
}) {
  const [symbol, setSymbol] = useState('')
  const [qty, setQty] = useState('1')
  const [price, setPrice] = useState<number | null>(null)
  const [priceError, setPriceError] = useState<string | null>(null)
  const quantity = Number(qty)
  const cost = price != null && quantity > 0 ? price * quantity : null

  async function lookUp() {
    setPrice(null)
    setPriceError(null)
    try {
      setPrice((await api.realQuote(symbol.trim().toUpperCase())).price)
    } catch (e) {
      setPriceError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Confirm
      title="Buy real shares"
      confirmLabel="Buy with real money"
      danger
      onClose={onClose}
      onConfirm={async () => {
        if (!symbol.trim()) throw new Error('Type the stock name, for example ITC.')
        if (!Number.isInteger(quantity) || quantity < 1) throw new Error('Choose at least 1 share.')
        await onSubmit(symbol.trim().toUpperCase(), quantity)
      }}
    >
      <p style={{ margin: '0 0 0.6rem' }}>
        This sends a <strong>real order to Zerodha</strong> with your own money, at the market price. Limit:{' '}
        {rupees(limits.max_order_inr)} per order, {rupees(limits.max_day_inr)} per day (used today:{' '}
        {rupees(limits.spent_today_inr)}).
      </p>
      <label style={{ display: 'block', marginBottom: '0.5rem' }}>
        <span className="tm-dim" style={{ fontSize: '0.75rem' }}>Stock</span>
        <input
          className="tm-input"
          style={{ width: '100%', marginTop: 4 }}
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          onBlur={() => symbol.trim() && lookUp()}
          placeholder="ITC"
        />
      </label>
      <label style={{ display: 'block' }}>
        <span className="tm-dim" style={{ fontSize: '0.75rem' }}>Number of shares</span>
        <input
          className="tm-input"
          style={{ width: '100%', marginTop: 4 }}
          type="number"
          inputMode="numeric"
          min="1"
          step="1"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
        />
      </label>
      {priceError && <p className="tm-neg" style={{ marginTop: '0.5rem' }}>{priceError}</p>}
      {cost != null && (
        <p style={{ marginTop: '0.5rem' }}>
          Price now {rupees(price!)} · about <strong>{rupees(cost)}</strong> of real money
        </p>
      )}
    </Confirm>
  )
}

function SellRealDialog({
  position,
  onSubmit,
  onClose,
}: {
  position: DetailedPosition
  onSubmit: (id: number, quantity: number) => Promise<unknown>
  onClose: () => void
}) {
  const [qty, setQty] = useState(String(position.quantity))
  const quantity = Number(qty)
  return (
    <Confirm
      title={`Sell ${position.symbol} for real`}
      confirmLabel="Sell with real money"
      danger
      onClose={onClose}
      onConfirm={async () => {
        if (!Number.isInteger(quantity) || quantity < 1 || quantity > position.quantity) {
          throw new Error(`Choose between 1 and ${position.quantity} shares.`)
        }
        await onSubmit(position.id, quantity)
      }}
    >
      <p style={{ margin: '0 0 0.6rem' }}>
        This sends a <strong>real sell order to Zerodha</strong> at the market price. You hold {position.quantity}{' '}
        shares; about {rupees(position.current_price * (quantity || 0))} at today’s price.
      </p>
      <label style={{ display: 'block' }}>
        <span className="tm-dim" style={{ fontSize: '0.75rem' }}>Shares to sell</span>
        <input
          className="tm-input"
          style={{ width: '100%', marginTop: 4 }}
          type="number"
          inputMode="numeric"
          min="1"
          max={position.quantity}
          step="1"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
        />
      </label>
    </Confirm>
  )
}
```

- [ ] **Step 4: Wire into `HoldingsTab`**

State and queries (after the existing `tracked` query):

```tsx
  const [buyReal, setBuyReal] = useState(false)
  const [sellReal, setSellReal] = useState<DetailedPosition | null>(null)
  const realStatus = useQuery({
    queryKey: ['realOrdersStatus'],
    queryFn: api.realOrdersStatus,
    retry: false,
    // While an order is waiting at Zerodha, look again every 15 s.
    refetchInterval: (q) => ((q.state.data?.waiting.length ?? 0) > 0 ? 15_000 : false),
  })
  const real = realStatus.data
  const waitingSymbols = useMemo(() => new Set((real?.waiting ?? []).map((w) => w.symbol)), [real])
  const afterRealOrder = (o: RealOrder) => {
    queryClient.invalidateQueries({ queryKey: ['realOrdersStatus'] })
    queryClient.invalidateQueries({ queryKey: ['realPositions'] })
    queryClient.invalidateQueries({ queryKey: ['realReport'] })
    setNotice(
      o.status === 'REJECTED'
        ? `Zerodha refused the ${o.side.toLowerCase()} of ${o.symbol}: ${o.message ?? 'no reason given'}.`
        : `Real ${o.side.toLowerCase()} of ${o.quantity} ${o.symbol} sent to Zerodha. It shows here once Zerodha confirms.`,
    )
  }
  const realBuy = useMutation({
    mutationFn: ({ symbol, quantity }: { symbol: string; quantity: number }) => api.realBuy(symbol, quantity),
    onSuccess: afterRealOrder,
  })
  const realSell = useMutation({
    mutationFn: ({ id, quantity }: { id: number; quantity: number }) => api.realSell(id, quantity),
    onSuccess: afterRealOrder,
  })
```

(add `RealOrder` to the types import, and `useEffect` to the react import). When a waiting order finishes, reload the holdings so the new or closed row appears:

```tsx
  const waitingCount = real?.waiting.length ?? 0
  const prevWaiting = useRef(waitingCount)
  useEffect(() => {
    if (prevWaiting.current > waitingCount) {
      queryClient.invalidateQueries({ queryKey: ['realPositions'] })
      queryClient.invalidateQueries({ queryKey: ['realReport'] })
    }
    prevWaiting.current = waitingCount
  }, [waitingCount, queryClient])
```

First card: change `sub` to

```tsx
        sub={
          real?.enabled
            ? 'Your real Zerodha shares. You can buy and sell them here for real, within your limits.'
            : 'Your real Zerodha shares, read by the bot each day. Nothing here buys or sells anything.'
        }
```

and change `action` to show both buttons:

```tsx
        action={
          <div className="tm-flex tm-wrap" style={{ gap: '0.4rem' }}>
            {real?.enabled && (
              <button className="tm-btn" onClick={() => setBuyReal(true)} disabled={realBuy.isPending}>
                Buy real shares
              </button>
            )}
            <button className="tm-btn" onClick={() => setAskImport(true)} disabled={importHoldings.isPending}>
              {untracked > 0 ? `Import ${untracked} new from Zerodha` : 'Import from Zerodha'}
            </button>
          </div>
        }
```

Status line, first thing inside that card (before `{notice && ...}`):

```tsx
        {real && (
          <div className="tm-dim" style={{ marginBottom: '0.6rem', fontSize: '0.8rem' }}>
            {real.enabled
              ? `Real orders: on · used today ${rupees(real.spent_today_inr)} of ${rupees(real.max_day_inr)} · ${real.market_text}`
              : 'Real orders: switched off'}
            {real.waiting.length > 0 &&
              ` · waiting at Zerodha: ${real.waiting.map((w) => `${w.side.toLowerCase()} ${w.quantity} ${w.symbol}`).join(', ')}`}
          </div>
        )}
```

Table row: replace the single "I sold this" cell with:

```tsx
                    <td>
                      <div className="tm-flex" style={{ gap: '0.3rem' }}>
                        {real?.enabled && (
                          <button
                            className="tm-btn"
                            onClick={() => setSellReal(p)}
                            disabled={realSell.isPending || waitingSymbols.has(p.symbol)}
                            title={waitingSymbols.has(p.symbol) ? 'An order is still waiting at Zerodha' : undefined}
                          >
                            Sell real
                          </button>
                        )}
                        <button className="tm-btn tm-btn-ghost" onClick={() => setSold(p)} disabled={manualClose.isPending}>
                          I sold this
                        </button>
                      </div>
                    </td>
```

Change the "Needs your attention" card `sub` to:

```tsx
          sub={
            real?.enabled
              ? 'The bot will not sell these for you. Use “Sell real” below if you decide to sell.'
              : 'The bot cannot sell these for you, because you bought them by hand.'
          }
```

Dialogs, next to the existing `{sold && ...}`:

```tsx
      {buyReal && real && (
        <BuyRealDialog
          limits={real}
          onClose={() => setBuyReal(false)}
          onSubmit={(symbol, quantity) => realBuy.mutateAsync({ symbol, quantity })}
        />
      )}
      {sellReal && (
        <SellRealDialog
          position={sellReal}
          onClose={() => setSellReal(null)}
          onSubmit={(id, quantity) => realSell.mutateAsync({ id, quantity })}
        />
      )}
```

- [ ] **Step 5: Type-check**

Run (from `frontend/` of the worktree): `npx tsc --noEmit -p .`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/trademind/pages/MyHoldings.tsx
git commit -m "My Holdings: Buy real / Sell real buttons with red confirms, limits and waiting orders shown"
```

(Do not commit the `node_modules` junction.)

---

### Task 6: Whole-branch verification (no push)

**Files:** none new.

- [ ] **Step 1: Lint only touched backend files**

```bash
cd backend
"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m ruff check src/swing_trade_ml/services/real_orders.py src/swing_trade_ml/services/execution.py src/swing_trade_ml/services/holdings_sync.py src/swing_trade_ml/brokers/kite.py src/swing_trade_ml/brokers/base.py src/swing_trade_ml/core/config.py src/swing_trade_ml/api/v1/endpoints/portfolio.py src/swing_trade_ml/schemas/__init__.py tests/test_real_holdings_*.py
```

Expected: no errors (fix any in the files listed only).

- [ ] **Step 2: Full backend suite**

Run: `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m pytest tests -q -x`
Expected: all PASS. Report the exact pass/fail counts.

- [ ] **Step 3: Confirm the switch is off everywhere**

```bash
git grep -n "ALLOW_REAL_HOLDINGS_ORDERS" -- ':!*test*'
```

Expected: only `config.py` (`= False`), `.env.example` (`=false`), `kite.py`, `real_orders.py`. No `true` anywhere.

- [ ] **Step 4: Confirm nothing was pushed**

```bash
git status -sb
git log --oneline origin/main..HEAD
```

Expected: branch `feature/real-holdings-orders`, no upstream. Stop here and hand over to the owner for review.
