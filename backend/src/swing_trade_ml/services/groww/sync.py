"""Groww holdings sync: fetch, check completeness, match stocks, record the result.

Display/tracking only. This step records what Groww returned; it does not touch the tracker
(`apply_sync` does, in a later step) and never places or changes any order.
"""

from __future__ import annotations

import logging
import re
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


def fetch_holdings() -> list[dict]:
    return groww_client.fetch_holdings()


def _get_redis():
    return groww_client._get_redis()


def clean_symbol(raw: str) -> str:
    return _SUFFIX.sub("", raw.strip().upper())


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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


def _acquire_lock():
    """Returns the Redis client holding the lock, or None. A down Redis never blocks a sync."""
    try:
        redis_client = _get_redis()
        got = redis_client.set(LOCK_KEY, "1", nx=True, ex=LOCK_SECONDS)
    except Exception:  # noqa: BLE001 - a down Redis must not block syncs
        logger.warning("groww sync lock unavailable; syncing without it")
        return None
    if not got:
        raise SyncAlreadyRunning
    return redis_client


def _release_lock(redis_client) -> None:
    if redis_client is None:
        return
    try:
        redis_client.delete(LOCK_KEY)
    except Exception:  # noqa: BLE001
        logger.warning("groww sync lock could not be released")


def _store_rows(db: Session, sync: GrowwSync, rows: list[Any]) -> None:
    dict_rows = [r if isinstance(r, dict) else {} for r in rows]
    for row, instrument_id, state in match_rows(db, dict_rows):
        extra = {k: v for k, v in row.items() if k not in _KNOWN}
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


def run_sync(db: Session, *, user_id: int, trigger: str) -> GrowwSync:
    """Fetch, classify, match and record one sync. Never raises except SyncAlreadyRunning."""
    redis_client = _acquire_lock()
    try:
        sync = GrowwSync(started_at=utcnow(), trigger=trigger, status=SYNC_FAILED)
        db.add(sync)
        db.flush()
        try:
            rows = fetch_holdings()
        except GrowwAuthError:
            sync.error_code = "auth"
        except GrowwUnavailable:
            sync.error_code = "unavailable"
        except Exception:  # recorded, never raised to the caller
            logger.exception("groww sync failed unexpectedly")
            sync.error_code = "unexpected"
        else:
            sync.status = classify(rows)
            sync.holdings_count = len(rows)
            _store_rows(db, sync, rows)
        sync.finished_at = utcnow()
        db.commit()
        return sync
    finally:
        _release_lock(redis_client)
