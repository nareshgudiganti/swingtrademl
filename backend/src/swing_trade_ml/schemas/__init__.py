"""Pydantic request/response models.

Kept in one module: they are thin, and having the whole API contract readable in
a single file is worth more here than package-per-domain ceremony.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ORM = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ system --


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    ready: bool
    database: bool
    broker_authenticated: bool
    scheduler_running: bool
    trading_mode: str
    live_trading_enabled: bool


class SystemStatus(BaseModel):
    app: str
    environment: str
    trading_mode: str
    live_trading_enabled: bool
    broker_authenticated: bool
    scheduler_running: bool
    scheduled_jobs: list[dict[str, Any]]
    telegram_enabled: bool
    active_model: str | None
    watchlist_size: int
    active_strategies: int
    open_positions: int
    latest_candle_date: date | None
    last_scan_at: datetime | None
    last_scan_result: dict[str, Any] | None
    status_level: str
    status_message: str


# -------------------------------------------------------------------- auth --


class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8)
    email: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class CurrentUserOut(BaseModel):
    model_config = ORM
    id: int
    username: str
    email: str | None
    auth_provider: str
    is_superuser: bool


class KiteLoginResponse(BaseModel):
    login_url: str
    instructions: str


class KiteSessionResponse(BaseModel):
    model_config = ORM
    authenticated: bool
    kite_user_id: str | None = None
    user_name: str | None = None
    expires_at: datetime | None = None


# ------------------------------------------------------------- instruments --


class InstrumentOut(BaseModel):
    model_config = ORM
    id: int
    instrument_token: int
    tradingsymbol: str
    name: str | None
    exchange: str
    instrument_type: str | None
    lot_size: int
    tick_size: float
    is_watchlisted: bool
    is_active: bool


class WatchlistRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, description="NSE trading symbols")
    exchange: str = "NSE"


class BackfillRequest(BaseModel):
    symbols: list[str] | None = Field(None, description="Defaults to the whole watchlist")
    interval: str = "day"
    days: int | None = None
    incremental: bool = True


# ------------------------------------------------------------ market data --


class CandleOut(BaseModel):
    model_config = ORM
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class QuoteOut(BaseModel):
    model_config = ORM
    instrument_id: int
    last_price: float
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    change_pct: float | None
    ts: datetime


# -------------------------------------------------------------- strategies --


class StrategyCreate(BaseModel):
    name: str
    strategy_type: str
    description: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)
    max_positions: int | None = None
    capital_allocation: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    # Caps how many new entries a scan acts on, ranked by confidence, even
    # when more position slots are free. Null = uncapped.
    max_daily_buys: int | None = None
    # "auto" places real orders as before; "advisory" only ever recommends —
    # see services/execution.py.
    execution_mode: str = Field("auto", pattern="^(auto|advisory)$")
    allow_pyramiding: bool = False


class StrategyUpdate(BaseModel):
    description: str | None = None
    params: dict[str, Any] | None = None
    symbols: list[str] | None = None
    is_active: bool | None = None
    max_positions: int | None = None
    capital_allocation: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_daily_buys: int | None = None
    execution_mode: str | None = Field(None, pattern="^(auto|advisory)$")
    allow_pyramiding: bool | None = None


class StrategyOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    description: str | None
    strategy_type: str
    params: dict[str, Any]
    symbols: list[str]
    is_active: bool
    mode: str
    max_positions: int | None
    capital_allocation: float | None
    stop_loss_pct: float | None
    take_profit_pct: float | None
    max_daily_buys: int | None
    execution_mode: str
    allow_pyramiding: bool
    created_at: datetime


class StrategyTypeInfo(BaseModel):
    strategy_type: str
    display_name: str
    description: str
    default_params: dict[str, Any]


class ScanResponse(BaseModel):
    strategies_run: int
    instruments_evaluated: int
    signals_generated: int
    buys: int
    exits: int
    executed: int
    errors: list[str]


# ----------------------------------------------------------------- signals --


class SignalOut(BaseModel):
    model_config = ORM
    id: int
    strategy_id: int
    instrument_id: int
    tradingsymbol: str
    name: str
    signal_type: str
    mode: str
    price: float
    confidence: float | None
    suggested_quantity: int | None
    stop_loss: float | None
    take_profit: float | None
    reason: str | None
    features: dict[str, Any]
    was_executed: bool
    rejection_reason: str | None
    advisory_only: bool
    generated_at: datetime


# ------------------------------------------------------------------ orders --


class OrderCreate(BaseModel):
    symbol: str = Field(..., description="NSE trading symbol, e.g. INFY")
    exchange: str = "NSE"
    transaction_type: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int = Field(..., gt=0)
    order_type: str = "MARKET"
    product: str = "CNC"
    price: float | None = None
    trigger_price: float | None = None


class OrderOut(BaseModel):
    model_config = ORM
    id: int
    signal_id: int | None
    strategy_id: int | None
    position_id: int | None
    instrument_id: int
    broker_order_id: str | None
    mode: str
    transaction_type: str
    order_type: str
    product: str
    quantity: int
    filled_quantity: int
    price: float | None
    average_price: float | None
    status: str
    status_message: str | None
    brokerage: float
    taxes: float
    slippage: float
    placed_at: datetime
    filled_at: datetime | None


# --------------------------------------------------------------- portfolio --


class PositionOut(BaseModel):
    model_config = ORM
    id: int
    strategy_id: int | None
    instrument_id: int
    mode: str
    status: str
    quantity: int
    entry_price: float
    entry_at: datetime
    exit_price: float | None
    exit_at: datetime | None
    exit_reason: str | None
    stop_loss: float | None
    take_profit: float | None
    current_price: float | None
    unrealized_pnl: float
    realized_pnl: float | None
    total_charges: float
    entry_confidence: float | None
    last_confidence: float | None


class TradeOut(BaseModel):
    model_config = ORM
    id: int
    symbol: str
    mode: str
    quantity: int
    entry_price: float
    exit_price: float
    entry_at: datetime
    exit_at: datetime
    holding_days: int
    gross_pnl: float
    charges: float
    net_pnl: float
    return_pct: float
    exit_reason: str | None
    exit_reason_label: str | None
    is_win: bool
    # From the linked Position — what this trade was actually being judged
    # against, so "did it hit the target, get stopped, or exit on the
    # model's own judgment short of either" is answerable without asking.
    stop_loss: float | None = None
    take_profit: float | None = None
    entry_confidence: float | None = None
    last_confidence: float | None = None
    # How the stock moved after we sold it, so a SIGNAL_EXIT or STOP_LOSS_HIT
    # can be judged in hindsight — did it keep falling (exit vindicated) or
    # rally afterward (profit left on the table)? Null until enough trading
    # days have actually passed since the exit.
    price_5d_after_exit: float | None = None
    return_5d_after_exit: float | None = None
    price_15d_after_exit: float | None = None
    return_15d_after_exit: float | None = None


class ClosePositionRequest(BaseModel):
    reason: str = "MANUAL"
    note: str | None = None


class ManualEntryRequest(BaseModel):
    """Record a position filled outside the app — e.g. an advisory-mode
    recommendation the user acted on manually in Zerodha."""

    strategy_id: int
    instrument_id: int
    quantity: int = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    brokerage: float | None = None
    taxes: float | None = None
    signal_id: int | None = None


class ManualExitRequest(BaseModel):
    exit_price: float = Field(gt=0)
    exit_reason: str = "MANUAL"
    brokerage: float | None = None
    taxes: float | None = None


class EquityPoint(BaseModel):
    date: str
    total_value: float
    cash: float
    holdings_value: float
    day_pnl: float
    drawdown_pct: float
    open_positions: int


# ---------------------------------------------------------------------- ml --


class TrainRequest(BaseModel):
    name: str = "swing_classifier"
    algorithm: str = Field(
        "lightgbm", pattern="^(lightgbm|random_forest|gradient_boosting|logistic_regression)$"
    )
    symbols: list[str] | None = None
    interval: str = "day"
    horizon_days: int | None = None
    target_return: float | None = None
    test_size: float | None = None
    hyperparameters: dict[str, Any] | None = None
    auto_activate: bool = False


class MLModelOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    version: str
    algorithm: str
    status: str
    n_samples: int | None
    prediction_horizon_days: int
    target_return_pct: float
    accuracy: float | None
    precision: float | None
    recall: float | None
    f1_score: float | None
    roc_auc: float | None
    training_symbols: list[str]
    train_start: datetime | None
    train_end: datetime | None
    trained_at: datetime | None
    activated_at: datetime | None


class MLModelDetail(MLModelOut):
    feature_names: list[str]
    hyperparameters: dict[str, Any]
    metrics: dict[str, Any]
    feature_importance: dict[str, Any]


class PredictionOut(BaseModel):
    id: int
    model_id: int
    instrument_id: int
    symbol: str
    ts: datetime
    predicted_class: int
    probability: float
    price_at_prediction: float
    actual_return: float | None
    was_correct: bool | None
    evaluated_at: datetime | None


class PredictionRunOut(BaseModel):
    symbol: str
    instrument_id: int
    probability: float
    predicted_class: int
    price: float
    ts: datetime


# ------------------------------------------------------------- backtest --


class BacktestRequest(BaseModel):
    strategy_type: str = Field(pattern="^(ml_swing|sma_crossover)$")
    symbols: list[str] | None = None
    start: date
    end: date | None = None
    interval: str = "day"
    params: dict[str, Any] | None = None
    starting_capital: float | None = None


class BacktestTradeOut(BaseModel):
    # BacktestTrade is a plain dataclass, not a dict — from_attributes lets
    # pydantic build this from its attributes the same way ORM rows validate.
    model_config = ORM
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    charges: float
    net_pnl: float
    return_pct: float
    holding_days: int
    exit_reason: str


class BacktestResponse(BaseModel):
    strategy_type: str
    symbols: list[str]
    start: date
    end: date
    starting_capital: float
    ending_value: float
    stats: dict[str, Any]
    trades: list[BacktestTradeOut]
    equity_curve: list[dict[str, Any]]


# ------------------------------------------------------------ notifications --


class TelegramTestResponse(BaseModel):
    ok: bool
    bot: str | None = None
    chat_id: str | None = None
    error: str | None = None


class MessageResponse(BaseModel):
    message: str
    detail: str | None = None


# ------------------------------------------------------------------ finance --


class FinanceTransactionOut(BaseModel):
    model_config = ORM
    id: int
    txn_date: datetime
    month: str
    description: str
    amount: float
    direction: str
    status: str | None
    transaction_id: str | None
    source: str | None
    category: str
    is_manual_override: bool
    is_reference_only: bool


class FinanceTransactionUpdate(BaseModel):
    category: str = Field(..., min_length=1, max_length=64)


class FinanceIngestResult(BaseModel):
    file_name: str
    source_type: str
    already_imported: bool
    transactions_parsed: int
    transactions_imported: int
    duplicates_skipped: int
    message: str


class FinanceIngestedFileOut(BaseModel):
    model_config = ORM
    id: int
    file_name: str
    source_type: str
    status: str
    transaction_count: int
    message: str | None
    created_at: datetime
    deleted_at: datetime | None


class FinanceCalculationSummary(BaseModel):
    total_debits: float
    total_credits: float
    net: float
    transaction_count: int


class FinanceMonthlySummary(BaseModel):
    month: str
    total_expense: float
    transaction_count: int
    avg_transaction: float


class FinanceCategorySummary(BaseModel):
    category: str
    total_expense: float
    transaction_count: int
    avg_transaction: float


class FinanceMonthlyCategorySummary(BaseModel):
    month: str
    category: str
    total_expense: float
    transaction_count: int


class FinanceMerchantSummary(BaseModel):
    description: str
    total_expense: float
    transaction_count: int


class FinanceLoanCreate(BaseModel):
    account_number: str | None = None
    name: str = Field(..., min_length=1, max_length=128)
    principal: float = Field(..., gt=0)
    annual_rate: float = Field(..., ge=0)
    tenure_months: int = Field(..., gt=0)
    emi: float = Field(..., gt=0)
    extra_payment: float = Field(0.0, ge=0)
    start_date: date


class FinanceLoanUpdate(BaseModel):
    account_number: str | None = None
    name: str | None = Field(None, min_length=1, max_length=128)
    principal: float | None = Field(None, gt=0)
    annual_rate: float | None = Field(None, ge=0)
    tenure_months: int | None = Field(None, gt=0)
    emi: float | None = Field(None, gt=0)
    extra_payment: float | None = Field(None, ge=0)
    start_date: date | None = None


class FinanceLoanOut(BaseModel):
    id: int
    account_number: str | None
    name: str
    principal: float
    annual_rate: float
    tenure_months: int
    emi: float
    extra_payment: float
    start_date: datetime
    outstanding: float
    scheduled_end: date
    estimated_close: date | None
    scheduled_pending_label: str
    pending_label: str
    monthly_interest: float
    yearly_interest: float
    total_interest: float
    estimated_interest: float
    interest_saved: float
    total_payable: float


class FinanceNetWorth(BaseModel):
    income_total: float
    expense_total: float
    cash_surplus: float
    investments_total: float
    liabilities: float
    net_worth: float


class FinanceRecurringBillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    category: str | None = Field(None, min_length=1, max_length=64)
    default_amount: float = Field(..., gt=0)


class FinanceRecurringBillUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    # None here is ambiguous between "leave category unchanged" and "clear
    # it" — the endpoint only ever sets this from a PATCH body that names the
    # key (model_dump(exclude_unset=True)), so an omitted key truly leaves it
    # alone, and an explicit null clears it. See update_recurring_bill.
    category: str | None = Field(None, max_length=64)
    default_amount: float | None = Field(None, gt=0)
    is_active: bool | None = None


class FinanceRecurringBillOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    category: str | None
    default_amount: float
    is_active: bool
    # This month's status, resolved server-side against the `month` query
    # param (defaults to the current month) — the page never has to compute
    # "is this paid yet" itself from a separate payments list.
    paid_this_month: bool
    amount_this_month: float | None
    paid_at: datetime | None


class FinanceBillPaymentIn(BaseModel):
    month: str = Field(..., min_length=7, max_length=7)
    amount: float = Field(..., gt=0)
    paid_at: date | None = None


class FinanceDailyCategoryIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class FinanceDailyCategoryOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    is_active: bool


class FinanceDailyExpenseIn(BaseModel):
    category: str = Field(..., min_length=1, max_length=64)
    amount: float = Field(..., gt=0)
    spent_at: date | None = None
    note: str | None = Field(None, max_length=255)


class FinanceCustomRuleIn(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=128)
    category: str = Field(..., min_length=1, max_length=64)
    priority: int = 90


class FinanceCustomRuleOut(BaseModel):
    model_config = ORM
    id: int
    keyword: str
    category: str
    priority: int


class FinanceRuleUpsertResult(BaseModel):
    rule: FinanceCustomRuleOut
    recategorized_count: int


class FinanceRecategorizeResult(BaseModel):
    recategorized_count: int
