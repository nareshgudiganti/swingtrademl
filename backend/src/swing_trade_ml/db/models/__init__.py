"""Importing this package registers every mapper on `Base.metadata`.

Alembic autogenerate and `create_all` both depend on that, so any new model
module must be re-exported here.
"""

from swing_trade_ml.db.models.account_deletion import AccountDeletion
from swing_trade_ml.db.models.admin_mfa import AdminMfa, AdminRecoveryCode
from swing_trade_ml.db.models.alerts import AlertOutbox, AlertSettings
from swing_trade_ml.db.models.audit import AuditLog, LoginCode
from swing_trade_ml.db.models.auth_tokens import AuthToken
from swing_trade_ml.db.models.billing import BillingEvent, PlanGrant, Subscription
from swing_trade_ml.db.models.brain import (
    BrainAlert,
    BrainDecision,
    BrainModuleSetting,
    BrainRun,
    FeatureSnapshot,
)
from swing_trade_ml.db.models.brain_golive import BrainApproval, BrainStageChange
from swing_trade_ml.db.models.corporate_actions import CorporateAction, PositionAdjustment
from swing_trade_ml.db.models.company import CompanyAnnouncement, CompanyShareholding
from swing_trade_ml.db.models.experiments import (
    ExperimentCohort,
    ExperimentJobRun,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentSelection,
)
from swing_trade_ml.db.models.feeds import (
    BlockDeal,
    DailyDelivery,
    InstitutionalFlow,
    TradingRestriction,
    UpcomingEvent,
)
from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.db.models.finance import (
    FinanceCustomRule,
    FinanceDailyCategory,
    FinanceIngestedFile,
    FinanceLoan,
    FinanceRecurringBill,
    FinanceRecurringBillPayment,
    FinanceTransaction,
)
from swing_trade_ml.db.models.groww import GrowwHolding, GrowwSync, StockAlias
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.identity import ScoreLedger, Security, SecurityAlias, SecuritySymbol
from swing_trade_ml.db.models.invites import InviteRequest
from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run, H05Signal
from swing_trade_ml.db.models.market import (
    Candle,
    CandleArrival,
    CandleCorrection,
    Instrument,
    Quote,
    WatchlistSnapshot,
)
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.db.models.module_switch import ModuleSwitch
from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav
from swing_trade_ml.db.models.registry import ModelResearchSlot
from swing_trade_ml.db.models.safety import RiskEvent, SystemState
from swing_trade_ml.db.models.service_keys import ServiceKey
from swing_trade_ml.db.models.session import BrokerSession, PlanSettings, SubscriptionPlan, User
from swing_trade_ml.db.models.simulation import (
    SimBlock,
    SimDay,
    SimExit,
    SimFill,
    SimMark,
    SimNotApplied,
    SimNotRanked,
    SimPortfolio,
    SimRun,
)
from swing_trade_ml.db.models.trading import (
    CapitalDeposit,
    Order,
    PortfolioSnapshot,
    Position,
    PositionScore,
    Signal,
    Strategy,
    Trade,
)
from swing_trade_ml.db.models.user_watchlist import (
    UserWatchlistItem,
    UserWatchlistItemChange,
    UserWatchlistSale,
)

__all__ = [
    "GrowwHolding",
    "GrowwSync",
    "StockAlias",
    "AlertOutbox",
    "AlertSettings",
    "AuditLog",
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
    "CandleArrival",
    "CandleCorrection",
    "CapitalDeposit",
    "CompanyAnnouncement",
    "CorporateAction",
    "CompanyShareholding",
    "DailyDelivery",
    "ExperimentCohort",
    "ExperimentJobRun",
    "ExperimentOutcome",
    "ExperimentProtocol",
    "ExperimentSelection",
    "H05Event",
    "HorizonRecordRow",
    "H05GroupDay",
    "H05Run",
    "H05Signal",
    "FeatureSnapshot",
    "FinanceCustomRule",
    "FinanceDailyCategory",
    "FinanceIngestedFile",
    "FinanceLoan",
    "FinanceRecurringBill",
    "FinanceRecurringBillPayment",
    "FinanceTransaction",
    "H05Event",
    "H05GroupDay",
    "H05Run",
    "H05Signal",
    "LaneOutcome",
    "LanePick",
    "InstitutionalFlow",
    "Instrument",
    "AdminMfa",
    "AdminRecoveryCode",
    "BillingEvent",
    "InviteRequest",
    "AccountDeletion",
    "AuthToken",
    "PlanGrant",
    "Subscription",
    "LoginCode",
    "MLModel",
    "ModuleSwitch",
    "ModelResearchSlot",
    "MutualFund",
    "MutualFundHolding",
    "MutualFundNav",
    "Order",
    "PlanSettings",
    "PortfolioSnapshot",
    "Position",
    "PositionAdjustment",
    "PositionScore",
    "Prediction",
    "Quote",
    "RiskEvent",
    "ScoreLedger",
    "Security",
    "SecurityAlias",
    "SecuritySymbol",
    "ServiceKey",
    "Signal",
    "SimBlock",
    "SimDay",
    "SimExit",
    "SimFill",
    "SimMark",
    "SimNotApplied",
    "SimNotRanked",
    "SimPortfolio",
    "SimRun",
    "Strategy",
    "SubscriptionPlan",
    "SystemState",
    "Trade",
    "TradingRestriction",
    "UpcomingEvent",
    "User",
    "UserWatchlistItem",
    "UserWatchlistItemChange",
    "UserWatchlistSale",
    "WatchlistSnapshot",
]
