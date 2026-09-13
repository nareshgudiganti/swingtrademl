"""Importing this package registers every mapper on `Base.metadata`.

Alembic autogenerate and `create_all` both depend on that, so any new model
module must be re-exported here.
"""

from swing_trade_ml.db.models.finance import (
    FinanceCustomRule,
    FinanceDailyCategory,
    FinanceIngestedFile,
    FinanceLoan,
    FinanceRecurringBill,
    FinanceRecurringBillPayment,
    FinanceTransaction,
)
from swing_trade_ml.db.models.market import Candle, Instrument, Quote
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav
from swing_trade_ml.db.models.session import BrokerSession, User
from swing_trade_ml.db.models.trading import (
    Order,
    PortfolioSnapshot,
    Position,
    Signal,
    Strategy,
    Trade,
)

__all__ = [
    "BrokerSession",
    "Candle",
    "FinanceCustomRule",
    "FinanceDailyCategory",
    "FinanceIngestedFile",
    "FinanceLoan",
    "FinanceRecurringBill",
    "FinanceRecurringBillPayment",
    "FinanceTransaction",
    "Instrument",
    "MLModel",
    "MutualFund",
    "MutualFundHolding",
    "MutualFundNav",
    "Order",
    "PortfolioSnapshot",
    "Position",
    "Prediction",
    "Quote",
    "Signal",
    "Strategy",
    "Trade",
    "User",
]
