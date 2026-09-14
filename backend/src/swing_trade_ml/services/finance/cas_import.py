"""CAS (Consolidated Account Statement) import — turns a CAMS/KFintech/
MF Central detailed statement into this app's per-lot mutual fund holdings,
matched against the AMFI scheme table by AMFI code. See
docs/superpowers/specs/2026-09-13-cas-import-design.md.

There is no broker/CAS API to poll — the user downloads the PDF from
camsonline.com or mfcentral.com and uploads it here whenever they want a
refresh. Every CAS-sourced holding for a (scheme, folio) is rebuilt from
scratch on each import rather than diffed, since the statement is always a
complete restatement of that folio's history; manually-added holdings
(source="manual") are never touched by an import.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date

from casparser.types import CASData, TransactionType
from dateutil import parser as dateutil_parser
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding
from swing_trade_ml.services.finance import mutual_funds as mf_service

log = get_logger(__name__)

# Transaction types that add units to the folio, in FIFO purchase order.
INCREASE_TYPES = {
    TransactionType.PURCHASE,
    TransactionType.PURCHASE_SIP,
    TransactionType.SWITCH_IN,
    TransactionType.SWITCH_IN_MERGER,
    TransactionType.DIVIDEND_REINVEST,
    TransactionType.GIFT_IN,
}

# Transaction types that remove units, consumed FIFO against the oldest lot.
DECREASE_TYPES = {
    TransactionType.REDEMPTION,
    TransactionType.SWITCH_OUT,
    TransactionType.SWITCH_OUT_MERGER,
    TransactionType.GIFT_OUT,
    TransactionType.SEGREGATION,
}

# Everything else (dividend payout, STT/stamp/TDS tax, misc, reversal,
# unknown) carries no unit effect for this purpose and is left alone.

_EPSILON = 1e-6


def build_lots_from_transactions(transactions: list[dict]) -> list[dict]:
    """Replay a scheme's transaction history into the purchase lots still
    held today. Pure function: takes plain dicts ({type, units, nav, date}),
    returns plain dicts ({units, purchase_nav, purchase_date}) — no casparser
    or DB objects, so this stays trivially testable."""
    lots: deque[dict] = deque()

    for txn in transactions:
        units = txn.get("units") or 0.0
        if units <= 0:
            continue

        if txn["type"] in INCREASE_TYPES:
            lots.append(
                {
                    "units": units,
                    "purchase_nav": txn.get("nav") or 0.0,
                    "purchase_date": txn["date"],
                }
            )
        elif txn["type"] in DECREASE_TYPES:
            remaining = units
            while remaining > _EPSILON and lots:
                lot = lots[0]
                if lot["units"] <= remaining + _EPSILON:
                    remaining -= lot["units"]
                    lots.popleft()
                else:
                    lot["units"] -= remaining
                    remaining = 0.0

    return list(lots)


@dataclass
class CasImportResult:
    folios_processed: int = 0
    schemes_matched: int = 0
    lots_created: int = 0
    unmatched_schemes: list[str] = field(default_factory=list)


def _as_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return dateutil_parser.parse(value).date()


def _sync_scheme_holdings(db: Session, scheme_id: int, folio_number: str, transactions: list[dict]) -> int:
    db.execute(
        delete(MutualFundHolding).where(
            MutualFundHolding.scheme_id == scheme_id,
            MutualFundHolding.folio_number == folio_number,
            MutualFundHolding.source == "cas",
        )
    )
    lots = build_lots_from_transactions(transactions)
    for lot in lots:
        db.add(
            MutualFundHolding(
                scheme_id=scheme_id,
                units=lot["units"],
                purchase_nav=lot["purchase_nav"],
                purchase_date=lot["purchase_date"],
                source="cas",
                folio_number=folio_number,
            )
        )
    return len(lots)


def import_cas_data(db: Session, cas_data: CASData) -> CasImportResult:
    result = CasImportResult(folios_processed=len(cas_data.folios))
    newly_tracked = False

    for folio in cas_data.folios:
        for scheme in folio.schemes:
            if not scheme.transactions:
                continue

            fund = None
            if scheme.amfi:
                fund = db.execute(
                    select(MutualFund).where(MutualFund.scheme_code == scheme.amfi)
                ).scalar_one_or_none()
            if fund is None:
                result.unmatched_schemes.append(scheme.scheme)
                continue

            result.schemes_matched += 1
            if not fund.is_tracked:
                fund.is_tracked = True
                newly_tracked = True

            transactions = [
                {
                    "type": txn.type,
                    "units": float(txn.units) if txn.units is not None else 0.0,
                    "nav": float(txn.nav) if txn.nav is not None else 0.0,
                    "date": _as_date(txn.date),
                }
                for txn in scheme.transactions
            ]
            result.lots_created += _sync_scheme_holdings(db, fund.id, folio.folio, transactions)

    db.commit()
    if newly_tracked:
        # Same "seed today's NAV immediately" behavior as manually adding a
        # holding (api/v1/endpoints/mutual_funds.py::create_holding) — done
        # once for the whole import rather than per-scheme to avoid hitting
        # AMFI once per newly-tracked fund.
        mf_service.sync_nav_snapshot(db)

    log.info(
        "mutual_funds.cas_import",
        folios=result.folios_processed,
        matched=result.schemes_matched,
        unmatched=len(result.unmatched_schemes),
        lots=result.lots_created,
    )
    return result
