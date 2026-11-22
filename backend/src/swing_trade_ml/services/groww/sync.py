"""Groww holdings sync: fetch, check completeness, match stocks, record the result.

Display/tracking only. This step records what Groww returned, then (complete syncs only) hands
it to `apply.apply_sync` to update the Groww Tracker. It never places or changes any order.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.base import utcnow
from swing_trade_ml.db.models.groww import (
    MATCH_CONFIRMED,
    MATCH_NEEDS,
    MATCH_SUGGESTED,
    SYNC_COMPLETE,
    SYNC_EMPTY,
    SYNC_FAILED,
    SYNC_PARTIAL,
    GrowwHolding,
    GrowwSync,
    StockAlias,
)
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.groww import apply as groww_apply
from swing_trade_ml.services.groww import client as groww_client
from swing_trade_ml.services.groww.client import GrowwAuthError, GrowwUnavailable

logger = logging.getLogger(__name__)

PROVIDER = "groww"
LOCK_KEY = "groww:sync_lock"
LOCK_SECONDS = 60
_SUFFIX = re.compile(r"-(EQ|BE|BZ|BL|SM|ST|IL)$")
_KNOWN = ("isin", "trading_symbol", "quantity", "average_price")


class SyncAlreadyRunning(Exception):  # noqa: N818 - name fixed by the task interface
    """Another Groww sync holds the lock."""


def owner_user_id(db: Session) -> int | None:
    """Whose tracker a sync updates when no person is behind the call (the 15:35 job, the API key):
    the first name in REAL_ACCOUNT_USERS, if that account exists and has the owner role (the same
    rule as can_see_real_account / idea_report.groww_user_ids). Every Groww write targets this one
    account, so a manual Refresh and the 15:35 job always update the same tracker."""
    from sqlalchemy import func

    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.session import User

    names = [n.strip().lower() for n in settings.REAL_ACCOUNT_USERS.split(",") if n.strip()]
    if not names:
        return None
    return db.scalar(
        select(User.id).where(func.lower(User.username) == names[0], User.role == "owner").limit(1)
    )


def fetch_holdings() -> list[dict]:
    return groww_client.fetch_holdings()


def _get_redis():
    return groww_client._get_redis()


def clean_symbol(raw: str) -> str:
    return _SUFFIX.sub("", raw.strip().upper())


def _num(value: Any) -> float | None:
    """A finite number, else None: NaN and infinity are malformed, never stored or applied."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _clean_extra(value: Any) -> Any:
    """Groww's own extra fields as stored JSON: a non-finite number becomes null (JSON cannot hold it)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean_extra(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_extra(v) for v in value]
    return value


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _row_ok(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and _text(row.get("isin")) is not None
        and _text(row.get("trading_symbol")) is not None
        and _num(row.get("quantity")) is not None
        and _num(row.get("average_price")) is not None
    )


def classify(rows: list[dict]) -> str:
    if not rows:
        return SYNC_EMPTY
    return SYNC_COMPLETE if all(_row_ok(r) for r in rows) else SYNC_PARTIAL


def match_rows(db: Session, rows: list[dict]) -> list[tuple[dict, int | None, str]]:
    out: list[tuple[dict, int | None, str]] = []
    for row in rows:
        isin = _text(row.get("isin"))
        symbol = _text(row.get("trading_symbol"))
        alias = None
        if isin:
            alias = db.scalar(
                select(StockAlias).where(StockAlias.provider == PROVIDER, StockAlias.external_id == isin)
            )
        if alias is not None and alias.instrument_id is not None:
            out.append((row, alias.instrument_id, MATCH_CONFIRMED))
            continue
        if symbol:
            ids = list(
                db.scalars(
                    select(Instrument.id).where(
                        Instrument.exchange == "NSE", Instrument.tradingsymbol == clean_symbol(symbol)
                    )
                )
            )
            if len(ids) == 1:
                out.append((row, ids[0], MATCH_SUGGESTED))
                continue
        out.append((row, None, MATCH_NEEDS))
    return out


_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)


def _acquire_lock() -> tuple[Any, str] | None:
    """Returns (redis client, our token) when we hold the lock, else None (Redis down: no lock)."""
    token = uuid.uuid4().hex
    try:
        redis_client = _get_redis()
        got = redis_client.set(LOCK_KEY, token, nx=True, ex=LOCK_SECONDS)
    except Exception:  # noqa: BLE001 - a down Redis must not block syncs
        logger.warning("groww sync lock unavailable; syncing without it")
        return None
    if not got:
        raise SyncAlreadyRunning
    return redis_client, token


def _release_lock(lock: tuple[Any, str] | None) -> None:
    """Delete the lock only if it is still ours (it may have expired and been re-taken)."""
    if lock is None:
        return
    redis_client, token = lock
    try:
        redis_client.eval(_RELEASE_LUA, 1, LOCK_KEY, token)
    except Exception:  # noqa: BLE001
        logger.warning("groww sync lock could not be released")


def _store_rows(db: Session, sync: GrowwSync, rows: list[Any]) -> None:
    dict_rows = [r if isinstance(r, dict) else {} for r in rows]
    for row, instrument_id, state in match_rows(db, dict_rows):
        extra = {k: _clean_extra(v) for k, v in row.items() if k not in _KNOWN}
        db.add(
            GrowwHolding(
                sync_id=sync.id,
                isin=_text(row.get("isin")) or "",
                trading_symbol=_text(row.get("trading_symbol")),
                quantity=_num(row.get("quantity")),
                average_price=_num(row.get("average_price")),
                extra=extra or None,
                instrument_id=instrument_id,
                match_state=state,
            )
        )


def _apply_safely(db: Session, sync: GrowwSync, user_id: int) -> None:
    """Apply a stored complete sync. A failure undoes the apply only; the stored sync stays."""
    try:
        with db.begin_nested():
            groww_apply.apply_sync(db, sync, user_id=user_id)
    except Exception as exc:  # noqa: BLE001 - never raised; no exception text (may hold data)
        logger.error("groww sync %s could not be applied to the tracker (%s)", sync.id, type(exc).__name__)
        return
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("groww sync %s apply could not be saved (%s)", sync.id, type(exc).__name__)
        db.rollback()


def run_sync(db: Session, *, user_id: int, trigger: str) -> GrowwSync:
    """Fetch, classify, match and record one sync. Never raises except SyncAlreadyRunning."""
    lock = _acquire_lock()
    try:
        started = utcnow()
        try:
            rows = fetch_holdings()
            error = None if isinstance(rows, list) else "unavailable"
        except GrowwAuthError:
            rows, error = None, "auth"
        except GrowwUnavailable:
            rows, error = None, "unavailable"
        except Exception as exc:  # noqa: BLE001 - recorded, never raised to the caller
            # The kind only: an error message can hold holdings data or a credential.
            logger.error("groww sync failed unexpectedly (%s)", type(exc).__name__)
            rows, error = None, "unexpected"
        if error is None:
            try:
                # Savepoint: a store failure undoes only this sync's rows, then a failed sync is logged.
                with db.begin_nested():
                    sync = GrowwSync(started_at=started, trigger=trigger, status=classify(rows))
                    sync.holdings_count = len(rows)
                    db.add(sync)
                    db.flush()
                    _store_rows(db, sync, rows)
                    sync.finished_at = utcnow()
            except Exception as exc:  # noqa: BLE001
                logger.error("groww sync could not be stored (%s)", type(exc).__name__)
                error = "store"
            else:
                try:
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.error("groww sync could not be saved (%s)", type(exc).__name__)
                    db.rollback()
                    error = "store"
                else:
                    if sync.status == SYNC_COMPLETE:
                        _apply_safely(db, sync, user_id)
                    return sync
        sync = GrowwSync(
            started_at=started, finished_at=utcnow(), trigger=trigger, status=SYNC_FAILED, error_code=error
        )
        db.add(sync)
        db.commit()
        return sync
    finally:
        _release_lock(lock)
