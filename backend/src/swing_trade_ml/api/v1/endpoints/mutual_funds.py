"""Mutual fund holdings — search, add/edit/remove a lot, list with computed
returns and risk. See
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md §8.
"""

from __future__ import annotations

import io

import casparser
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav
from swing_trade_ml.schemas import (
    MessageResponse,
    MutualFundCasImportResult,
    MutualFundHoldingCreate,
    MutualFundHoldingOut,
    MutualFundHoldingUpdate,
    MutualFundNavPoint,
    MutualFundSearchResult,
)
from swing_trade_ml.services.finance import cas_import as cas_import_service
from swing_trade_ml.services.finance import mutual_funds as mf_service

router = APIRouter(prefix="/mutual-funds", tags=["mutual-funds"])


@router.get("/search", response_model=list[MutualFundSearchResult])
def search(db: DbSession, q: str = Query(..., min_length=2)) -> list[MutualFund]:
    funds = db.execute(
        select(MutualFund).where(MutualFund.name.ilike(f"%{q}%")).limit(25)
    ).scalars().all()
    return [
        MutualFundSearchResult(
            scheme_id=f.id, scheme_code=f.scheme_code, name=f.name,
            amc_name=f.amc_name, category=f.category, is_tracked=f.is_tracked,
        )
        for f in funds
    ]


def _holding_out(db: DbSession, holding: MutualFundHolding) -> MutualFundHoldingOut:
    fund = db.get(MutualFund, holding.scheme_id)
    latest = db.execute(
        select(MutualFundNav)
        .where(MutualFundNav.scheme_id == holding.scheme_id)
        .order_by(MutualFundNav.date.desc())
        .limit(1)
    ).scalar_one_or_none()

    value = mf_service.holding_value(holding, latest.nav) if latest else None
    history = [
        n.nav for n in db.execute(
            select(MutualFundNav).where(MutualFundNav.scheme_id == holding.scheme_id).order_by(MutualFundNav.date)
        ).scalars().all()
    ]
    risk = mf_service.holding_risk(history) if len(history) >= 2 else None

    return MutualFundHoldingOut(
        id=holding.id, scheme_id=holding.scheme_id, scheme_name=fund.name if fund else "Unknown",
        category=fund.category if fund else None, units=holding.units, purchase_nav=holding.purchase_nav,
        purchase_date=holding.purchase_date, latest_nav=latest.nav if latest else None,
        current_value=value["current_value"] if value else None,
        cost_basis=holding.units * holding.purchase_nav,
        absolute_return=value["absolute_return"] if value else None,
        absolute_return_pct=value["absolute_return_pct"] if value else None,
        annualized_return_pct=value["annualized_return_pct"] if value else None,
        volatility=risk["volatility"] if risk else None,
        max_drawdown=risk["max_drawdown"] if risk else None,
        source=holding.source,
        folio_number=holding.folio_number,
    )


@router.post("/holdings", response_model=MutualFundHoldingOut, status_code=status.HTTP_201_CREATED)
def create_holding(payload: MutualFundHoldingCreate, db: DbSession) -> MutualFundHoldingOut:
    fund = db.get(MutualFund, payload.scheme_id)
    if fund is None:
        raise HTTPException(status_code=404, detail="Scheme not found")

    holding = MutualFundHolding(
        scheme_id=payload.scheme_id, units=payload.units, purchase_nav=payload.purchase_nav,
        purchase_date=payload.purchase_date, notes=payload.notes,
    )
    db.add(holding)

    was_tracked = fund.is_tracked
    fund.is_tracked = True
    db.commit()
    db.refresh(holding)

    if not was_tracked:
        # New to tracking — seed at least today's NAV so the holdings list
        # isn't empty of price data until tomorrow's sync job runs. A full
        # historical backfill (spec §6) is a separate, explicitly deferred
        # follow-up once the AMFI historical-file endpoint is confirmed
        # (see the spec's §11 open items) — this seed keeps the feature
        # usable in the meantime.
        mf_service.sync_nav_snapshot(db)

    return _holding_out(db, holding)


@router.get("/holdings", response_model=list[MutualFundHoldingOut])
def list_holdings(db: DbSession) -> list[MutualFundHoldingOut]:
    holdings = db.execute(select(MutualFundHolding)).scalars().all()
    return [_holding_out(db, h) for h in holdings]


@router.post("/import-cas", response_model=MutualFundCasImportResult)
async def import_cas(
    db: DbSession,
    file: UploadFile = File(...),
    password: str | None = Form(None),
) -> MutualFundCasImportResult:
    """Import holdings from a CAMS/KFintech/MF Central Consolidated Account
    Statement PDF — covers every mutual fund a PAN holds, on any platform
    (Paytm Money, Groww, direct, etc.), since there's no broker API for this.
    Every CAS-sourced lot is rebuilt from scratch on each import; manually
    added holdings are untouched. Requires a *Detailed* statement (not
    Summary) since only the detailed one carries transaction-level history."""
    content = await file.read()
    max_bytes = settings.FINANCE_MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {settings.FINANCE_MAX_UPLOAD_MB}MB limit",
        )

    try:
        cas_data = casparser.read_cas_pdf(io.BytesIO(content), password or "", output="pydantic")
    except Exception as exc:  # noqa: BLE001 - casparser raises assorted parse/password errors
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not read the CAS statement: {exc}"
        ) from exc

    if not cas_data.folios:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No mutual fund folios found in this statement. Make sure you requested a "
            "Detailed (not Summary) CAS from camsonline.com or mfcentral.com.",
        )

    result = cas_import_service.import_cas_data(db, cas_data)
    return MutualFundCasImportResult(
        folios_processed=result.folios_processed,
        schemes_matched=result.schemes_matched,
        lots_created=result.lots_created,
        unmatched_schemes=result.unmatched_schemes,
    )


@router.patch("/holdings/{holding_id}", response_model=MutualFundHoldingOut)
def update_holding(holding_id: int, payload: MutualFundHoldingUpdate, db: DbSession) -> MutualFundHoldingOut:
    holding = db.get(MutualFundHolding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(holding, field, value)
    db.commit()
    db.refresh(holding)
    return _holding_out(db, holding)


@router.delete("/holdings/{holding_id}", response_model=MessageResponse)
def delete_holding(holding_id: int, db: DbSession) -> MessageResponse:
    holding = db.get(MutualFundHolding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    db.delete(holding)
    db.commit()
    return MessageResponse(message="Holding removed")


@router.get("/{scheme_id}/history", response_model=list[MutualFundNavPoint])
def scheme_history(scheme_id: int, db: DbSession) -> list[MutualFundNavPoint]:
    rows = db.execute(
        select(MutualFundNav).where(MutualFundNav.scheme_id == scheme_id).order_by(MutualFundNav.date)
    ).scalars().all()
    return [MutualFundNavPoint(date=r.date, nav=r.nav) for r in rows]
