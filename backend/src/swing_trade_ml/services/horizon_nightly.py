# ruff: noqa: E501 (long explanatory lines)
"""The 5-session recommendation records, written from the day's real 5D predictions (#387, #389).

One stored prediction of a 5-session model for one stock on one market session becomes one versioned horizon record
keyed by the stock's permanent `security_id` (services/identity). The record names its exact provenance: the model id,
name and version, the prediction row it came from (`run_ref = "prediction:<id>"`), the scan it belongs to
(`scan_key = "h5:<session>"`) and the input cutoff (the prediction's own candle time).

Rules, in plain words:
* Only a model trained for exactly 5 sessions is read. A 10- or 15-session model's prediction is never turned into a 5D
  record, and the workflow's own guard refuses it a second time.
* A stock with no `security_id` yet (a database the identity backfill never ran on, or an instrument added since) is
  linked first through the identity writer's own idempotent path, which links a re-issued token to the same company
  and REFUSES a symbol that belongs to a different company (it never merges). A refused stock is skipped and counted;
  the others are unaffected. `record_prediction` on its own never creates a stock.
* A retry adds nothing; a prediction that was re-scored to a different value adds the next revision (the first one stays).
* It reads `predictions` and `ml_models` and writes only `horizon_records`. It never touches signals, orders, the Brain,
  the h05 lane or any model.

The nightly job is registered only when `HORIZON_NIGHTLY_ENABLED` is true (default false) and is wired in
`workers/scheduler.py::add_horizon_nightly_job`. Nothing runs until the owner approves and switches it on.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.horizons import ModelOutput, run_horizon
from swing_trade_ml.core.config import REPO_ROOT
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import IST, last_closed_trading_day, next_trading_day
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.services import horizon_records
from swing_trade_ml.services.identity import resolve, writer
from swing_trade_ml.services.model_registry import role_of

log = get_logger(__name__)

HORIZON = 5
JOB_ID = "horizon5_nightly"
# Evening, after the scan and the candles are in; later passes only fill what is missing (a retry adds nothing).
SCHEDULE = {"day_of_week": "mon-fri", "hour": "17,19,21", "minute": 30}


class HorizonNightlySettings(BaseSettings):
    """Its own switch, so nothing about it lives in the shared Settings class. Off unless the owner turns it on."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_prefix="HORIZON_NIGHTLY_",
        extra="ignore",
        case_sensitive=False,
    )

    ENABLED: bool = False


def enabled() -> bool:
    return bool(HorizonNightlySettings().ENABLED)


@dataclass
class DaySummary:
    session: date
    predictions: int = 0
    recorded: int = 0  # new rows written (a first record or a new revision)
    unchanged: int = 0  # the same result was already stored (a retry)
    resolved: int = 0  # stocks that already had a security_id
    linked: int = 0  # stocks given a security_id by this pass (identity writer, idempotent)
    refused: int = 0  # identity conflict (the symbol is another company's): the stock is skipped
    unresolved: int = 0  # still no security_id after linking
    skipped: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session": str(self.session),
            "predictions": self.predictions,
            "recorded": self.recorded,
            "unchanged": self.unchanged,
            "resolved": self.resolved,
            "linked": self.linked,
            "refused": self.refused,
            "unresolved": self.unresolved,
            "skipped": dict(self.skipped),
        }


def sessions_from(session: date, count: int = 7) -> list[date]:
    """The exchange sessions starting at `session`: the calendar the workflow dates the due session from."""
    out = [session]
    while len(out) < count:
        out.append(next_trading_day(out[-1]))
    return out


def _day_bounds(session: date) -> tuple[datetime, datetime]:
    start = datetime(session.year, session.month, session.day, tzinfo=IST)
    return start, start + timedelta(days=1)


def model_output(model: MLModel, prediction: Prediction, instrument: Instrument, session: date) -> ModelOutput:
    """One stored prediction as the workflow's input. The model's own horizon and role travel with it."""
    return ModelOutput(
        model_name=model.name,
        model_version=model.version,
        forecast_horizon_sessions=model.prediction_horizon_days,
        role=role_of(model)["role"],
        symbol=instrument.tradingsymbol,
        input_session=session,
        input_close=prediction.price_at_prediction,
        score=prediction.probability,
    )


def record_prediction(
    db: Session,
    prediction: Prediction,
    model: MLModel,
    instrument: Instrument,
    session: date,
    *,
    policies: Any = None,
) -> horizon_records.SaveResult | None:
    """Turn one real 5D prediction into its horizon record. None when the stock is not recognised or the model is
    not a 5-session model. Never creates a stock and never writes a record of another horizon."""
    if model.prediction_horizon_days != HORIZON or model.id != prediction.model_id:
        return None
    security_id = resolve(db, token=instrument.instrument_token, symbol=instrument.tradingsymbol, on_date=session)
    if security_id is None:
        return None
    kwargs = {} if policies is None else {"policies": policies}
    record = run_horizon(
        HORIZON,
        [model_output(model, prediction, instrument, session)],
        session,
        sessions_from(session),
        symbol=instrument.tradingsymbol,
        **kwargs,
    )
    if record.model_version is None:
        # A "no decision" result still names the model that was asked, so its version is never lost.
        record = replace(record, model_name=model.name, model_version=model.version)
    return horizon_records.save_record(
        db,
        record,
        security_id=security_id,
        model_id=model.id,
        scan_key=f"h5:{session}",
        run_ref=f"prediction:{prediction.id}",
        input_cutoff=prediction.ts,
    )


def _link(db: Session, instrument: Instrument, summary: DaySummary) -> bool:
    """Make sure the instrument has a security_id. The token is the unambiguous key, so it decides whether the stock
    is already known. True = usable now; False = refused (an identity conflict) and counted."""
    if resolve(db, token=str(instrument.instrument_token)) is not None:
        summary.resolved += 1
        return True
    try:
        with db.begin_nested():
            writer.ensure_for_instrument(db, instrument)
    except writer.IdentityConflictError:
        summary.refused += 1
        log.warning("horizon5.identity_conflict", symbol=instrument.tradingsymbol)
        return False
    summary.linked += 1
    return True


def record_day(db: Session, session: date, *, policies: Any = None) -> DaySummary:
    """Write the records of every 5-session prediction made on one market session. Safe to run again. Does not commit."""
    summary = DaySummary(session)
    start, end = _day_bounds(session)
    rows = db.execute(
        select(Prediction, MLModel, Instrument)
        .join(MLModel, MLModel.id == Prediction.model_id)
        .join(Instrument, Instrument.id == Prediction.instrument_id)
        .where(Prediction.ts >= start, Prediction.ts < end, MLModel.prediction_horizon_days == HORIZON)
        .order_by(Prediction.model_id, Prediction.instrument_id, Prediction.ts)
    ).all()
    latest: dict[tuple[int, int], tuple[Prediction, MLModel, Instrument]] = {}
    for prediction, model, instrument in rows:  # the newest prediction of the session per model and stock
        latest[(model.id, instrument.id)] = (prediction, model, instrument)
    linked: dict[int, bool] = {}  # instrument id -> usable (so a stock with several models is linked once)
    for prediction, model, instrument in latest.values():
        summary.predictions += 1
        if instrument.id not in linked:
            linked[instrument.id] = _link(db, instrument, summary)
        if not linked[instrument.id]:
            continue
        result = record_prediction(db, prediction, model, instrument, session, policies=policies)
        if result is None:
            summary.unresolved += 1
        elif result.created:
            summary.recorded += 1
        else:
            summary.unchanged += 1
    return summary


def job_horizon_nightly(now: datetime | None = None) -> dict[str, Any] | None:
    """The nightly pass for the last closed session. Never raises into the worker."""
    from swing_trade_ml.db.session import session_scope

    try:
        session = last_closed_trading_day(now or datetime.now(UTC))
        with session_scope() as db:
            result = record_day(db, session).as_dict()
        log.info("horizon5.nightly", **result)
        return result
    except Exception as exc:  # noqa: BLE001
        log.error("horizon5.nightly_failed", error_kind=type(exc).__name__)
        return None


def register(target) -> bool:
    """Add the nightly job to a scheduler ONLY when HORIZON_NIGHTLY_ENABLED is true. Returns whether it did."""
    if not enabled():
        return False
    target.add_job(
        job_horizon_nightly,
        CronTrigger(timezone=IST, **SCHEDULE),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return True
