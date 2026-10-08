"""Importing this package registers every mapper on `Base.metadata`.

Alembic autogenerate and `create_all` both depend on that, so any new model
module must be re-exported here.
"""

from swing_trade_ml.db.models.brain import BrainAlert, BrainDecision, BrainModuleSetting, BrainRun, FeatureSnapshot
from swing_trade_ml.db.models.brain_golive import BrainApproval, BrainStageChange
from swing_trade_ml.db.models.finance import (
    FinanceCustomRule,
    FinanceDailyCategory,
    FinanceIngestedFile,
    FinanceLoan,
    FinanceRecurringBill,
    FinanceRecurringBillPayment,
    FinanceTransaction,
)
from swing_trade_ml.db.models.feeds import (
    BlockDeal,
    DailyDelivery,
    InstitutionalFlow,
    TradingRestriction,
    UpcomingEvent,
)
from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.db.models.market import Candle, CandleCorrection, Instrument, Quote, WatchlistSnapshot
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav
from swing_trade_ml.db.models.safety import RiskEvent, SystemState
from swing_trade_ml.db.models.session import BrokerSession, PlanSettings, SubscriptionPlan, User
from swing_trade_ml.db.models.trading import (
    Order,
    PortfolioSnapshot,
    Position,
    PositionScore,
    Signal,
    Strategy,
    Trade,
)

__all__ = [
    "BlockDeal",
    "BrainAlert",
    "BrainApproval",
    "BrainDecision",
    "BrainModuleSetting",
    "BrainRun",
    "BrainStageChange",
    "BrokerFill",
    "BrokerSession",
    "Candle",
    "CandleCorrection",
    "DailyDelivery",
    "FeatureSnapshot",
    "FinanceCustomRule",
    "FinanceDailyCategory",
    "FinanceIngestedFile",
    "FinanceLoan",
    "FinanceRecurringBill",
    "FinanceRecurringBillPayment",
    "FinanceTransaction",
    "Instrument",
    "InstitutionalFlow",
    "MLModel",
    "MutualFund",
    "MutualFundHolding",
    "MutualFundNav",
    "Order",
    "PlanSettings",
    "PortfolioSnapshot",
    "Position",
    "PositionScore",
    "Prediction",
    "Quote",
    "RiskEvent",
    "Signal",
    "Strategy",
    "SubscriptionPlan",
    "SystemState",
    "Trade",
    "TradingRestriction",
    "UpcomingEvent",
    "User",
    "WatchlistSnapshot",
]
