"""Two lighter-weight ways to log spend than uploading a statement:

- A recurring bill (rent, subscriptions) is entered once; each month you
  confirm it was paid and the actual amount, which is logged here.
- A daily expense (food, transport) is logged on the spot, one entry at a
  time, against a small set of categories you maintain.

Both paths end up as ordinary FinanceTransaction rows — same dedup, same
category field, same monthly/category summaries everything else on the
Finance page already computes. Nothing downstream needs to know a row came
from a form instead of a PDF.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import FinanceDirection
from swing_trade_ml.db.models.finance import (
    FinanceRecurringBill,
    FinanceRecurringBillPayment,
    FinanceTransaction,
)

# Common household bills, offered as a one-click starting point so a new
# user checks them off and fills in the real amount instead of typing every
# name and category from scratch. default_amount is a placeholder (must be
# >0 per FinanceRecurringBillCreate) meant to be edited immediately.
DEFAULT_BILLS: list[tuple[str, str]] = [
    ("Rent", "Housing"),
    ("Building Maintenance", "Housing"),
    ("Electricity", "Utilities"),
    ("Water (Municipal)", "Utilities"),
    ("Water Can (RO)", "Utilities"),
    ("Internet/WiFi", "Utilities"),
    ("Gas/LPG", "Utilities"),
    ("Milk Bill", "Groceries"),
    ("Airtel Recharge", "Subscriptions"),
    ("Netflix", "Subscriptions"),
    ("ChatGPT", "Subscriptions"),
    ("Gym", "Health"),
    ("Kids Activities Fee", "Education"),
    ("Insurance", "Insurance"),
    ("EMI", "Debt"),
    ("Credit Card Bill", "Debt"),
    ("SIP", "Investments"),
]


def _month_key(d: datetime) -> str:
    return d.strftime("%Y-%m")


def seed_default_bills(db: Session) -> list[FinanceRecurringBill]:
    """Create any DEFAULT_BILLS not already present (by name, case-
    insensitive) among active bills. Safe to call repeatedly — already-added
    defaults, or bills the user renamed/removed, are left alone."""
    existing_names = {
        name.lower()
        for name in db.execute(
            select(FinanceRecurringBill.name).where(FinanceRecurringBill.is_active.is_(True))
        )
        .scalars()
        .all()
    }
    created = []
    for name, category in DEFAULT_BILLS:
        if name.lower() in existing_names:
            continue
        bill = FinanceRecurringBill(name=name, category=category, default_amount=1)
        db.add(bill)
        created.append(bill)
    if created:
        db.commit()
        for bill in created:
            db.refresh(bill)
    return created


def record_bill_payment(
    db: Session,
    bill: FinanceRecurringBill,
    month: str,
    amount: float,
    paid_at: datetime,
) -> FinanceRecurringBillPayment:
    """Mark `bill` paid for `month`, creating or updating both the payment
    record and its linked transaction. Re-paying an already-paid month (e.g.
    correcting the amount) updates both in place rather than double-counting."""
    payment = db.execute(
        select(FinanceRecurringBillPayment).where(
            FinanceRecurringBillPayment.bill_id == bill.id,
            FinanceRecurringBillPayment.month == month,
        )
    ).scalar_one_or_none()

    txn = None
    if payment and payment.transaction_id:
        txn = db.get(FinanceTransaction, payment.transaction_id)

    # The bill's category is optional, but FinanceTransaction.category isn't
    # (every other transaction on the page has one) — falls back the same
    # way an unrecognised statement line would.
    category = bill.category or "Uncategorised"

    if txn is None:
        txn = FinanceTransaction(
            dedup_key=f"recurring-bill:{bill.id}:{month}",
            source="manual_recurring",
            category=category,
            is_manual_override=True,
        )
        db.add(txn)

    txn.txn_date = paid_at
    txn.month = month
    txn.description = bill.name
    txn.amount = amount
    txn.direction = FinanceDirection.DEBIT
    txn.category = category

    if payment is None:
        payment = FinanceRecurringBillPayment(bill_id=bill.id, month=month)
        db.add(payment)
    payment.amount = amount
    payment.paid_at = paid_at

    db.flush()
    payment.transaction_id = txn.id
    db.commit()
    db.refresh(payment)
    return payment


def unpay_bill(db: Session, payment: FinanceRecurringBillPayment) -> None:
    """Undo a payment — deletes the payment record and its linked
    transaction, so a misclick doesn't leave a phantom expense behind."""
    if payment.transaction_id:
        txn = db.get(FinanceTransaction, payment.transaction_id)
        if txn is not None:
            db.delete(txn)
    db.delete(payment)
    db.commit()


def record_daily_expense(
    db: Session,
    category: str,
    amount: float,
    spent_at: datetime,
    note: str | None = None,
) -> FinanceTransaction:
    txn = FinanceTransaction(
        dedup_key=f"daily:{uuid4().hex}",
        txn_date=spent_at,
        month=_month_key(spent_at),
        description=note or category,
        amount=amount,
        direction=FinanceDirection.DEBIT,
        source="manual_daily",
        category=category,
        is_manual_override=True,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn
