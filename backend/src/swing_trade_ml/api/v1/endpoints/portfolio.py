"""Positions, trades, equity curve, and performance statistics."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.sql import Select

from swing_trade_ml.api.deps import (
    DbSession,
    PlanAccessDep,
    PrincipalDep,
    book_for,
    require_real_account,
)
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core import market_session
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import (
    ExitReason,
    OrderStatus,
    PositionStatus,
    SignalType,
    TradingMode,
)
from swing_trade_ml.core.strategy_policy import is_staged
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Order, Position, Signal, Strategy, Trade
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.ml.sector_map import get_sector_bucket, sector_display_name
from swing_trade_ml.schemas import (
    ClosePositionRequest,
    EquityPoint,
    ManualEntryRequest,
    ManualExitRequest,
    MessageResponse,
    PositionOut,
    RealBuyRequest,
    RealSellRequest,
    TesterPaperBuyRequest,
    TradeOut,
)
from swing_trade_ml.services import brain_position_score, held_read, real_orders, score_history
from swing_trade_ml.services import portfolio as portfolio_service
from swing_trade_ml.services.execution import (
    close_position,
    manual_close_position,
    manual_open_position,
    position_action,
)
from swing_trade_ml.services.exit_policy import exit_confidence_for
from swing_trade_ml.services.holdings_sync import (
    close_positions_no_longer_held,
)
from swing_trade_ml.services.holdings_sync import (
    held_symbols as _held_symbols,
)
from swing_trade_ml.services.plans import history_cutoff, strategy_visible
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME
from swing_trade_ml.strategies.tier import cap_tier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

#: Which of the two books a positions/trades query is asking about.
#: "bot" = everything the bot runs itself, in whichever mode it is in.
#: "real" = the My Holdings book (the `real_trading` advisory strategy).
#: "all" = both, the historical behaviour, kept for existing callers.
BookFilter = Literal["all", "bot", "real", "tester"]


def _position_sector(symbol: str) -> str:
    bucket = get_sector_bucket(symbol)
    return sector_display_name(bucket) if bucket else "Unclassified"


def _position_cap_tier(db: DbSession, position: Position) -> str | None:
    from swing_trade_ml.services.tester_paper import (
        TESTER_PAPER_STRATEGY_NAME,
        entry_signal_cap_tier,
    )

    if position.strategy and position.strategy.name == TESTER_PAPER_STRATEGY_NAME:
        return entry_signal_cap_tier(db, position.id)
    if position.strategy:
        return cap_tier(position.strategy.params.get("model_name") if position.strategy.params else None)
    return None


def _scope_to_book(stmt: Select[Any], strategy_id_col: Any, book: BookFilter) -> Select[Any]:
    """Narrow a Position/Trade query to one of the two books.

    Rows with no strategy at all belong to the bot's book: only the
    `real_trading` strategy marks a row as hand-bought.
    """
    if book == "all":
        return stmt
    if book == "real":
        return stmt.where(
            strategy_id_col.in_(
                select(Strategy.id).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
            )
        )
    if book == "tester":
        from swing_trade_ml.services.tester_paper import only_tester

        return stmt.where(only_tester(strategy_id_col))
    return stmt.where(portfolio_service.exclude_hand_books(strategy_id_col))


@router.get("/summary", response_model=dict)
def summary(
    db: DbSession,
    principal: PrincipalDep,
    mode: str | None = None,
    book: BookFilter = "all",
    all_time: bool = False,
) -> dict[str, Any]:
    """Headline performance figures — the dashboard's main panel.

    Pass `mode=paper` explicitly to review the paper track record after
    switching to live, and `book=bot` to leave the hand-bought My Holdings
    rows out so the figures describe the bot's own book alone.

    Paper figures cover the current trial by default; `all_time=true` returns
    the full record including trials that predate the running code. The reply
    names the boundary in `measured_since` either way.
    """
    book = book_for(principal, book)
    if book == "tester":
        from swing_trade_ml.services import tester_paper as tester_paper_service

        return tester_paper_service.performance_stats(db)
    return portfolio_service.performance_stats(
        db, mode, bot_book_only=book == "bot", all_time=all_time
    )


@router.get("/positions", response_model=list[PositionOut])
def list_positions(
    db: DbSession,
    principal: PrincipalDep,
    open_only: bool = True,
    limit: int = Query(100, le=1000),
    mode: str | None = None,
) -> list[Position]:
    """Pass `mode=live` to see real (advisory) positions instead of the
    broker's current default — e.g. paper-simulated ones."""
    stmt = (
        select(Position)
        .where(Position.mode == (mode or get_broker().mode))
        .order_by(Position.entry_at.desc())
        .limit(limit)
    )
    if open_only:
        stmt = stmt.where(Position.status == PositionStatus.OPEN)
    # No `book` parameter here: a tester gets the tester book, everyone else the visible books.
    stmt = _scope_to_book(
        stmt, Position.strategy_id, book_for(principal, "tester" if principal.is_tester else "all")
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/positions/detailed", response_model=list[dict])
def detailed_positions(
    db: DbSession,
    principal: PrincipalDep,
    mode: str | None = None,
    book: BookFilter = "all",
) -> list[dict[str, Any]]:
    """Open positions with symbols and computed P&L, ready to render.

    `book=bot` is the bot's own book in whichever mode it is running —
    simulated rows while TRADING_MODE is paper, real ones once it is live.
    `book=real` is the My Holdings book: shares bought by hand in Zerodha
    and tracked under the advisory `real_trading` strategy (see
    services/execution.py's manual_open_position and engine.run_all_active).

    The two are told apart by strategy rather than by mode, because the
    My Holdings book is stored as mode="live" whatever the bot is doing —
    so without this filter it would merge into the bot's own list the day
    TRADING_MODE flips to live. `mode` is ignored for `book=real`, which is
    live by construction.
    """
    book = book_for(principal, book)
    effective_mode = TradingMode.LIVE if book == "real" else (mode or get_broker().mode)
    stmt = (
        select(Position, Instrument.tradingsymbol, Instrument.name)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .where(Position.mode == effective_mode, Position.status == PositionStatus.OPEN)
        .order_by(Position.entry_at.desc())
    )
    stmt = _scope_to_book(stmt, Position.strategy_id, book)
    rows = db.execute(stmt).all()

    # The active model's own horizon — the "X days" a BUY signal was actually
    # judged against. Positions opened under an earlier model version are
    # shown against the CURRENT model's horizon as the best available
    # context, not a stored-forever value from whichever version bought it.
    active_model = get_active_model(db)
    horizon_days = active_model.prediction_horizon_days if active_model else None

    # A still-open position can only have an unactioned EXIT/SELL signal
    # against it under an "advisory" strategy — an "auto" one closes the
    # position the moment such a signal fires (see process_decision), so
    # this is otherwise always empty. Batched once rather than per-position:
    # position counts here are small, but there is no reason to N+1 anyway.
    latest_pending_exit: dict[tuple[int, int], object] = {}
    if rows:
        instrument_ids = {position.instrument_id for position, _, _ in rows}
        strategy_ids = {position.strategy_id for position, _, _ in rows}
        for inst_id, strat_id, generated_at in db.execute(
            select(Signal.instrument_id, Signal.strategy_id, Signal.generated_at).where(
                Signal.mode == effective_mode,
                Signal.instrument_id.in_(instrument_ids),
                Signal.strategy_id.in_(strategy_ids),
                Signal.signal_type.in_([SignalType.EXIT, SignalType.SELL]),
                Signal.was_executed.is_(False),
            )
        ):
            key = (inst_id, strat_id)
            if key not in latest_pending_exit or generated_at > latest_pending_exit[key]:
                latest_pending_exit[key] = generated_at

    # "Today's move" per position — current price vs. yesterday's close, or
    # vs. entry price for anything bought today (never held "yesterday", so
    # a previous close isn't the right reference — you can't have a day
    # change on a position that didn't exist yet). One batched query rather
    # than N+1: the most recent candle strictly before today, per instrument.
    today_start_ist = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_close_by_instrument: dict[int, float] = {}
    if rows:
        instrument_ids = {position.instrument_id for position, _, _ in rows}
        latest_ts_per_instrument = (
            select(Candle.instrument_id, func.max(Candle.ts).label("ts"))
            .where(
                Candle.instrument_id.in_(instrument_ids),
                Candle.interval == "day",
                Candle.ts < today_start_ist.astimezone(UTC),
            )
            .group_by(Candle.instrument_id)
            .subquery()
        )
        for inst_id, close in db.execute(
            select(Candle.instrument_id, Candle.close).join(
                latest_ts_per_instrument,
                (Candle.instrument_id == latest_ts_per_instrument.c.instrument_id)
                & (Candle.ts == latest_ts_per_instrument.c.ts),
            )
        ):
            prev_close_by_instrument[inst_id] = float(close)

    trails = score_history.trails_for(db, [position.id for position, _, _ in rows])

    result = []
    for position, symbol, name in rows:
        current = position.current_price or position.entry_price
        invested = position.entry_price * position.quantity

        entered_today = position.entry_at.astimezone(IST) >= today_start_ist
        day_reference = (
            position.entry_price if entered_today else prev_close_by_instrument.get(position.instrument_id)
        )
        day_pnl = (current - day_reference) * position.quantity if day_reference is not None else None

        pending_at = latest_pending_exit.get((position.instrument_id, position.strategy_id))
        exit_signal_pending = pending_at is not None and pending_at >= position.entry_at
        # Falls back to ml_swing's own default when the strategy doesn't
        # override it — same lookup _check_confidence_decay() uses.
        exit_confidence = exit_confidence_for(position.strategy)
        is_brain = is_staged(position.strategy)
        brain_band = None
        if is_brain:
            _, brain_band = brain_position_score.latest_for(trails.get(position.id, []), exit_confidence)
        action_code, action_label = position_action(
            position.entry_confidence,
            position.last_confidence,
            alert_sent=position.confidence_alert_sent_at is not None,
            holding_days=position.holding_days,
            horizon_days=horizon_days,
            exit_confidence=exit_confidence,
            exit_signal_pending=exit_signal_pending,
            # The stop/target/time-stop alert check_exits already sent to
            # Telegram. Without this the most urgent rows on the page — an
            # advisory holding past its stop that the bot may not sell —
            # rendered as an ordinary confidence read, so "Needs attention"
            # stayed empty while the alerts kept arriving.
            exit_alert_sent=position.advisory_alert_sent_at is not None,
        )

        result.append(
            {
                "id": position.id,
                "symbol": symbol,
                "name": name,
                "quantity": position.quantity,
                "entry_price": position.entry_price,
                "current_price": current,
                "invested": invested,
                "current_value": current * position.quantity,
                "unrealized_pnl": position.unrealized_pnl,
                "unrealized_pnl_pct": (current / position.entry_price - 1) if position.entry_price else 0.0,
                "day_pnl": day_pnl,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
                "entry_at": position.entry_at,
                "holding_days": position.holding_days,
                "strategy_id": position.strategy_id,
                "strategy_name": position.strategy.name if position.strategy else None,
                "cap_tier": _position_cap_tier(db, position),
                "sector": _position_sector(symbol),
                "entry_confidence": position.entry_confidence,
                "last_confidence": position.last_confidence,
                # Day-by-day score history (oldest first); days with no scan are absent.
                "score_trail": trails.get(position.id, []),
                # A brain position's last_confidence is just its entry number, so its
                # badge comes from the newest day on the trail (None when there is none).
                "score_band": brain_band if is_brain else (
                    score_history.score_band(position.last_confidence, exit_confidence)
                    if position.last_confidence is not None
                    else None
                ),
                "score_from_trail": is_brain,
                "horizon_days": horizon_days,
                "action_code": action_code,
                "action_label": action_label,
                # Day N of the trade, plus one word on what to do (SELL / SELL_PARTIALLY /
                # WATCH / HOLD) for the Testing and My Holdings tabs. Display only.
                **held_read.describe(
                    position,
                    action_code,
                    action_label,
                    (current / position.entry_price - 1) if position.entry_price else 0.0,
                ),
            }
        )
    return result


@router.get("/health", response_model=dict)
def holdings_health(
    db: DbSession,
    principal: PrincipalDep,
    book: Literal["bot", "tester", "real"] = "bot",
) -> dict[str, Any]:
    """Plain-English health check of ONE book's open holdings: too much in one
    stock or sector, a stop-loss further than agreed, a trade past its
    15-trading-day plan, a results day coming up. Read-only warnings — it never
    places an order or changes a stop, a size or a limit. There is no "all":
    paper and real money are never checked together. The real book is private
    to REAL_ACCOUNT_USERS, through the same `book_for` guard as every read here."""
    from swing_trade_ml.services import holdings_health as health_service

    return health_service.health_for_book(db, book_for(principal, book))


def _load_kite_holdings(db: DbSession) -> list[dict[str, Any]]:
    """Authenticate and pull raw Kite holdings, turning a rejected/expired
    token or any other Kite-side failure into a clean 400 instead of letting
    a bare KiteException reach the generic handler as an opaque
    "Internal server error" — which is exactly what happened here: the
    account's Kite session expired, reauth_and_retry's auto-relogin has no
    working credentials (TOTP auto-login is unavailable on this account), so
    the raw kiteconnect exception was reaching the client unexplained.
    """
    from kiteconnect.exceptions import KiteException

    from swing_trade_ml.brokers.kite import kite_broker

    kite_broker.load_session(db)
    if not kite_broker.is_authenticated:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No active Kite session — log in to see real holdings.",
        )

    try:
        return kite_broker.get_holdings(db)
    except KiteException as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Zerodha rejected the request — the Kite session has likely expired. "
            f"Log in to Kite again and retry. ({exc})",
        ) from exc


def _held_quantity(h: dict[str, Any]) -> int:
    """Shares actually owned, including ones bought in the last day or two
    that haven't settled into demat yet.

    Kite's `quantity` field is the *settled* (T+1) quantity only — a stock
    bought today or yesterday sits entirely in `t1_quantity` and reads as
    `quantity: 0` until settlement, so filtering on `quantity != 0` silently
    dropped every recent buy from the holdings list, the import, and every
    P&L total built from them.
    """
    return h["quantity"] + h.get("t1_quantity", 0)


@router.get("/holdings", response_model=list[dict], dependencies=[Depends(require_real_account)])
def holdings(db: DbSession) -> list[dict[str, Any]]:
    """Real Zerodha equity holdings — actual shares sitting in the connected
    account, as opposed to the Position rows below (which track the bot's
    own paper-mode trades and know nothing about anything bought manually).
    Pure pass-through to Kite; nothing here is generated or predicted.
    """
    result = []
    for h in _load_kite_holdings(db):
        qty = _held_quantity(h)
        if qty == 0:
            continue
        result.append(
            {
                "symbol": h["tradingsymbol"],
                "exchange": h["exchange"],
                "quantity": qty,
                "average_price": h["average_price"],
                "last_price": h["last_price"],
                "close_price": h.get("close_price"),
                "pnl": (h["last_price"] - h["average_price"]) * qty,
                "day_change": h.get("day_change"),
                "day_change_percentage": h.get("day_change_percentage"),
            }
        )
    return result



def _get_or_create_real_trading_strategy(db: DbSession) -> Strategy:
    """The advisory, live-mode strategy that real Zerodha holdings are tracked
    under.

    Created on demand because requiring the user to hand-build it first meant
    import-holdings failed with a bare 404 on a fresh install, and the
    frontend already hard-codes this name (lib/tiers.ts, Positions.tsx).

    Advisory is not a detail: it is what guarantees this strategy can never
    place or close a broker order. It observes real positions and reports on
    them; every actual trade stays the operator's own.
    """
    strategy = db.execute(
        select(Strategy).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
    ).scalar_one_or_none()
    if strategy is not None:
        return strategy

    strategy = Strategy(
        name=REAL_TRADING_STRATEGY_NAME,
        strategy_type="ml_swing",
        description="Real Zerodha holdings, tracked with ML confidence. Advisory only.",
        params={},
        is_active=True,
        mode="live",
        execution_mode="advisory",
    )
    db.add(strategy)
    db.flush()
    return strategy


def _derive_stop_target(
    db: DbSession, instrument: Instrument, price: float
) -> tuple[float | None, float | None, str]:
    """Stop and target for a holding bought outside this app.

    Anchored to *today's* price, not the original purchase price, and this is
    the whole point: a stock bought at 100 and now trading at 150 has a stop
    derived from 100 sitting far below the market, protecting nothing. Today's
    price protects the gain that actually exists.

    Uses the same 2x/4x ATR multiples and the same clamp as ml_swing, so an
    imported holding and a bot-entered position are judged on one convention.
    """
    from swing_trade_ml.ml.dataset import load_candles
    from swing_trade_ml.ml.features import atr

    if price <= 0:
        return None, None, "no price"

    fallback_stop = round(price * (1 - settings.DEFAULT_STOP_LOSS_PCT), 2)
    fallback_target = round(price * (1 + settings.DEFAULT_TAKE_PROFIT_PCT), 2)

    df = load_candles(db, instrument.id, "day", limit=60)
    if df is None or len(df) < 20:
        return fallback_stop, fallback_target, "fixed pct (not enough candles for ATR)"

    try:
        atr_value = float(atr(df["high"], df["low"], df["close"], 14).iloc[-1])
    except Exception:  # noqa: BLE001
        return fallback_stop, fallback_target, "fixed pct (ATR failed)"

    if not atr_value or atr_value <= 0:
        return fallback_stop, fallback_target, "fixed pct (ATR unavailable)"

    stop = price - 2.0 * atr_value
    target = price + 4.0 * atr_value
    # Same clamp ml_swing applies: never risk more per trade than the risk
    # model allows, so tighten rather than skip.
    stop = max(stop, price * (1 - settings.DEFAULT_STOP_LOSS_PCT * 2))
    return round(stop, 2), round(target, 2), "2x/4x ATR from current price"


@router.post(
    "/positions/import-holdings", response_model=list[dict], dependencies=[Depends(require_real_account)]
)
def import_real_holdings(db: DbSession, strategy_id: int | None = None) -> list[dict[str, Any]]:
    """Pull real Zerodha holdings and record each one as a tracked position
    under the given (advisory, live-mode) strategy — see
    services/execution.py's manual_open_position — so it starts getting the
    same daily confidence/stop-loss tracking paper positions already get,
    instead of sitting as a dumb price/quantity row.

    Safe to call repeatedly: holdings already tracked under this strategy
    (an OPEN position on the same instrument) are skipped, not duplicated.
    """
    if strategy_id is None:
        strategy = _get_or_create_real_trading_strategy(db)
    else:
        strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    if strategy.execution_mode != "advisory":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only an advisory strategy can import real holdings — "
            "an auto strategy would treat them as its own trades to manage.",
        )

    kite_holdings = _load_kite_holdings(db)

    results: list[dict[str, Any]] = []

    # Close what is no longer owned before adding anything — importing used to
    # only ever add, so a stock sold by hand stayed OPEN here forever and kept
    # alerting. See services/holdings_sync.py.
    results.extend(close_positions_no_longer_held(db, strategy, _held_symbols(kite_holdings)))

    already_tracked = {
        p.instrument_id
        for p in db.execute(
            select(Position).where(
                Position.strategy_id == strategy.id, Position.status == PositionStatus.OPEN
            )
        ).scalars()
    }
    # A real app order still waiting on a stock (e.g. a buy that filled after
    # 15:29 and is reconciled next morning) already shows in Kite holdings.
    # Importing it would track N shares, then reconcile adds the fill: 2N.
    order_waiting = set(
        db.execute(
            select(Order.instrument_id).where(
                Order.strategy_id == strategy.id,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
            )
        ).scalars()
    )
    for h in kite_holdings:
        held_quantity = _held_quantity(h)
        if held_quantity == 0:
            continue
        instrument = db.execute(
            select(Instrument).where(
                Instrument.exchange == h["exchange"], Instrument.tradingsymbol == h["tradingsymbol"]
            )
        ).scalar_one_or_none()

        # A holding bought on BSE has exchange="BSE", but sync_instruments only
        # ingests NSE, so the exact match finds nothing and the holding was
        # silently skipped. It is the same company: fall back to the NSE
        # listing, which is also the only one with candle history, a sector
        # mapping and a trained model behind it. The two venues' prices track
        # within a few basis points, which is well inside the ATR the stop is
        # derived from.
        exchange_note = None
        if instrument is None:
            instrument = db.execute(
                select(Instrument).where(
                    Instrument.exchange == "NSE",
                    Instrument.tradingsymbol == h["tradingsymbol"],
                    Instrument.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if instrument is not None:
                exchange_note = f"held on {h['exchange']}, tracked against NSE prices"

        if instrument is None:
            results.append(
                {
                    "symbol": h["tradingsymbol"],
                    "status": "skipped",
                    "reason": (
                        f"no instrument row for {h['tradingsymbol']} on "
                        f"{h['exchange']} or NSE — run sync-instruments"
                    ),
                }
            )
            continue
        if instrument.id in already_tracked:
            results.append({"symbol": h["tradingsymbol"], "status": "already_tracked"})
            continue
        if instrument.id in order_waiting:
            results.append(
                {
                    "symbol": h["tradingsymbol"],
                    "status": "order_waiting",
                    "reason": "a real order for this stock is still waiting at Zerodha",
                }
            )
            continue

        # Anchor risk levels to what the stock trades at now, not to what it
        # was bought at — see _derive_stop_target. Without these the position
        # has no stop, no target, trail_stop no-ops, and the only exit it can
        # ever reach is the 60-day time stop.
        current_price = float(h.get("last_price") or 0) or float(h["average_price"])
        stop_loss, take_profit, basis = _derive_stop_target(db, instrument, current_price)

        manual_open_position(
            db,
            strategy,
            instrument,
            held_quantity,
            h["average_price"],
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        already_tracked.add(instrument.id)
        results.append(
            {
                "symbol": h["tradingsymbol"],
                "status": "imported",
                "quantity": held_quantity,
                "entry_price": h["average_price"],
                "current_price": current_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "levels_basis": basis,
                **({"note": exchange_note} if exchange_note else {}),
            }
        )

    # Put every tracked symbol on the strategy's own universe.
    #
    # Without this the import looks like it worked and then does nothing: an
    # empty `symbols` means "scan the watchlist", and a stock bought by hand
    # is generally not watchlisted. The strategy would evaluate none of them,
    # so entry_confidence/last_confidence stay NULL, the model's read never
    # updates, and no EXIT signal or confidence-decay alert can ever fire —
    # the whole reason for tracking a real holding here.
    tracked_symbols = sorted(
        {
            i.tradingsymbol
            for i in db.execute(
                select(Instrument)
                .join(Position, Position.instrument_id == Instrument.id)
                .where(
                    Position.strategy_id == strategy.id,
                    Position.status == PositionStatus.OPEN,
                )
            ).scalars()
        }
    )
    if tracked_symbols != sorted(strategy.symbols or []):
        strategy.symbols = tracked_symbols  # new list object, so the JSON column is dirtied
        db.flush()

    return results


@router.post("/tester/buy", status_code=status.HTTP_201_CREATED)
def tester_paper_buy(payload: TesterPaperBuyRequest, db: DbSession) -> dict[str, Any]:
    """Manual paper buy for the tester book — never touches live Kite or the bot book."""
    from swing_trade_ml.services import tester_paper as tester_paper_service

    try:
        position = tester_paper_service.paper_buy(
            db,
            payload.symbol.strip(),
            payload.quantity,
            payload.cap_tier,
            payload.exchange,
        )
    except tester_paper_service.PaperTesterDisabled as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except tester_paper_service.PaperTesterNotPaperMode as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    instrument = db.get(Instrument, position.instrument_id)
    return {
        "position_id": position.id,
        "symbol": instrument.tradingsymbol if instrument else payload.symbol.upper(),
        "quantity": position.quantity,
        "entry_price": position.entry_price,
        "cap_tier": payload.cap_tier,
    }


@router.post("/positions/manual", response_model=PositionOut, status_code=status.HTTP_201_CREATED)
def create_manual_position(payload: ManualEntryRequest, db: DbSession) -> Position:
    """Record a position filled outside the app — the counterpart to
    advisory-mode recommendations, which never place a real order."""
    strategy = db.get(Strategy, payload.strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    instrument = db.get(Instrument, payload.instrument_id)
    if instrument is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")

    signal = None
    if payload.signal_id is not None:
        signal = db.get(Signal, payload.signal_id)
        if signal is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Signal not found")

    return manual_open_position(
        db,
        strategy,
        instrument,
        payload.quantity,
        payload.entry_price,
        payload.stop_loss,
        payload.take_profit,
        payload.brokerage,
        payload.taxes,
        signal,
    )


@router.post("/positions/{position_id}/manual-close", response_model=TradeOut)
def close_manual_position(
    position_id: int, payload: ManualExitRequest, db: DbSession, principal: PrincipalDep
) -> Trade:
    """Record the exit fill for a position closed outside the app."""
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    _refuse_other_peoples_real_position(principal, position)
    if position.status != PositionStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Position is already closed")

    try:
        reason = ExitReason(payload.exit_reason)
    except ValueError:
        reason = ExitReason.MANUAL

    return manual_close_position(
        db, position, payload.exit_price, reason, payload.brokerage, payload.taxes
    )


# ---------------------------------------- real orders from My Holdings --
# The owner's own hand-placed Zerodha orders while the bot stays on paper.
# Every check lives in services/real_orders.py; these only translate.

_OWNER = [Depends(require_real_account)]  # the real Zerodha account: named owners only
_SEND_FAILED = "The order could not be sent to Zerodha. Check the Kite app before trying again."


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


def _refuse_other_peoples_real_position(principal: Any, position: Position) -> None:
    """A My Holdings row (hand-bought, real money) may only be closed by the
    named owner. Same answer as a missing row, so its existence isn't revealed."""
    is_real = position.mode == TradingMode.LIVE or (
        position.strategy is not None and position.strategy.name == REAL_TRADING_STRATEGY_NAME
    )
    if is_real and not principal.can_see_real_account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")


def _refuse_tester_outside_tester_book(principal: Any, position: Position, db: DbSession) -> None:
    """A tester may only close positions in the manual paper-testing book."""
    if principal.is_owner or not principal.is_tester:
        return
    from swing_trade_ml.services.tester_paper import get_or_create_strategy

    if position.strategy_id != get_or_create_strategy(db).id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only close positions in your testing book.")


def _lock_strategy(db: DbSession, strategy_id: int) -> None:
    # Serialise double-clicks: a second request waits here until the first has
    # committed, so it sees the first order in the waiting/daily-limit checks.
    db.execute(select(Strategy).where(Strategy.id == strategy_id).with_for_update()).scalar_one()


@router.get("/real/orders-status", dependencies=_OWNER)
def real_orders_status(db: DbSession) -> dict[str, Any]:
    strategy = db.execute(
        select(Strategy).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
    ).scalar_one_or_none()
    return real_orders.status(db, strategy)


@router.get("/real/account", dependencies=_OWNER)
def real_account(db: DbSession) -> dict[str, Any]:
    """The whole Zerodha account at a glance, like Zerodha's own dashboard:
    cash still available, what every held share cost and is worth, today's
    move, and the total. Live from Zerodha and read-only — every share in the
    account counts, tracked in My Holdings or not."""
    from kiteconnect.exceptions import KiteException

    from swing_trade_ml.brokers.kite import kite_broker

    held = [(h, _held_quantity(h)) for h in _load_kite_holdings(db)]
    held = [(h, qty) for h, qty in held if qty > 0]
    try:
        cash = kite_broker.get_margins(db).available_cash
    except KiteException as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Zerodha did not return your cash balance. Log in to Kite again and retry. ({exc})",
        ) from exc

    invested = sum(h["average_price"] * qty for h, qty in held)
    current = sum(h["last_price"] * qty for h, qty in held)
    # Kite's day_change is per share: today's price minus yesterday's close.
    day_pnl = sum((h.get("day_change") or 0.0) * qty for h, qty in held)
    return {
        "cash_available": cash,
        "invested": invested,
        "current_value": current,
        "total_pnl": current - invested,
        "total_pnl_pct": (current - invested) / invested if invested else None,
        "day_pnl": day_pnl,
        "account_value": cash + current,
        "stocks": len(held),
    }


@router.get("/real/quote", dependencies=_OWNER)
def real_quote(db: DbSession, symbol: str, exchange: str = "NSE") -> dict[str, Any]:
    instrument = _instrument_or_404(db, symbol, exchange)
    try:
        price = real_orders.quote(db, instrument)
    except real_orders.RealOrderRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        logger.exception("Real-holdings quote failed for %s", instrument.tradingsymbol)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Could not get a live price from Zerodha just now."
        ) from exc
    return {"symbol": instrument.tradingsymbol, "exchange": instrument.exchange, "price": price}


@router.post("/real/buy", status_code=status.HTTP_201_CREATED, dependencies=_OWNER)
def real_buy(payload: RealBuyRequest, db: DbSession) -> dict[str, Any]:
    instrument = _instrument_or_404(db, payload.symbol, payload.exchange)
    strategy = _get_or_create_real_trading_strategy(db)
    _lock_strategy(db, strategy.id)
    try:
        order = real_orders.buy(db, strategy, instrument, payload.quantity)
    except real_orders.RealOrderRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        logger.exception("Real-holdings buy failed for %s", instrument.tradingsymbol)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _SEND_FAILED) from exc
    return _real_order_out(order, instrument)


@router.post("/real/positions/{position_id}/sell", status_code=status.HTTP_201_CREATED, dependencies=_OWNER)
def real_sell(position_id: int, payload: RealSellRequest, db: DbSession) -> dict[str, Any]:
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holding not found.")
    if position.strategy_id is not None:
        _lock_strategy(db, position.strategy_id)
    try:
        order = real_orders.sell(db, position, payload.quantity)
    except real_orders.RealOrderRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        logger.exception("Real-holdings sell failed for position %s", position_id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _SEND_FAILED) from exc
    return _real_order_out(order, db.get(Instrument, position.instrument_id))


@router.post("/positions/{position_id}/close", response_model=MessageResponse)
def close(
    position_id: int, payload: ClosePositionRequest, db: DbSession, principal: PrincipalDep
) -> MessageResponse:
    """Manually exit a position at the current market price."""
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    _refuse_other_peoples_real_position(principal, position)
    _refuse_tester_outside_tester_book(principal, position, db)
    if position.status != PositionStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Position is already closed")
    if position.mode == TradingMode.LIVE:
        # A real-money market order outside the session would be refused by
        # Zerodha; say so plainly instead (one market clock, design step 2).
        session = market_session.session()
        if not market_session.is_open(session.now):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The market is closed right now, so a real-money sale cannot be sent. "
                f"It opens {market_session.when(session.next_open)}.",
            )

    try:
        reason = ExitReason(payload.reason)
    except ValueError:
        reason = ExitReason.MANUAL

    try:
        trade = close_position(db, position, None, reason, payload.note)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if trade is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Exit order did not fill — check order history"
        )
    return MessageResponse(
        message=f"Closed position {position_id}",
        detail=(
            f"Exited at ₹{trade.exit_price:,.2f} — "
            f"Net P&L ₹{trade.net_pnl:,.2f} ({trade.return_pct:+.2%})"
        ),
    )


EXIT_REASON_LABELS = {
    ExitReason.TARGET_HIT: "Target reached",
    ExitReason.STOP_LOSS_HIT: "Stop-loss hit",
    ExitReason.SIGNAL_EXIT: "Model changed its mind",
    ExitReason.MANUAL: "Closed manually",
    ExitReason.RISK_LIMIT: "Risk limit",
    # No longer always 60 days — the time limit is set per strategy now.
    ExitReason.TIME_STOP: "Held too long (time limit)",
    ExitReason.SCALE_OUT: "Sold part at first target",
}


# Checkpoints for "was this exit actually right?" — a handful of trading days
# (not calendar days, since candles only exist for trading days) after we sold.
# 5 ≈ "next few days", 15 ≈ "next few weeks", matching how the user framed it.
POST_EXIT_CHECKPOINTS = {"5d": 5, "15d": 15}


def _post_exit_moves(db: DbSession, trades: list[Trade]) -> dict[int, dict[str, float | None]]:
    """For each closed trade, how the stock moved after we sold it.

    Lets you tell a validated exit (price kept falling) from a premature one
    (price kept rising after we sold — profit left on the table), the same
    question raised earlier about ITC/DIVISLAB but now answerable for every
    trade without asking me to check.
    """
    if not trades:
        return {}
    instrument_ids = {t.instrument_id for t in trades}
    earliest_exit = min(t.exit_at for t in trades)

    rows = db.execute(
        select(Candle.instrument_id, Candle.ts, Candle.close)
        .where(
            Candle.interval == "day",
            Candle.instrument_id.in_(instrument_ids),
            Candle.ts > earliest_exit,
        )
        .order_by(Candle.instrument_id, Candle.ts)
    ).all()
    candles_by_instrument: dict[int, list[tuple[datetime, float]]] = {}
    for instrument_id, ts, close in rows:
        candles_by_instrument.setdefault(instrument_id, []).append((ts, close))

    moves: dict[int, dict[str, float | None]] = {}
    for trade in trades:
        future = [c for c in candles_by_instrument.get(trade.instrument_id, []) if c[0] > trade.exit_at]
        entry: dict[str, float | None] = {}
        for label, n in POST_EXIT_CHECKPOINTS.items():
            if len(future) >= n and trade.exit_price:
                price = future[n - 1][1]
                entry[f"price_{label}_after_exit"] = price
                entry[f"return_{label}_after_exit"] = (price - trade.exit_price) / trade.exit_price
            else:
                entry[f"price_{label}_after_exit"] = None
                entry[f"return_{label}_after_exit"] = None
        moves[trade.id] = entry
    return moves


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    db: DbSession,
    access: PlanAccessDep,
    principal: PrincipalDep,
    wins_only: bool | None = None,
    limit: int = Query(100, le=1000),
    book: BookFilter = "all",
    all_time: bool = False,
) -> list[dict[str, Any]]:
    """Closed trades in the current mode. `book` splits the bot's own record
    from the My Holdings one exactly as /positions/detailed does — without
    it, a live bot's trade list would also contain every sale recorded by
    hand against a real Zerodha holding.

    Scoped to the current paper trial by default, so the list agrees with the
    counts /summary reports rather than showing trades those counts exclude.
    `all_time=true` returns every trade ever closed."""
    book = book_for(principal, book)
    mode = TradingMode.LIVE if book == "real" else get_broker().mode
    since = None if (all_time or book == "tester") else portfolio_service.trial_start(mode)
    stmt = (
        select(Trade, Position, Strategy)
        .outerjoin(Position, Position.id == Trade.position_id)
        .outerjoin(Strategy, Strategy.id == Trade.strategy_id)
        .where(Trade.mode == mode)
        .order_by(Trade.exit_at.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(Trade.exit_at >= since)
    cutoff = history_cutoff(access)
    if cutoff is not None:
        stmt = stmt.where(Trade.exit_at >= cutoff)
    stmt = _scope_to_book(stmt, Trade.strategy_id, book)
    if wins_only is not None:
        stmt = stmt.where(Trade.is_win.is_(wins_only))

    triples = [row for row in db.execute(stmt).all() if strategy_visible(row[2], access)]
    post_exit = _post_exit_moves(db, [trade for trade, _, _ in triples])

    result = []
    for trade, position, strategy in triples:
        result.append(
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "mode": trade.mode,
                "quantity": trade.quantity,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "entry_at": trade.entry_at,
                "exit_at": trade.exit_at,
                "holding_days": trade.holding_days,
                "gross_pnl": trade.gross_pnl,
                "charges": trade.charges,
                "net_pnl": trade.net_pnl,
                "return_pct": trade.return_pct,
                "exit_reason": trade.exit_reason,
                "exit_reason_label": EXIT_REASON_LABELS.get(trade.exit_reason, trade.exit_reason),
                "is_win": trade.is_win,
                "stop_loss": position.stop_loss if position else None,
                "take_profit": position.take_profit if position else None,
                "entry_confidence": position.entry_confidence if position else None,
                "last_confidence": position.last_confidence if position else None,
                "strategy_name": strategy.name if strategy else None,
                "cap_tier": (
                    cap_tier(strategy.params.get("model_name") if strategy.params else None)
                    if strategy
                    else None
                ),
                **post_exit.get(trade.id, {}),
            }
        )
    return result


@router.get("/equity-curve", response_model=list[EquityPoint])
def equity_curve(
    db: DbSession,
    days: int = Query(180, le=1825), mode: str | None = None,
    all_time: bool = False,
) -> list[dict[str, Any]]:
    """The equity chart, trimmed to the current paper trial by default so it
    starts where the reported return does. `all_time=true` shows the account's
    whole history."""
    return portfolio_service.equity_curve(db, mode, days, all_time=all_time)


@router.post("/snapshot", response_model=MessageResponse)
def snapshot(db: DbSession) -> MessageResponse:
    """Mark to market and record an equity-curve point immediately."""
    portfolio_service.mark_to_market(db)
    snap = portfolio_service.take_snapshot(db)
    return MessageResponse(
        message="Snapshot recorded",
        detail=f"Total value ₹{snap.total_value:,.2f}, drawdown {snap.drawdown_pct:.2%}",
    )
